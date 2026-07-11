"""
services/ibm_services.py - IBM Cloud Integration Layer for JanSahayak
Mirrors the exact function signatures used in aws_services.py.
Called exclusively from services/ai_provider.py — never imported directly.

Packages required:
  ibm-watsonx-ai   → Granite LLM + Vision (foundation model inference)
  ibm-watson       → Watson Speech to Text (classic Watson services)
  ibm-cloud-sdk-core → shared IAM auth
"""
import os
import io
import re
import json
import uuid
import base64
import logging
import time

logger = logging.getLogger(__name__)

# ── Config from env vars ───────────────────────────────────────────────────────
WATSONX_API_KEY    = os.getenv("IBM_WATSONX_API_KEY", "")
WATSONX_PROJECT_ID = os.getenv("IBM_WATSONX_PROJECT_ID", "")
WATSONX_URL        = os.getenv("IBM_WATSONX_URL", "https://eu-gb.ml.cloud.ibm.com")

# Text model — confirmed via SDK ChatModels.GRANITE_3_3_8B_INSTRUCT
IBM_LLM_MODEL_ID    = os.getenv("IBM_LLM_MODEL_ID", "ibm/granite-3-3-8b-instruct")

# Vision model — override via env var; falls back to Tesseract on ModelNotFound
IBM_VISION_MODEL_ID = os.getenv("IBM_VISION_MODEL_ID", "ibm/granite-vision-3-2-2b")
logger.info(f"[IBM] Vision model: {IBM_VISION_MODEL_ID} (override via IBM_VISION_MODEL_ID)")

STT_APIKEY = os.getenv("IBM_SPEECH_TO_TEXT_APIKEY", "")
STT_URL    = os.getenv("IBM_SPEECH_TO_TEXT_URL", "")

COS_APIKEY      = os.getenv("IBM_COS_APIKEY", "")
COS_INSTANCE_ID = os.getenv("IBM_COS_INSTANCE_ID", "")
COS_ENDPOINT    = os.getenv("IBM_COS_ENDPOINT", "")
COS_BUCKET      = os.getenv("IBM_COS_BUCKET", "jansahayak-ibm")

CLOUDANT_URL    = os.getenv("IBM_CLOUDANT_URL", "")
CLOUDANT_APIKEY = os.getenv("IBM_CLOUDANT_APIKEY", "")


# ── Lazy client factories ──────────────────────────────────────────────────────

def _watsonx_client():
    """Return an ibm-watsonx-ai APIClient."""
    from ibm_watsonx_ai import APIClient, Credentials
    creds = Credentials(url=WATSONX_URL, api_key=WATSONX_API_KEY)
    return APIClient(creds)


def _watsonx_model(model_id: str):
    """Return a watsonx ModelInference instance."""
    from ibm_watsonx_ai.foundation_models import ModelInference
    return ModelInference(
        model_id=model_id,
        credentials={"url": WATSONX_URL, "apikey": WATSONX_API_KEY},
        project_id=WATSONX_PROJECT_ID,
    )


def _stt_client():
    """Return a Watson SpeechToTextV1 client."""
    from ibm_watson import SpeechToTextV1
    from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
    auth = IAMAuthenticator(STT_APIKEY)
    stt = SpeechToTextV1(authenticator=auth)
    stt.set_service_url(STT_URL)
    return stt


def _cos_client():
    """Return a boto3 S3 client configured for IBM COS."""
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=COS_ENDPOINT,
        aws_access_key_id=COS_APIKEY,
        aws_secret_access_key=COS_INSTANCE_ID,  # COS uses resource instance ID as secret
        region_name="eu-gb",
    )


def _cloudant_headers() -> dict:
    """Obtain a short-lived IAM bearer token for Cloudant REST calls."""
    import requests
    resp = requests.post(
        "https://iam.cloud.ibm.com/identity/token",
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": CLOUDANT_APIKEY,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ══════════════════════════════════════════════════════════════════════════════
# LLM — watsonx.ai Granite (mirrors bedrock_llm)
# ══════════════════════════════════════════════════════════════════════════════

def ibm_llm(prompt: str, system: str = "", max_tokens: int = 1000) -> str:
    """
    Call ibm/granite-3-3-8b-instruct via watsonx.ai.
    Signature mirrors aws_services.bedrock_llm(prompt, system, max_tokens) → str.
    """
    model = _watsonx_model(IBM_LLM_MODEL_ID)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = model.chat(
        messages=messages,
        params={"max_new_tokens": max_tokens, "temperature": 0.7, "top_p": 0.9},
    )
    # ibm-watsonx-ai chat() returns a dict with choices[].message.content
    text = response["choices"][0]["message"]["content"].strip()
    logger.info(f"[IBM-LLM] Response: {len(text)} chars via {IBM_LLM_MODEL_ID}")
    return text


# ══════════════════════════════════════════════════════════════════════════════
# OCR — Granite Vision + Tesseract fallback (mirrors textract_aadhaar_ocr)
# ══════════════════════════════════════════════════════════════════════════════

def ibm_ocr_aadhaar(img_bytes: bytes) -> dict:
    """
    Extract Aadhaar data using Granite Vision via watsonx.ai.
    Signature mirrors aws_services.textract_aadhaar_ocr(img_bytes) → dict.

    Raises on ANY failure — no internal fallback.
    The caller (ai_provider.ocr_document) is solely responsible for
    deciding whether to fall back to Tesseract or AWS Textract.
    """
    result = _granite_vision_ocr(img_bytes)   # raises on any network/model/parse error
    if not (result.get("aadhaar") or result.get("name")):
        raise ValueError(
            f"Granite Vision returned a response but extracted no Aadhaar fields: {result}"
        )
    result["source"] = "ibm_granite_vision"
    logger.info(f"[IBM-OCR] Granite Vision success: {result.get('name','?')}")
    return result


def _granite_vision_ocr(img_bytes: bytes) -> dict:
    """Use Granite Vision model via watsonx.ai for Aadhaar OCR."""
    image_b64 = base64.b64encode(img_bytes).decode("utf-8")

    model = _watsonx_model(IBM_VISION_MODEL_ID)
    prompt_text = (
        "This is an Aadhaar card image. Extract ALL fields carefully and return "
        "ONLY a valid JSON object with no extra text:\n"
        '{\n  "name": "full name in English",\n  "aadhaar": "12 digit number no spaces",\n'
        '  "dob": "DD/MM/YYYY",\n  "gender": "Male or Female",\n'
        '  "address": "full address string",\n  "district": "district name",\n'
        '  "state": "state name",\n  "pincode": "6 digit pincode"\n}\n'
        "If any field not found use null. Return ONLY the JSON, nothing else."
    )

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                },
                {"type": "text", "text": prompt_text},
            ],
        }
    ]

    response = model.chat(messages=messages, params={"max_new_tokens": 600})
    raw = response["choices"][0]["message"]["content"].strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    result = json.loads(raw)

    # Clean aadhaar digits
    if result.get("aadhaar"):
        result["aadhaar"] = re.sub(r"\D", "", str(result["aadhaar"]))[:12]
    # Derive pincode from address if missing
    if not result.get("pincode") and result.get("address"):
        m = re.search(r"\b(\d{6})\b", result["address"])
        if m:
            result["pincode"] = m.group(1)
    # Mask aadhaar
    if result.get("aadhaar") and len(result["aadhaar"]) == 12:
        result["aadhaar_masked"] = "XXXX XXXX " + result["aadhaar"][-4:]

    return result


def tesseract_ocr(img_bytes: bytes) -> dict:
    """
    Local Tesseract OCR — pytesseract is already a dependency.

    This is a standalone helper, NOT an internal fallback.
    Called directly by ai_provider.ocr_document() as a last resort after
    both IBM Granite Vision AND AWS Textract have failed.

    Raises on failure so ai_provider can log/handle it.
    """
    import pytesseract
    from PIL import Image

    img = Image.open(io.BytesIO(img_bytes))
    full_text = pytesseract.image_to_string(img)
    if not full_text.strip():
        raise ValueError("Tesseract returned empty text — image may be unreadable")

    logger.info(f"[Tesseract] Extracted {len(full_text)} chars")

    result: dict = {
        "name": None, "aadhaar": None, "dob": None, "gender": None,
        "address": None, "district": None, "state": None, "pincode": None,
        "source": "tesseract",
    }

    m = re.search(r"\b(\d{4}\s?\d{4}\s?\d{4})\b", full_text)
    if m:
        result["aadhaar"] = re.sub(r"\s", "", m.group(1))
        result["aadhaar_masked"] = "XXXX XXXX " + result["aadhaar"][-4:]

    m = re.search(r"\b(\d{2}[/\-]\d{2}[/\-]\d{4})\b", full_text)
    if m:
        result["dob"] = m.group(1).replace("-", "/")

    if re.search(r"\bMALE\b", full_text, re.IGNORECASE):
        result["gender"] = "MALE"
    elif re.search(r"\bFEMALE\b", full_text, re.IGNORECASE):
        result["gender"] = "FEMALE"

    m = re.search(r"\b(\d{6})\b", full_text)
    if m:
        result["pincode"] = m.group(1)

    return result


# Keep the old private name as an alias so nothing breaks if referenced elsewhere
_tesseract_ocr_fallback = tesseract_ocr


# ══════════════════════════════════════════════════════════════════════════════
# Speech-to-Text — Watson STT (mirrors transcribe_voice_s3)
# ══════════════════════════════════════════════════════════════════════════════

# Watson STT model IDs for Indian languages
_STT_LANG_MAP = {
    "hi": "hi-IN_Telephony",
    "te": "en-IN_Telephony",   # Telugu not yet available; use en-IN
    "ta": "en-IN_Telephony",   # Tamil — en-IN fallback
    "kn": "en-IN_Telephony",
    "ml": "en-IN_Telephony",
    "mr": "hi-IN_Telephony",
    "bn": "en-IN_Telephony",
    "as": "en-IN_Telephony",
    "en": "en-IN_Telephony",
}


def ibm_transcribe_audio(audio_bytes: bytes, lang: str = "hi") -> str:
    """
    Transcribe voice note via Watson Speech to Text.
    Signature mirrors aws_services.transcribe_voice_s3(audio_bytes, lang) → str.
    """
    model = _STT_LANG_MAP.get(lang, "en-IN_Telephony")
    stt = _stt_client()

    result = stt.recognize(
        audio=io.BytesIO(audio_bytes),
        content_type="audio/ogg",
        model=model,
        max_alternatives=1,
    ).get_result()

    transcripts = result.get("results", [])
    if not transcripts:
        raise ValueError("Watson STT returned no transcription results")

    text = transcripts[0]["alternatives"][0]["transcript"].strip()
    logger.info(f"[IBM-STT] Transcribed {len(text)} chars via Watson ({model})")
    return text


# ══════════════════════════════════════════════════════════════════════════════
# Object Storage — IBM COS via boto3 S3-compatible API (mirrors s3_upload_*)
# ══════════════════════════════════════════════════════════════════════════════

def ibm_upload_screenshot(img_bytes: bytes, app_id: str, scheme: str) -> str:
    """
    Upload form screenshot to IBM COS. Returns public URL.
    Mirrors aws_services.s3_upload_screenshot(img_bytes, app_id, scheme) → str.
    """
    key = f"screenshots/{scheme}/{app_id}.jpg"
    _cos_client().put_object(
        Bucket=COS_BUCKET,
        Key=key,
        Body=img_bytes,
        ContentType="image/jpeg",
        Metadata={"app_id": app_id, "scheme": scheme},
    )
    url = f"{COS_ENDPOINT}/{COS_BUCKET}/{key}"
    logger.info(f"[IBM-COS] Screenshot uploaded: {url}")
    return url


def ibm_upload_aadhaar(img_bytes: bytes, phone: str) -> str:
    """
    Upload masked Aadhaar image to IBM COS.
    Mirrors aws_services.s3_upload_aadhaar(img_bytes, phone) → str.
    """
    key = f"aadhaar/{phone[:4]}XXXXXX.jpg"
    _cos_client().put_object(
        Bucket=COS_BUCKET,
        Key=key,
        Body=img_bytes,
        ContentType="image/jpeg",
        Metadata={"masked": "true"},
    )
    logger.info(f"[IBM-COS] Aadhaar stored securely")
    return key


# ══════════════════════════════════════════════════════════════════════════════
# Cloudant — Document Store (mirrors DynamoDB save/get)
# ══════════════════════════════════════════════════════════════════════════════

def _cloudant_request(method: str, path: str, data: dict = None) -> dict:
    """Make an authenticated HTTP request to Cloudant REST API."""
    import requests
    headers = _cloudant_headers()
    url = f"{CLOUDANT_URL.rstrip('/')}/{path}"
    if method == "GET":
        resp = requests.get(url, headers=headers, timeout=15)
    elif method == "PUT":
        resp = requests.put(url, headers=headers, json=data, timeout=15)
    elif method == "POST":
        resp = requests.post(url, headers=headers, json=data, timeout=15)
    else:
        raise ValueError(f"Unsupported method: {method}")
    resp.raise_for_status()
    return resp.json()


def ibm_db_write(collection: str, doc_id: str, data: dict) -> bool:
    """
    Write a document to IBM Cloudant.
    collection maps to a Cloudant database name.
    Mirrors aws_services.dynamo_save_user / dynamo_save_application signatures.

    Raises on any unexpected failure so ai_provider.py can trigger AWS fallback.
    Only two specific HTTP status codes are intentionally silenced:
      - HTTP 412 Precondition Failed: database already exists (PUT /db is idempotent)
      - HTTP 404 Not Found:           document is new, no _rev needed yet
    Everything else (401 auth error, 408/504 timeout, 5xx server error, DNS
    failure, etc.) propagates as-is.
    """
    import requests as _requests

    # ── Step 1: Ensure database exists (idempotent PUT) ───────────────────────
    try:
        _cloudant_request("PUT", collection)
    except _requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 412:
            pass  # 412 Precondition Failed = DB already exists; expected, ignored
        else:
            raise  # 401, 403, 5xx, etc. → propagate to ai_provider fallback

    doc = {"_id": doc_id, **{k: str(v) for k, v in data.items() if v is not None}}

    # ── Step 2: Fetch _rev for existing documents (required for Cloudant updates) ─
    try:
        existing = _cloudant_request("GET", f"{collection}/{doc_id}")
        doc["_rev"] = existing["_rev"]
    except _requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            pass  # 404 Not Found = new document; no _rev needed; expected, ignored
        else:
            raise  # 401, 403, 5xx, etc. → propagate to ai_provider fallback

    # ── Step 3: Write the document — any failure MUST propagate ──────────────
    _cloudant_request("PUT", f"{collection}/{doc_id}", doc)
    logger.info(f"[IBM-Cloudant] Written {collection}/{doc_id}")
    return True



def ibm_db_read(collection: str, doc_id: str) -> dict:
    """
    Read a document from IBM Cloudant.
    Mirrors aws_services.dynamo_get_user(phone) → dict.
    """
    result = _cloudant_request("GET", f"{collection}/{doc_id}")
    # Strip Cloudant internal fields before returning
    return {k: v for k, v in result.items() if not k.startswith("_")}
