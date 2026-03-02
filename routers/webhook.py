"""
routers/webhook.py — WhatsApp (Twilio) Webhook
JanSahayak | Team VUPO | AWS AI for Bharat 2026
"""
import os, uuid, threading
from typing import Dict
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response
from routers.chat import (
    t, detect_language, get_llm_response, transcribe_audio,
    extract_options_tag, extract_phone_from_text,
)

router = APIRouter(tags=["webhook"])

TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM  = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

_STATE: Dict[str, dict] = {}

LANGUAGES = {
    "1": ("hi", "Hindi"),   "2": ("te", "Telugu"),  "3": ("ta", "Tamil"),
    "4": ("kn", "Kannada"), "5": ("ml", "Malayalam"),"6": ("mr", "Marathi"),
    "7": ("bn", "Bengali"), "8": ("as", "Assamese"), "9": ("en", "English"),
}
SCHEMES = {
    "1": ("pmkisan",  "PM-KISAN"),
    "2": ("ration",   "Ration Card"),
    "3": ("ayushman", "Ayushman Bharat"),
}

def _get_db():
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not firebase_admin._apps:
        cred_path = "/home/ubuntu/app/firebase-credentials.json"
        firebase_admin.initialize_app(credentials.Certificate(cred_path))
    return firestore.client()

def get_state(user):
    try:
        db = _get_db()
        doc = db.collection('wa_users').document(user.replace('+','').replace(':','')).get()
        if doc.exists:
            data = doc.to_dict()
            _STATE[user] = data
            return data
    except Exception as e:
        print('[FIREBASE GET] ' + str(e))
    if user not in _STATE:
        _STATE[user] = {'step': 'language_selection', 'language': 'en'}
    return _STATE[user]

def save_state(user, data):
    _STATE.setdefault(user, {}).update(data)
    try:
        db = _get_db()
        db.collection('wa_users').document(user.replace('+','').replace(':','')).set(_STATE[user], merge=True)
    except Exception as e:
        print('[FIREBASE SAVE] ' + str(e))


def twiml(message):
    xml = '<?xml version="1.0" encoding="UTF-8"?><Response><Message>' + message + '</Message></Response>'
    return Response(content=xml, media_type="application/xml")

def lang_menu():
    return ("Welcome to JanSahayak!\nReply with number:\n\n"
            "1 - Hindi\n2 - Telugu\n3 - Tamil\n4 - Kannada\n"
            "5 - Malayalam\n6 - Marathi\n7 - Bengali\n8 - Assamese\n9 - English")

def scheme_menu(lang):
    msgs = {
        "en": "Which scheme?\n\n1 - PM-KISAN (Rs.6000/year)\n2 - Ration Card\n3 - Ayushman Bharat (Rs.5 lakh)",
        "hi": "कौन सी योजना?\n\n1 - PM-KISAN\n2 - राशन कार्ड\n3 - आयुष्मान भारत",
        "te": "ఏ పథకం?\n\n1 - PM-KISAN\n2 - రేషన్ కార్డ్\n3 - ఆయుష్మాన్ భారత్",
        "ta": "எந்த திட்டம்?\n\n1 - PM-KISAN\n2 - ரேஷன் கார்டு\n3 - ஆயுஷ்மான் பாரத்",
        "mr": "कोणती योजना?\n\n1 - PM-KISAN\n2 - रेशन कार्ड\n3 - आयुष्मान भारत",
    }
    return msgs.get(lang, msgs["en"])

def send_whatsapp(to, message):
    try:
        import requests
        requests.post(
            "https://api.twilio.com/2010-04-01/Accounts/" + TWILIO_SID + "/Messages.json",
            auth=(TWILIO_SID, TWILIO_TOKEN),
            data={"From": TWILIO_FROM, "To": to, "Body": message},
            timeout=15,
        )
    except Exception as e:
        print("[TWILIO ERROR] " + str(e))

def _send_whatsapp_screenshot(user, scheme, user_data, ref):
    import os
    try:
        from PIL import Image, ImageDraw
        snames = {"pmkisan": "PM-KISAN", "ration": "Ration Card", "ayushman": "Ayushman Bharat"}
        surls  = {"pmkisan": "pmkisan.gov.in", "ration": "nfsa.gov.in", "ayushman": "pmjay.gov.in"}
        name   = user_data.get("name", "Applicant")
        mobile = user_data.get("mobile", "")
        masked = user_data.get("aadhaar_masked", "XXXX XXXX XXXX")
        dob    = user_data.get("dob", "")
        gender = user_data.get("gender", "")
        sname  = snames.get(scheme, scheme)
        W, H = 800, 520
        img  = Image.new("RGB", (W, H), "#f0f4ff")
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, W, 60], fill="#1a237e")
        draw.text((20, 15), "JanSahayak - " + sname + " Application", fill="white")
        draw.text((W-200, 15), "Portal: " + surls.get(scheme,""), fill="#90caf9")
        draw.rectangle([20, 75, 280, 105], fill="#43a047")
        draw.text((30, 82), "SUBMITTED SUCCESSFULLY", fill="white")
        fields = [("Application ID", ref), ("Applicant Name", name),
                  ("Date of Birth", dob), ("Gender", gender),
                  ("Mobile Number", mobile), ("Aadhaar Number", masked),
                  ("Scheme", sname), ("Status", "Under Review")]
        y = 125
        for label, value in fields:
            draw.rectangle([20, y, W-20, y+30], fill="white", outline="#c5cae9")
            draw.text((30, y+7), label+":", fill="#5c6bc0")
            draw.text((260, y+7), str(value), fill="#212121")
            y += 35
        draw.rectangle([0, H-40, W, H], fill="#1a237e")
        draw.text((20, H-28), "JanSahayak AI  |  AWS AI for Bharat 2026", fill="#90caf9")
        static_dir = "/home/ubuntu/app/static"
        os.makedirs(static_dir, exist_ok=True)
        filepath = os.path.join(static_dir, "app_" + ref + ".png")
        img.save(filepath)
        public_url = "http://3.88.113.30:8000/static/app_" + ref + ".png"
        import requests as _req
        _req.post(
            "https://api.twilio.com/2010-04-01/Accounts/" + TWILIO_SID + "/Messages.json",
            auth=(TWILIO_SID, TWILIO_TOKEN),
            data={"From": TWILIO_FROM, "To": user,
                  "Body": "Application form submitted by JanSahayak",
                  "MediaUrl": public_url},
            timeout=15,
        )
        print("[SCREENSHOT] Sent: " + public_url)
    except Exception as e:
        print("[SCREENSHOT ERROR] " + str(e))
    scheme_msg = {
        "ration":   "Ration Card issued within 30 working days.",
        "ayushman": "Ayushman Bharat Rs.5 lakh health cover activated.",
        "pmkisan":  "PM-KISAN Rs.6000/year will be credited to your bank.",
    }
    snames2 = {"pmkisan": "PM-KISAN", "ration": "Ration Card", "ayushman": "Ayushman Bharat"}
    send_whatsapp(user,
        "✅ Application Submitted!\n\n"
        "📋 ID: " + ref + "\n"
        "👤 " + user_data.get("name","") + "\n"
        "🏛 " + snames2.get(scheme,scheme) + "\n\n"
        + scheme_msg.get(scheme,"") + "\n\n"
        "📌 Save your Application ID.\n"
        "Type 'hi' to apply for another scheme.")

def run_rpa(user, scheme, user_data):
    ref = "JS" + uuid.uuid4().hex[:6].upper()
    try:
        from rpa_agent import (submit_pm_kisan_application,
                               submit_ration_card_application,
                               submit_ayushman_application)
        fn = (submit_ration_card_application if scheme == "ration"
              else submit_ayushman_application if scheme == "ayushman"
              else submit_pm_kisan_application)
        result = fn(user_data)
        ref = result.get("application_id", ref)
    except Exception as e:
        print("[RPA ERROR] " + str(e))
    _send_whatsapp_screenshot(user, scheme, user_data, ref)

def ask_eligibility(scheme_key, lang):
    if scheme_key == "pmkisan":
        msgs = {
            "en": "PM-KISAN is for farmers.\n\nAre you a farmer?\n\n1 - Yes\n2 - No",
            "hi": "PM-KISAN किसानों के लिए है।\n\nक्या आप किसान हैं?\n\n1 - हाँ\n2 - नहीं",
            "te": "PM-KISAN రైతుల కోసం.\n\nమీరు రైతు అవునా?\n\n1 - అవును\n2 - కాదు",
            "ta": "PM-KISAN விவசாயிகளுக்கானது.\n\nநீங்கள் விவசாயியா?\n\n1 - ஆம்\n2 - இல்லை",
            "mr": "PM-KISAN शेतकऱ्यांसाठी.\n\nतुम्ही शेतकरी आहात का?\n\n1 - होय\n2 - नाही",
        }
    elif scheme_key == "ration":
        msgs = {
            "en": "Ration Card eligibility.\n\nAnnual family income?\n\n1 - Less than Rs.1 lakh\n2 - Rs.1-2 lakh\n3 - More than Rs.2 lakh",
            "hi": "राशन कार्ड पात्रता।\n\nसालाना आमदनी?\n\n1 - Rs.1 लाख से कम\n2 - Rs.1-2 लाख\n3 - Rs.2 लाख से अधिक",
            "te": "రేషన్ కార్డ్ అర్హత.\n\nవార్షిక ఆదాయం?\n\n1 - Rs.1 లక్ష కంటే తక్కువ\n2 - Rs.1-2 లక్షలు\n3 - Rs.2 లక్షలు పైన",
            "ta": "ரேஷன் கார்டு தகுதி.\n\nஆண்டு வருமானம்?\n\n1 - Rs.1 லட்சத்திற்கும் குறைவு\n2 - Rs.1-2 லட்சம்\n3 - Rs.2 லட்சத்திற்கும் அதிகம்",
            "mr": "रेशन कार्ड पात्रता.\n\nवार्षिक उत्पन्न?\n\n1 - Rs.1 लाखापेक्षा कमी\n2 - Rs.1-2 लाख\n3 - Rs.2 लाखापेक्षा जास्त",
        }
    else:
        msgs = {
            "en": "Ayushman Bharat is for low-income families.\n\nAnnual family income?\n\n1 - Less than Rs.1 lakh\n2 - Rs.1-2 lakh\n3 - More than Rs.2 lakh",
            "hi": "आयुष्मान भारत कम आय परिवारों के लिए।\n\nसालाना आमदनी?\n\n1 - Rs.1 लाख से कम\n2 - Rs.1-2 लाख\n3 - Rs.2 लाख से अधिक",
            "te": "ఆయుష్మాన్ భారత్ తక్కువ ఆదాయ కుటుంబాలకు.\n\nవార్షిక ఆదాయం?\n\n1 - Rs.1 లక్ష కంటే తక్కువ\n2 - Rs.1-2 లక్షలు\n3 - Rs.2 లక్షలు పైన",
            "ta": "ஆயுஷ்மான் பாரத் குறைந்த வருமான குடும்பங்களுக்கானது.\n\nஆண்டு வருமானம்?\n\n1 - Rs.1 லட்சத்திற்கும் குறைவு\n2 - Rs.1-2 லட்சம்\n3 - Rs.2 லட்சத்திற்கும் அதிகம்",
            "mr": "आयुष्मान भारत कमी उत्पन्न कुटुंबांसाठी.\n\nवार्षिक उत्पन्न?\n\n1 - Rs.1 लाखापेक्षा कमी\n2 - Rs.1-2 लाख\n3 - Rs.2 लाखापेक्षा जास्त",
        }
    return msgs.get(lang, msgs["en"])

@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    form_data  = await request.form()
    user       = form_data.get("From", "")
    body       = (form_data.get("Body", "") or "").strip()
    num_media  = int(form_data.get("NumMedia", 0) or 0)
    media_url  = form_data.get("MediaUrl0")
    media_type = form_data.get("MediaContentType0", "")

    print("[WA] From=" + user + " Body=" + repr(body))

    state = get_state(user)
    step  = state.get("step", "language_selection")
    lang  = state.get("language", "en")

    if body.lower() in ["hi", "hello", "start", "restart", "menu", "namaste"]:
        _STATE[user] = {"step": "language_selection", "language": "en"}
        return twiml(lang_menu())

    if step == "language_selection":
        if body in LANGUAGES:
            lang_code, lang_name = LANGUAGES[body]
            save_state(user, {"language": lang_code, "step": "scheme_selection"})
            return twiml(lang_name + " selected!\n\n" + scheme_menu(lang_code))
        detected = detect_language(body)
        if detected:
            save_state(user, {"language": detected, "step": "scheme_selection"})
            return twiml(scheme_menu(detected))
        return twiml(lang_menu())

    if step == "scheme_selection":
        if body in SCHEMES:
            scheme_key, scheme_name = SCHEMES[body]
            save_state(user, {"scheme": scheme_key, "step": "eligibility"})
            return twiml(ask_eligibility(scheme_key, lang))
        return twiml(scheme_menu(lang))

    if num_media > 0 and "audio" in media_type:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(media_url, auth=(TWILIO_SID, TWILIO_TOKEN), timeout=30)
            transcript = transcribe_audio(r.content, lang)
            if not transcript:
                return twiml("Could not understand. Please speak clearly or type a number.")
            print("[VOICE] " + transcript)
            phone = extract_phone_from_text(transcript)
            if phone and step == "mobile":
                save_state(user, {"mobile": phone, "step": "aadhaar_upload"})
                msgs = {
                    "en": "Got number: " + phone + "\n\nNow send Aadhaar photo (front side).",
                    "hi": "नंबर मिला: " + phone + "\n\nआधार कार्ड की फोटो भेजें।",
                    "te": "నంబర్: " + phone + "\n\nఆధార్ ఫోటో పంపండి.",
                }
                return twiml(msgs.get(lang, msgs["en"]))
            llm_response = get_llm_response(state.get("history", []), transcript, lang, state.get("scheme"))
            cleaned, _ = extract_options_tag(llm_response)
            return twiml("Voice: " + transcript + "\n\n" + cleaned)
        except Exception as e:
            print("[VOICE ERROR] " + str(e))
            return twiml("Voice processing failed. Please type your answer.")

    if num_media > 0 and "image" in media_type:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(media_url, auth=(TWILIO_SID, TWILIO_TOKEN),
                                     timeout=30, follow_redirects=True)
            from routers.documents import run_aadhaar_ocr
            result = run_aadhaar_ocr(r.content)
            name   = result.get("name", "")
            dob    = result.get("dob", "")
            gender = result.get("gender", "")
            if name:
                raw    = result.get("aadhaar", "")
                masked = "XXXX XXXX " + str(raw)[-4:] if len(str(raw)) >= 4 else str(raw)
                save_state(user, {
                    "name": name, "dob": dob, "gender": gender,
                    "aadhaar_masked": masked, "step": "confirm_aadhaar",
                    "state_name": result.get("state", ""),
                    "district": result.get("district", ""),
                })
                confirm_msgs = {
                    "en": "Aadhaar verified!\n\nName: " + name + "\nDOB: " + dob + "\nGender: " + gender + "\n\nCorrect?\n1 - Yes\n2 - No",
                    "hi": "आधार सत्यापित!\n\nनाम: " + name + "\nजन्म: " + dob + "\nलिंग: " + gender + "\n\nसही है?\n1 - हाँ\n2 - नहीं",
                    "te": "ఆధార్ ధృవీకరించబడింది!\n\nపేరు: " + name + "\nజన్మ: " + dob + "\nలింగం: " + gender + "\n\nసరైనదా?\n1 - అవును\n2 - కాదు",
                }
                return twiml(confirm_msgs.get(lang, confirm_msgs["en"]))
            else:
                fail_msgs = {
                    "en": "Could not read Aadhaar. Send a clear front-side photo.",
                    "hi": "आधार नहीं पढ़ पाया। साफ़ फोटो भेजें।",
                    "te": "ఆధార్ చదవలేకపోయాను. స్పష్టమైన ఫోటో పంపండి.",
                }
                return twiml(fail_msgs.get(lang, fail_msgs["en"]))
        except Exception as e:
            print("[OCR ERROR] " + str(e))
            return twiml("Could not read the card. Please send a clearer photo.")


    if step == "eligibility":
        scheme = state.get("scheme", "pmkisan")
        if scheme == "pmkisan":
            if body == "1":
                save_state(user, {"step": "income"})
                return twiml({"en": "Annual family income?\n\n1 - Less than Rs.1 lakh\n2 - Rs.1-2 lakh\n3 - More than Rs.2 lakh", "hi": "सालाना आमदनी?\n\n1 - Rs.1 लाख से कम\n2 - Rs.1-2 लाख\n3 - Rs.2 लाख से अधिक", "te": "వార్షిక ఆదాయం?\n\n1 - Rs.1 లక్ష కంటే తక్కువ\n2 - Rs.1-2 లక్షలు\n3 - Rs.2 లక్షలు పైన", "ta": "ஆண்டு வருமானம்?\n\n1 - Rs.1 லட்சத்திற்கும் குறைவு\n2 - Rs.1-2 லட்சம்\n3 - Rs.2 லட்சத்திற்கும் அதிகம்", "mr": "वार्षिक उत्पन्न?\n\n1 - Rs.1 लाखापेक्षा कमी\n2 - Rs.1-2 लाख\n3 - Rs.2 लाखापेक्षा जास्त", "kn": "ವಾರ್ಷಿಕ ಆದಾಯ?\n\n1 - Rs.1 ಲಕ್ಷಕ್ಕಿಂತ ಕಡಿಮೆ\n2 - Rs.1-2 ಲಕ್ಷ\n3 - Rs.2 ಲಕ್ಷಕ್ಕಿಂತ ಹೆಚ್ಚು", "ml": "വാർഷിക വരുമാനം?\n\n1 - Rs.1 ലക്ഷത്തിൽ കുറവ്\n2 - Rs.1-2 ലക്ഷം\n3 - Rs.2 ലക്ഷത്തിൽ കൂടുതൽ"}.get(lang, "Annual family income?\n\n1 - Less than Rs.1 lakh\n2 - Rs.1-2 lakh\n3 - More than Rs.2 lakh"))
            elif body == "2":
                save_state(user, {"step": "scheme_selection"})
                return twiml("Sorry, PM-KISAN is only for farmers.\n\n" + scheme_menu(lang))
            return twiml("Reply 1 for Yes, 2 for No")
        elif scheme == "ration":
            if body == "3":
                save_state(user, {"step": "scheme_selection"})
                return twiml("Sorry, Ration Card is for families earning less than Rs.2 lakh/year.\n\n" + scheme_menu(lang))
            if body in ["1", "2"]:
                save_state(user, {"income": body, "step": "mobile"})
                return twiml({"en": "You are eligible for Ration Card!\n\nPlease type your 10-digit mobile number.", "hi": "आप राशन कार्ड के पात्र हैं!\n\nमोबाइल नंबर भेजें।", "te": "మీరు రేషన్ కార్డ్‌కు అర్హులు!\n\nమొబైల్ నంబర్ పంపండి.", "ta": "நீங்கள் ரேஷன் கார்டுக்கு தகுதியானவர்!\n\nமொபைல் எண் அனுப்பவும்.", "mr": "तुम्ही रेशन कार्डसाठी पात्र आहात!\n\nमोबाइल नंबर पाठवा."}.get(lang, "You are eligible for Ration Card!\n\nPlease type your 10-digit mobile number."))
        else:
            if body == "3":
                save_state(user, {"step": "scheme_selection"})
                return twiml("Sorry, Ayushman Bharat is for families earning less than Rs.2 lakh/year.\n\n" + scheme_menu(lang))
            if body in ["1", "2"]:
                save_state(user, {"income": body, "step": "mobile"})
                return twiml({"en": "You are eligible for Ayushman Bharat!\n\nPlease type your 10-digit mobile number.", "hi": "आप आयुष्मान भारत के पात्र हैं!\n\nमोबाइल नंबर भेजें।", "te": "మీరు ఆయుష్మాన్ భారత్‌కు అర్హులు!\n\nమొబైల్ నంబర్ పంపండి.", "ta": "நீங்கள் ஆயுஷ்மான் பாரத்திற்கு தகுதியானவர்!\n\nமொபைல் எண் அனுப்பவும்.", "mr": "तुम्ही आयुष्मान भारतसाठी पात्र आहात!\n\nमोबाइल नंबर पाठवा."}.get(lang, "You are eligible for Ayushman Bharat!\n\nPlease type your 10-digit mobile number."))

    if step == "income":
        if body == "3":
            save_state(user, {"step": "scheme_selection"})
            return twiml("Sorry, income limit for PM-KISAN is Rs.2 lakh/year.\n\n" + scheme_menu(lang))
        save_state(user, {"income": body, "step": "land"})
        return twiml({"en": "How much agricultural land?\n\n1 - Less than 2 acres\n2 - 2-5 acres\n3 - More than 5 acres", "hi": "कितनी कृषि भूमि?\n\n1 - 2 एकड़ से कम\n2 - 2-5 एकड़\n3 - 5 एकड़ से अधिक", "te": "ఎంత వ్యవసాయ భూమి?\n\n1 - 2 ఎకరాల కంటే తక్కువ\n2 - 2-5 ఎకరాలు\n3 - 5 ఎకరాలు పైన", "ta": "எவ்வளவு விவசாய நிலம்?\n\n1 - 2 ஏக்கருக்கும் குறைவு\n2 - 2-5 ஏக்கர்\n3 - 5 ஏக்கருக்கும் அதிகம்", "mr": "किती शेतजमीन?\n\n1 - 2 एकरापेक्षा कमी\n2 - 2-5 एकर\n3 - 5 एकरापेक्षा जास्त", "kn": "ಎಷ್ಟು ಕೃಷಿ ಭೂಮಿ?\n\n1 - 2 ಎಕರೆಗಿಂತ ಕಡಿಮೆ\n2 - 2-5 ಎಕರೆ\n3 - 5 ಎಕರೆಗಿಂತ ಹೆಚ್ಚು", "ml": "എത്ര കൃഷി ഭൂമി?\n\n1 - 2 ഏക്കറിൽ കുറവ്\n2 - 2-5 ഏക്കർ\n3 - 5 ഏക്കറിൽ കൂടുതൽ"}.get(lang, "How much agricultural land?\n\n1 - Less than 2 acres\n2 - 2-5 acres\n3 - More than 5 acres"))

    if step == "land":
        if body == "3":
            save_state(user, {"step": "scheme_selection"})
            return twiml("Sorry, PM-KISAN is for farmers with 5 acres or less.\n\n" + scheme_menu(lang))
        save_state(user, {"land": body, "step": "mobile"})
        save_state(user, {"land": body, "step": "mobile"})
        return twiml({"en": "You are eligible for PM-KISAN!\n\nPlease type your 10-digit mobile number.", "hi": "आप PM-KISAN के पात्र हैं!\n\nमोबाइल नंबर भेजें।", "te": "మీరు PM-KISAN కు అర్హులు!\n\nమొబైల్ నంబర్ పంపండి.", "ta": "நீங்கள் PM-KISAN க்கு தகுதியானவர்!\n\nமொபைல் எண் அனுப்பவும்.", "mr": "तुम्ही PM-KISAN साठी पात्र आहात!\n\nमोबाइल नंबर पाठवा."}.get(lang, "You are eligible for PM-KISAN!\n\nPlease type your 10-digit mobile number."))
    if step == "mobile":
        phone = extract_phone_from_text(body)
        if phone:
            save_state(user, {"mobile": phone, "step": "aadhaar_upload"})
            msgs = {
                "en": "Got number: " + phone + "\n\nNow send a clear Aadhaar photo (front side).",
                "hi": "नंबर मिला: " + phone + "\n\nआधार कार्ड की फोटो भेजें।",
                "te": "నంబర్: " + phone + "\n\nఆధార్ కార్డ్ ఫోటో పంపండి.",
            }
            return twiml(msgs.get(lang, msgs["en"]))
        return twiml("Please send a valid 10-digit mobile number.")

    if step == "aadhaar_upload":
        msgs = {
            "en": "Please send a clear photo of your Aadhaar card (front side).",
            "hi": "आधार कार्ड की साफ़ फोटो भेजें।",
            "te": "ఆధార్ కార్డ్ ముందు వైపు ఫోటో పంపండి.",
        }
        return twiml(msgs.get(lang, msgs["en"]))

    if step == "confirm_aadhaar":
        if body == "1":
            save_state(user, {"step": "confirm_submit"})
            name   = state.get("name", "")
            mobile = state.get("mobile", "")
            masked = state.get("aadhaar_masked", "")
            scheme = state.get("scheme", "pmkisan")
            scheme_names = {"pmkisan": "PM-KISAN", "ration": "Ration Card", "ayushman": "Ayushman Bharat"}
            summary_msgs = {
                "en": "Summary:\n\nName: " + name + "\nMobile: " + mobile + "\nAadhaar: " + masked + "\nScheme: " + scheme_names.get(scheme, "") + "\n\nSubmit?\n1 - Yes\n2 - Cancel",
                "hi": "सारांश:\n\nनाम: " + name + "\nमोबाइल: " + mobile + "\nआधार: " + masked + "\nयोजना: " + scheme_names.get(scheme, "") + "\n\nजमा करें?\n1 - हाँ\n2 - रद्द",
                "te": "సారాంశం:\n\nపేరు: " + name + "\nమొబైల్: " + mobile + "\nఆధార్: " + masked + "\nపథకం: " + scheme_names.get(scheme, "") + "\n\nసమర్పించమా?\n1 - అవును\n2 - రద్దు",
            }
            return twiml(summary_msgs.get(lang, summary_msgs["en"]))
        else:
            save_state(user, {"step": "aadhaar_upload"})
            msgs = {
                "en": "Please resend a clearer Aadhaar photo.",
                "hi": "आधार कार्ड की साफ़ फोटो दोबारा भेजें।",
                "te": "ఆధార్ స్పష్టమైన ఫోటో మళ్ళీ పంపండి.",
            }
            return twiml(msgs.get(lang, msgs["en"]))

    if step == "confirm_submit":
        if body == "1":
            save_state(user, {"step": "submitted"})
            processing_msgs = {
                "en": "Processing your application... Please wait.",
                "hi": "आपका आवेदन प्रक्रिया में है...",
                "te": "మీ దరఖాస్తు ప్రక్రియలో ఉంది...",
            }
            send_whatsapp(user, processing_msgs.get(lang, processing_msgs["en"]))
            threading.Thread(
                target=run_rpa,
                args=(user, state.get("scheme", "pmkisan"), state),
                daemon=True
            ).start()
            return twiml("")
        else:
            save_state(user, {"step": "scheme_selection"})
            return twiml("Cancelled.\n\n" + scheme_menu(lang))

    llm_response = get_llm_response(state.get("history", []), body, lang, state.get("scheme"))
    cleaned, _ = extract_options_tag(llm_response)
    return twiml(cleaned)
