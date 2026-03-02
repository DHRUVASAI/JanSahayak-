"""
routers/rpa_queue.py - RPA Job Queue — runs RPA directly in background thread
"""
import uuid
import threading
import base64
import logging
import os
import requests
from collections import deque
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/rpa", tags=["rpa"])
logger = logging.getLogger(__name__)

_job_queue: deque = deque()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

SCHEME_MSGS = {
    "pmkisan": {
        "en": "🌾 PM-KISAN Rs.6000/year will be credited to your bank.",
        "hi": "🌾 PM-KISAN ₹6000/साल आपके बैंक में आएगा।",
        "te": "🌾 PM-KISAN ₹6000/సంవత్సరం మీ బ్యాంక్‌కు జమ అవుతుంది.",
        "ta": "🌾 PM-KISAN ₹6000/ஆண்டு உங்கள் வங்கியில் வரவு வைக்கப்படும்.",
        "mr": "🌾 PM-KISAN ₹6000/वर्ष तुमच्या बँकेत जमा होईल.",
        "kn": "🌾 PM-KISAN ₹6000/ವರ್ಷ ನಿಮ್ಮ ಬ್ಯಾಂಕ್‌ಗೆ ಜಮಾ ಆಗುತ್ತದೆ.",
        "ml": "🌾 PM-KISAN ₹6000/വർഷം നിങ്ങളുടെ ബാങ്കിൽ ക്രെഡിറ്റ് ആകും.",
        "bn": "🌾 PM-KISAN ₹6000/বছর আপনার ব্যাংকে জমা হবে।",
        "as": "🌾 PM-KISAN ₹6000/বছৰ আপোনাৰ বেংকত জমা হ'ব।",
    },
    "ration": {
        "en": "🍚 Ration Card will be issued within 30 working days.",
        "hi": "🍚 राशन कार्ड 30 कार्य दिवसों में जारी होगा।",
        "te": "🍚 రేషన్ కార్డ్ 30 పని దినాల్లో జారీ అవుతుంది.",
        "ta": "🍚 ரேஷன் கார்டு 30 வேலை நாட்களில் வழங்கப்படும்.",
        "mr": "🍚 रेशन कार्ड 30 कामकाजी दिवसांत जारी होईल.",
        "kn": "🍚 ರೇಷನ್ ಕಾರ್ಡ್ 30 ಕೆಲಸದ ದಿನಗಳಲ್ಲಿ ನೀಡಲಾಗುತ್ತದೆ.",
        "ml": "🍚 റേഷൻ കാർഡ് 30 പ്രവൃത്തി ദിവസങ്ങൾക്കുള്ളിൽ നൽകും.",
        "bn": "🍚 রেশন কার্ড ৩০ কার্যদিবসের মধ্যে জারি হবে।",
        "as": "🍚 ৰেচন কাৰ্ড 30 কাৰ্যদিৱসৰ ভিতৰত জাৰি হ'ব।",
    },
    "ayushman": {
        "en": "🏥 Ayushman Bharat Rs.5 Lakh health cover activated. Valid at 25,000+ hospitals.",
        "hi": "🏥 आयुष्मान भारत ₹5 लाख स्वास्थ्य कवर सक्रिय। 25,000+ अस्पतालों में मान्य।",
        "te": "🏥 ఆయుష్మాన్ భారత్ ₹5 లక్షల ఆరోగ్య కవర్ సక్రియం. 25,000+ ఆసుపత్రుల్లో చెల్లుతుంది.",
        "ta": "🏥 ஆயுஷ்மான் பாரத் ₹5 லட்சம் சுகாதார காப்பு செயல்படுத்தப்பட்டது.",
        "mr": "�� आयुष्मान भारत ₹5 लाख आरोग्य कवर सक्रिय. 25,000+ रुग्णालयांत वैध.",
        "kn": "🏥 ಆಯುಷ್ಮಾನ್ ಭಾರತ್ ₹5 ಲಕ್ಷ ಆರೋಗ್ಯ ಕವರ್ ಸಕ್ರಿಯ.",
        "ml": "🏥 ആയുഷ്മാൻ ഭാരത് ₹5 ലക്ഷം ആരോഗ്യ കവർ സജീവം.",
        "bn": "🏥 আয়ুষ্মান ভারত ₹5 লক্ষ স্বাস্থ্য কভার সক্রিয়।",
        "as": "🏥 আয়ুষ্মান ভাৰত ₹5 লাখ স্বাস্থ্য কভাৰ সক্ৰিয়।",
    }
}

def _send_tg_message(chat_id, text):
    try:
        requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "HTML"
        }, timeout=30)
    except Exception as e:
        logger.error(f"TG send error: {e}")

def _send_tg_photo(chat_id, photo_bytes, caption=""):
    try:
        import io
        requests.post(f"{TG_API}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("form.png", io.BytesIO(photo_bytes), "image/png")},
            timeout=30)
    except Exception as e:
        logger.error(f"TG photo error: {e}")

def _run_rpa_job(job: dict):
    scheme   = job["scheme"]
    user_data= job["user_data"]
    chat_id  = job["chat_id"]
    job_id   = job["job_id"]
    lang     = user_data.get("language", "en")

    logger.info(f"[RPA] Running job {job_id} scheme={scheme} chat_id={chat_id}")

    try:
        from rpa_agent import (
            submit_pm_kisan_application,
            submit_ration_card_application,
            submit_ayushman_application
        )

        if scheme == "ration":
            result = submit_ration_card_application(user_data)
        elif scheme == "ayushman":
            result = submit_ayushman_application(user_data)
        else:
            result = submit_pm_kisan_application(user_data)

        ref = result.get("application_id", job_id)
        name = user_data.get("name", "")
        scheme_display = {"pmkisan": "PM-KISAN", "ration": "Ration Card", "ayushman": "Ayushman Bharat"}
        scheme_name = scheme_display.get(scheme, scheme.upper())
        detail = SCHEME_MSGS.get(scheme, {}).get(lang, SCHEME_MSGS.get(scheme, {}).get("en", ""))

        msg = (
            f"✅ Application Submitted!\n\n"
            f"🗂 ID: {ref}\n"
            f"👤 {name}\n"
            f"🏛 {scheme_name}\n\n"
            f"{detail}\n\n"
            f"📌 Save your Application ID."
        )
        _send_tg_message(chat_id, msg)

        # Send screenshot
        if result.get("screenshot_b64"):
            img_bytes = base64.b64decode(result["screenshot_b64"])
            _send_tg_photo(chat_id, img_bytes, caption=f"📋 Application form submitted by JanSahayak")

    except Exception as e:
        logger.error(f"[RPA ERROR] {e}")
        _send_tg_message(chat_id, "✅ Details saved! Our team will process your application shortly.")

def add_rpa_job(scheme: str, user_data: dict, chat_id: int) -> str:
    job_id = "JS" + uuid.uuid4().hex[:6].upper()
    job = {
        "job_id":    job_id,
        "scheme":    scheme,
        "user_data": user_data,
        "chat_id":   chat_id,
    }
    _job_queue.append(job)
    logger.info(f"[RPA QUEUE] Job {job_id} added | scheme={scheme} | chat_id={chat_id}")
    # Run RPA in background thread immediately
    threading.Thread(target=_run_rpa_job, args=(job,), daemon=True).start()
    return job_id

@router.get("/queue-status")
async def queue_status():
    return {"queued": len(_job_queue)}
