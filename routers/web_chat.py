import os
import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from firebase_admin import firestore
from routers.chat import get_llm_response, extract_options_tag, transcribe_audio, t, resolve_callback
from routers.rpa_queue import add_rpa_job
from routers.documents import run_aadhaar_ocr
from services import ai_provider

logger = logging.getLogger("web_chat")
router = APIRouter(prefix="/api/web-chat", tags=["web_chat"])

# Helper to get Firestore DB
def _db():
    return firestore.client()

class MessageRequest(BaseModel):
    session_id: str
    message: str
    language: Optional[str] = "en"
    scheme: Optional[str] = None
    mobile: Optional[str] = None

class SubmitRequest(BaseModel):
    session_id: str
    scheme: str
    user_data: Dict[str, Any]

@router.post("/message")
async def process_message(req: MessageRequest):
    session_id = req.session_id.strip()
    user_msg = req.message.strip()
    lang = req.language or "en"
    scheme = req.scheme
    
    db = _db()
    user_ref = db.collection("web_users").document(session_id)
    user_doc = user_ref.get()
    user_data = user_doc.to_dict() if user_doc.exists else {}
    
    # Resolve callback button values to clean human-readable text (same as Telegram)
    resolved = resolve_callback(user_msg)
    if resolved:
        user_msg = resolved
        logger.info(f"[WebChat] Resolved callback {req.message} to: '{user_msg}'")
    
    # Intercept language selection clicks
    if user_msg.startswith("lang_"):
        chosen_lang = user_msg.replace("lang_", "")
        confirm_txt = t(chosen_lang, "lang_confirm")
        prompt_txt = t(chosen_lang, "scheme_prompt")
        reply = f"{confirm_txt}<br><br>{prompt_txt}"
        
        user_ref.set({
            "language": chosen_lang,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }, merge=True)
        
        return {"reply": reply, "tag": "schemes"}
    
    # Intercept final confirmation step
    if user_msg.lower() in ["yes", "ans_yes", "yes ✅"] and user_data.get("step") == "confirmed":
        processing_msgs = {
            "en": "⚙️ Processing your application... please wait.",
            "hi": "⚙️ आवेदन प्रक्रिया में है... कृपया प्रतीक्षा करें।",
            "te": "⚙️ దరఖాస్తు ప్రక్రియలో ఉంది... దయచేసి వేచి ఉండండి.",
            "ta": "⚙️ விண்ணப்பம் செயலாக்கப்படுகிறது...",
            "mr": "⚙️ अर्ज प्रक्रियेत आहे... थांबा.",
            "kn": "⚙️ ಅರ್ಜಿ ಪ್ರಕ್ರಿಯೆಯಲ್ಲಿದೆ...",
            "ml": "⚙️ അപേക്ഷ പ്രോസസ് ചെയ്യുന്നു...",
            "bn": "⚙️ আবেদন প্রক্রিয়া চলছে...",
            "as": "⚙️ আবেদন প্ৰক্ৰিয়া চলిছে...",
        }
        reply = processing_msgs.get(lang, processing_msgs["en"])
        user_ref.set({
            "step": "submitted",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }, merge=True)
        return {"reply": reply, "tag": ""}

    # Extract and cache mobile number
    mobile_num = req.mobile or user_data.get("mobile")
    if req.mobile and req.mobile != user_data.get("mobile"):
        user_ref.set({"mobile": req.mobile}, merge=True)
        user_data["mobile"] = req.mobile

    history = user_data.get("history", [])
    
    # Generate LLM reply (passing verified mobile number to fulfill Rule 7)
    llm_response = get_llm_response(history, user_msg, lang, scheme, mobile=mobile_num)
    cleaned, tag = extract_options_tag(llm_response)
    
    # Detect if summary/confirm step is presented
    step = user_data.get("step", "")
    if tag == "yes_no" and ("submit" in cleaned.lower() or "summary" in cleaned.lower() or "సమర్పించ" in cleaned or "జమ" in cleaned or "सारांश" in cleaned):
        step = "confirmed"
        logger.info("[WebChat] Set user session step to: 'confirmed'")

    # Append to history
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": cleaned})
    
    # Keep history under 20 messages
    if len(history) > 20:
        history = history[-20:]
        
    # Save back to firestore
    user_ref.set({
        "history": history,
        "language": lang,
        "scheme": scheme,
        "step": step,
        "mobile": mobile_num,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }, merge=True)
    
    return {"reply": cleaned, "tag": tag}

@router.post("/voice")
async def transcribe_voice(file: UploadFile = File(...), language: Optional[str] = "en"):
    try:
        content = await file.read()
        transcription = transcribe_audio(content, language)
        if not transcription:
            raise HTTPException(status_code=400, detail="Transcription failed")
        return {"transcription": transcription}
    except Exception as e:
        logger.error(f"Voice transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ocr")
async def ocr_document(file: UploadFile = File(...)):
    try:
        content = await file.read()
        ocr_data = run_aadhaar_ocr(content)
        if not ocr_data:
            raise HTTPException(status_code=400, detail="OCR returned empty/invalid response")
        return ocr_data
    except Exception as e:
        logger.error(f"OCR processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/submit")
async def submit_web_application(req: SubmitRequest):
    try:
        db = _db()
        job_id = "JS" + uuid.uuid4().hex[:6].upper()
        
        # Save to applications collection
        app_entry = {
            "application_id": job_id,
            "scheme": req.scheme,
            "user_data": req.user_data,
            "status": "Under Review",
            "submission_date": datetime.now(timezone.utc).isoformat(),
            "name": req.user_data.get("name", "Unknown Applicant"),
            "mobile": req.user_data.get("mobile", ""),
            "aadhaar_masked": req.user_data.get("aadhaar_masked", "") or req.user_data.get("aadhaar", "")[-4:].rjust(12, "*")
        }
        
        db.collection("applications").document(job_id).set(app_entry)
        
        # Guest-to-Registered sync: directly save their profile in the auth/users table
        mobile_clean = req.user_data.get("mobile", "").replace("+91","").strip()
        if mobile_clean:
            db.collection("users").document(mobile_clean).set({
                "name": req.user_data.get("name", ""),
                "mobile": mobile_clean,
                "address": req.user_data.get("address", ""),
                "state": req.user_data.get("state", ""),
                "district": req.user_data.get("district", ""),
                "pincode": req.user_data.get("pincode", ""),
                "registered_via": "web_guest",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }, merge=True)
            logger.info(f"[Auth-Sync] Saved guest user profile to users/{mobile_clean}")
            
        # Trigger RPA with aligned job_id
        add_rpa_job(req.scheme, req.user_data, req.session_id, job_id=job_id)
        
        return {"status": "success", "job_id": job_id}
    except Exception as e:
        logger.error(f"Application submission failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/applications")
async def list_applications():
    try:
        db = _db()
        docs = db.collection("applications").order_by("submission_date", direction=firestore.Query.DESCENDING).limit(50).get()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        logger.error(f"Failed to list applications: {e}")
        return []
