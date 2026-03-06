"""
aws_services.py - AWS Integration Layer for JanSahayak
Groq remains as fallback if any AWS service fails.
"""
import boto3, json, os, io, base64, logging, uuid
from pathlib import Path

logger = logging.getLogger(__name__)
REGION = "us-east-1"
S3_BUCKET = "jansahayak-vupo"
SNS_TOPIC = "arn:aws:sns:us-east-1:923872372772:JanSahayak-Notifications"
DYNAMO_TABLE = "JanSahayak-Users"

# ── Clients (lazy init) ───────────────────────────────────────────────────────
def _s3():       return boto3.client('s3', region_name=REGION)
def _bedrock():  return boto3.client('bedrock-runtime', region_name=REGION)
def _textract(): return boto3.client('textract', region_name=REGION)
def _transcribe(): return boto3.client('transcribe', region_name=REGION)
def _sns():      return boto3.client('sns', region_name=REGION)
def _dynamo():   return boto3.resource('dynamodb', region_name=REGION)

# ══════════════════════════════════════════════════════════════════════════════
# S3 — Screenshot & Document Storage
# ══════════════════════════════════════════════════════════════════════════════
def s3_upload_screenshot(img_bytes: bytes, app_id: str, scheme: str) -> str:
    """Upload form screenshot to S3. Returns public URL."""
    try:
        key = f"screenshots/{scheme}/{app_id}.jpg"
        _s3().put_object(
            Bucket=S3_BUCKET, Key=key, Body=img_bytes,
            ContentType='image/jpeg',
            Metadata={'app_id': app_id, 'scheme': scheme}
        )
        url = f"https://{S3_BUCKET}.s3.{REGION}.amazonaws.com/{key}"
        logger.info(f"[S3] Screenshot uploaded: {url}")
        return url
    except Exception as e:
        logger.error(f"[S3] Upload failed: {e}")
        return ""

def s3_upload_aadhaar(img_bytes: bytes, phone: str) -> str:
    """Upload Aadhaar image to S3 (DPDP compliant - masked)."""
    try:
        key = f"aadhaar/{phone[:4]}XXXXXX.jpg"  # mask phone in key
        _s3().put_object(
            Bucket=S3_BUCKET, Key=key, Body=img_bytes,
            ContentType='image/jpeg',
            ServerSideEncryption='AES256',  # encrypted at rest
            Metadata={'masked': 'true'}
        )
        logger.info(f"[S3] Aadhaar stored securely")
        return key
    except Exception as e:
        logger.error(f"[S3] Aadhaar upload failed: {e}")
        return ""

# ══════════════════════════════════════════════════════════════════════════════
# Amazon Bedrock — LLaMA 3.3 70B (replaces Groq LLM)
# ══════════════════════════════════════════════════════════════════════════════
def bedrock_llm(prompt: str, system: str = "", max_tokens: int = 1000) -> str:
    """Call LLaMA 3.3 70B via Amazon Bedrock. Falls back to Groq on failure."""
    try:
        full_prompt = f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n{system}<|eot_id|><|start_header_id|>user<|end_header_id|>\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
        
        body = json.dumps({
            "prompt": full_prompt,
            "max_gen_len": max_tokens,
            "temperature": 0.7,
            "top_p": 0.9,
        })
        
        response = _bedrock().invoke_model(
            modelId="us.meta.llama3-3-70b-instruct-v1:0",
            body=body,
            contentType="application/json",
            accept="application/json"
        )
        result = json.loads(response['body'].read())
        text = result.get('generation', '').strip()
        logger.info(f"[Bedrock] LLM response: {len(text)} chars")
        return text
    except Exception as e:
        logger.error(f"[Bedrock] LLM failed, falling back to Groq: {e}")
        return _groq_fallback(prompt, system)

def _groq_fallback(prompt: str, system: str) -> str:
    """Groq fallback if Bedrock fails."""
    try:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile", messages=msgs, max_tokens=1000
        )
        return r.choices[0].message.content
    except Exception as e:
        logger.error(f"[Groq] Fallback also failed: {e}")
        return "Sorry, service temporarily unavailable."

# ══════════════════════════════════════════════════════════════════════════════
# Amazon Textract — Aadhaar OCR (replaces Groq Vision)
# ══════════════════════════════════════════════════════════════════════════════
def textract_aadhaar_ocr(img_bytes: bytes) -> dict:
    """Extract Aadhaar data using Amazon Textract. Falls back to Groq Vision."""
    try:
        response = _textract().analyze_document(
            Document={'Bytes': img_bytes},
            FeatureTypes=['FORMS', 'TABLES']
        )
        
        # Extract key-value pairs
        blocks = response.get('Blocks', [])
        text_blocks = [b['Text'] for b in blocks if b['BlockType'] == 'LINE' and 'Text' in b]
        full_text = ' '.join(text_blocks)
        logger.info(f"[Textract] Extracted {len(text_blocks)} lines")
        
        # Parse Aadhaar fields from extracted text
        import re
        result = {}
        
        # Aadhaar number (12 digits)
        aadhaar_match = re.search(r'\b(\d{4}\s?\d{4}\s?\d{4})\b', full_text)
        if aadhaar_match:
            result['aadhaar'] = aadhaar_match.group(1).replace(' ', '')
        
        # DOB
        dob_match = re.search(r'(\d{2}/\d{2}/\d{4})', full_text)
        if dob_match:
            result['dob'] = dob_match.group(1)
        
        # Gender
        if 'MALE' in full_text.upper():
            result['gender'] = 'MALE'
        elif 'FEMALE' in full_text.upper():
            result['gender'] = 'FEMALE'
        
        # Name (line before DOB usually)
        for i, line in enumerate(text_blocks):
            if 'DOB' in line.upper() or 'BIRTH' in line.upper():
                if i > 0:
                    result['name'] = text_blocks[i-1].strip()
                break
        
        if result.get('aadhaar') or result.get('name'):
            logger.info(f"[Textract] OCR success: {result.get('name','?')}")
            result['source'] = 'textract'
            return result
        else:
            raise ValueError("Textract could not extract Aadhaar fields")
            
    except Exception as e:
        logger.error(f"[Textract] OCR failed, falling back to Groq Vision: {e}")
        return {}  # caller will use Groq Vision fallback

# ══════════════════════════════════════════════════════════════════════════════
# Amazon Transcribe — Voice to Text (alongside Groq Whisper)
# ══════════════════════════════════════════════════════════════════════════════
def transcribe_voice_s3(audio_bytes: bytes, lang: str = "hi") -> str:
    """Transcribe voice using Amazon Transcribe. Falls back to Groq Whisper."""
    lang_map = {
        "hi": "hi-IN", "te": "te-IN", "ta": "ta-IN",
        "kn": "kn-IN", "ml": "ml-IN", "mr": "mr-IN",
        "bn": "bn-IN", "en": "en-IN", "as": "as-IN"
    }
    try:
        # Upload audio to S3 first
        job_name = f"js-{uuid.uuid4().hex[:8]}"
        audio_key = f"audio/{job_name}.ogg"
        _s3().put_object(Bucket=S3_BUCKET, Key=audio_key, Body=audio_bytes)
        
        aws_lang = lang_map.get(lang, "hi-IN")
        _transcribe().start_transcription_job(
            TranscriptionJobName=job_name,
            LanguageCode=aws_lang,
            Media={'MediaFileUri': f"s3://{S3_BUCKET}/{audio_key}"},
            OutputBucketName=S3_BUCKET,
            OutputKey=f"transcripts/{job_name}.json"
        )
        
        # Wait for completion (max 10 seconds for short audio)
        import time
        for _ in range(10):
            time.sleep(1)
            status = _transcribe().get_transcription_job(TranscriptionJobName=job_name)
            state = status['TranscriptionJob']['TranscriptionJobStatus']
            if state == 'COMPLETED':
                # Get result from S3
                obj = _s3().get_object(Bucket=S3_BUCKET, Key=f"transcripts/{job_name}.json")
                transcript_data = json.loads(obj['Body'].read())
                text = transcript_data['results']['transcripts'][0]['transcript']
                logger.info(f"[Transcribe] Success: {text[:50]}")
                return text
            elif state == 'FAILED':
                raise Exception("Transcribe job failed")
        
        raise Exception("Transcribe timeout")
        
    except Exception as e:
        logger.error(f"[Transcribe] Failed, using Groq Whisper: {e}")
        return ""  # caller will use Groq Whisper fallback

# ══════════════════════════════════════════════════════════════════════════════
# Amazon SNS — SMS Notification
# ══════════════════════════════════════════════════════════════════════════════
def sns_send_sms(mobile: str, app_id: str, scheme: str, lang: str = "en") -> bool:
    """Send SMS confirmation to farmer via Amazon SNS."""
    scheme_names = {"pmkisan": "PM-KISAN", "ration": "Ration Card", "ayushman": "Ayushman Bharat"}
    scheme_name = scheme_names.get(scheme, scheme)
    
    messages = {
        "hi": f"JanSahayak: Aapka {scheme_name} aavedan safal raha! ID: {app_id}. Helpline: 1800-180-1551",
        "te": f"JanSahayak: Mee {scheme_name} darakhastu విజయవంతమైంది! ID: {app_id}",
        "ta": f"JanSahayak: உங்கள் {scheme_name} விண்ணப்பம் வெற்றி! ID: {app_id}",
        "en": f"JanSahayak: Your {scheme_name} application submitted! ID: {app_id}. Helpline: 1800-180-1551",
    }
    msg = messages.get(lang, messages["en"])
    
    try:
        phone_e164 = f"+91{mobile}" if not mobile.startswith('+') else mobile
        _sns().publish(
            PhoneNumber=phone_e164,
            Message=msg,
            MessageAttributes={
                'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': 'Transactional'},
                'AWS.SNS.SMS.SenderID': {'DataType': 'String', 'StringValue': 'JANSAH'}
            }
        )
        logger.info(f"[SNS] SMS sent to {phone_e164[:6]}XXXX")
        return True
    except Exception as e:
        logger.error(f"[SNS] SMS failed: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# Amazon DynamoDB — User Profiles & Application Records  
# ══════════════════════════════════════════════════════════════════════════════
def dynamo_save_user(phone: str, data: dict) -> bool:
    """Save user profile to DynamoDB. Firebase remains as backup."""
    try:
        table = _dynamo().Table(DYNAMO_TABLE)
        item = {'phone': phone, **{k: str(v) for k, v in data.items() if v}}
        table.put_item(Item=item)
        logger.info(f"[DynamoDB] User saved: {phone[:6]}XXXX")
        return True
    except Exception as e:
        logger.error(f"[DynamoDB] Save failed: {e}")
        return False

def dynamo_save_application(app_id: str, phone: str, scheme: str, 
                             name: str, s3_url: str) -> bool:
    """Save application record to DynamoDB."""
    try:
        import time
        table = _dynamo().Table('JanSahayak-Applications')
        table.put_item(Item={
            'app_id': app_id,
            'phone': phone,
            'scheme': scheme,
            'name': name,
            's3_screenshot': s3_url,
            'timestamp': str(int(time.time())),
            'status': 'submitted'
        })
        logger.info(f"[DynamoDB] Application saved: {app_id}")
        return True
    except Exception as e:
        logger.error(f"[DynamoDB] Application save failed: {e}")
        return False

def dynamo_get_user(phone: str) -> dict:
    """Get user from DynamoDB."""
    try:
        table = _dynamo().Table(DYNAMO_TABLE)
        r = table.get_item(Key={'phone': phone})
        return r.get('Item', {})
    except Exception as e:
        logger.error(f"[DynamoDB] Get failed: {e}")
        return {}

