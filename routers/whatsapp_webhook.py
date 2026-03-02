"""
routers/whatsapp_webhook.py
JanSahayak — WhatsApp Bot via Twilio
Full flow: Language → Scheme → Eligibility → Mobile → Aadhaar OCR → Consent → RPA
Zero typing: numbered replies + voice messages
"""

import os
import re
import time
import uuid
import tempfile
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# ── Twilio config ─────────────────────────────────────────────────────────────
TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM  = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

# ── Firebase ──────────────────────────────────────────────────────────────────
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(
            os.getenv("FIREBASE_CREDENTIALS_PATH", "/home/ubuntu/app/firebase-credentials.json")
        )
        firebase_admin.initialize_app(cred)
    except Exception as e:
        logger.error("Firebase init error: %s", e)

db = firestore.client()

# ── Firebase helpers ──────────────────────────────────────────────────────────
def get_user(phone: str) -> dict:
    doc = db.collection("whatsapp_users").document(phone).get()
    return doc.to_dict() if doc.exists else {}

def update_user(phone: str, data: dict):
    db.collection("whatsapp_users").document(phone).set(data, merge=True)

def append_history(phone: str, role: str, content: str):
    doc = db.collection("whatsapp_users").document(phone).get()
    user_data = doc.to_dict() if doc.exists else {}
    history = user_data.get("history", [])
    history.append({"role": role, "content": content})
    if len(history) > 20:
        history = history[-20:]
    db.collection("whatsapp_users").document(phone).set({"history": history}, merge=True)

def get_history(phone: str) -> list:
    return get_user(phone).get("history", [])

# ── Language config ───────────────────────────────────────────────────────────
LANGUAGES = {
    "1": ("hi", "हिंदी"),
    "2": ("te", "తెలుగు"),
    "3": ("ta", "தமிழ்"),
    "4": ("kn", "ಕನ್ನಡ"),
    "5": ("ml", "മലയാളം"),
    "6": ("mr", "मराठी"),
    "7": ("bn", "বাংলা"),
    "8": ("as", "অসমীয়া"),
    "9": ("en", "English"),
}

SCHEME_NAMES = {
    "1": ("pmkisan",  "PM-KISAN (₹6000/year)"),
    "2": ("ration",   "Ration Card"),
    "3": ("ayushman", "Ayushman Bharat (₹5 lakh health)"),
}

# ── Multilingual messages ─────────────────────────────────────────────────────
MSGS = {
    "welcome": {
        "hi": "🙏 JanSahayak में आपका स्वागत है!\n\nअपनी भाषा चुनें:\n1 - हिंदी\n2 - తెలుగు\n3 - தமிழ்\n4 - ಕನ್ನಡ\n5 - മലയാളം\n6 - मराठी\n7 - বাংলা\n8 - অসমীয়া\n9 - English\n\nजवाब में नंबर भेजें (1-9)",
        "en": "🙏 Welcome to JanSahayak!\n\nSelect your language:\n1 - हिंदी\n2 - తెలుగు\n3 - தமிழ்\n4 - ಕನ್ನಡ\n5 - മലയാളം\n6 - मराठी\n7 - বাংলা\n8 - অসমীয়া\n9 - English\n\nReply with number (1-9)",
    },
    "lang_confirm": {
        "hi": "✅ हिंदी चुनी गई!\n\nकौन सी योजना के लिए आवेदन करना है?\n1 - PM-KISAN (₹6000/साल)\n2 - राशन कार्ड\n3 - आयुष्मान भारत (₹5 लाख स्वास्थ्य)\n\nनंबर भेजें (1-3)",
        "te": "✅ తెలుగు ఎంచుకున్నారు!\n\nఏ పథకానికి దరఖాస్తు చేయాలి?\n1 - PM-KISAN (₹6000/సంవత్సరం)\n2 - రేషన్ కార్డ్\n3 - ఆయుష్మాన్ భారత్ (₹5 లక్షల ఆరోగ్యం)\n\nనంబర్ పంపండి (1-3)",
        "ta": "✅ தமிழ் தேர்ந்தெடுக்கப்பட்டது!\n\nஎந்த திட்டத்திற்கு விண்ணப்பிக்க?\n1 - PM-KISAN (₹6000/ஆண்டு)\n2 - ரேஷன் கார்டு\n3 - ஆயுஷ்மான் பாரத் (₹5 லட்சம்)\n\nஎண் அனுப்பவும் (1-3)",
        "kn": "✅ ಕನ್ನಡ ಆಯ್ಕೆ ಆಯಿತು!\n\nಯಾವ ಯೋಜನೆಗೆ ಅರ್ಜಿ ಸಲ್ಲಿಸಬೇಕು?\n1 - PM-KISAN (₹6000/ವರ್ಷ)\n2 - ರೇಷನ್ ಕಾರ್ಡ್\n3 - ಆಯುಷ್ಮಾನ್ ಭಾರತ್\n\nಸಂಖ್ಯೆ ಕಳುಹಿಸಿ (1-3)",
        "ml": "✅ മലയാളം തിരഞ്ഞെടുത്തു!\n\nഏത് പദ്ധതിക്ക് അപേക്ഷിക്കണം?\n1 - PM-KISAN (₹6000/വർഷം)\n2 - റേഷൻ കാർഡ്\n3 - ആയുഷ്മാൻ ഭാരത്\n\nനമ്പർ അയക്കുക (1-3)",
        "mr": "✅ मराठी निवडली!\n\nकोणत्या योजनेसाठी अर्ज करायचा?\n1 - PM-KISAN (₹6000/वर्ष)\n2 - रेशन कार्ड\n3 - आयुष्मान भारत\n\nनंबर पाठवा (1-3)",
        "bn": "✅ বাংলা বেছে নেওয়া হয়েছে!\n\nকোন প্রকল্পের জন্য আবেদন করতে চান?\n1 - PM-KISAN (₹6000/বছর)\n2 - রেশন কার্ড\n3 - আয়ুষ্মান ভারত\n\nনম্বর পাঠান (1-3)",
        "as": "✅ অসমীয়া বাছনি কৰা হ'ল!\n\nকোন আঁচনিৰ বাবে আবেদন কৰিব?\n1 - PM-KISAN (₹6000/বছৰ)\n2 - ৰেচন কাৰ্ড\n3 - আয়ুষ্মান ভাৰত\n\nনম্বৰ পঠাওক (1-3)",
        "en": "✅ English selected!\n\nWhich scheme to apply for?\n1 - PM-KISAN (₹6000/year)\n2 - Ration Card\n3 - Ayushman Bharat (₹5 lakh health)\n\nReply with number (1-3)",
    },
    "farmer_check": {
        "hi": "क्या आप किसान हैं और खेती करते हैं?\n1 - हाँ\n2 - नहीं",
        "te": "మీరు రైతు మరియు వ్యవసాయం చేస్తున్నారా?\n1 - అవును\n2 - కాదు",
        "ta": "நீங்கள் விவசாயி மற்றும் விவசாயம் செய்கிறீர்களா?\n1 - ஆம்\n2 - இல்லை",
        "en": "Are you a farmer and do farming?\n1 - Yes\n2 - No",
        "mr": "तुम्ही शेतकरी आहात का?\n1 - होय\n2 - नाही",
        "kn": "ನೀವು ರೈತರೇ ಮತ್ತು ಕೃಷಿ ಮಾಡುತ್ತೀರಾ?\n1 - ಹೌದು\n2 - ಇಲ್ಲ",
        "ml": "നിങ്ങൾ കർഷകനും കൃഷി ചെയ്യുന്നുണ്ടോ?\n1 - അതെ\n2 - ഇല്ല",
        "bn": "আপনি কি কৃষক এবং চাষ করেন?\n1 - হ্যাঁ\n2 - না",
        "as": "আপুনি কৃষক আৰু খেতি কৰেনে?\n1 - হয়\n2 - নহয়",
    },
    "land_check": {
        "hi": "आपके पास कितनी ज़मीन है?\n1 - 2 एकड़ से कम\n2 - 2 से 5 एकड़\n3 - 5 एकड़ से ज़्यादा",
        "te": "మీకు ఎంత భూమి ఉంది?\n1 - 2 ఎకరాల కంటే తక్కువ\n2 - 2 నుండి 5 ఎకరాలు\n3 - 5 ఎకరాల కంటే ఎక్కువ",
        "ta": "உங்களிடம் எவ்வளவு நிலம் உள்ளது?\n1 - 2 ஏக்கருக்கு குறைவு\n2 - 2 முதல் 5 ஏக்கர்\n3 - 5 ஏக்கருக்கு அதிகம்",
        "en": "How much land do you have?\n1 - Less than 2 acres\n2 - 2 to 5 acres\n3 - More than 5 acres",
        "mr": "तुमच्याकडे किती जमीन आहे?\n1 - 2 एकरपेक्षा कमी\n2 - 2 ते 5 एकर\n3 - 5 एकरपेक्षा जास्त",
        "kn": "ನಿಮ್ಮ ಬಳಿ ಎಷ್ಟು ಭೂಮಿ ಇದೆ?\n1 - 2 ಎಕರೆಗಿಂತ ಕಡಿಮೆ\n2 - 2 ರಿಂದ 5 ಎಕರೆ\n3 - 5 ಎಕರೆಗಿಂತ ಹೆಚ್ಚು",
        "ml": "നിങ്ങൾക്ക് എത്ര ഭൂമിയുണ്ട്?\n1 - 2 ഏക്കറിൽ കുറവ്\n2 - 2 മുതൽ 5 ഏക്കർ\n3 - 5 ഏക്കറിൽ കൂടുതൽ",
        "bn": "আপনার কত জমি আছে?\n1 - ২ একরের কম\n2 - ২ থেকে ৫ একর\n3 - ৫ একরের বেশি",
        "as": "আপোনাৰ কিমান মাটি আছে?\n1 - 2 একৰতকৈ কম\n2 - 2 ৰ পৰা 5 একৰ\n3 - 5 একৰতকৈ বেছি",
    },
    "income_check": {
        "hi": "आपकी सालाना आमदनी कितनी है?\n1 - 1 लाख से कम\n2 - 1 से 2 लाख\n3 - 2 लाख से ज़्यादा",
        "te": "మీ వార్షిక ఆదాయం ఎంత?\n1 - 1 లక్ష కంటే తక్కువ\n2 - 1 నుండి 2 లక్షలు\n3 - 2 లక్షల కంటే ఎక్కువ",
        "ta": "உங்கள் ஆண்டு வருமானம் எவ்வளவு?\n1 - 1 லட்சத்திற்கு குறைவு\n2 - 1 முதல் 2 லட்சம்\n3 - 2 லட்சத்திற்கு அதிகம்",
        "en": "What is your annual income?\n1 - Less than 1 lakh\n2 - 1 to 2 lakh\n3 - More than 2 lakh",
        "mr": "तुमचे वार्षिक उत्पन्न किती आहे?\n1 - 1 लाखापेक्षा कमी\n2 - 1 ते 2 लाख\n3 - 2 लाखापेक्षा जास्त",
        "kn": "ನಿಮ್ಮ ವಾರ್ಷಿಕ ಆದಾಯ ಎಷ್ಟು?\n1 - 1 ಲಕ್ಷಕ್ಕಿಂತ ಕಡಿಮೆ\n2 - 1 ರಿಂದ 2 ಲಕ್ಷ\n3 - 2 ಲಕ್ಷಕ್ಕಿಂತ ಹೆಚ್ಚು",
        "ml": "നിങ്ങളുടെ വാർഷിക വരുമാനം എത്ര?\n1 - 1 ലക്ഷത്തിൽ കുറവ്\n2 - 1 മുതൽ 2 ലക്ഷം\n3 - 2 ലക്ഷത്തിൽ കൂടുതൽ",
        "bn": "আপনার বার্ষিক আয় কত?\n1 - ১ লাখের কম\n2 - ১ থেকে ২ লাখ\n3 - ২ লাখের বেশি",
        "as": "আপোনাৰ বাৰ্ষিক আয় কিমান?\n1 - 1 লাখতকৈ কম\n2 - 1 ৰ পৰা 2 লাখ\n3 - 2 লাখতকৈ বেছি",
    },
    "not_eligible": {
        "hi": "😔 माफ़ करें, आप इस योजना के पात्र नहीं हैं।\n\nकिसी और योजना के लिए आवेदन करें?\n1 - PM-KISAN\n2 - राशन कार्ड\n3 - आयुष्मान भारत",
        "te": "😔 క్షమించండి, మీరు ఈ పథకానికి అర్హులు కాదు.\n\nమరొక పథకానికి దరఖాస్తు చేయాలా?\n1 - PM-KISAN\n2 - రేషన్ కార్డ్\n3 - ఆయుష్మాన్ భారత్",
        "en": "😔 Sorry, you are not eligible for this scheme.\n\nApply for another scheme?\n1 - PM-KISAN\n2 - Ration Card\n3 - Ayushman Bharat",
        "mr": "😔 माफ करा, तुम्ही या योजनेसाठी पात्र नाही.\n\nदुसऱ्या योजनेसाठी अर्ज करायचा?\n1 - PM-KISAN\n2 - रेशन कार्ड\n3 - आयुष्मान भारत",
        "ta": "😔 மன்னிக்கவும், நீங்கள் இந்த திட்டத்திற்கு தகுதியற்றவர்.\n\nவேறு திட்டத்திற்கு விண்ணப்பிக்கவும்?\n1 - PM-KISAN\n2 - ரேஷன் கார்டு\n3 - ஆயுஷ்மான் பாரத்",
        "kn": "😔 ಕ್ಷಮಿಸಿ, ನೀವು ಈ ಯೋಜನೆಗೆ ಅರ್ಹರಲ್ಲ.\n\nಮತ್ತೊಂದು ಯೋಜನೆಗೆ ಅರ್ಜಿ ಸಲ್ಲಿಸಬೇಕೇ?\n1 - PM-KISAN\n2 - ರೇಷನ್ ಕಾರ್ಡ್\n3 - ಆಯುಷ್ಮಾನ್ ಭಾರತ್",
        "ml": "😔 ക്ഷമിക്കണം, നിങ്ങൾ ഈ പദ്ധതിക്ക് യോഗ്യരല്ല.\n\nമറ്റൊരു പദ്ധതിക്ക് അപേക്ഷിക്കണോ?\n1 - PM-KISAN\n2 - റേഷൻ കാർഡ്\n3 - ആയുഷ്മാൻ ഭാരത്",
        "bn": "😔 দুঃখিত, আপনি এই প্রকল্পের জন্য যোগ্য নন।\n\nঅন্য প্রকল্পের জন্য আবেদন করবেন?\n1 - PM-KISAN\n2 - রেশন কার্ড\n3 - আয়ুষ্মান ভারত",
        "as": "😔 দুঃখিত, আপুনি এই আঁচনিৰ বাবে যোগ্য নহয়।\n\nআন আঁচনিৰ বাবে আবেদন কৰিব?\n1 - PM-KISAN\n2 - ৰেচন কাৰ্ড\n3 - আয়ুষ্মান ভাৰত",
    },
    "ask_mobile": {
        "hi": "✅ आप पात्र हैं!\n\nअब अपना 10 अंकों का मोबाइल नंबर बोलें या टाइप करें:",
        "te": "✅ మీరు అర్హులు!\n\nఇప్పుడు మీ 10 అంకెల మొబైల్ నంబర్ చెప్పండి లేదా టైప్ చేయండి:",
        "ta": "✅ நீங்கள் தகுதியானவர்!\n\nஇப்போது உங்கள் 10 இலக்க மொபைல் எண்ணை சொல்லுங்கள் அல்லது தட்டச்சு செய்யுங்கள்:",
        "en": "✅ You are eligible!\n\nNow speak or type your 10-digit mobile number:",
        "mr": "✅ तुम्ही पात्र आहात!\n\nआता तुमचा 10 अंकी मोबाइल नंबर बोला किंवा टाइप करा:",
        "kn": "✅ ನೀವು ಅರ್ಹರು!\n\nಈಗ ನಿಮ್ಮ 10 ಅಂಕಿಯ ಮೊಬೈಲ್ ನಂಬರ್ ಹೇಳಿ ಅಥವಾ ಟೈಪ್ ಮಾಡಿ:",
        "ml": "✅ നിങ്ങൾ യോഗ്യരാണ്!\n\nഇപ്പോൾ നിങ്ങളുടെ 10 അക്ക മൊബൈൽ നമ്പർ പറയുക അല്ലെങ്കിൽ ടൈപ്പ് ചെയ്യുക:",
        "bn": "✅ আপনি যোগ্য!\n\nএখন আপনার ১০ সংখ্যার মোবাইল নম্বর বলুন বা টাইপ করুন:",
        "as": "✅ আপুনি যোগ্য!\n\nএতিয়া আপোনাৰ 10 সংখ্যাৰ মোবাইল নম্বৰ কওক বা টাইপ কৰক:",
    },
    "confirm_mobile": {
        "hi": "আপনার নंबর: {phone}\nকি এটা সঠিক?\n1 - হাँ\n2 - না, ফিরে দেওয়া হোক",
        "te": "మీ నంబర్: {phone}\nఇది సరైనదా?\n1 - అవును\n2 - కాదు, మళ్ళీ",
        "en": "Your number: {phone}\nIs this correct?\n1 - Yes\n2 - No, retry",
        "hi": "आपका नंबर: {phone}\nक्या यह सही है?\n1 - हाँ\n2 - नहीं, दोबारा",
        "mr": "तुमचा नंबर: {phone}\nहे बरोबर आहे का?\n1 - होय\n2 - नाही, पुन्हा",
        "ta": "உங்கள் எண்: {phone}\nசரியா?\n1 - ஆம்\n2 - இல்லை, மீண்டும்",
        "kn": "ನಿಮ್ಮ ನಂಬರ್: {phone}\nಸರಿಯಾಗಿದೆಯೇ?\n1 - ಹೌದು\n2 - ಇಲ್ಲ, ಮತ್ತೆ",
        "ml": "നിങ്ങളുടെ നമ്പർ: {phone}\nശരിയാണോ?\n1 - അതെ\n2 - ഇല്ല, വീണ്ടും",
        "bn": "আপনার নম্বর: {phone}\nএটা কি সঠিক?\n1 - হ্যাঁ\n2 - না, আবার",
        "as": "আপোনাৰ নম্বৰ: {phone}\nসঠিক নেকি?\n1 - হয়\n2 - নহয়, পুনৰ",
    },
    "ask_aadhaar": {
        "hi": "✅ मोबाइल नंबर सेव हो गया!\n\nअब अपने आधार कार्ड के सामने की तरफ की साफ़ फ़ोटो भेजें\n📸 अच्छी रोशनी में फ़ोटो लें",
        "te": "✅ మొబైల్ నంబర్ సేవ్ అయింది!\n\nఇప్పుడు మీ ఆధార్ కార్డ్ ముందు వైపు స్పష్టమైన ఫోటో పంపండి\n📸 మంచి వెలుతురులో ఫోటో తీయండి",
        "ta": "✅ மொபைல் எண் சேமிக்கப்பட்டது!\n\nஇப்போது உங்கள் ஆதார் கார்டின் முன் பக்க தெளிவான புகைப்படம் அனுப்பவும்\n📸 நல்ல வெளிச்சத்தில் படம் எடுக்கவும்",
        "en": "✅ Mobile number saved!\n\nNow send a clear photo of the FRONT side of your Aadhaar card\n📸 Take photo in good lighting",
        "mr": "✅ मोबाइल नंबर सेव्ह झाला!\n\nआता तुमच्या आधार कार्डच्या समोरच्या बाजूचा स्पष्ट फोटो पाठवा\n📸 चांगल्या प्रकाशात फोटो घ्या",
        "kn": "✅ ಮೊಬೈಲ್ ನಂಬರ್ ಸೇವ್ ಆಯಿತು!\n\nಈಗ ನಿಮ್ಮ ಆಧಾರ್ ಕಾರ್ಡ್ ಮುಂಭಾಗದ ಸ್ಪಷ್ಟ ಫೋಟೋ ಕಳುಹಿಸಿ\n📸 ಉತ್ತಮ ಬೆಳಕಿನಲ್ಲಿ ಫೋಟೋ ತೆಗೆಯಿರಿ",
        "ml": "✅ മൊബൈൽ നമ്പർ സേവ് ചെയ്തു!\n\nഇപ്പോൾ നിങ്ങളുടെ ആധാർ കാർഡിന്റെ മുൻവശത്തിന്റെ വ്യക്തമായ ഫോട്ടോ അയക്കുക\n📸 നല്ല വെളിച்ചത്തിൽ ഫോട്ടോ എടുക്കുക",
        "bn": "✅ মোবাইল নম্বর সেভ হয়েছে!\n\nএখন আপনার আধার কার্ডের সামনের দিকের স্পষ্ট ছবি পাঠান\n📸 ভালো আলোয় ছবি তুলুন",
        "as": "✅ মোবাইল নম্বৰ সংৰক্ষিত!\n\nএতিয়া আপোনাৰ আধাৰ কাৰ্ডৰ সন্মুখ পিনৰ স্পষ্ট ফটো পঠাওক\n📸 ভাল পোহৰত ফটো তোলক",
    },
    "ocr_fail": {
        "hi": "😔 आधार कार्ड साफ नहीं दिख रहा।\nकृपया अच्छी रोशनी में, सामने की तरफ की साफ़ फ़ोटो दोबारा भेजें।",
        "te": "😔 ఆధార్ కార్డ్ స్పష్టంగా కనిపించలేదు.\nమంచి వెలుతురులో ముందు వైపు స్పష్టమైన ఫోటో మళ్ళీ పంపండి.",
        "en": "😔 Could not read Aadhaar clearly.\nPlease send a clearer photo of the front side in good lighting.",
        "mr": "😔 आधार कार्ड नीट दिसत नाही.\nचांगल्या प्रकाशात, समोरच्या बाजूचा स्पष्ट फोटो पुन्हा पाठवा.",
        "ta": "😔 ஆதார் கார்டு தெளிவாக தெரியவில்லை.\nதயவுசெய்து நல்ல வெளிச்சத்தில் முன் பக்க தெளிவான புகைப்படம் மீண்டும் அனுப்பவும்.",
        "kn": "😔 ಆಧಾರ್ ಕಾರ್ಡ್ ಸ್ಪಷ್ಟವಾಗಿ ಕಾಣಿಸುತ್ತಿಲ್ಲ.\nಉತ್ತಮ ಬೆಳಕಿನಲ್ಲಿ ಮುಂಭಾಗದ ಸ್ಪಷ್ಟ ಫೋಟೋ ಮತ್ತೆ ಕಳುಹಿಸಿ.",
        "ml": "😔 ആധാർ കാർഡ് വ്യക്തമായി കാണുന്നില്ല.\nനല്ല വെളിച്ചത്തിൽ മുൻവശത്തിന്റെ വ്യക്തമായ ഫോട്ടോ വീണ്ടും അയക്കുക.",
        "bn": "😔 আধার কার্ড স্পষ্ট দেখা যাচ্ছে না।\nভালো আলোয় সামনের দিকের স্পষ্ট ছবি আবার পাঠান।",
        "as": "😔 আধাৰ কাৰ্ড স্পষ্টকৈ দেখা নাযায়।\nভাল পোহৰত সন্মুখ পিনৰ স্পষ্ট ফটো পুনৰ পঠাওক।",
    },
    "ocr_helpline": {
        "hi": "😔 बार-बार आधार पढ़ने में परेशानी हो रही है।\nकृपया हेल्पलाइन पर कॉल करें: 1800-180-1551 (निःशुल्क, सोम-शनि 9AM-6PM)",
        "te": "😔 ఆధార్ చదవడంలో పదే పదే సమస్య వస్తోంది.\nహెల్ప్‌లైన్‌కు కాల్ చేయండి: 1800-180-1551 (ఉచితం)",
        "en": "😔 Having repeated trouble reading your Aadhaar.\nPlease call helpline: 1800-180-1551 (free, Mon-Sat 9AM-6PM)",
        "mr": "😔 वारंवार आधार वाचण्यात अडचण येत आहे.\nहेल्पलाइनवर कॉल करा: 1800-180-1551 (निःशुल्क)",
        "ta": "😔 ஆதார் படிப்பதில் மீண்டும் மீண்டும் சிக்கல்.\nஹெல்ப்லைனை அழைக்கவும்: 1800-180-1551 (இலவசம்)",
        "kn": "😔 ಆಧಾರ್ ಓದುವಲ್ಲಿ ಮತ್ತೆ ಮತ್ತೆ ತೊಂದರೆ.\nಹೆಲ್ಪ್‌ಲೈನ್ ಕರೆ ಮಾಡಿ: 1800-180-1551 (ಉಚಿತ)",
        "ml": "😔 ആധാർ വായിക്കാൻ വീണ്ടും വീണ്ടും ബുദ്ധിമുട്ട്.\nഹെൽപ്‌ലൈൻ വിളിക്കുക: 1800-180-1551 (സൗജന്യം)",
        "bn": "😔 বারবার আধার পড়তে সমস্যা হচ্ছে।\nহেল্পলাইনে কল করুন: 1800-180-1551 (বিনামূল্যে)",
        "as": "😔 বাৰে বাৰে আধাৰ পঢ়াত সমস্যা হৈছে।\nহেল্পলাইনত ফোন কৰক: 1800-180-1551 (বিনামূলীয়া)",
    },
    "consent": {
        "hi": "📋 আवेदन सারांश:\n👤 নাম: {name}\n📱 মোবাইল: {mobile}\n🆔 আধার: {aadhaar}\n🎯 যোजনা: {scheme}\n\nকি আমি এখন আবেদন জমা করব?\n1 - হাँ, জমা করুন\n2 - না, বাতিল করুন",
        "te": "📋 దరఖాస్తు సారాంశం:\n👤 పేరు: {name}\n📱 మొబైల్: {mobile}\n🆔 ఆధార్: {aadhaar}\n🎯 పథకం: {scheme}\n\nఇప్పుడు దరఖాస్తు సమర్పించమా?\n1 - అవును, సమర్పించు\n2 - కాదు, రద్దు",
        "en": "📋 Application Summary:\n👤 Name: {name}\n📱 Mobile: {mobile}\n🆔 Aadhaar: {aadhaar}\n🎯 Scheme: {scheme}\n\nShall I submit your application now?\n1 - Yes, Submit\n2 - No, Cancel",
        "hi": "📋 आवेदन सारांश:\n👤 नाम: {name}\n📱 मोबाइल: {mobile}\n🆔 आधार: {aadhaar}\n🎯 योजना: {scheme}\n\nक्या मैं अभी आवेदन जमा करूं?\n1 - हाँ, जमा करें\n2 - नहीं, रद्द करें",
        "mr": "📋 अर्ज सारांश:\n👤 नाव: {name}\n📱 मोबाइल: {mobile}\n🆔 आधार: {aadhaar}\n🎯 योजना: {scheme}\n\nआता अर्ज सादर करू का?\n1 - होय, सादर करा\n2 - नाही, रद्द करा",
        "ta": "📋 விண்ணப்ப சுருக்கம்:\n👤 பெயர்: {name}\n📱 மொபைல்: {mobile}\n🆔 ஆதார்: {aadhaar}\n🎯 திட்டம்: {scheme}\n\nஇப்போது விண்ணப்பிக்கலாமா?\n1 - ஆம், சமர்ப்பி\n2 - இல்லை, ரத்து",
        "kn": "📋 ಅರ್ಜಿ ಸಾರಾಂಶ:\n👤 ಹೆಸರು: {name}\n📱 ಮೊಬೈಲ್: {mobile}\n🆔 ಆಧಾರ್: {aadhaar}\n🎯 ಯೋಜನೆ: {scheme}\n\nಈಗ ಅರ್ಜಿ ಸಲ್ಲಿಸಲೇ?\n1 - ಹೌದು, ಸಲ್ಲಿಸು\n2 - ಇಲ್ಲ, ರದ್ದು",
        "ml": "📋 അപേക്ഷ സംഗ്രഹം:\n👤 പേര്: {name}\n📱 മൊബൈൽ: {mobile}\n🆔 ആധാർ: {aadhaar}\n🎯 പദ്ധതി: {scheme}\n\nഇപ്പോൾ അപേക്ഷ സമർപ്പിക്കണോ?\n1 - അതെ, സമർപ്പിക്കുക\n2 - ഇല്ല, റദ്ദാക്കുക",
        "bn": "📋 আবেদন সারাংশ:\n👤 নাম: {name}\n📱 মোবাইল: {mobile}\n🆔 আধার: {aadhaar}\n🎯 প্রকল্প: {scheme}\n\nএখন আবেদন জমা দেব?\n1 - হ্যাঁ, জমা দিন\n2 - না, বাতিল",
        "as": "📋 আবেদনৰ সাৰাংশ:\n👤 নাম: {name}\n📱 মোবাইল: {mobile}\n🆔 আধাৰ: {aadhaar}\n🎯 আঁচনি: {scheme}\n\nএতিয়া আবেদন দাখিল কৰিবনে?\n1 - হয়, দাখিল কৰক\n2 - নহয়, বাতিল",
    },
    "processing": {
        "hi": "⚙️ आपका आवेदन प्रक्रिया में है... कृपया प्रतीक्षा करें।",
        "te": "⚙️ మీ దరఖాస్తు ప్రక్రియలో ఉంది... దయచేసి వేచి ఉండండి.",
        "en": "⚙️ Processing your application... please wait.",
        "mr": "⚙️ तुमचा अर्ज प्रक्रियेत आहे... कृपया प्रतीक्षा करा.",
        "ta": "⚙️ உங்கள் விண்ணப்பம் செயலாக்கப்படுகிறது... காத்திருக்கவும்.",
        "kn": "⚙️ ನಿಮ್ಮ ಅರ್ಜಿ ಪ್ರಕ್ರಿಯೆಯಲ್ಲಿದೆ... ದಯವಿಟ್ಟು ಕಾಯಿರಿ.",
        "ml": "⚙️ നിങ്ങളുടെ അപേക്ഷ പ്രോസസ് ചെയ്യുന്നു... ദയവായി കാത്തിരിക്കുക.",
        "bn": "⚙️ আপনার আবেদন প্রক্রিয়া চলছে... অনুগ্রহ করে অপেক্ষা করুন।",
        "as": "⚙️ আপোনাৰ আবেদন প্ৰক্ৰিয়া চলিছে... অনুগ্ৰহ কৰি অপেক্ষা কৰক।",
    },
    "error": {
        "hi": "😔 कुछ गड़बड़ हुई। कृपया फिर से कोशिश करें।\nमदद के लिए: hi लिखें",
        "te": "😔 సమస్య వచ్చింది. దయచేసి మళ్ళీ ప్రయత్నించండి.\nసహాయానికి: hi టైప్ చేయండి",
        "en": "😔 Something went wrong. Please try again.\nType 'hi' to restart.",
        "mr": "😔 काहीतरी चुकले. कृपया पुन्हा प्रयत्न करा.\nमदतीसाठी: hi लिहा",
        "ta": "😔 ஏதோ தவறு நடந்தது. மீண்டும் முயற்சிக்கவும்.\nதொடங்க: hi என்று தட்டச்சு செய்யுங்கள்",
        "kn": "😔 ಏನೋ ತಪ್ಪಾಯಿತು. ದಯವಿಟ್ಟು ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.\nಸಹಾಯಕ್ಕೆ: hi ಟೈಪ್ ಮಾಡಿ",
        "ml": "😔 എന്തോ തെറ്റ് സംഭവിച്ചു. വീണ്ടും ശ്രമിക്കുക.\nസഹായത്തിന്: hi ടൈപ്പ് ചെയ്യുക",
        "bn": "😔 কিছু ভুল হয়েছে। আবার চেষ্টা করুন।\nসাহায্যের জন্য: hi লিখুন",
        "as": "😔 কিবা ভুল হ'ল। পুনৰ চেষ্টা কৰক।\nসহায়ৰ বাবে: hi লিখক",
    },
}

def m(key: str, lang: str, **kwargs) -> str:
    """Get message in correct language with format args."""
    msg = MSGS.get(key, {}).get(lang) or MSGS.get(key, {}).get("en", "")
    if kwargs:
        try:
            msg = msg.format(**kwargs)
        except KeyError:
            pass
    return msg

# ── Groq voice transcription ──────────────────────────────────────────────────
async def transcribe_voice(audio_bytes: bytes, lang: str = "hi") -> str:
    try:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        with open(tmp_path, "rb") as af:
            result = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=("voice.ogg", af, "audio/ogg"),
                response_format="text",
                language=lang if lang in ["hi", "te", "ta", "kn", "ml", "mr", "bn", "en"] else "hi",
            )
        os.unlink(tmp_path)
        return result if isinstance(result, str) else result.text
    except Exception as e:
        logger.error("Whisper error: %s", e)
        return ""

# ── Phone extraction ──────────────────────────────────────────────────────────
def extract_phone(text: str) -> Optional[str]:
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    return None

# ── TwiML response ────────────────────────────────────────────────────────────
def twiml(message: str) -> Response:
    # Escape XML special chars
    message = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xml = '<?xml version="1.0" encoding="UTF-8"?><Response><Message>' + message + "</Message></Response>"
    return Response(content=xml, media_type="application/xml")

# ── RPA runner ────────────────────────────────────────────────────────────────
import threading

def run_rpa(phone: str, scheme: str, user_data: dict):
    try:
        from rpa_agent import (submit_pm_kisan_application,
                               submit_ration_card_application,
                               submit_ayushman_application)
        fn = (submit_ration_card_application if scheme == "ration"
              else submit_ayushman_application if scheme == "ayushman"
              else submit_pm_kisan_application)
        result = fn(user_data)
        ref = result.get("application_id", "JS" + uuid.uuid4().hex[:6].upper())
        lang = user_data.get("language", "en")
        scheme_details = {
            "ration":   "Ration Card issued within 30 working days.",
            "ayushman": "Ayushman Bharat Rs.5 Lakh health cover activated.",
            "pmkisan":  "PM-KISAN Rs.6000/year will be credited to your bank.",
        }
        success_msgs = {
            "hi": "✅ आवेदन सफलतापूर्वक जमा!\n\nID: " + ref + "\n" + scheme_details.get(scheme, ""),
            "te": "✅ దరఖాస్తు విజయవంతంగా సమర్పించబడింది!\n\nID: " + ref + "\n" + scheme_details.get(scheme, ""),
            "en": "✅ Application submitted successfully!\n\nID: " + ref + "\n" + scheme_details.get(scheme, ""),
            "mr": "✅ अर्ज यशस्वीरित्या सादर!\n\nID: " + ref + "\n" + scheme_details.get(scheme, ""),
            "ta": "✅ விண்ணப்பம் வெற்றிகரமாக சமர்ப்பிக்கப்பட்டது!\n\nID: " + ref,
            "kn": "✅ ಅರ್ಜಿ ಯಶಸ್ವಿಯಾಗಿ ಸಲ್ಲಿಕೆಯಾಯಿತು!\n\nID: " + ref,
            "ml": "✅ അപേക്ഷ വിജയകരമായി സമർപ്പിച്ചു!\n\nID: " + ref,
            "bn": "✅ আবেদন সফলভাবে জমা দেওয়া হয়েছে!\n\nID: " + ref,
            "as": "✅ আবেদন সফলতাৰে দাখিল!\n\nID: " + ref,
        }
        msg = success_msgs.get(lang, success_msgs["en"])
        # Send via Twilio
        _send_whatsapp(phone, msg)
        update_user(phone, {"step": "completed"})
    except Exception as e:
        logger.error("RPA error: %s", e)
        _send_whatsapp(phone, "Application received! Our team will process it shortly.")

def _send_whatsapp(to: str, message: str):
    """Send WhatsApp message via Twilio REST API."""
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        to_fmt = "whatsapp:" + to if not to.startswith("whatsapp:") else to
        client.messages.create(body=message, from_=TWILIO_FROM, to=to_fmt)
        logger.info("WhatsApp sent to %s", to)
    except Exception as e:
        logger.error("Twilio send error: %s", e)

# ── Main webhook ──────────────────────────────────────────────────────────────
@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    try:
        form = await request.form()
    except Exception as e:
        logger.error("Form parse error: %s", e)
        return twiml("Sorry, something went wrong.")

    raw_from  = form.get("From", "")
    body      = (form.get("Body") or "").strip()
    num_media = int(form.get("NumMedia", 0) or 0)
    media_url = form.get("MediaUrl0")
    media_type = form.get("MediaContentType0", "")

    # Normalize phone
    phone = raw_from.replace("whatsapp:", "").strip()
    logger.info("[WA] from=%s body=%r media=%s", phone, body, num_media)

    user_data = get_user(phone)
    lang      = user_data.get("language", "en")
    step      = user_data.get("step", "new")
    body_lower = body.lower().strip()

    # ── Handle restart keywords ───────────────────────────────────────────────
    restart_words = ["hi", "hello", "start", "restart", "namaste", "menu",
                     "నమస్కారం", "नमस्ते", "வணக்கம்", "ನಮಸ್ಕಾರ"]
    if body_lower in restart_words or step == "new":
        db.collection("whatsapp_users").document(phone).set({
            "phone": phone, "step": "language_selection",
            "language": "en", "scheme": None, "history": [],
            "mobile": None, "aadhaar_data": None,
            "schemes_applied": [], "ocr_failures": 0,
        })
        return twiml(m("welcome", "en"))

    # ── Handle voice messages ─────────────────────────────────────────────────
    if num_media > 0 and media_url and "audio" in media_type:
        async with httpx.AsyncClient() as client:
            r = await client.get(media_url,
                                 auth=(TWILIO_SID, TWILIO_TOKEN),
                                 timeout=30.0, follow_redirects=True)
            audio_bytes = r.content
        transcript = await transcribe_voice(audio_bytes, lang)
        if transcript:
            logger.info("Voice transcript: %s", transcript)
            # Use transcript as body for further processing
            body = transcript
            body_lower = body.lower().strip()
            append_history(phone, "user", "[Voice] " + transcript)
        else:
            return twiml(m("error", lang))

    # ── STEP: Language selection ──────────────────────────────────────────────
    if step == "language_selection":
        if body.strip() in LANGUAGES:
            lang_code, lang_name = LANGUAGES[body.strip()]
            update_user(phone, {"language": lang_code, "step": "scheme_selection"})
            return twiml(m("lang_confirm", lang_code))
        else:
            return twiml(m("welcome", "en"))

    # ── STEP: Scheme selection ────────────────────────────────────────────────
    if step == "scheme_selection":
        if body.strip() in SCHEME_NAMES:
            scheme_key, scheme_name = SCHEME_NAMES[body.strip()]
            update_user(phone, {"scheme": scheme_key, "step": "farmer_check"})
            return twiml(m("farmer_check", lang))
        else:
            return twiml(m("lang_confirm", lang))

    # ── STEP: Farmer check (PM-KISAN eligibility) ─────────────────────────────
    if step == "farmer_check":
        scheme = user_data.get("scheme", "pmkisan")
        if body.strip() == "1":  # Yes - is farmer
            if scheme == "pmkisan":
                update_user(phone, {"step": "land_check", "is_farmer": True})
                return twiml(m("land_check", lang))
            else:
                update_user(phone, {"step": "ask_mobile"})
                return twiml(m("ask_mobile", lang))
        elif body.strip() == "2":  # No - not farmer
            if scheme == "pmkisan":
                update_user(phone, {"step": "scheme_selection"})
                return twiml(m("not_eligible", lang))
            else:
                update_user(phone, {"step": "ask_mobile"})
                return twiml(m("ask_mobile", lang))
        else:
            return twiml(m("farmer_check", lang))

    # ── STEP: Land check ──────────────────────────────────────────────────────
    if step == "land_check":
        if body.strip() == "3":  # More than 5 acres - not eligible
            update_user(phone, {"step": "scheme_selection"})
            return twiml(m("not_eligible", lang))
        elif body.strip() in ["1", "2"]:
            land_map = {"1": "less than 2 acres", "2": "2 to 5 acres"}
            update_user(phone, {"land": land_map[body.strip()], "step": "income_check"})
            return twiml(m("income_check", lang))
        else:
            return twiml(m("land_check", lang))

    # ── STEP: Income check ────────────────────────────────────────────────────
    if step == "income_check":
        if body.strip() == "3":  # More than 2 lakh - not eligible
            update_user(phone, {"step": "scheme_selection"})
            return twiml(m("not_eligible", lang))
        elif body.strip() in ["1", "2"]:
            income_map = {"1": "less than 1 lakh", "2": "1 to 2 lakh"}
            update_user(phone, {"income": income_map[body.strip()], "step": "ask_mobile"})
            return twiml(m("ask_mobile", lang))
        else:
            return twiml(m("income_check", lang))

    # ── STEP: Mobile collection ───────────────────────────────────────────────
    if step == "ask_mobile":
        phone_num = extract_phone(body)
        if phone_num:
            formatted = phone_num[:4] + " " + phone_num[4:7] + " " + phone_num[7:]
            update_user(phone, {"mobile_pending": phone_num, "step": "confirm_mobile"})
            return twiml(m("confirm_mobile", lang, phone=formatted))
        else:
            retry_msgs = {
                "hi": "कृपया 10 अंकों का मोबाइल नंबर बोलें या टाइप करें:",
                "te": "దయచేసి 10 అంకెల మొబైల్ నంబర్ చెప్పండి:",
                "en": "Please speak or type your 10-digit mobile number:",
                "mr": "कृपया 10 अंकी मोबाइल नंबर बोला किंवा टाइप करा:",
                "ta": "10 இலக்க மொபைல் எண்ணை சொல்லுங்கள்:",
            }
            return twiml(retry_msgs.get(lang, retry_msgs["en"]))

    # ── STEP: Confirm mobile ──────────────────────────────────────────────────
    if step == "confirm_mobile":
        if body.strip() == "1":  # Yes confirmed
            mobile = user_data.get("mobile_pending", "")
            update_user(phone, {"mobile": mobile, "mobile_pending": None, "step": "ask_aadhaar"})
            return twiml(m("ask_aadhaar", lang))
        elif body.strip() == "2":  # No retry
            update_user(phone, {"mobile_pending": None, "step": "ask_mobile"})
            return twiml(m("ask_mobile", lang))
        else:
            mobile = user_data.get("mobile_pending", "")
            formatted = mobile[:4] + " " + mobile[4:7] + " " + mobile[7:] if len(mobile) == 10 else mobile
            return twiml(m("confirm_mobile", lang, phone=formatted))

    # ── STEP: Aadhaar photo ───────────────────────────────────────────────────
    if step == "ask_aadhaar":
        if num_media > 0 and media_url and "image" in media_type:
            ocr_failures = user_data.get("ocr_failures", 0)
            if ocr_failures >= 3:
                update_user(phone, {"ocr_failures": 0})
                return twiml(m("ocr_helpline", lang))

            processing_msgs = {
                "hi": "📸 आधार कार्ड स्कैन हो रहा है...",
                "te": "📸 ఆధార్ కార్డ్ స్కాన్ అవుతోంది...",
                "en": "📸 Scanning your Aadhaar card...",
                "mr": "📸 आधार कार्ड स्कॅन होत आहे...",
                "ta": "📸 ஆதார் கார்டு ஸ்கேன் செய்யப்படுகிறது...",
            }
            # Download image
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(media_url,
                                        auth=(TWILIO_SID, TWILIO_TOKEN),
                                        timeout=30.0, follow_redirects=True)
                    image_bytes = r.content

                from routers.documents import run_aadhaar_ocr
                result = run_aadhaar_ocr(image_bytes)
                name   = result.get("name", "")
                dob    = result.get("dob", "")
                gender = result.get("gender", "")

                if name:
                    masked = result.get("aadhaar_masked") or result.get("aadhaar_masked", "XXXX XXXX ****")
                    update_user(phone, {
                        "aadhaar_data": result,
                        "name": name, "dob": dob, "gender": gender,
                        "state": result.get("state", ""),
                        "district": result.get("district", ""),
                        "pincode": result.get("pincode", ""),
                        "aadhaar_masked": masked,
                        "ocr_failures": 0,
                        "step": "confirm_aadhaar",
                    })
                    ocr_confirm = {
                        "hi": "✅ आधार स्कैन हो गया!\n\n👤 नाम: " + name + "\n📅 जन्म: " + dob + "\n⚧ लिंग: " + gender + "\n🔢 आधार: " + masked + "\n\nक्या यह सही है?\n1 - हाँ\n2 - नहीं, दोबारा भेजें",
                        "te": "✅ ఆధార్ స్కాన్ అయింది!\n\n👤 పేరు: " + name + "\n📅 జన్మ: " + dob + "\n⚧ లింగం: " + gender + "\n🔢 ఆధార్: " + masked + "\n\nఇది సరైనదా?\n1 - అవును\n2 - కాదు, మళ్ళీ పంపండి",
                        "en": "✅ Aadhaar scanned!\n\n👤 Name: " + name + "\n📅 DOB: " + dob + "\n⚧ Gender: " + gender + "\n🔢 Aadhaar: " + masked + "\n\nIs this correct?\n1 - Yes\n2 - No, resend",
                        "mr": "✅ आधार स्कॅन झाले!\n\n👤 नाव: " + name + "\n📅 जन्म: " + dob + "\n⚧ लिंग: " + gender + "\n🔢 आधार: " + masked + "\n\nहे बरोबर आहे का?\n1 - होय\n2 - नाही, पुन्हा पाठवा",
                        "ta": "✅ ஆதார் ஸ்கேன் ஆனது!\n\n👤 பெயர்: " + name + "\n📅 பிறந்த தேதி: " + dob + "\n⚧ பாலினம்: " + gender + "\n🔢 ஆதார்: " + masked + "\n\nசரியா?\n1 - ஆம்\n2 - இல்லை, மீண்டும் அனுப்பு",
                    }
                    return twiml(ocr_confirm.get(lang, ocr_confirm["en"]))
                else:
                    update_user(phone, {"ocr_failures": ocr_failures + 1})
                    return twiml(m("ocr_fail", lang))

            except Exception as e:
                logger.error("OCR error: %s", e)
                update_user(phone, {"ocr_failures": user_data.get("ocr_failures", 0) + 1})
                return twiml(m("ocr_fail", lang))
        else:
            return twiml(m("ask_aadhaar", lang))

    # ── STEP: Confirm Aadhaar ─────────────────────────────────────────────────
    if step == "confirm_aadhaar":
        if body.strip() == "1":  # Confirmed
            ud = get_user(phone)
            scheme = ud.get("scheme", "pmkisan")
            scheme_display = {"pmkisan": "PM-KISAN", "ration": "Ration Card", "ayushman": "Ayushman Bharat"}
            update_user(phone, {"step": "consent"})
            return twiml(m("consent", lang,
                name=ud.get("name", ""),
                mobile=ud.get("mobile", ""),
                aadhaar=ud.get("aadhaar_masked", ""),
                scheme=scheme_display.get(scheme, scheme),
            ))
        elif body.strip() == "2":  # Resend
            update_user(phone, {"step": "ask_aadhaar", "ocr_failures": 0})
            return twiml(m("ask_aadhaar", lang))
        else:
            return twiml(m("error", lang))

    # ── STEP: Final consent + RPA trigger ────────────────────────────────────
    if step == "consent":
        if body.strip() == "1":  # Submit
            # Duplicate check
            existing = list(db.collection("whatsapp_applications")
                            .where("phone", "==", phone)
                            .where("scheme", "==", user_data.get("scheme"))
                            .limit(1).stream())
            if existing:
                dup_msgs = {
                    "hi": "आप पहले से इस योजना के लिए आवेदन कर चुके हैं।",
                    "te": "మీరు ఇప్పటికే ఈ పథకానికి దరఖాస్తు చేశారు.",
                    "en": "You have already applied for this scheme.",
                    "mr": "तुम्ही या योजनेसाठी आधीच अर्ज केला आहे.",
                }
                return twiml(dup_msgs.get(lang, dup_msgs["en"]))

            db.collection("whatsapp_applications").add({
                "phone": phone,
                "scheme": user_data.get("scheme"),
                "time": time.time(),
            })
            update_user(phone, {"step": "processing"})
            threading.Thread(
                target=run_rpa,
                args=(phone, user_data.get("scheme", "pmkisan"), get_user(phone)),
                daemon=True
            ).start()
            return twiml(m("processing", lang))

        elif body.strip() == "2":  # Cancel
            update_user(phone, {"step": "scheme_selection"})
            cancel_msgs = {
                "hi": "आवेदन रद्द किया गया।\n\nदोबारा शुरू करने के लिए:\n1 - PM-KISAN\n2 - राशन कार्ड\n3 - आयुष्मान भारत",
                "te": "దరఖాస్తు రద్దు చేయబడింది.\n\nమళ్ళీ ప్రారంభించడానికి:\n1 - PM-KISAN\n2 - రేషన్ కార్డ్\n3 - ఆయుష్మాన్ భారత్",
                "en": "Application cancelled.\n\nTo restart:\n1 - PM-KISAN\n2 - Ration Card\n3 - Ayushman Bharat",
            }
            return twiml(cancel_msgs.get(lang, cancel_msgs["en"]))
        else:
            ud = get_user(phone)
            scheme_display = {"pmkisan": "PM-KISAN", "ration": "Ration Card", "ayushman": "Ayushman Bharat"}
            return twiml(m("consent", lang,
                name=ud.get("name", ""),
                mobile=ud.get("mobile", ""),
                aadhaar=ud.get("aadhaar_masked", ""),
                scheme=scheme_display.get(ud.get("scheme", ""), ""),
            ))

    # ── Fallback ──────────────────────────────────────────────────────────────
    return twiml(m("error", lang))
