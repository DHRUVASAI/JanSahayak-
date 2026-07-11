import os, re, json, logging
from pathlib import Path
from groq import Groq
from services import ai_provider

logger = logging.getLogger(__name__)

_T_PATH = Path(__file__).parent.parent / "translations.json"
with open(_T_PATH, encoding="utf-8") as _f:
    TRANSLATIONS = json.load(_f)

def t(lang, key):
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"]).get(key) or TRANSLATIONS["en"].get(key) or key

import random
_GROQ_KEYS = [k for k in [os.getenv("GROQ_API_KEY"), os.getenv("GROQ_API_KEY_2")] if k]
def _get_client():
    return Groq(api_key=random.choice(_GROQ_KEYS))
LLM_MODEL = "llama-3.3-70b-versatile"

LANGUAGE_NAMES = {
    "en":"English","hi":"Hindi","te":"Telugu","ta":"Tamil",
    "kn":"Kannada","ml":"Malayalam","mr":"Marathi","as":"Assamese","bn":"Bengali"
}

SCRIPT_RANGES = {
    "hi":(0x0900,0x097F),"te":(0x0C00,0x0C7F),"ta":(0x0B80,0x0BFF),
    "kn":(0x0C80,0x0CFF),"ml":(0x0D00,0x0D7F),"bn":(0x0980,0x09FF)
}

ROMANIZED_LANG_MAP = {
    "namaskar":"hi","namaste":"hi","haan":"hi","kisan":"hi",
    "namaskaram":"te","avunu":"te","kaadu":"te","raitu":"te",
    "vanakkam":"ta","aam":"ta","illai":"ta",
    "haudu":"kn","illa":"kn","athe":"ml","alla":"ml",
    "ho":"mr","shetkari":"mr","nomoskar":"as","hoy":"as"
}

def detect_language(text):
    if not text: return None
    for char in text:
        cp = ord(char)
        for lang,(lo,hi) in SCRIPT_RANGES.items():
            if lo<=cp<=hi:
                if lang=="hi" and any(w in text for w in ["ahe","nahi","shetkari"]): return "mr"
                if lang=="bn" and any(w in text for w in ["nhoy","hoy","moi"]): return "as"
                return lang
    for word in re.findall(r"\w+", text.lower()):
        if word in ROMANIZED_LANG_MAP: return ROMANIZED_LANG_MAP[word]
    return None

def build_yes_no_keyboard(lang="en"):
    return {"inline_keyboard":[[{"text":t(lang,"yes"),"callback_data":"ans_yes"},{"text":t(lang,"no"),"callback_data":"ans_no"}]]}

def build_income_keyboard(lang="en"):
    opts=t(lang,"income_options")
    return {"inline_keyboard":[[{"text":opts[0],"callback_data":"income_low"},{"text":opts[1],"callback_data":"income_mid"},{"text":opts[2],"callback_data":"income_high"}]]}

def build_land_keyboard(lang="en"):
    opts=t(lang,"land_options")
    return {"inline_keyboard":[[{"text":opts[0],"callback_data":"land_small"},{"text":opts[1],"callback_data":"land_mid"},{"text":opts[2],"callback_data":"land_large"}]]}

def build_family_keyboard(lang="en"):
    opts=t(lang,"family_options")
    if not isinstance(opts,list): opts=["1-2","3-4","5+"]
    return {"inline_keyboard":[[{"text":opts[0],"callback_data":"family_small"},{"text":opts[1],"callback_data":"family_mid"},{"text":opts[2],"callback_data":"family_large"}]]}

def build_contact_keyboard(lang="en"):
    return {"inline_keyboard":[[{"text":t(lang,"share_contact"),"callback_data":"request_contact"}],[{"text":t(lang,"voice_hint"),"callback_data":"hint_voice"}]]}

def build_gender_keyboard(lang="en"):
    opts = t(lang, "gender_options")
    if not isinstance(opts, list): opts = ["Male 👨", "Female 👩"]
    return {"inline_keyboard": [[
        {"text": opts[0], "callback_data": "gender_male"},
        {"text": opts[1], "callback_data": "gender_female"}
    ]]}

def build_schemes_keyboard(lang="en"):
    return {"inline_keyboard":[
        [{"text":t(lang,"scheme_pmkisan"),"callback_data":"scheme_pmkisan"}],
        [{"text":t(lang,"scheme_ration"),"callback_data":"scheme_ration"}],
        [{"text":t(lang,"scheme_ayushman"),"callback_data":"scheme_ayushman"}],
        [{"text":t(lang,"scheme_nsap"),"callback_data":"scheme_nsap"}]
    ]}

def build_language_keyboard():
    langs=[("🇮🇳 English","lang_en"),("हिंदी","lang_hi"),("తెలుగు","lang_te"),
           ("தமிழ்","lang_ta"),("ಕನ್ನಡ","lang_kn"),("മലയാളം","lang_ml"),
           ("मराठी","lang_mr"),("অসমীয়া","lang_as"),("বাংলা","lang_bn")]
    rows=[]
    for i in range(0,len(langs),3):
        rows.append([{"text":lbl,"callback_data":cb} for lbl,cb in langs[i:i+3]])
    return {"inline_keyboard":rows}

def get_keyboard_for_options_tag(tag,lang="en"):
    tag=tag.strip().lower()
    if tag=="yes_no": return build_yes_no_keyboard(lang)
    if tag=="income": return build_income_keyboard(lang)
    if tag=="land": return build_land_keyboard(lang)
    if tag=="contact": return build_contact_keyboard(lang)
    if tag=="gender": return build_gender_keyboard(lang)
    if tag=="schemes": return build_schemes_keyboard(lang)
    if tag=="family": return build_family_keyboard(lang)
    return None

def extract_options_tag(text):
    match=re.search(r"OPTIONS:\s*(\w+)",text,re.IGNORECASE)
    if match:
        tag=match.group(1)
        cleaned=re.sub(r"OPTIONS:\s*\w+","",text,flags=re.IGNORECASE).strip()
        return cleaned,tag
    return text,None

CALLBACK_ANSWER_MAP={
    "ans_yes":"Yes","ans_no":"No",
    "income_low":"Less than 1 lakh","income_mid":"1 to 2 lakh","income_high":"More than 2 lakh",
    "land_small":"Less than 2 acres","land_mid":"2 to 5 acres","land_large":"More than 5 acres",
    "family_small":"1 to 2 members","family_mid":"3 to 4 members","family_large":"5 or more members",
    "scheme_pmkisan":"PM-KISAN","scheme_ration":"Ration Card","scheme_ayushman":"Ayushman Bharat","scheme_nsap":"NSAP Classifier",
    "gender_male":"Male","gender_female":"Female"
}

def resolve_callback(callback_data):
    if callback_data.startswith("state_"):
        return callback_data.replace("state_","").replace("_"," ").title()
    return CALLBACK_ANSWER_MAP.get(callback_data)

def check_eligibility_from_callback(scheme, callback_data, step=None):
    """
    Only reject when we are SURE about the context.
    ans_no means not_farmer ONLY when step is farmer_check.
    For govt employee question, ans_no means they are NOT a govt employee = eligible.
    """
    if scheme == "pmkisan":
        if callback_data == "income_high": return "income_too_high"
        if callback_data == "land_large": return "land_too_large"
        # Only reject as not_farmer if explicitly on farmer step
        if callback_data == "ans_no" and step == "farmer_check": return "not_farmer"
    if scheme == "ration":
        if callback_data == "income_high": return "ration_income_too_high"
        if callback_data == "income_mid": return "ration_income_too_high"
    return None

SYSTEM_PROMPT="""You are JanSahayak, a helpful assistant for rural Indians applying for government schemes.
Be warm, simple, and patient like a trusted village helper.

ABSOLUTE RULES:
1. ALWAYS reply in the user selected language. NEVER switch languages.
2. Ask ONLY ONE question at a time.
3. NEVER say application submitted, form filled, or application complete. You only collect information.
4. NEVER skip Aadhaar collection. Always ask for Aadhaar photo.
5. NEVER assume or make up any user data.
6. ALWAYS end questions with OPTIONS tag for buttons.
7. If the user's mobile number is ALREADY known or mentioned in the conversation history, DO NOT ask for it and do NOT output "OPTIONS: contact". Instead, proceed directly to asking for their Aadhaar card photo (Step 3) without any options tag.
8. When the user provides the extracted Aadhaar details (e.g., "Document uploaded. Extracted details: ..."), you MUST immediately construct and output the Application Summary in the selected language. Do NOT apologize, do NOT refuse, and do NOT say you cannot store or process it. Simply format the summary containing Name, Mobile, masked Aadhaar, District, State, and Scheme, and ask: "Shall I submit your application now?" followed by "OPTIONS: yes_no".
9. If a user is not eligible for a scheme (e.g., they answer "No" to being a farmer, their land size is too large, or their income is too high), you MUST immediately state that they are not eligible, explain why in simple terms, and prompt them to choose another scheme by outputting: "OPTIONS: schemes" at the end. Do NOT ask them to start over or repeat the eligibility questions for the same scheme.

MANDATORY COLLECTION ORDER:
Step 1: Eligibility questions
Step 2: Mobile number -> OPTIONS: contact (Skip if mobile is already known)
Step 3: Ask user to send clear photo of Aadhaar card (Do not include any OPTIONS tag here)
Step 4: After Aadhaar received -> show summary
Step 5: Confirmation -> OPTIONS: yes_no
Step 6: Say details saved, team will process shortly

SCHEMES:
- PM-KISAN: 6000/year for farmers. land<=5acres, income<=2L, not govt employee
- Ration Card: subsidized food. income<1L for BPL
- Ayushman Bharat: health insurance 5L. family income<5L
- NSAP: National Social Assistance Program. Financial assistance for BPL. You must collect: 
  1. Age.
  2. BPL status. (DO NOT say "BPL" to the user. Instead, ask: "Does your family have a BPL ration card or low income?" -> OPTIONS: yes_no)
  3. Gender. (OPTIONS: gender)
  4. Disability. (DO NOT ask for percentage. Instead, ask: "Do you have a severe disability of 80% or more?" -> OPTIONS: yes_no)
  5. Primary earning member deceased status. (DO NOT say "breadwinner". Instead, ask: "Has the primary earning member of your family passed away?" -> OPTIONS: yes_no)
  6. Receiving other pensions. (Ask: "Are you already receiving any other pension?" -> OPTIONS: yes_no)

OPTIONS TAGS:
- Yes/No -> OPTIONS: yes_no
- Income -> OPTIONS: income
- Land size -> OPTIONS: land
- Family members -> OPTIONS: family
- Mobile number -> OPTIONS: contact
- Gender -> OPTIONS: gender
- Scheme selection -> OPTIONS: schemes"""

def _process_nsap_recommendation(result, conversation_history, user_message, language, scheme):
    if not result:
        return result
    if scheme and "nsap" in scheme.lower():
        if "options: contact" in result or "options: contact" in result.lower():
            try:
                from services.nsap_service import extract_features_and_predict
                full_history = conversation_history + [{"role": "user", "content": user_message}]
                predicted = extract_features_and_predict(full_history)
                
                desc_en = {
                    "IGNOAPS": "Indira Gandhi National Old Age Pension Scheme (IGNOAPS)",
                    "IGNWPS": "Indira Gandhi National Widow Pension Scheme (IGNWPS)",
                    "IGNDPS": "Indira Gandhi National Disability Pension Scheme (IGNDPS)",
                    "NFBS": "National Family Benefit Scheme (NFBS)",
                    "Annapurna": "Annapurna Scheme (Annapurna)",
                    "Ineligible": "None (Ineligible)"
                }.get(predicted, "None (Ineligible)")
                
                desc_hi = {
                    "IGNOAPS": "इंदिरा गांधी राष्ट्रीय वृद्धावस्था पेंशन योजना (IGNOAPS)",
                    "IGNWPS": "इंदिरा गांधी राष्ट्रीय विधवा पेंशन योजना (IGNWPS)",
                    "IGNDPS": "इंदिरा गांधी राष्ट्रीय विकलांगता पेंशन योजना (IGNDPS)",
                    "NFBS": "राष्ट्रीय पारिवारिक लाभ योजना (NFBS)",
                    "Annapurna": "अन्नपूर्णा योजना (Annapurna)",
                    "Ineligible": "कोई नहीं (अपात्र)"
                }.get(predicted, "कोई नहीं (अपात्र)")
                
                if predicted != "Ineligible":
                    rec_en = f"🎯 **NSAP Recommendation**: Based on our machine learning model classification, the most appropriate scheme for you is: **{desc_en}**."
                    rec_hi = f"🎯 **एनएसएपी (NSAP) पात्रता सिफ़ारिश**: हमारे मशीन लर्निंग मॉडल वर्गीकरण के अनुसार, आपके लिए सबसे उपयुक्त योजना: **{desc_hi}** है।"
                else:
                    rec_en = f"⚠️ **NSAP Recommendation**: Based on our machine learning model classification, you do not meet the eligibility criteria for the NSAP schemes (must be from a Below Poverty Line household)."
                    rec_hi = f"⚠️ **एनएसएपी (NSAP) पात्रता सिफ़ารिश**: हमारे मशीन लर्निंग मॉडल वर्गीकरण के अनुसार, आप एनएसएपी योजना के पात्रता मानदंडों को पूरा नहीं करते हैं (बीपीएल होना आवश्यक है)।"
                    
                rec = rec_hi if language == "hi" else rec_en
                result = f"{rec}\n\n{result}"
            except Exception as e:
                logger.error(f"Error running NSAP classifier: {e}")
    return result

def get_llm_response(conversation_history,user_message,language="en",scheme=None,mobile=None):
    lang_name=LANGUAGE_NAMES.get(language,"English")
    system=SYSTEM_PROMPT+f"\n\nUSER LANGUAGE: {lang_name}. Every reply must be in {lang_name} only."
    if scheme: system+=f" Scheme: {scheme.upper()}."
    if mobile:
        system+=f"\nUser's verified mobile number is: {mobile}. Do NOT ask for the user's mobile number or contact details. Proceed directly to asking the user to upload their Aadhaar card photo."

    # Build full prompt string from conversation history + new message
    history_text = ""
    for msg in conversation_history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        history_text += f"\n[{role}]: {content}"
    full_prompt = history_text + f"\n[user]: {user_message}" if history_text else user_message

    import time
    for attempt in range(3):
        try:
            # Route through ai_provider (IBM Granite or AWS Bedrock based on AI_PROVIDER env)
            result = ai_provider.get_llm_response(full_prompt, system, max_tokens=512)
            if result and result != "Sorry, service temporarily unavailable.":
                return _process_nsap_recommendation(result, conversation_history, user_message, language, scheme)
            # If ai_provider returned its own fallback string, try Groq directly
            raise Exception("ai_provider returned empty/fallback result")
        except Exception as e:
            logger.error(f"LLM error via ai_provider (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(2)
                continue
            # Final fallback: Groq directly
            try:
                response=_get_client().chat.completions.create(
                    model=LLM_MODEL,
                    messages=[{"role":"system","content":system}]+conversation_history+[{"role":"user","content":user_message}],
                    max_tokens=512,temperature=0.2)
                return _process_nsap_recommendation(response.choices[0].message.content, conversation_history, user_message, language, scheme)
            except Exception as groq_e:
                logger.error(f"Groq final fallback also failed: {groq_e}")
                return "Sorry, please try again."
    return "Sorry, please try again."

def transcribe_audio(audio_bytes,language=None):
    import tempfile
    # Route through ai_provider (IBM Watson STT or AWS Transcribe based on AI_PROVIDER env)
    try:
        lang = language or "hi"
        result = ai_provider.transcribe_audio(audio_bytes, lang)
        if result:
            return result
    except Exception as e:
        logger.warning(f"ai_provider transcribe_audio failed, using Groq Whisper: {e}")

    # Groq Whisper fallback
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg",delete=False) as f:
            f.write(audio_bytes); f.flush()
            with open(f.name,"rb") as af:
                kwargs={"file":af,"model":"whisper-large-v3"}
                if language: kwargs["language"]=language
                return _get_client().audio.transcriptions.create(**kwargs).text
    except Exception as e:
        logger.error(f"Whisper error: {e}"); return ""

def extract_phone_from_text(text):
    if not text:
        return None
    digits=re.sub(r"\D","",text)
    match=re.search(r"(?:91|0)?(\d{10})",digits)
    return match.group(1) if match else None
