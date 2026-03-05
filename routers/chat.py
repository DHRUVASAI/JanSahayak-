import os, re, json, logging
from pathlib import Path
from groq import Groq

logger = logging.getLogger(__name__)

_T_PATH = Path("/home/ubuntu/app/translations.json")
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

def build_schemes_keyboard(lang="en"):
    return {"inline_keyboard":[
        [{"text":t(lang,"scheme_pmkisan"),"callback_data":"scheme_pmkisan"}],
        [{"text":t(lang,"scheme_ration"),"callback_data":"scheme_ration"}],
        [{"text":t(lang,"scheme_ayushman"),"callback_data":"scheme_ayushman"}]
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
    "scheme_pmkisan":"PM-KISAN","scheme_ration":"Ration Card","scheme_ayushman":"Ayushman Bharat"
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

MANDATORY COLLECTION ORDER:
Step 1: Eligibility questions
Step 2: Mobile number -> OPTIONS: contact
Step 3: Ask user to send clear photo of Aadhaar card
Step 4: After Aadhaar received -> show summary
Step 5: Confirmation -> OPTIONS: yes_no
Step 6: Say details saved, team will process shortly

SCHEMES:
- PM-KISAN: 6000/year for farmers. land<=5acres, income<=2L, not govt employee
- Ration Card: subsidized food. income<1L for BPL
- Ayushman Bharat: health insurance 5L. family income<5L

OPTIONS TAGS:
- Yes/No -> OPTIONS: yes_no
- Income -> OPTIONS: income
- Land size -> OPTIONS: land
- Family members -> OPTIONS: family
- Mobile number -> OPTIONS: contact
- Scheme selection -> OPTIONS: schemes"""

def get_llm_response(conversation_history,user_message,language="en",scheme=None):
    lang_name=LANGUAGE_NAMES.get(language,"English")
    system=SYSTEM_PROMPT+f"\n\nUSER LANGUAGE: {lang_name}. Every reply must be in {lang_name} only."
    if scheme: system+=f" Scheme: {scheme.upper()}."
    # Try Amazon Bedrock first
    try:
        from aws_services import bedrock_llm
        full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in conversation_history])
        full_prompt += f"\nuser: {user_message}"
        reply = bedrock_llm(full_prompt, system=system, max_tokens=512)
        if reply:
            logger.info("[Bedrock] LLM response used")
            return reply
    except Exception as e:
        logger.error(f"[Bedrock] Failed, using Groq: {e}")
    import time
    for attempt in range(3):
        try:
            response=_get_client().chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role":"system","content":system}]+conversation_history+[{"role":"user","content":user_message}],
                max_tokens=512,temperature=0.2)
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM error (attempt {attempt+1}): {e}")
            if "429" in str(e) and attempt < 2:
                time.sleep(10)
                continue
            return "Sorry, please try again."
    return "Sorry, please try again."

def transcribe_audio(audio_bytes,language=None):
    import tempfile
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
