"""
services/ai_provider.py - Provider-Agnostic AI Abstraction Layer for JanSahayak

Exposes provider-agnostic functions that route to IBM or AWS based on:
  AI_PROVIDER env var: "aws" (default) or "ibm"

On any IBM call failure:
  - Logs a WARNING with the error
  - Automatically falls back to the equivalent AWS function
  - Logs which provider actually served the request

Shadow Write (DB only):
  DB_SHADOW_WRITE=true  → writes go to BOTH DynamoDB AND Cloudant
  DB_READ_SOURCE=aws    → "aws" or "ibm" controls which DB serves reads

NOTE: sns_send_sms() is intentionally excluded from this abstraction.
      IBM Cloud has no equivalent for transactional A2P SMS.
      All SMS calls remain direct: from aws_services import sns_send_sms
"""
import os
import logging

import aws_services

logger = logging.getLogger(__name__)

_PROVIDER      = lambda: os.getenv("AI_PROVIDER", "aws").lower()
_SHADOW_WRITE  = lambda: os.getenv("DB_SHADOW_WRITE", "false").lower() == "true"
_READ_SOURCE   = lambda: os.getenv("DB_READ_SOURCE", "aws").lower()


def _ibm():
    """Lazy import of ibm_services to avoid hard import failure if SDK not installed."""
    from services import ibm_services
    return ibm_services


def _log_provider(fn_name: str, provider: str) -> None:
    logger.info(f"[AI_PROVIDER] {fn_name} served by: {provider.upper()}")


# ══════════════════════════════════════════════════════════════════════════════
# LLM — Text generation
# ══════════════════════════════════════════════════════════════════════════════

def get_llm_response(prompt: str, system: str = "", max_tokens: int = 1000) -> str:
    """
    Generate LLM response.
    AWS: bedrock_llm (LLaMA 3.3 70B)
    IBM: ibm_llm (Granite 3.3 8B Instruct)
    """
    if _PROVIDER() == "ibm":
        try:
            result = _ibm().ibm_llm(prompt, system, max_tokens)
            _log_provider("get_llm_response", "ibm")
            return result
        except Exception as e:
            logger.warning(f"[AI_PROVIDER] IBM get_llm_response failed → AWS fallback: {e}")

    result = aws_services.bedrock_llm(prompt, system, max_tokens)
    _log_provider("get_llm_response", "aws")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# OCR — Aadhaar card document extraction
# ══════════════════════════════════════════════════════════════════════════════

def ocr_document(img_bytes: bytes) -> dict:
    """
    Extract Aadhaar fields from image bytes.
    Fallback chain (each only attempted if previous raises):
      1. IBM Granite Vision  (when AI_PROVIDER=ibm)
      2. AWS Textract        (always attempted if IBM fails or AI_PROVIDER=aws)
      3. Local Tesseract     (last resort — provider-agnostic, no network call)
    Returns {} only when ALL three levels fail.
    Caller (documents.py) still has its own Groq Vision path after this.
    """
    if _PROVIDER() == "ibm":
        try:
            result = _ibm().ibm_ocr_aadhaar(img_bytes)
            _log_provider("ocr_document", "ibm/granite-vision")
            return result
        except Exception as e:
            logger.warning(f"[AI_PROVIDER] IBM Granite Vision OCR failed → AWS Textract: {e}")

    try:
        result = aws_services.textract_aadhaar_ocr(img_bytes)
        _log_provider("ocr_document", "aws/textract")
        return result
    except Exception as e:
        logger.warning(f"[AI_PROVIDER] AWS Textract OCR failed → Tesseract: {e}")

    # Third resort: local Tesseract — no network, always available
    try:
        result = _ibm().tesseract_ocr(img_bytes)
        _log_provider("ocr_document", "local/tesseract")
        return result
    except Exception as e:
        logger.error(f"[AI_PROVIDER] Tesseract also failed: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# Speech-to-Text — Voice transcription
# ══════════════════════════════════════════════════════════════════════════════

def transcribe_audio(audio_bytes: bytes, lang: str = "hi") -> str:
    """
    Transcribe voice audio bytes to text.
    AWS: transcribe_voice_s3 (Amazon Transcribe)
    IBM: ibm_transcribe_audio (Watson Speech to Text)
    Returns "" on failure — caller should use its own Groq Whisper fallback.
    """
    if _PROVIDER() == "ibm":
        try:
            result = _ibm().ibm_transcribe_audio(audio_bytes, lang)
            _log_provider("transcribe_audio", "ibm")
            return result
        except Exception as e:
            logger.warning(f"[AI_PROVIDER] IBM transcribe_audio failed → AWS fallback: {e}")

    result = aws_services.transcribe_voice_s3(audio_bytes, lang)
    _log_provider("transcribe_audio", "aws")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# File Upload — Screenshots and Aadhaar images
# ══════════════════════════════════════════════════════════════════════════════

def upload_screenshot(img_bytes: bytes, app_id: str, scheme: str) -> str:
    """
    Upload form screenshot to object storage. Returns URL.
    AWS: s3_upload_screenshot
    IBM: ibm_upload_screenshot (IBM COS)
    """
    if _PROVIDER() == "ibm":
        try:
            result = _ibm().ibm_upload_screenshot(img_bytes, app_id, scheme)
            _log_provider("upload_screenshot", "ibm")
            return result
        except Exception as e:
            logger.warning(f"[AI_PROVIDER] IBM upload_screenshot failed → AWS fallback: {e}")

    result = aws_services.s3_upload_screenshot(img_bytes, app_id, scheme)
    _log_provider("upload_screenshot", "aws")
    return result


def upload_aadhaar(img_bytes: bytes, phone: str) -> str:
    """
    Upload masked Aadhaar image to object storage. Returns storage key.
    AWS: s3_upload_aadhaar
    IBM: ibm_upload_aadhaar (IBM COS)
    """
    if _PROVIDER() == "ibm":
        try:
            result = _ibm().ibm_upload_aadhaar(img_bytes, phone)
            _log_provider("upload_aadhaar", "ibm")
            return result
        except Exception as e:
            logger.warning(f"[AI_PROVIDER] IBM upload_aadhaar failed → AWS fallback: {e}")

    result = aws_services.s3_upload_aadhaar(img_bytes, phone)
    _log_provider("upload_aadhaar", "aws")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Database — User profiles and application records
# Shadow write: DB_SHADOW_WRITE=true writes to BOTH providers simultaneously
# DB_READ_SOURCE controls which provider serves reads
# ══════════════════════════════════════════════════════════════════════════════

def db_save_user(phone: str, data: dict) -> bool:
    """
    Save user profile.
    AWS: dynamo_save_user
    IBM: ibm_db_write("jansahayak-users", phone, data)
    """
    primary_provider = _PROVIDER()

    # ── Primary write ──────────────────────────────────────────────────────
    if primary_provider == "ibm":
        try:
            result = _ibm().ibm_db_write("jansahayak-users", phone, data)
            _log_provider("db_save_user[write]", "ibm")
        except Exception as e:
            logger.warning(f"[AI_PROVIDER] IBM db_save_user failed → AWS fallback: {e}")
            result = aws_services.dynamo_save_user(phone, data)
            _log_provider("db_save_user[write/fallback]", "aws")
    else:
        result = aws_services.dynamo_save_user(phone, data)
        _log_provider("db_save_user[write]", "aws")

    # ── Shadow write to the OTHER provider ────────────────────────────────
    if _SHADOW_WRITE():
        if primary_provider == "ibm":
            try:
                aws_services.dynamo_save_user(phone, data)
                logger.info("[AI_PROVIDER] Shadow write to AWS DynamoDB: OK")
            except Exception as e:
                logger.warning(f"[AI_PROVIDER] Shadow write to AWS failed: {e}")
        else:
            try:
                _ibm().ibm_db_write("jansahayak-users", phone, data)
                logger.info("[AI_PROVIDER] Shadow write to IBM Cloudant: OK")
            except Exception as e:
                logger.warning(f"[AI_PROVIDER] Shadow write to IBM failed: {e}")

    return result


def db_save_application(app_id: str, phone: str, scheme: str,
                         name: str, s3_url: str) -> bool:
    """
    Save application record.
    AWS: dynamo_save_application
    IBM: ibm_db_write("jansahayak-applications", app_id, {...})
    """
    import time as _time
    ibm_data = {
        "app_id": app_id, "phone": phone, "scheme": scheme,
        "name": name, "screenshot_url": s3_url,
        "timestamp": str(int(_time.time())), "status": "submitted",
    }
    primary_provider = _PROVIDER()

    if primary_provider == "ibm":
        try:
            result = _ibm().ibm_db_write("jansahayak-applications", app_id, ibm_data)
            _log_provider("db_save_application[write]", "ibm")
        except Exception as e:
            logger.warning(f"[AI_PROVIDER] IBM db_save_application failed → AWS fallback: {e}")
            result = aws_services.dynamo_save_application(app_id, phone, scheme, name, s3_url)
            _log_provider("db_save_application[write/fallback]", "aws")
    else:
        result = aws_services.dynamo_save_application(app_id, phone, scheme, name, s3_url)
        _log_provider("db_save_application[write]", "aws")

    if _SHADOW_WRITE():
        if primary_provider == "ibm":
            try:
                aws_services.dynamo_save_application(app_id, phone, scheme, name, s3_url)
                logger.info("[AI_PROVIDER] Shadow write application to AWS: OK")
            except Exception as e:
                logger.warning(f"[AI_PROVIDER] Shadow write application to AWS failed: {e}")
        else:
            try:
                _ibm().ibm_db_write("jansahayak-applications", app_id, ibm_data)
                logger.info("[AI_PROVIDER] Shadow write application to IBM: OK")
            except Exception as e:
                logger.warning(f"[AI_PROVIDER] Shadow write application to IBM failed: {e}")

    return result


def db_get_user(phone: str) -> dict:
    """
    Get user profile.
    Read source is controlled by DB_READ_SOURCE env var (default: "aws").
    AWS: dynamo_get_user
    IBM: ibm_db_read("jansahayak-users", phone)
    """
    read_source = _READ_SOURCE()

    if read_source == "ibm":
        try:
            result = _ibm().ibm_db_read("jansahayak-users", phone)
            _log_provider("db_get_user[read]", "ibm")
            return result
        except Exception as e:
            logger.warning(f"[AI_PROVIDER] IBM db_get_user failed → AWS fallback: {e}")

    result = aws_services.dynamo_get_user(phone)
    _log_provider("db_get_user[read]", "aws")
    return result
