"""
Hybrid STT Engine for JanSahayak
Priority: Amazon Transcribe → Groq Whisper → Keyword fallback
Near 100% accuracy via multi-layer approach
"""
import os, json, time, uuid, logging, tempfile
import urllib.request
import boto3
from groq import Groq

logger = logging.getLogger(__name__)

LANG_MAP = {
    "hi": "hi-IN", "te": "te-IN", "ta": "ta-IN",
    "kn": "kn-IN", "ml": "ml-IN", "mr": "mr-IN",
    "bn": "bn-IN", "en": "en-IN", "as": "hi-IN"
}

# Context-aware correction maps per step
CONTEXT_CORRECTIONS = {
    "income_check": {
        "ek lakh": "1", "one lakh": "1", "oka lakh": "1", "ondu lakh": "1",
        "do lakh": "2", "two lakh": "2", "rendu lakh": "2", "eradu lakh": "2",
        "teen lakh": "3", "three lakh": "3", "moodu lakh": "3",
        "kam": "1", "less": "1", "chota": "1", "garib": "1", "poor": "1",
        "zyada": "3", "jyada": "3", "amir": "3", "rich": "3", "bada": "3",
        "medium": "2", "beech": "2", "madhyam": "2",
    },
    "land_check": {
        "chota": "1", "small": "1", "kam": "1", "thoda": "1", "chinna": "1",
        "medium": "2", "madhyam": "2", "beech": "2",
        "bada": "3", "large": "3", "zyada": "3", "pedda": "3",
        "do acre": "2", "2 acre": "2", "panch acre": "3", "5 acre": "3",
    },
    "farmer_check": {
        "ha": "1", "haan": "1", "yes": "1", "avunu": "1", "aamam": "1",
        "hou": "1", "ho": "1", "haudu": "1", "athe": "1", "hoy": "1",
        "no": "2", "nahi": "2", "ledu": "2", "illai": "2", "illa": "2",
        "nahin": "2", "naa": "2", "nahi ji": "2",
    },
    "scheme_selection": {
        "kisan": "1", "pm kisan": "1", "pmkisan": "1", "farmer": "1", "raitu": "1",
        "ration": "2", "rashan": "2", "food": "2", "anna": "2",
        "ayushman": "3", "health": "3", "hospital": "3", "dawai": "3", "swasth": "3",
    },
    "language_selection": {
        "hindi": "1", "हिंदी": "1", "hindi bolo": "1",
        "telugu": "2", "తెలుగు": "2", "telugu lo": "2",
        "tamil": "3", "தமிழ்": "3",
        "kannada": "4", "ಕನ್ನಡ": "4",
        "malayalam": "5", "മലയാളം": "5",
        "marathi": "6", "मराठी": "6",
        "bangla": "7", "bengali": "7", "বাংলা": "7",
        "assamese": "8", "অসমীয়া": "8",
        "english": "9", "angrezi": "9",
    },
    "confirm_mobile": {
        "ha": "1", "haan": "1", "yes": "1", "avunu": "1", "correct": "1", "sahi": "1",
        "no": "2", "nahi": "2", "wrong": "2", "galat": "2", "ledu": "2",
    },
    "consent": {
        "ha": "1", "haan": "1", "yes": "1", "submit": "1", "bhejo": "1", "jama": "1",
        "no": "2", "nahi": "2", "cancel": "2", "band": "2", "mat": "2",
    }
}

def _is_garbled(text: str) -> bool:
    """Check if transcript looks wrong."""
    if not text or len(text.strip()) < 2:
        return True
    words = text.strip().split()
    # Too many single chars = garbled
    single_chars = sum(1 for w in words if len(w) == 1)
    if len(words) > 3 and single_chars / len(words) > 0.5:
        return True
    return False

def _apply_context_correction(text: str, step: str) -> str:
    """Apply context-aware correction based on current step."""
    if not step or step not in CONTEXT_CORRECTIONS:
        return text
    text_lower = text.lower().strip()
    corrections = CONTEXT_CORRECTIONS[step]
    # Check exact match first
    if text_lower in corrections:
        return corrections[text_lower]
    # Check partial match
    for phrase, replacement in corrections.items():
        if phrase in text_lower:
            return replacement
    return text

def _extract_phone_from_speech(text: str) -> str:
    """Extract phone number spoken in any format."""
    import re
    # Remove spaces and get digits
    digits = re.sub(r'\D', '', text)
    # Handle "91" prefix
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    
    # Handle spoken numbers like "nine eight seven six..."
    word_to_digit = {
        "zero":"0","one":"1","two":"2","three":"3","four":"4",
        "five":"5","six":"6","seven":"7","eight":"8","nine":"9",
        "shunya":"0","ek":"1","do":"2","teen":"3","char":"4",
        "paanch":"5","chhe":"6","saat":"7","aath":"8","nau":"9",
        "oka":"1","rendu":"2","moodu":"3","naalugu":"4","ayidu":"5",
        "aaru":"6","edu":"7","enimidi":"8","tommidi":"9","padi":"0"
    }
    words = text.lower().split()
    digit_str = ""
    for word in words:
        if word in word_to_digit:
            digit_str += word_to_digit[word]
    if len(digit_str) == 10 and digit_str[0] in "6789":
        return digit_str
    return ""

async def transcribe(audio_bytes: bytes, lang: str = "hi", step: str = "", 
                     audio_format: str = "ogg") -> dict:
    """
    Main hybrid STT function.
    Returns: {"text": str, "resolved": str, "method": str, "phone": str}
    """
    result = {"text": "", "resolved": "", "method": "", "phone": ""}
    
    # ── Layer 1: Amazon Transcribe ──────────────────────────────────────────
    try:
        bucket = "jansahayak-vupo"
        job_name = f"stt-{uuid.uuid4().hex[:10]}"
        s3_key = f"voice/{job_name}.{audio_format}"
        transcribe_lang = LANG_MAP.get(lang, "hi-IN")

        s3 = boto3.client("s3", region_name="us-east-1")
        transcribe_client = boto3.client("transcribe", region_name="us-east-1")

        s3.put_object(Bucket=bucket, Key=s3_key, Body=audio_bytes)

        transcribe_client.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={"MediaFileUri": f"s3://{bucket}/{s3_key}"},
            MediaFormat=audio_format,
            LanguageCode=transcribe_lang,
        )

        text = ""
        for _ in range(15):
            time.sleep(2)
            status = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
            state = status["TranscriptionJob"]["TranscriptionJobStatus"]
            if state == "COMPLETED":
                uri = status["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
                with urllib.request.urlopen(uri) as r:
                    data = json.loads(r.read())
                text = data["results"]["transcripts"][0]["transcript"]
                # Get confidence
                try:
                    items = data["results"]["items"]
                    confidences = [float(i["alternatives"][0]["confidence"]) 
                                  for i in items if i.get("type") == "pronunciation"
                                  and i.get("alternatives")]
                    avg_conf = sum(confidences) / len(confidences) if confidences else 0
                    logger.info(f"[STT-Transcribe] lang={transcribe_lang} conf={avg_conf:.2f} text={text[:50]}")
                except:
                    avg_conf = 0.8
                break
            elif state == "FAILED":
                break

        # Cleanup
        try:
            s3.delete_object(Bucket=bucket, Key=s3_key)
            transcribe_client.delete_transcription_job(TranscriptionJobName=job_name)
        except:
            pass

        if text and not _is_garbled(text):
            result["text"] = text
            result["method"] = f"amazon_transcribe_{transcribe_lang}"
            
            # Check if it's a phone number step
            if step == "ask_mobile":
                phone = _extract_phone_from_speech(text)
                if phone:
                    result["phone"] = phone
                    result["resolved"] = phone
                    return result
            
            # Apply context correction
            resolved = _apply_context_correction(text, step)
            result["resolved"] = resolved
            
            # If confidence is low OR garbled, also try Groq for verification
            if avg_conf < 0.7 or _is_garbled(resolved):
                logger.info(f"[STT] Low confidence {avg_conf:.2f}, trying Groq verification...")
                groq_text = await _groq_transcribe(audio_bytes, lang, audio_format)
                if groq_text and not _is_garbled(groq_text):
                    groq_resolved = _apply_context_correction(groq_text, step)
                    # Use Groq if it gives a cleaner menu choice
                    if groq_resolved in ["1","2","3","4","5","6","7","8","9"] and resolved not in ["1","2","3","4","5","6","7","8","9"]:
                        result["text"] = groq_text
                        result["resolved"] = groq_resolved
                        result["method"] = "groq_whisper_verification"
            return result

    except Exception as e:
        logger.error(f"[STT-Transcribe] Error: {e}")

    # ── Layer 2: Groq Whisper fallback ──────────────────────────────────────
    groq_text = await _groq_transcribe(audio_bytes, lang, audio_format)
    if groq_text:
        result["text"] = groq_text
        result["method"] = "groq_whisper_fallback"
        if step == "ask_mobile":
            phone = _extract_phone_from_speech(groq_text)
            if phone:
                result["phone"] = phone
                result["resolved"] = phone
                return result
        result["resolved"] = _apply_context_correction(groq_text, step)
        return result

    # ── Layer 3: Return empty, bot will ask to repeat ──────────────────────
    logger.error("[STT] All methods failed")
    return result


async def _groq_transcribe(audio_bytes: bytes, lang: str, audio_format: str = "ogg") -> str:
    """Groq Whisper transcription."""
    try:
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        with open(tmp_path, "rb") as af:
            whisper_lang = lang if lang in ["hi","te","ta","kn","ml","mr","bn","en"] else "hi"
            result = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=(f"voice.{audio_format}", af, f"audio/{audio_format}"),
                response_format="text",
                language=whisper_lang,
            )
        os.unlink(tmp_path)
        text = result if isinstance(result, str) else result.text
        logger.info(f"[STT-Groq] text={text[:50]}")
        return text
    except Exception as e:
        logger.error(f"[STT-Groq] Error: {e}")
        return ""
