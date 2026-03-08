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
# Amazon Textract + LLaMA Hybrid Aadhaar OCR
# ══════════════════════════════════════════════════════════════════════════════
INDIAN_STATES = {
    'andhra pradesh','arunachal pradesh','assam','bihar','chhattisgarh',
    'goa','gujarat','haryana','himachal pradesh','jharkhand','karnataka',
    'kerala','madhya pradesh','maharashtra','manipur','meghalaya','mizoram',
    'nagaland','odisha','punjab','rajasthan','sikkim','tamil nadu','telangana',
    'tripura','uttar pradesh','uttarakhand','west bengal','delhi','jammu',
    'kashmir','ladakh','puducherry','chandigarh','andaman','nicobar',
    'dadra','daman','lakshadweep'
}

def _is_likely_name(text: str) -> bool:
    import re
    t = text.strip().lower()
    if not t or len(t) < 3: return False
    if any(k in t for k in [
        'street','road','nagar','colony','ward','village','post','dist',
        'pin','state','near','opp','plot','flat','house','floor','door',
        'mandal','taluk','tehsil','block','sector','phase','layout',
        's/o','d/o','w/o','c/o','h/no','vill','po ','government','india',
        'unique','authority','uidai','enrollment','enrolment'
    ]): return False
    for s in INDIAN_STATES:
        if s in t: return False
    if re.search(r'\d', t): return False
    if len(t.split()) > 5: return False
    alpha_ratio = sum(c.isalpha() or c == ' ' for c in t) / max(len(t), 1)
    if alpha_ratio < 0.85: return False
    return True

def _llama_parse_aadhaar(raw_text: str) -> dict:
    import json, re, boto3
    prompt = """You are an Aadhaar card parser. Extract fields from this OCR text.
IMPORTANT: 
- name = person full name ONLY (e.g. "Ramu Yadav"). NOT state, district, village, or address words.
- dob = DD/MM/YYYY format
- gender = MALE or FEMALE
- aadhaar = 12 digit number
- address = full address
- state = Indian state from address
- district = district from address  
- pincode = 6 digit PIN

Return ONLY valid JSON, no explanation.

OCR TEXT:
""" + raw_text + """

JSON:"""
    try:
        bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
        body = json.dumps({
            "prompt": f"<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n",
            "max_gen_len": 400, "temperature": 0.0,
        })
        response = bedrock.invoke_model(
            modelId="us.meta.llama3-3-70b-instruct-v1:0",
            body=body, contentType="application/json", accept="application/json"
        )
        text = json.loads(response['body'].read()).get('generation', '')
        match = re.search(r'\{.*?\}', text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            logger.info(f"[LLaMA-OCR] name={parsed.get('name','?')}, state={parsed.get('state','?')}")
            return parsed
    except Exception as e:
        logger.error(f"[LLaMA-OCR] Failed: {e}")
    return {}

def _groq_vision_ocr(img_bytes: bytes) -> dict:
    import base64, json, re
    try:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        b64 = base64.b64encode(img_bytes).decode()
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": "Extract from Aadhaar: name (person name ONLY not state/address), dob (DD/MM/YYYY), gender, aadhaar (12 digits), address, state, district, pincode. Return ONLY JSON."}
            ]}],
            max_tokens=400, temperature=0.0
        )
        text = response.choices[0].message.content
        match = re.search(r'\{.*?\}', text, re.DOTALL)
        if match:
            result = json.loads(match.group())
            result['source'] = 'groq_vision'
            logger.info(f"[Groq-Vision] name={result.get('name','?')}")
            return result
    except Exception as e:
        logger.error(f"[Groq-Vision] Failed: {e}")
    return {}

def textract_aadhaar_ocr(img_bytes: bytes) -> dict:
    """Hybrid OCR: Textract raw text -> LLaMA semantic parse -> Groq Vision fallback -> Regex last resort."""
    import re
    raw_lines = []

    # Stage 1: Textract raw extraction
    try:
        response = _textract().analyze_document(
            Document={'Bytes': img_bytes}, FeatureTypes=['FORMS', 'TABLES']
        )
        blocks = response.get('Blocks', [])
        raw_lines = [b['Text'] for b in blocks if b['BlockType'] == 'LINE' and 'Text' in b]
        logger.info(f"[Textract] Extracted {len(raw_lines)} lines: {raw_lines[:5]}")
    except Exception as e:
        logger.error(f"[Textract] Failed: {e}")

    # Stage 2: LLaMA semantic parsing
    if len(raw_lines) > 3:
        full_text = '\n'.join(raw_lines)
        result = _llama_parse_aadhaar(full_text)
        if result.get('aadhaar'):
            if not _is_likely_name(result.get('name', '')):
                logger.warning(f"[Hybrid-OCR] Bad name from LLaMA: '{result.get('name')}' — filtering")
                for line in raw_lines:
                    if _is_likely_name(line):
                        result['name'] = line.strip()
                        logger.info(f"[Hybrid-OCR] Corrected name: {result['name']}")
                        break
            # Extra blocklist for known junk names
            JUNK_NAMES = ["THE WORK", "GOVERNMENT OF INDIA", "UIDAI", "UNIQUE IDENTIFICATION",
                          "INCOME TAX", "INDIA", "AUTHORITY", "AADHAAR", "AADHAR", "YOUR NAME",
                          "NAME", "DOB", "MALE", "FEMALE", "ADDRESS"]
            if result.get('name', '').upper().strip() in JUNK_NAMES:
                logger.warning(f"[Hybrid-OCR] Junk name blocked: '{result.get('name')}'")
                result['name'] = None
                for line in raw_lines:
                    if _is_likely_name(line) and line.upper().strip() not in JUNK_NAMES:
                        result['name'] = line.strip()
                        logger.info(f"[Hybrid-OCR] Replaced with: {result['name']}")
                        break
            result['source'] = 'textract+llama'
            logger.info(f"[Hybrid-OCR] SUCCESS name={result.get('name')} aadhaar=****{result.get('aadhaar','')[-4:]}")
            return result

    # Stage 3: Groq Vision fallback
    logger.info("[Hybrid-OCR] Trying Groq Vision fallback")
    result = _groq_vision_ocr(img_bytes)
    if result.get('aadhaar') or result.get('name'):
        return result

    # Stage 4: Regex last resort (never return empty)
    logger.warning("[Hybrid-OCR] Using regex last resort")
    result = {'source': 'regex_fallback'}
    full_text = ' '.join(raw_lines)
    m = re.search(r'\b(\d{4}\s?\d{4}\s?\d{4})\b', full_text)
    if m: result['aadhaar'] = m.group(1).replace(' ', '')
    m = re.search(r'(\d{2}/\d{2}/\d{4})', full_text)
    if m: result['dob'] = m.group(1)
    if 'MALE' in full_text.upper(): result['gender'] = 'MALE'
    elif 'FEMALE' in full_text.upper(): result['gender'] = 'FEMALE'
    for line in raw_lines:
        if _is_likely_name(line):
            result['name'] = line.strip()
            break
    return result

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

