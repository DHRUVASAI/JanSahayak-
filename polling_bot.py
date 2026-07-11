"""
polling_bot.py — JanSahayak Telegram Bot
Full flow: Language → Scheme → Eligibility → Mobile → Aadhaar → Confirm → RPA
"""
import os, sys, re, time, logging, requests
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

import tempfile
try:
    import fcntl
    _lock_path = os.path.join(tempfile.gettempdir(), "jansahayak.lock")
    _lock = open(_lock_path, "w")
    try:
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        print("Another instance running! Exiting.")
        sys.exit(1)
except ImportError:
    pass

import firebase_admin
from firebase_admin import credentials, firestore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from routers.chat import (
    t, get_llm_response, detect_language, extract_options_tag,
    get_keyboard_for_options_tag, build_language_keyboard,
    build_schemes_keyboard, build_yes_no_keyboard, build_contact_keyboard,
    resolve_callback, check_eligibility_from_callback,
    extract_phone_from_text, transcribe_audio, LANGUAGE_NAMES
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ── Firebase ──────────────────────────────────────────────────────────────────
if not firebase_admin._apps:
    cred_path = os.getenv("FIREBASE_CREDENTIALS", str((Path(__file__).parent / "firebase-credentials.json").resolve()))
    try:
        firebase_admin.initialize_app(credentials.Certificate(cred_path))
        logger.info("Firebase connected!")
    except Exception as e:
        logger.error(f"Firebase error: {e}")

db = firestore.client()

def get_user_doc(chat_id):
    doc = db.collection("users").document(str(chat_id)).get()
    return doc.to_dict() if doc.exists else {}

def update_user(chat_id, data):
    db.collection("users").document(str(chat_id)).set(data, merge=True)

def get_history(chat_id):
    return get_user_doc(chat_id).get("history", [])

def append_history(chat_id, role, content):
    doc = get_user_doc(chat_id)
    history = doc.get("history", [])
    history.append({"role": role, "content": content})
    if len(history) > 20:
        history = history[-20:]
    db.collection("users").document(str(chat_id)).set({"history": history}, merge=True)

# ── Telegram helpers ──────────────────────────────────────────────────────────
def send_message(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        import json
        payload["reply_markup"] = json.dumps(keyboard)
    try:
        requests.post(f"{TG}/sendMessage", json=payload, timeout=30)
    except Exception as e:
        logger.error(f"send_message error: {e}")

def send_photo(chat_id, photo_bytes, caption=""):
    import io
    try:
        requests.post(f"{TG}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("form.png", io.BytesIO(photo_bytes), "image/png")},
            timeout=30)
    except Exception as e:
        logger.error(f"send_photo error: {e}")

def send_typing(chat_id):
    try:
        requests.post(f"{TG}/sendChatAction", json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except:
        pass

def remove_reply_keyboard(chat_id, text="✅"):
    try:
        import json
        requests.post(f"{TG}/sendMessage", json={
            "chat_id": chat_id, "text": text,
            "reply_markup": json.dumps({"remove_keyboard": True})
        }, timeout=10)
    except:
        pass

def get_file_bytes(file_id):
    try:
        r = requests.get(f"{TG}/getFile", params={"file_id": file_id}, timeout=10)
        path = r.json()["result"]["file_path"]
        r2 = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}", timeout=30)
        return r2.content
    except Exception as e:
        logger.error(f"get_file error: {e}")
        return None

SCHEME_NAMES = {
    "scheme_pmkisan": "pmkisan",
    "scheme_ration": "ration",
    "scheme_ayushman": "ayushman",
    "scheme_nsap": "nsap",
}

# ── /start handler ────────────────────────────────────────────────────────────
def handle_start(chat_id, user_name):
    user_data = get_user_doc(chat_id)
    lang = user_data.get("language")
    name = user_data.get("name") or user_name

    if lang and user_data.get("mobile"):
        # Returning user
        welcome_back = {
            "en": f"Welcome back, <b>{name}</b>! 👋\nWhat would you like to do today?",
            "hi": f"वापस आपका स्वागत है, <b>{name}</b>! 👋\nआज क्या करना है?",
            "te": f"తిరిగి స్వాగతం, <b>{name}</b>! 👋\nఈరోజు ఏమి చేయాలి?",
            "ta": f"மீண்டும் வரவேற்கிறோம், <b>{name}</b>! 👋",
            "kn": f"ಮರಳಿ ಸ್ವಾಗತ, <b>{name}</b>! 👋",
            "ml": f"തിരിച്ചുവരവിനു സ്വാഗതം, <b>{name}</b>! 👋",
            "mr": f"परत स्वागत आहे, <b>{name}</b>! ��",
            "as": f"পুনৰ স্বাগতম, <b>{name}</b>! 👋",
            "bn": f"আবার স্বাগতম, <b>{name}</b>! 👋",
        }
        update_user(chat_id, {"step": "scheme_selection", "history": [], "scheme": None})
        send_message(chat_id, welcome_back.get(lang, welcome_back["en"]), build_schemes_keyboard(lang))
    else:
        # New user
        update_user(chat_id, {
            "chat_id": str(chat_id), "step": "language_selection",
            "language": None, "scheme": None, "history": [],
            "mobile": None, "aadhaar_data": None, "schemes_applied": [],
            "ocr_failures": 0,
        })
        welcome = "🙏 <b>Welcome to JanSahayak!</b>\nआपका स्वागत है | స్వాగతం | வரவேற்கிறோம்\n\nPlease select your language / अपनी भाषा चुनें:"
        send_message(chat_id, welcome, build_language_keyboard())

# ── Scheme selection handler ──────────────────────────────────────────────────
def handle_scheme_selection(chat_id, scheme_key, lang):
    update_user(chat_id, {"scheme": scheme_key, "step": "eligibility", "history": []})
    scheme_display = {"pmkisan": "PM-KISAN", "ration": "Ration Card", "ayushman": "Ayushman Bharat", "nsap": "NSAP Classifier"}
    user_msg = f"I want to apply for {scheme_display.get(scheme_key, scheme_key)}"
    history = get_history(chat_id)
    send_typing(chat_id)
    llm_response = get_llm_response(history, user_msg, lang, scheme_key)
    cleaned, tag = extract_options_tag(llm_response)
    keyboard = get_keyboard_for_options_tag(tag, lang) if tag else None
    append_history(chat_id, "user", user_msg)
    append_history(chat_id, "assistant", cleaned)
    send_message(chat_id, cleaned, keyboard)

# ── Callback query handler ────────────────────────────────────────────────────
def handle_callback_query(callback_query):
    chat_id = callback_query["message"]["chat"]["id"]
    data = callback_query.get("data", "")
    user_data = get_user_doc(chat_id)
    lang = user_data.get("language", "en") or "en"
    scheme = user_data.get("scheme")

    # Answer callback
    try:
        requests.post(f"{TG}/answerCallbackQuery",
            json={"callback_query_id": callback_query["id"]}, timeout=5)
    except:
        pass

    # Language selection
    if data.startswith("lang_"):
        lang_code = data.replace("lang_", "")
        update_user(chat_id, {"language": lang_code, "step": "scheme_selection"})
        confirm = t(lang_code, "lang_confirm")
        send_message(chat_id, confirm, build_schemes_keyboard(lang_code))
        return

    # Scheme selection
    if data.startswith("scheme_"):
        scheme_key = data.replace("scheme_", "")
        update_user(chat_id, {"scheme": scheme_key})
        handle_scheme_selection(chat_id, scheme_key, lang)
        return

    # Aadhaar confirmation
    if user_data.get("step") == "confirm_aadhaar":
        if data == "ans_yes":
            update_user(chat_id, {"step": "confirmed"})
            user_data = get_user_doc(chat_id)
            name = user_data.get("name", "")
            mobile = user_data.get("mobile", "")
            aadhaar_masked = user_data.get("aadhaar_masked", "")
            state = user_data.get("state", "")
            district = user_data.get("district", "")
            scheme_display = {"pmkisan": "PM-KISAN", "ration": "Ration Card", "ayushman": "Ayushman Bharat", "nsap": "NSAP Classifier"}
            scheme_name = scheme_display.get(scheme or "", "")
            summary = {
                "en": f"📋 Application Summary\n\n👤 Name: {name}\n📱 Mobile: {mobile}\n🆔 Aadhaar: {aadhaar_masked}\n📍 {district}, {state}\n🎯 Scheme: {scheme_name}\n\nShall I submit your application now?",
                "hi": f"📋 आवेदन सारांश\n\n👤 नाम: {name}\n📱 मोबाइल: {mobile}\n🆔 आधार: {aadhaar_masked}\n📍 {district}, {state}\n🎯 योजना: {scheme_name}\n\nक्या अभी जमा करूं?",
                "te": f"📋 దరఖాస్తు సారాంశం\n\n👤 పేరు: {name}\n📱 మొబైల్: {mobile}\n🆔 ఆధార్: {aadhaar_masked}\n📍 {district}, {state}\n🎯 పథకం: {scheme_name}\n\nఇప్పుడు సమర్పించమా?",
                "ta": f"📋 விண்ணப்ப சுருக்கம்\n\n👤 {name}\n📱 {mobile}\n🆔 {aadhaar_masked}\n🎯 {scheme_name}\n\nசமர்ப்பிக்கலாமா?",
                "mr": f"📋 अर्ज सारांश\n\n👤 {name}\n📱 {mobile}\n🆔 {aadhaar_masked}\n🎯 {scheme_name}\n\nआता सादर करू का?",
                "kn": f"📋 ಅರ್ಜಿ ಸಾರಾಂಶ\n\n👤 {name}\n📱 {mobile}\n🆔 {aadhaar_masked}\n🎯 {scheme_name}\n\nಈಗ ಸಲ್ಲಿಸಲೇ?",
                "ml": f"📋 അപേക്ഷ സംഗ്രഹം\n\n👤 {name}\n📱 {mobile}\n🆔 {aadhaar_masked}\n🎯 {scheme_name}\n\nഇപ്പോൾ സമർപ്പിക്കണോ?",
                "bn": f"📋 আবেদন সারাংশ\n\n👤 {name}\n📱 {mobile}\n🆔 {aadhaar_masked}\n🎯 {scheme_name}\n\nএখন জমা দেব?",
                "as": f"📋 আবেদনৰ সাৰাংশ\n\n👤 {name}\n📱 {mobile}\n🆔 {aadhaar_masked}\n🎯 {scheme_name}\n\nএতিয়া দাখিল কৰিবনে?",
            }
            send_message(chat_id, summary.get(lang, summary["en"]), build_yes_no_keyboard(lang))
            return
        elif data == "ans_no":
            update_user(chat_id, {"step": "aadhaar_upload", "aadhaar_data": None})
            retry = {
                "en": "No problem! Please send your Aadhaar card photo again. 📷",
                "hi": "कोई बात नहीं! आधार कार्ड की फोटो फिर से भेजें। 📷",
                "te": "ఫర్వాలేదు! ఆధార్ కార్డు ఫోటో మళ్ళీ పంపండి. 📷",
                "ta": "பரவாயில்லை! ஆதார் கார்டு படம் மீண்டும் அனுப்பவும். 📷",
                "mr": "काळजी नको! आधार कार्डचा फोटो पुन्हा पाठवा. 📷",
                "kn": "ಪರವಾಗಿಲ್ಲ! ಆಧಾರ್ ಕಾರ್ಡ್ ಫೋಟೋ ಮತ್ತೆ ಕಳುಹಿಸಿ. 📷",
                "ml": "കുഴപ്പമില്ല! ആധാർ കാർഡ് ഫോട്ടോ വീണ്ടും അയക്കൂ. 📷",
                "bn": "কোনো সমস্যা নেই! আবার আধার কার্ডের ছবি পাঠান. 📷",
                "as": "কোনো সমস্যা নাই! আধাৰ কাৰ্ডৰ ফটো পুনৰ পঠাওক. 📷",
            }
            send_message(chat_id, retry.get(lang, retry["en"]))
            return

    # Final submission confirmation
    if user_data.get("step") == "confirmed":
        if data == "ans_yes":
            update_user(chat_id, {"step": "submitted"})
            schemes_applied = user_data.get("schemes_applied", [])
            if scheme and scheme not in schemes_applied:
                schemes_applied.append(scheme)
                update_user(chat_id, {"schemes_applied": schemes_applied})
            processing = {
                "en": "⚙️ Processing your application... please wait.",
                "hi": "⚙️ आवेदन प्रक्रिया में है... कृपया प्रतीक्षा करें।",
                "te": "⚙️ దరఖాస్తు ప్రక్రియలో ఉంది... దయచేసి వేచి ఉండండి.",
                "ta": "⚙️ விண்ணப்பம் செயலாக்கப்படுகிறது...",
                "mr": "⚙️ अर्ज प्रक्रियेत आहे... थांबा.",
                "kn": "⚙️ ಅರ್ಜಿ ಪ್ರಕ್ರಿಯೆಯಲ್ಲಿದೆ...",
                "ml": "⚙️ അപേക്ഷ പ്രോസസ് ചെയ്യുന്നു...",
                "bn": "⚙️ আবেদন প্রক্রিয়া চলছে...",
                "as": "⚙️ আবেদন প্ৰক্ৰিয়া চলিছে...",
            }
            send_message(chat_id, processing.get(lang, processing["en"]))
            # Run RPA in background
            import threading
            threading.Thread(target=_run_rpa, args=(chat_id, scheme, user_data, lang), daemon=True).start()
            return
        elif data == "ans_no":
            update_user(chat_id, {"step": "scheme_selection"})
            cancel = {
                "en": "Application cancelled. Would you like to apply for another scheme?",
                "hi": "आवेदन रद्द। क्या दूसरी योजना के लिए आवेदन करना है?",
                "te": "దరఖాస్తు రద్దు. మరొక పథకానికి దరఖాస్తు చేయాలా?",
                "ta": "விண்ணப்பம் ரத்து. வேறு திட்டத்திற்கு விண்ணப்பிக்கவும்?",
                "mr": "अर्ज रद्द. दुसऱ्या योजनेसाठी अर्ज करायचा?",
                "kn": "ಅರ್ಜಿ ರದ್ದು. ಮತ್ತೊಂದು ಯೋಜನೆಗೆ ಅರ್ಜಿ ಸಲ್ಲಿಸಬೇಕೇ?",
                "ml": "അപേക്ഷ റദ്ദ്. മറ്റൊരു പദ്ധതിക്ക് അപേക്ഷിക്കണോ?",
                "bn": "আবেদন বাতিল। অন্য প্রকল্পের জন্য আবেদন করবেন?",
                "as": "আবেদন বাতিল। আন আঁচনিৰ বাবে আবেদন কৰিব?",
            }
            send_message(chat_id, cancel.get(lang, cancel["en"]), build_schemes_keyboard(lang))
            return

    # Mobile confirmation
    mobile_pending = user_data.get("mobile_pending")
    if mobile_pending:
        if data == "ans_yes":
            update_user(chat_id, {"mobile": mobile_pending, "mobile_pending": None, "step": "aadhaar_upload"})
            saved = {
                "en": f"✅ Mobile {mobile_pending} saved!\n\nNow please send a clear photo of your Aadhaar card. 📷",
                "hi": f"✅ मोबाइल {mobile_pending} सेव!\n\nआधार कार्ड की साफ़ फोटो भेजें। 📷",
                "te": f"✅ మొబైల్ {mobile_pending} సేవ్!\n\nఆధార్ కార్డు స్పష్టమైన ఫోటో పంపండి. 📷",
                "ta": f"✅ மொபைல் {mobile_pending} சேமிக்கப்பட்டது!\n\nஆதார் கார்டு படம் அனுப்பவும். 📷",
                "mr": f"✅ मोबाइल {mobile_pending} सेव्ह!\n\nआधार कार्डचा फोटो पाठवा. 📷",
                "kn": f"✅ ಮೊಬೈಲ್ {mobile_pending} ಸೇವ್!\n\nಆಧಾರ್ ಕಾರ್ಡ್ ಫೋಟೋ ಕಳುಹಿಸಿ. 📷",
                "ml": f"✅ മൊബൈൽ {mobile_pending} സേവ്!\n\nആധാർ കാർഡ് ഫോട്ടോ അയക്കൂ. 📷",
                "bn": f"✅ মোবাইল {mobile_pending} সেভ!\n\nআধার কার্ডের ছবি পাঠান. 📷",
                "as": f"✅ মোবাইল {mobile_pending} সংৰক্ষিত!\n\nআধাৰ কাৰ্ডৰ ফটো পঠাওক. 📷",
            }
            send_message(chat_id, saved.get(lang, saved["en"]))
            return
        elif data == "ans_no":
            update_user(chat_id, {"mobile_pending": None})
            retry = {
                "en": "No problem! Please share your mobile number again.",
                "hi": "कोई बात नहीं! मोबाइल नंबर फिर से शेयर करें।",
                "te": "ఫర్వాలేదు! మొబైల్ నంబర్ మళ్ళీ షేర్ చేయండి.",
                "ta": "பரவாயில்லை! மீண்டும் மொபைல் எண் பகிரவும்.",
                "mr": "काळजी नको! पुन्हा मोबाइल नंबर शेअर करा.",
                "kn": "ಪರವಾಗಿಲ್ಲ! ಮೊಬೈಲ್ ನಂಬರ್ ಮತ್ತೆ ಶೇರ್ ಮಾಡಿ.",
                "ml": "കുഴപ്പമില്ല! വീണ്ടും മൊബൈൽ നമ്പർ ഷെയർ ചെയ്യൂ.",
                "bn": "কোনো সমস্যা নেই! আবার মোবাইল নম্বর শেয়ার করুন।",
                "as": "কোনো সমস্যা নাই! পুনৰ মোবাইল নম্বৰ শ্বেয়াৰ কৰক।",
            }
            send_message(chat_id, retry.get(lang, retry["en"]), build_contact_keyboard(lang))
            return

    # contact request
    if data == "request_contact":
        request_contact(chat_id, lang)
        return

    # Eligibility callbacks → feed to LLM
    human_answer = resolve_callback(data)
    if not human_answer:
        return

    user_step = user_data.get("step", "")
    rejection = check_eligibility_from_callback(scheme or "", data, step=user_step)
    if rejection:
        rejection_msgs = {
            "not_farmer": {
                "en": "😔 Sorry, PM-KISAN is only for farmers. You are not eligible.",
                "hi": "😔 माफ़ करें, PM-KISAN केवल किसानों के लिए है।",
                "te": "😔 క్షమించండి, PM-KISAN కేవలం రైతులకు మాత్రమే.",
                "ta": "�� மன்னிக்கவும், PM-KISAN விவசாயிகளுக்கு மட்டுமே.",
                "mr": "😔 माफ करा, PM-KISAN फक्त शेतकऱ्यांसाठी आहे.",
                "kn": "😔 ಕ್ಷಮಿಸಿ, PM-KISAN ರೈತರಿಗೆ ಮಾತ್ರ.",
                "ml": "😔 ക്ഷമിക്കണം, PM-KISAN കർഷകർക്ക് മാത്രം.",
                "bn": "😔 দুঃখিত, PM-KISAN শুধু কৃষকদের জন্য।",
                "as": "😔 দুঃখিত, PM-KISAN কেৱল কৃষকৰ বাবে।",
            },
            "income_too_high": {
                "en": "😔 Sorry, your income exceeds the eligible limit for this scheme.",
                "hi": "😔 माफ़ करें, आपकी आय सीमा से अधिक है।",
                "te": "😔 క్షమించండి, మీ ఆదాయం పరిమితి కంటే ఎక్కువ.",
                "ta": "😔 மன்னிக்கவும், உங்கள் வருமானம் அதிகமாக உள்ளது.",
                "mr": "😔 माफ करा, तुमचे उत्पन्न मर्यादेपेक्षा जास्त आहे.",
                "kn": "😔 ಕ್ಷಮಿಸಿ, ನಿಮ್ಮ ಆದಾಯ ಮಿತಿ ಮೀರಿದೆ.",
                "ml": "😔 ക്ഷമിക്കണം, നിങ്ങളുടെ വരുമാനം പരിധി കവിഞ്ഞു.",
                "bn": "😔 দুঃখিত, আপনার আয় সীমা ছাড়িয়েছে।",
                "as": "😔 দুঃখিত, আপোনাৰ আয় সীমাতকৈ বেছি।",
            },
            "land_too_large": {
                "en": "😔 Sorry, PM-KISAN is only for farmers with 5 acres or less.",
                "hi": "😔 माफ़ करें, PM-KISAN 5 एकड़ तक की ज़मीन वालों के लिए है।",
                "te": "😔 క్షమించండి, PM-KISAN 5 ఎకరాల వరకు మాత్రమే.",
                "ta": "😔 மன்னிக்கவும், PM-KISAN 5 ஏக்கர் வரை மட்டுமே.",
                "mr": "😔 माफ करा, PM-KISAN 5 एकरपर्यंतच आहे.",
                "kn": "😔 ಕ್ಷಮಿಸಿ, PM-KISAN 5 ಎಕರೆ ವರೆಗೆ ಮಾತ್ರ.",
                "ml": "😔 ക്ഷമിക്കണം, PM-KISAN 5 ഏക്കർ വരെ മാത്രം.",
                "bn": "😔 দুঃখিত, PM-KISAN ৫ একর পর্যন্ত জমির জন্য।",
                "as": "😔 দুঃখিত, PM-KISAN 5 একৰ পৰ্যন্ত মাটিৰ বাবে।",
            },
        }
        msg_dict = rejection_msgs.get(rejection, {})
        msg = msg_dict.get(lang, msg_dict.get("en", "You are not eligible."))
        send_message(chat_id, msg)
        retry = {
            "en": "Would you like to apply for another scheme?",
            "hi": "क्या किसी और योजना के लिए आवेदन करना है?",
            "te": "మరొక పథకానికి దరఖాస్తు చేయాలా?",
            "ta": "வேறு திட்டத்திற்கு விண்ணப்பிக்கவும்?",
            "mr": "दुसऱ्या योजनेसाठी अर्ज करायचा?",
            "kn": "ಮತ್ತೊಂದು ಯೋಜನೆಗೆ ಅರ್ಜಿ ಸಲ್ಲಿಸಬೇಕೇ?",
            "ml": "മറ്റൊരു പദ്ധതിക്ക് അപേക്ഷിക്കണോ?",
            "bn": "অন্য প্রকল্পের জন্য আবেদন করবেন?",
            "as": "আন আঁচনিৰ বাবে আবেদন কৰিব?",
        }
        time.sleep(1)
        send_message(chat_id, retry.get(lang, retry["en"]), build_schemes_keyboard(lang))
        return

    history = get_history(chat_id)
    send_typing(chat_id)
    llm_response = get_llm_response(history, human_answer, lang, scheme)
    cleaned, tag = extract_options_tag(llm_response)
    keyboard = get_keyboard_for_options_tag(tag, lang) if tag else None
    append_history(chat_id, "user", human_answer)
    append_history(chat_id, "assistant", cleaned)
    send_message(chat_id, cleaned, keyboard)

# ── RPA runner ────────────────────────────────────────────────────────────────
def _run_rpa(chat_id, scheme, user_data, lang):
    try:
        from routers.rpa_queue import add_rpa_job
        job_id = add_rpa_job(scheme or "pmkisan", user_data, chat_id)
        logger.info(f"RPA job {job_id} started for scheme={scheme}")
    except Exception as e:
        logger.error(f"RPA error: {e}")
        send_message(chat_id, "✅ Details saved! Our team will process your application shortly.")
        send_message(chat_id, "Apply for another scheme?", build_schemes_keyboard(lang))

# ── Contact handler ───────────────────────────────────────────────────────────
def handle_contact(chat_id, contact, user_data):
    lang = user_data.get("language", "en") or "en"
    phone = contact.get("phone_number", "").replace("+91", "").replace("+", "").strip()
    if len(phone) > 10:
        phone = phone[-10:]
    digits = phone[:4] + " " + phone[4:8] + " " + phone[8:] if len(phone) == 10 else phone
    update_user(chat_id, {"mobile_pending": phone})
    remove_reply_keyboard(chat_id, "✅")
    confirm_msgs = {
        "en": f"📱 Your number: {digits}\nIs this correct?",
        "hi": f"📱 आपका नंबर: {digits}\nक्या यह सही है?",
        "te": f"📱 మీ నంబర్: {digits}\nఇది సరైనదా?",
        "ta": f"📱 உங்கள் எண்: {digits}\nசரியா?",
        "kn": f"📱 ನಿಮ್ಮ ನಂಬರ್: {digits}\nಸರಿಯಾಗಿದೆಯೇ?",
        "ml": f"📱 നിങ്ങളുടെ നമ്പർ: {digits}\nശരിയാണോ?",
        "mr": f"📱 तुमचा नंबर: {digits}\nबरोबर आहे का?",
        "as": f"📱 আপোনাৰ নম্বৰ: {digits}\nসঠিক নেকি?",
        "bn": f"📱 আপনার নম্বর: {digits}\nসঠিক?",
    }
    send_message(chat_id, confirm_msgs.get(lang, f"📱 Your number: {digits}\nCorrect?"),
                 get_keyboard_for_options_tag("yes_no", lang))

def request_contact(chat_id, lang):
    import json
    keyboard = {"keyboard": [[{"text": t(lang, "share_contact"), "request_contact": True}]], "resize_keyboard": True, "one_time_keyboard": True}
    voice_hint = t(lang, "voice_hint")
    send_message(chat_id, voice_hint, keyboard)

# ── Voice handler ─────────────────────────────────────────────────────────────
def handle_voice(chat_id, voice, user_data):
    lang = user_data.get("language", "en") or "en"
    scheme = user_data.get("scheme")
    step = user_data.get("step", "")
    processing = {
        "en": "🎤 Processing your voice...",
        "hi": "🎤 आपकी आवाज़ सुन रहा हूँ...",
        "te": "🎤 మీ వాయిస్ వింటున్నాను...",
        "ta": "🎤 உங்கள் குரலை கேட்கிறேன்...",
        "mr": "🎤 तुमचा आवाज ऐकत आहे...",
        "kn": "🎤 ನಿಮ್ಮ ಧ್ವನಿ ಕೇಳಿಸುತ್ತಿದ್ದೇನೆ...",
        "ml": "🎤 ശബ്ദം കേൾക്കുന്നു...",
        "bn": "🎤 আপনার কণ্ঠ শুনছি...",
        "as": "🎤 আপোনাৰ কণ্ঠ শুনিছো...",
    }
    send_message(chat_id, processing.get(lang, "🎤 Processing voice..."))
    audio_bytes = get_file_bytes(voice["file_id"])
    if not audio_bytes:
        send_message(chat_id, "❌ Could not download audio.")
        return
    transcript = transcribe_audio(audio_bytes, lang)
    if not transcript:
        send_message(chat_id, "❌ Could not understand. Please speak clearly or type.")
        return
    logger.info(f"Transcript [{lang}]: {transcript}")
    # Check if phone number
    if any(k in step for k in ["mobile", "contact", "phone"]):
        phone = extract_phone_from_text(transcript)
        if phone:
            update_user(chat_id, {"mobile_pending": phone})
            transcript = phone
    history = get_history(chat_id)
    send_typing(chat_id)
    llm_response = get_llm_response(history, transcript, lang, scheme)
    cleaned, tag = extract_options_tag(llm_response)
    keyboard = get_keyboard_for_options_tag(tag, lang) if tag else None
    append_history(chat_id, "user", f"[Voice] {transcript}")
    append_history(chat_id, "assistant", cleaned)
    send_message(chat_id, f"🎤 <i>{transcript}</i>\n\n{cleaned}", keyboard)

# ── Photo/Aadhaar handler ─────────────────────────────────────────────────────
def handle_photo(chat_id, photo, user_data):
    lang = user_data.get("language", "en") or "en"
    step = user_data.get("step", "")
    ocr_failures = user_data.get("ocr_failures", 0)

    if ocr_failures >= 3:
        helpline = {
            "en": "😔 Having repeated trouble reading Aadhaar. Please call helpline: 1800-180-1551 (free)",
            "hi": "😔 बार-बार समस्या। हेल्पलाइन: 1800-180-1551 (निःशुल्क)",
            "te": "😔 పదే పదే సమస్య. హెల్ప్‌లైన్: 1800-180-1551 (ఉచితం)",
        }
        send_message(chat_id, helpline.get(lang, helpline["en"]))
        update_user(chat_id, {"ocr_failures": 0})
        return

    scanning = {
        "en": "🔍 Reading your Aadhaar card...",
        "hi": "🔍 आधार कार्ड पढ़ रहा हूँ...",
        "te": "🔍 ఆధార్ కార్డు చదువుతున్నాను...",
        "ta": "🔍 ஆதார் கார்டு படிக்கிறேன்...",
        "mr": "🔍 आधार कार्ड वाचत आहे...",
        "kn": "🔍 ಆಧಾರ್ ಕಾರ್ಡ್ ಓದುತ್ತಿದ್ದೇನೆ...",
        "ml": "🔍 ആധാർ കാർഡ് വായിക്കുന്നു...",
        "bn": "🔍 আধার কার্ড পড়ছি...",
        "as": "🔍 আধাৰ কাৰ্ড পঢ়িছো...",
    }
    send_message(chat_id, scanning.get(lang, scanning["en"]))

    try:
        file_id = photo[-1]["file_id"]
        photo_bytes = get_file_bytes(file_id)
        if not photo_bytes:
            send_message(chat_id, t(lang, "error_ocr_failed"))
            return

        from routers.documents import run_aadhaar_ocr, mask_aadhaar
        result = run_aadhaar_ocr(photo_bytes)
        name = result.get("name", "")
        dob = result.get("dob", "")
        gender = result.get("gender", "")
        raw_aadhaar = result.get("aadhaar", "")
        masked = mask_aadhaar(raw_aadhaar) or result.get("aadhaar_masked", "XXXX XXXX ****")

        if name:
            update_user(chat_id, {
                "aadhaar_data": result,
                "step": "confirm_aadhaar",
                "name": name, "dob": dob, "gender": gender,
                "state": result.get("state", ""),
                "district": result.get("district", ""),
                "pincode": result.get("pincode", ""),
                "aadhaar_masked": masked,
                "ocr_failures": 0,
            })
            confirm = {
                "en": f"✅ Aadhaar verified!\n\n👤 Name: <b>{name}</b>\n📅 DOB: {dob}\n⚧ Gender: {gender}\n🔢 Aadhaar: {masked}\n\nIs this correct?",
                "hi": f"✅ आधार सत्यापित!\n\n👤 नाम: <b>{name}</b>\n📅 जन्म: {dob}\n⚧ लिंग: {gender}\n🔢 आधार: {masked}\n\nक्या यह सही है?",
                "te": f"✅ ఆధార్ ధృవీకరించబడింది!\n\n👤 పేరు: <b>{name}</b>\n📅 జన్మ: {dob}\n⚧ లింగం: {gender}\n🔢 ఆధార్: {masked}\n\nఇది సరైనదా?",
                "ta": f"✅ ஆதார் சரிபார்க்கப்பட்டது!\n\n👤 பெயர்: <b>{name}</b>\n📅 பிறந்த தேதி: {dob}\n⚧ பாலினம்: {gender}\n🔢 ஆதார்: {masked}\n\nசரியா?",
                "mr": f"✅ आधार सत्यापित!\n\n👤 नाव: <b>{name}</b>\n📅 जन्म: {dob}\n⚧ लिंग: {gender}\n🔢 आधार: {masked}\n\nहे बरोबर आहे का?",
                "kn": f"✅ ಆಧಾರ್ ಪರಿಶೀಲಿಸಲಾಗಿದೆ!\n\n👤 ಹೆಸರು: <b>{name}</b>\n📅 ಜನ್ಮ: {dob}\n⚧ ಲಿಂಗ: {gender}\n🔢 ಆಧಾರ್: {masked}\n\nಸರಿಯಾಗಿದೆಯೇ?",
                "ml": f"✅ ആധാർ സ്ഥിരീകരിച്ചു!\n\n👤 പേര്: <b>{name}</b>\n📅 ജനനം: {dob}\n⚧ ലിംഗം: {gender}\n🔢 ആധാർ: {masked}\n\nശരിയാണോ?",
                "bn": f"✅ আধার যাচাই হয়েছে!\n\n👤 নাম: <b>{name}</b>\n📅 জন্ম: {dob}\n⚧ লিঙ্গ: {gender}\n🔢 আধার: {masked}\n\nএটা কি সঠিক?",
                "as": f"✅ আধাৰ যাচাই হ'ল!\n\n👤 নাম: <b>{name}</b>\n📅 জন্ম: {dob}\n⚧ লিংগ: {gender}\n🔢 আধাৰ: {masked}\n\nসঠিক নেকি?",
            }
            send_message(chat_id, confirm.get(lang, confirm["en"]), build_yes_no_keyboard(lang))
        else:
            update_user(chat_id, {"ocr_failures": ocr_failures + 1})
            fail = {
                "en": "❌ Could not read Aadhaar clearly. Please send a clear, well-lit photo of the FRONT side.",
                "hi": "❌ आधार साफ़ नहीं दिखा। सामने की तरफ की साफ़ फोटो भेजें।",
                "te": "❌ ఆధార్ స్పష్టంగా కనిపించలేదు. ముందు వైపు స్పష్టమైన ఫోటో పంపండి.",
                "ta": "❌ ஆதார் தெளிவாக தெரியவில்லை. முன் பக்க தெளிவான படம் அனுப்பவும்.",
                "mr": "❌ आधार नीट दिसले नाही. समोरच्या बाजूचा स्पष्ट फोटो पाठवा.",
                "kn": "❌ ಆಧಾರ್ ಸ್ಪಷ್ಟವಾಗಿ ಕಾಣಿಸಲಿಲ್ಲ. ಮುಂಭಾಗದ ಸ್ಪಷ್ಟ ಫೋಟೋ ಕಳುಹಿಸಿ.",
                "ml": "❌ ആധാർ വ്യക്തമായി കാണുന്നില്ല. മുൻവശത്തിന്റെ ഫോട്ടോ അയക്കൂ.",
                "bn": "❌ আধার স্পষ্ট দেখা যায়নি। সামনের দিকের স্পষ্ট ছবি পাঠান।",
                "as": "❌ আধাৰ স্পষ্টকৈ দেখা নগ'ল। সন্মুখৰ স্পষ্ট ফটো পঠাওক।",
            }
            send_message(chat_id, fail.get(lang, fail["en"]))
    except Exception as e:
        logger.error(f"OCR error: {e}")
        update_user(chat_id, {"ocr_failures": ocr_failures + 1})
        send_message(chat_id, t(lang, "error_ocr_failed"))

# ── Text handler ──────────────────────────────────────────────────────────────
def handle_text(chat_id, text, user_data):
    lang = user_data.get("language") or detect_language(text) or "en"
    scheme = user_data.get("scheme")
    step = user_data.get("step", "")

    if not user_data.get("language") and lang:
        update_user(chat_id, {"language": lang})

    if step == "aadhaar_upload":
        remind = {
            "en": "📷 Please send a photo of your Aadhaar card (front side).",
            "hi": "📷 आधार कार्ड की फोटो भेजें (सामने की तरफ)।",
            "te": "�� ఆధార్ కార్డు ఫోటో పంపండి (ముందు వైపు).",
            "ta": "📷 ஆதார் கார்டு படம் அனுப்பவும் (முன் பக்கம்).",
            "mr": "📷 आधार कार्डचा फोटो पाठवा (समोरची बाजू).",
            "kn": "📷 ಆಧಾರ್ ಕಾರ್ಡ್ ಫೋಟೋ ಕಳುಹಿಸಿ (ಮುಂಭಾಗ).",
            "ml": "📷 ആധാർ കാർഡ് ഫോട്ടോ അയക്കൂ (മുൻ വശം).",
            "bn": "📷 আধার কার্ডের ছবি পাঠান (সামনের দিক)।",
            "as": "📷 আধাৰ কাৰ্ডৰ ফটো পঠাওক (সন্মুখ পিন)।",
        }
        send_message(chat_id, remind.get(lang, remind["en"]))
        return

    history = get_history(chat_id)
    send_typing(chat_id)
    llm_response = get_llm_response(history, text, lang, scheme)
    cleaned, tag = extract_options_tag(llm_response)
    keyboard = get_keyboard_for_options_tag(tag, lang) if tag else None
    append_history(chat_id, "user", text)
    append_history(chat_id, "assistant", cleaned)
    send_message(chat_id, cleaned, keyboard)

# ── Main dispatcher ───────────────────────────────────────────────────────────
def process_update(update):
    try:
        if "callback_query" in update:
            handle_callback_query(update["callback_query"])
            return

        message = update.get("message", {})
        if not message:
            return

        chat_id = message["chat"]["id"]
        user_name = message.get("from", {}).get("first_name", "User")
        user_data = get_user_doc(chat_id)
        lang = user_data.get("language", "en") or "en"

        # Commands
        if "text" in message:
            text = message["text"]
            if text.startswith("/start"):
                handle_start(chat_id, user_name)
                return
            if text.startswith("/language") or text.startswith("/lang"):
                update_user(chat_id, {"language": None, "step": "language_selection"})
                send_message(chat_id, "🌐 Select your language / अपनी भाषा चुनें:", build_language_keyboard())
                return
            if text.startswith("/help"):
                help_msg = {
                    "en": "📋 <b>JanSahayak Help</b>\n\n/start - Start over\n/language - Change language\n/help - This menu\n\nI help you apply for:\n🌾 PM-KISAN\n�� Ration Card\n🏥 Ayushman Bharat",
                    "hi": "📋 <b>JanSahayak मदद</b>\n\n/start - फिर से शुरू\n/language - भाषा बदलें\n/help - यह मेनू",
                    "te": "📋 <b>JanSahayak సహాయం</b>\n\n/start - మళ్ళీ ప్రారంభించు\n/language - భాష మార్చు\n/help - ఈ మెనూ",
                }
                send_message(chat_id, help_msg.get(lang, help_msg["en"]))
                return

        if "contact" in message:
            handle_contact(chat_id, message["contact"], user_data)
            return

        if "voice" in message:
            handle_voice(chat_id, message["voice"], user_data)
            return

        if "photo" in message:
            handle_photo(chat_id, message["photo"], user_data)
            return

        if "text" in message:
            handle_text(chat_id, message["text"], user_data)
            return

    except Exception as e:
        logger.error(f"process_update error: {e}")
        try:
            chat_id = update.get("message", {}).get("chat", {}).get("id") or \
                      update.get("callback_query", {}).get("message", {}).get("chat", {}).get("id")
            if chat_id:
                user_data = get_user_doc(chat_id)
                lang = user_data.get("language", "en") or "en"
                send_message(chat_id, t(lang, "error_generic"))
        except:
            pass

# ── Polling loop ──────────────────────────────────────────────────────────────
def main():
    # Delete webhook
    try:
        r = requests.get(f"{TG}/deleteWebhook", params={"drop_pending_updates": True}, timeout=10)
        logger.info(f"Webhook deleted: {r.json().get('description', '')}")
    except Exception as e:
        logger.error(f"deleteWebhook error: {e}")

    logger.info("🚀 JanSahayak polling bot started!")
    offset = 0
    while True:
        try:
            r = requests.get(f"{TG}/getUpdates", params={
                "offset": offset, "timeout": 30,
                "allowed_updates": ["message", "callback_query"]
            }, timeout=35)
            if not r.ok:
                data = r.json()
                if data.get("error_code") == 409:
                    logger.warning(f"getUpdates not ok: {data}")
                    time.sleep(5)
                    continue
            updates = r.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    process_update(update)
                except Exception as e:
                    logger.error(f"Update error: {e}")
        except Exception as e:
            logger.error(f"Poll error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
