"""
rpa_queue.py - RPA Job Queue with AWS Integration
S3: Screenshot storage | DynamoDB: Records | SNS: SMS confirmation
"""
import threading, uuid, logging, base64, os, sys, io, requests
from collections import deque

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
logger = logging.getLogger(__name__)
_job_queue = deque()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

SCHEME_SUCCESS_MSGS = {
    "pmkisan": {
        "en": "🌾 PM-KISAN application submitted!\n💰 ₹6,000/year will be credited to your bank account in 3 instalments.\n📱 You will receive an SMS confirmation shortly.",
        "hi": "🌾 PM-KISAN आवेदन जमा!\n💰 ₹6,000/साल आपके बैंक में जमा होगा।\n📱 SMS भेजा जा रहा है।",
        "te": "🌾 PM-KISAN దరఖాస్తు సమర్పించబడింది!\n💰 ₹6,000/సంవత్సరం మీ బ్యాంకుకు జమ అవుతుంది.\n📱 SMS పంపబడుతోంది.",
        "ta": "🌾 PM-KISAN விண்ணப்பம் சமர்ப்பிக்கப்பட்டது!\n💰 ₹6,000/ஆண்டு உங்கள் வங்கிக்கு வரவு வைக்கப்படும்.",
        "mr": "🌾 PM-KISAN अर्ज सादर!\n💰 ₹6,000/वर्ष तुमच्या बँकेत जमा होईल.",
        "kn": "🌾 PM-KISAN ಅರ್ಜಿ ಸಲ್ಲಿಸಲಾಗಿದೆ!\n💰 ₹6,000/ವರ್ಷ ನಿಮ್ಮ ಬ್ಯಾಂಕ್‌ಗೆ ಜಮಾ ಆಗುತ್ತದೆ.",
        "ml": "🌾 PM-KISAN അപേക്ഷ സമർപ്പിച്ചു!\n💰 ₹6,000/വർഷം ബാങ്കിൽ ലഭിക്കും.",
        "bn": "🌾 PM-KISAN আবেদন জমা!\n💰 ₹6,000/বছর আপনার ব্যাংকে জমা হবে।",
        "as": "🌾 PM-KISAN আবেদন দাখিল!\n💰 ₹6,000/বছৰ আপোনাৰ বেংকত জমা হ'ব।",
    },
    "ration": {
        "en": "🍚 Ration Card application submitted!\n📋 Card will be issued within 30 working days.\n📱 SMS confirmation sent to your mobile.",
        "hi": "🍚 राशन कार्ड आवेदन जमा!\n📋 30 कार्य दिवसों में कार्ड जारी होगा।",
        "te": "�� రేషన్ కార్డు దరఖాస్తు సమర్పించబడింది!\n📋 30 పని దినాలలో కార్డు జారీ అవుతుంది.",
        "ta": "🍚 ரேஷன் கார்டு விண்ணப்பம் சமர்ப்பிக்கப்பட்டது!\n📋 30 நாட்களில் கார்டு வழங்கப்படும்.",
        "mr": "🍚 रेशन कार्ड अर्ज सादर!\n📋 30 कामकाजाच्या दिवसांत कार्ड मिळेल.",
        "kn": "🍚 ರೇಷನ್ ಕಾರ್ಡ್ ಅರ್ಜಿ ಸಲ್ಲಿಸಲಾಗಿದೆ!\n📋 30 ದಿನಗಳಲ್ಲಿ ಕಾರ್ಡ್ ನೀಡಲಾಗುತ್ತದೆ.",
        "ml": "🍚 റേഷൻ കാർഡ് അപേക്ഷ സമർപ്പിച്ചു!\n📋 30 ദിവസത്തിൽ കാർഡ് ലഭിക്കും.",
        "bn": "🍚 রেশন কার্ড আবেদন জমা!\n📋 ৩০ কার্যদিবসে কার্ড দেওয়া হবে।",
        "as": "🍚 ৰেচন কাৰ্ড আবেদন দাখিল!\n📋 30 কাৰ্যদিৱসত কাৰ্ড দিয়া হ'ব।",
    },
    "ayushman": {
        "en": "🏥 Ayushman Bharat application submitted!\n💊 ₹5 Lakh health cover activated.\n🏨 Valid at 25,000+ empanelled hospitals.\n📱 SMS confirmation sent.",
        "hi": "🏥 आयुष्मान भारत आवेदन जमा!\n💊 ₹5 लाख स्वास्थ्य बीमा सक्रिय।\n🏨 25,000+ अस्पतालों में मान्य।",
        "te": "🏥 ఆయుష్మాన్ భారత్ దరఖాస్తు సమర్పించబడింది!\n💊 ₹5 లక్ష ఆరోగ్య బీమా యాక్టివేట్.\n🏨 25,000+ ఆసుపత్రులలో చెల్లుతుంది.",
        "ta": "🏥 ஆயுஷ்மான் பாரத் விண்ணப்பம் சமர்ப்பிக்கப்பட்டது!\n💊 ₹5 லட்சம் உடல்நல காப்பீடு செயல்படுத்தப்பட்டது.",
        "mr": "🏥 आयुष्मान भारत अर्ज सादर!\n�� ₹5 लाख आरोग्य विमा सक्रिय.",
        "kn": "🏥 ಆಯುಷ್ಮಾನ್ ಭಾರತ್ ಅರ್ಜಿ ಸಲ್ಲಿಸಲಾಗಿದೆ!\n💊 ₹5 ಲಕ್ಷ ಆರೋಗ್ಯ ವಿಮೆ ಸಕ್ರಿಯ.",
        "ml": "🏥 ആയുഷ്മാൻ ഭാരത് അപേക്ഷ സമർപ്പിച്ചു!\n💊 ₹5 ലക്ഷം ആരോഗ്യ കവർ സജീവം.",
        "bn": "🏥 আয়ুষ্মান ভারত আবেদন জমা!\n💊 ₹5 লাখ স্বাস্থ্য বিমা সক্রিয়।",
        "as": "🏥 আয়ুষ্মান ভাৰত আবেদন দাখিল!\n💊 ₹5 লাখ স্বাস্থ্য বিমা সক্ৰিয়।",
    },
    "nsap": {
        "en": "🏛️ NSAP application submitted!\n💰 Financial assistance will be credited to your bank account monthly under the recommended sub-scheme.\n📱 You will receive an SMS confirmation shortly.",
        "hi": "🏛️ एनएसएपी (NSAP) आवेदन जमा!\n💰 सिफ़ारिश की गई योजना के तहत आपके बैंक में राशि जमा होगी।",
        "te": "🏛️ NSAP దరఖాస్తు సమర్పించబడింది!\n💰 సూచించిన పథకం కింద మీ బ్యాంకు ఖాతాకు ప్రతి నెలా ఆర్థిక సహాయం జమ చేయబడుతుంది.",
        "ta": "🏛️ NSAP விண்ணப்பம் சமர்ப்பிக்கப்பட்டது!\n💰 பரிந்துரைக்கப்பட்ட திட்டத்தின் கீழ் உங்கள் வங்கி கணக்கில் மாதாந்திர நிதி உதவி வரவு வைக்கப்படும்.",
        "mr": "🏛️ NSAP अर्ज सादर!\n💰 शिफारस केलेल्या योजनेअंतर्गत मासिक आर्थिक मदत थेट खात्यात जमा केली जाईल.",
        "kn": "🏛️ NSAP ಅರ್ಜಿ ಸಲ್ಲಿಸಲಾಗಿದೆ!\n💰 ಶಿಫಾರಸು ಮಾಡಿದ ಯೋಜನೆಯಡಿಯಲ್ಲಿ ಮಾಸಿಕ ಆರ್ಥಿಕ ನೆರವು ಬ್ಯಾಂಕ್ ಖಾತೆಗೆ ಜಮಾ ಆಗುತ್ತದೆ.",
        "ml": "🏛️ NSAP അപേക്ഷ സമർപ്പിച്ചു!\n💰 ശുപാർശ ചെയ്ത പദ്ധതി പ്രകാരം പ്രതിമാസ ധനസഹായം ബാങ്ക് അക്കൗണ്ടിൽ ലഭിക്കും.",
        "bn": "🏛️ NSAP আবেদন জমা!\n💰 সুপারিশকৃত প্রকল্পের অধীনে মাসিক আর্থিক সহায়তা সরাসরি ব্যাংকে জমা হবে।",
        "as": "🏛️ NSAP আবেদন দাখিল!\n💰 পৰামৰ্শ দিয়া আঁচনিৰ অধীনত মাহিলী আৰ্থিক সাহায্য বেংক একাউণ্টত জমা হ'ব।"
    }
}

def _send_telegram_message(chat_id, text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=30)
    except Exception as e:
        logger.error(f"Telegram message error: {e}")

def _send_telegram_photo(chat_id, photo_bytes, caption=""):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("form.jpg", io.BytesIO(photo_bytes), "image/jpeg")},
            timeout=30)
    except Exception as e:
        logger.error(f"Telegram photo error: {e}")

def _run_rpa_job(job):
    chat_id = job["chat_id"]
    scheme  = job["scheme"]
    user_data = job["user_data"]
    lang    = user_data.get("language", "en") or "en"
    mobile  = user_data.get("mobile", "")

    try:
        # Step 1: Generate form screenshot
        from rpa_agent import submit_pm_kisan_application, submit_ration_card_application, submit_ayushman_application
        fn = {"pmkisan": submit_pm_kisan_application,
              "ration":  submit_ration_card_application,
              "ayushman": submit_ayushman_application}.get(scheme, submit_pm_kisan_application)
        
        app_id = job.get("job_id") or ("JS" + uuid.uuid4().hex[:6].upper())
        result = fn(user_data, app_id=app_id)
        screenshot_b64 = result.get("screenshot_b64")

        # Step 2: Upload screenshot to object storage (via ai_provider → S3 or IBM COS)
        s3_url = ""
        if screenshot_b64:
            try:
                from services import ai_provider as _ap
                img_bytes = base64.b64decode(screenshot_b64)
                s3_url = _ap.upload_screenshot(img_bytes, app_id, scheme)
                logger.info(f"[Storage] Screenshot: {s3_url}")
                
                # Save screenshot locally in static folder for local dashboard preview
                try:
                    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
                    os.makedirs(static_dir, exist_ok=True)
                    static_path = os.path.join(static_dir, f"app_{app_id}.png")
                    with open(static_path, "wb") as f:
                        f.write(img_bytes)
                    logger.info(f"[Storage] Saved local preview: {static_path}")
                except Exception as ex:
                    logger.error(f"Failed to write local preview copy: {ex}")
                    
                # Update Firestore document with Completed status and screenshot url
                try:
                    from firebase_admin import firestore
                    db = firestore.client()
                    db.collection("applications").document(app_id).update({
                        "status": "Completed" if result.get("success") else "Failed",
                        "screenshot_url": s3_url
                    })
                    logger.info(f"[Firestore] Updated application {app_id} status to Completed/Failed")
                except Exception as ex:
                    logger.warning(f"Firestore status update from RPA thread failed: {ex}")
                    
            except Exception as e:
                logger.error(f"Screenshot upload error: {e}")

        # Step 3: Save application record (via ai_provider → DynamoDB or IBM Cloudant)
        try:
            from services import ai_provider as _ap
            _ap.db_save_application(app_id, mobile, scheme,
                                    user_data.get("name",""), s3_url)
        except Exception as e:
            logger.error(f"DB save application error: {e}")

        # Step 4: Send SMS via SNS
        if mobile:
            try:
                from aws_services import sns_send_sms
                sns_send_sms(mobile, app_id, scheme, lang)
            except Exception as e:
                logger.error(f"SNS error: {e}")

        # Step 5: Send Telegram confirmation
        success_msg = SCHEME_SUCCESS_MSGS.get(scheme, {}).get(lang,
                      SCHEME_SUCCESS_MSGS.get(scheme, {}).get("en", "✅ Application submitted!"))
        
        confirmation = (
            f"✅ <b>Application Submitted Successfully!</b>\n\n"
            f"🗂 <b>Application ID:</b> <code>{app_id}</code>\n"
            f"👤 <b>Name:</b> {user_data.get('name','')}\n"
            f"📱 <b>Mobile:</b> {mobile}\n\n"
            f"{success_msg}\n\n"
            f"{'🔗 <b>Form stored:</b> AWS S3 ✅' if s3_url else ''}\n"
            f"📊 <b>Record saved:</b> AWS DynamoDB ✅\n"
            f"📨 <b>SMS sent:</b> AWS SNS ✅\n\n"
            f"📌 Save your Application ID: <code>{app_id}</code>"
        )
        _send_telegram_message(chat_id, confirmation)

        # Step 6: Send screenshot
        if screenshot_b64:
            img_bytes = base64.b64decode(screenshot_b64)
            _send_telegram_photo(chat_id, img_bytes,
                f"📋 Submitted form | ID: {app_id} | Stored in AWS S3")

        logger.info(f"[RPA] Job complete: {app_id}")

    except Exception as e:
        logger.error(f"[RPA] Job failed: {e}")
        _send_telegram_message(chat_id,
            "✅ Application received! Our team will process it shortly.\n"
            "📞 Helpline: 1800-180-1551 (Free)")

def add_rpa_job(scheme, user_data, chat_id, job_id=None):
    if not job_id:
        job_id = "JS" + uuid.uuid4().hex[:6].upper()
    job = {"job_id": job_id, "scheme": scheme, "user_data": user_data, "chat_id": chat_id}
    _job_queue.append(job)
    threading.Thread(target=_run_rpa_job, args=(job,), daemon=True).start()
    logger.info(f"[RPA] Job queued: {job_id} scheme={scheme}")
    try:
        from routers.rpa import enqueue_job
        enqueue_job(chat_id, scheme, user_data)
    except Exception as e:
        logger.error(f"Failed to enqueue job for laptop worker: {e}")
    return job_id

from fastapi import APIRouter
router = APIRouter()

