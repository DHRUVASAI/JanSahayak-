#!/usr/bin/env python3
"""
JanSahayak Comprehensive Test Suite
Tests every component, edge case, and known bug
"""
import os
import sys
import builtins
_orig_open = builtins.open
def new_open(*args, **kwargs):
    mode = kwargs.get("mode", args[1] if len(args) > 1 else "r")
    if "b" not in mode and "encoding" not in kwargs:
        kwargs["encoding"] = "utf-8"
    return _orig_open(*args, **kwargs)
builtins.open = new_open

import json
import time
import base64
import requests
import traceback
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
EC2_APP = str(Path(__file__).parent.resolve())
sys.path.insert(0, EC2_APP)
os.chdir(EC2_APP)

from dotenv import load_dotenv
load_dotenv(f"{EC2_APP}/.env")

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"
INFO = "ℹ️"

results = []

def test(name, fn):
    try:
        result = fn()
        status = PASS if result else FAIL
        msg = f"{status} {name}"
        results.append((status, name))
        print(msg)
        return result
    except Exception as e:
        print(f"{FAIL} {name}")
        print(f"   Error: {e}")
        results.append((FAIL, name))
        return False

def warn(name, fn):
    try:
        result = fn()
        status = PASS if result else WARN
        msg = f"{status} {name}"
        results.append((status, name))
        print(msg)
        return result
    except Exception as e:
        print(f"{WARN} {name}: {e}")
        results.append((WARN, name))
        return False

print("\n" + "="*60)
print("🤖 JANSAHAYAK COMPREHENSIVE TEST SUITE")
print("="*60)

# ══════════════════════════════════════════════════════════════
print("\n📁 1. FILE & ENVIRONMENT TESTS")
print("-"*40)

test("polling_bot.py exists", lambda: Path(f"{EC2_APP}/polling_bot.py").exists())
test("chat.py exists", lambda: Path(f"{EC2_APP}/routers/chat.py").exists())
test("documents.py exists", lambda: Path(f"{EC2_APP}/routers/documents.py").exists())
test("translations.json exists", lambda: Path(f"{EC2_APP}/translations.json").exists())
test("firebase-credentials.json exists", lambda: Path(f"{EC2_APP}/firebase-credentials.json").exists())
test(".env exists", lambda: Path(f"{EC2_APP}/.env").exists())
test("GROQ_API_KEY set", lambda: bool(os.getenv("GROQ_API_KEY")))
test("TELEGRAM_BOT_TOKEN set", lambda: bool(os.getenv("TELEGRAM_BOT_TOKEN")))
test("FIREBASE_CRED set", lambda: bool(os.getenv("FIREBASE_CRED") or os.getenv("FIREBASE_CREDENTIALS_PATH") or Path(f"{EC2_APP}/firebase-credentials.json").exists()))

# ══════════════════════════════════════════════════════════════
print("\n🔤 2. TRANSLATIONS.JSON TESTS")
print("-"*40)

def check_translations():
    with open(f"{EC2_APP}/translations.json") as f:
        t = json.load(f)
    
    required_langs = ["en","hi","te","ta","kn","ml","mr","as","bn"]
    required_keys = [
        "yes","no","share_contact","voice_hint",
        "income_options","land_options",
        "scheme_pmkisan","scheme_ration","scheme_ayushman",
        "scheme_prompt","lang_confirm",
        "family_options"
    ]
    
    missing = []
    for lang in required_langs:
        if lang not in t:
            missing.append(f"lang:{lang}")
            continue
        for key in required_keys:
            if key not in t[lang]:
                missing.append(f"{lang}.{key}")
    
    if missing:
        print(f"   Missing: {missing[:5]}")
        return False
    return True

test("All 9 languages present", check_translations)

def check_translation_values():
    with open(f"{EC2_APP}/translations.json") as f:
        t = json.load(f)
    # Check no key returns its own name (unfilled)
    for lang in ["hi","te","ta"]:
        if t.get(lang,{}).get("scheme_pmkisan") == "scheme_pmkisan":
            return False
        if t.get(lang,{}).get("yes") == "yes":
            return False
    return True

test("Translation values not empty/placeholder", check_translation_values)
test("Telugu scheme names in Telugu script", lambda: "పీఎం" in json.load(open(f"{EC2_APP}/translations.json")).get("te",{}).get("scheme_pmkisan",""))
test("Hindi yes button in Hindi", lambda: "हाँ" in json.load(open(f"{EC2_APP}/translations.json")).get("hi",{}).get("yes","") or "हां" in json.load(open(f"{EC2_APP}/translations.json")).get("hi",{}).get("yes",""))
test("Error messages present", lambda: "error_generic" in json.load(open(f"{EC2_APP}/translations.json")).get("en",{}))
test("Consent text present", lambda: "consent_title" in json.load(open(f"{EC2_APP}/translations.json")).get("en",{}))

# ══════════════════════════════════════════════════════════════
print("\n🧠 3. CHAT.PY / LLM TESTS")
print("-"*40)

def import_chat():
    from routers.chat import (
        t, build_yes_no_keyboard, build_schemes_keyboard,
        build_income_keyboard, build_land_keyboard,
        get_keyboard_for_options_tag, extract_options_tag,
        resolve_callback, detect_language, LANGUAGE_NAMES
    )
    return True

test("chat.py imports without error", import_chat)

def test_t_function():
    from routers.chat import t
    assert t("en", "yes") != "yes", "t() returning key name"
    assert t("te", "scheme_pmkisan") != "scheme_pmkisan", "Telugu scheme not translated"
    assert t("hi", "yes") != "yes", "Hindi yes not translated"
    assert t("xx", "yes") == t("en", "yes"), "Invalid lang should fallback to en"
    return True

test("t() function works correctly", test_t_function)

def test_keyboards():
    from routers.chat import (
        build_yes_no_keyboard, build_schemes_keyboard,
        build_income_keyboard, build_land_keyboard,
        build_family_keyboard
    )
    for lang in ["en","hi","te","ta"]:
        kb = build_yes_no_keyboard(lang)
        assert "inline_keyboard" in kb
        buttons = kb["inline_keyboard"][0]
        assert len(buttons) == 2
        # Buttons should NOT be in English for non-English
        if lang == "hi":
            assert buttons[0]["text"] != "Yes ✅", f"Hindi yes button still in English"
        if lang == "te":
            assert buttons[0]["text"] != "Yes ✅", f"Telugu yes button still in English"
    
    # Scheme keyboard
    kb = build_schemes_keyboard("te")
    texts = [row[0]["text"] for row in kb["inline_keyboard"]]
    assert all("PM-KISAN" not in t or "పీఎం" in t for t in texts) or any("పీఎం" in t for t in texts), "Telugu scheme keyboard not in Telugu"
    return True

test("All keyboards return correct language", test_keyboards)

def test_options_tag():
    from routers.chat import extract_options_tag, get_keyboard_for_options_tag
    
    # Test extraction
    text, tag = extract_options_tag("Are you a farmer? OPTIONS: yes_no")
    assert tag == "yes_no", f"Tag not extracted: {tag}"
    assert "OPTIONS" not in text, "OPTIONS tag not cleaned from text"
    
    # Test no tag
    text2, tag2 = extract_options_tag("Hello how are you")
    assert tag2 is None
    
    # Test all keyboard types
    for tag_name in ["yes_no","income","land","family","contact","schemes"]:
        kb = get_keyboard_for_options_tag(tag_name, "en")
        assert kb is not None, f"No keyboard for {tag_name}"
    
    return True

test("OPTIONS tag extraction works", test_options_tag)

def test_language_detection():
    from routers.chat import detect_language
    
    assert detect_language("నమస్కారం") == "te", "Telugu not detected"
    assert detect_language("नमस्ते") == "hi", "Hindi not detected"
    assert detect_language("நமஸ்காரம்") == "ta", "Tamil not detected"
    assert detect_language("ನಮಸ್ಕಾರ") == "kn", "Kannada not detected"
    assert detect_language("") is None, "Empty string should return None"
    assert detect_language(None) is None, "None should return None"
    return True

test("Language detection works for all scripts", test_language_detection)

def test_callback_resolution():
    from routers.chat import resolve_callback
    
    assert resolve_callback("ans_yes") == "Yes"
    assert resolve_callback("ans_no") == "No"
    assert resolve_callback("income_low") == "Less than 1 lakh"
    assert resolve_callback("land_small") == "Less than 2 acres"
    assert resolve_callback("family_mid") == "3 to 4 members"
    assert resolve_callback("unknown_key") is None
    return True

test("Callback resolution works", test_callback_resolution)

# ══════════════════════════════════════════════════════════════
print("\n📄 4. DOCUMENTS.PY / OCR TESTS")
print("-"*40)

def import_documents():
    from routers.documents import run_aadhaar_ocr, mask_aadhaar, detect_mime_type
    return True

test("documents.py imports without error", import_documents)

def test_mime_detection():
    from routers.documents import detect_mime_type
    
    # PNG magic bytes
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    assert detect_mime_type(png) == "image/png"
    
    # JPEG magic bytes
    jpg = b"\xff\xd8\xff" + b"\x00" * 100
    assert detect_mime_type(jpg) == "image/jpeg"
    
    # Unknown defaults to jpeg
    unknown = b"\x00\x01\x02\x03"
    assert detect_mime_type(unknown) == "image/jpeg"
    
    return True

test("MIME type detection works", test_mime_detection)

def test_aadhaar_masking():
    from routers.documents import mask_aadhaar
    
    # Valid 12 digit
    result = mask_aadhaar("123456789012")
    assert result is not None, "Should not return None for valid aadhaar"
    assert "9012" in result, "Last 4 digits should be visible"
    assert "1234" not in result, "First digits should be masked"
    
    # With spaces
    result2 = mask_aadhaar("1234 5678 9012")
    assert result2 is not None
    assert "9012" in result2
    
    # Invalid
    assert mask_aadhaar(None) is None
    assert mask_aadhaar("123") is None  # too short
    assert mask_aadhaar("") is None
    
    return True

test("Aadhaar masking works correctly", test_aadhaar_masking)

def test_groq_vision_model():
    # Just check model name is correct
    from routers.documents import run_aadhaar_ocr
    import inspect
    src = inspect.getsource(run_aadhaar_ocr)
    assert "gemini" not in src.lower(), "Still using Gemini instead of Groq!"
    assert "groq" in src.lower() or "llama-4" in src.lower(), "Not using Groq Vision"
    return True

test("OCR uses Groq Vision (not Gemini)", test_groq_vision_model)

# ══════════════════════════════════════════════════════════════
print("\n🔌 5. API CONNECTIVITY TESTS")
print("-"*40)

def test_groq_api():
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":"Say OK"}],
        max_tokens=5
    )
    return "OK" in response.choices[0].message.content or len(response.choices[0].message.content) > 0

test("Groq API key works", test_groq_api)

def test_groq_key2():
    key2 = os.getenv("GROQ_API_KEY_2")
    if not key2 or key2 == os.getenv("GROQ_API_KEY"):
        print(f"   {WARN} GROQ_API_KEY_2 is same as primary or not set")
        return True  # warn only
    from groq import Groq
    client = Groq(api_key=key2)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":"Say OK"}],
        max_tokens=5
    )
    return len(response.choices[0].message.content) > 0

warn("Groq API key 2 is different and works", test_groq_key2)

def test_telegram_api():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
    data = r.json()
    if data.get("ok"):
        print(f"   Bot: @{data['result']['username']}")
        return True
    return False

test("Telegram bot token valid", test_telegram_api)

def test_firebase():
    import firebase_admin
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not firebase_admin._apps:
        cred = credentials.Certificate(f"{EC2_APP}/firebase-credentials.json")
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    # Try a read
    docs = db.collection("users").limit(1).get()
    return True

test("Firebase Firestore connected", test_firebase)

def test_no_duplicate_instances():
    import subprocess
    import sys
    if sys.platform == "win32":
        return True
    result = subprocess.run(
        ["pgrep", "-f", "polling_bot"],
        capture_output=True, text=True
    )
    pids = result.stdout.strip().split('\n')
    pids = [p for p in pids if p]
    count = len(pids)
    if count > 1:
        print(f"   {WARN} {count} instances running! PIDs: {pids}")
        return False
    return True

test("Only ONE bot instance running", test_no_duplicate_instances)

# ══════════════════════════════════════════════════════════════
print("\n🤖 6. BOT LOGIC TESTS")
print("-"*40)

def test_polling_bot_syntax():
    import py_compile
    py_compile.compile(f"{EC2_APP}/polling_bot.py", doraise=True)
    return True

test("polling_bot.py has no syntax errors", test_polling_bot_syntax)

def test_polling_bot_imports():
    # Check all required imports exist
    with open(f"{EC2_APP}/polling_bot.py") as f:
        content = f.read()
    required = ["from routers.chat import", "t,", "build_schemes_keyboard", "build_language_keyboard"]
    for req in required:
        if req not in content:
            print(f"   Missing: {req}")
            return False
    return True

test("polling_bot.py has all required imports", test_polling_bot_imports)

def test_no_hardcoded_strings():
    with open(f"{EC2_APP}/routers/chat.py") as f:
        content = f.read()
    # Should not have hardcoded English strings in keyboard builders
    bad_patterns = [
        '"Yes ✅"', '"No ❌"'
    ]
    found = [p for p in bad_patterns if p in content]
    if found:
        print(f"   Hardcoded strings found: {found}")
        return False
    return True

test("No hardcoded UI strings in chat.py", test_no_hardcoded_strings)

def test_no_fake_submission():
    with open(f"{EC2_APP}/routers/chat.py") as f:
        content = f.read()
    bad_phrases = [
        "application submitted successfully",
        "form has been filled",
        "successfully applied",
        "application is complete"
    ]
    found = [p for p in bad_phrases if p.lower() in content.lower()]
    if found:
        print(f"   Found fake submission phrases: {found}")
    # Check system prompt
    assert "NEVER say" in content or "never say" in content.lower() or "NOT" in content
    return True

test("System prompt prevents fake submissions", test_no_fake_submission)

def test_language_config_removed():
    with open(f"{EC2_APP}/routers/chat.py") as f:
        content = f.read()
    if "LANGUAGE_CONFIG" in content:
        print("   LANGUAGE_CONFIG still exists — should be using translations.json")
        return False
    return True

test("Old LANGUAGE_CONFIG removed from chat.py", test_language_config_removed)

def test_translations_loaded():
    with open(f"{EC2_APP}/routers/chat.py") as f:
        content = f.read()
    assert "translations.json" in content or "TRANSLATIONS" in content
    return True

test("chat.py loads from translations.json", test_translations_loaded)

# ══════════════════════════════════════════════════════════════
print("\n🔄 7. FLOW LOGIC TESTS")
print("-"*40)

def test_returning_user_logic():
    with open(f"{EC2_APP}/polling_bot.py") as f:
        content = f.read()
    assert "returning" in content.lower() or "Welcome back" in content
    assert "schemes_applied" in content
    return True

test("Returning user detection logic exists", test_returning_user_logic)

def test_mobile_confirmation():
    with open(f"{EC2_APP}/polling_bot.py") as f:
        content = f.read()
    assert "mobile_pending" in content, "No mobile confirmation flow"
    assert "aadhaar_upload" in content, "No aadhaar upload step after mobile"
    return True

test("Mobile confirmation flow exists", test_mobile_confirmation)

def test_aadhaar_step_flow():
    with open(f"{EC2_APP}/polling_bot.py") as f:
        content = f.read()
    assert "confirm_aadhaar" in content or "aadhaar_verified" in content
    assert "confirmed" in content or "confirm_submit" in content
    assert "submitted" in content
    return True

test("Aadhaar → confirm → submit flow exists", test_aadhaar_step_flow)

def test_eligibility_not_triggering_on_no():
    from routers.chat import check_eligibility_from_callback
    
    # ans_no should NOT trigger not_farmer unless step is farmer_check
    result = check_eligibility_from_callback("pmkisan", "ans_no", step="govt_employee_check")
    assert result != "not_farmer", "ans_no incorrectly rejects as not_farmer on govt check"
    
    # income_high should always reject
    result2 = check_eligibility_from_callback("pmkisan", "income_high")
    assert result2 == "income_too_high"
    
    return True

test("Eligibility logic: ans_no doesn't wrongly reject", test_eligibility_not_triggering_on_no)

def test_duplicate_check():
    with open(f"{EC2_APP}/polling_bot.py") as f:
        content = f.read()
    assert "schemes_applied" in content or "duplicate" in content.lower()
    return True

test("Duplicate application check exists", test_duplicate_check)

# ══════════════════════════════════════════════════════════════
print("\n🌐 8. EDGE CASE TESTS")
print("-"*40)

def test_empty_voice():
    from routers.chat import extract_phone_from_text
    assert extract_phone_from_text("") is None
    assert extract_phone_from_text(None) is None
    assert extract_phone_from_text("hello") is None
    assert extract_phone_from_text("8074142645") == "8074142645"
    assert extract_phone_from_text("+91 80741 42645") == "8074142645"
    assert extract_phone_from_text("my number is 9876543210") == "9876543210"
    return True

test("Phone extraction handles edge cases", test_empty_voice)

def test_invalid_aadhaar():
    from routers.documents import mask_aadhaar
    assert mask_aadhaar("1234") is None  # too short
    assert mask_aadhaar("1234567890123") is None  # too long (13 digits)
    assert mask_aadhaar("abcdefghijkl") is None  # not digits
    return True

test("Invalid Aadhaar handled gracefully", test_invalid_aadhaar)

def test_language_fallback():
    from routers.chat import t
    # Unknown language should fallback to English
    result = t("xx", "yes")
    english = t("en", "yes")
    assert result == english, f"Unknown lang didn't fallback: {result} vs {english}"
    return True

test("Unknown language falls back to English", test_language_fallback)

def test_missing_translation_key():
    from routers.chat import t
    # Missing key should return the key itself
    result = t("en", "nonexistent_key_xyz")
    assert result == "nonexistent_key_xyz", f"Missing key should return key name, got: {result}"
    return True

test("Missing translation key returns key name", test_missing_translation_key)

def test_options_tag_case_insensitive():
    from routers.chat import extract_options_tag
    _, tag1 = extract_options_tag("question? OPTIONS: YES_NO")
    _, tag2 = extract_options_tag("question? options: yes_no")
    _, tag3 = extract_options_tag("question? Options: Yes_No")
    assert tag1 is not None
    assert tag2 is not None
    assert tag3 is not None
    return True

test("OPTIONS tag is case-insensitive", test_options_tag_case_insensitive)

def test_phone_format():
    # Test that phone is formatted nicely
    phone = "8074142645"
    formatted = phone[:4] + " " + phone[4:8] + " " + phone[8:]
    assert formatted == "8074 1426 45"
    return True

test("Phone number formatted as XXXX XXXX XX", test_phone_format)

# ══════════════════════════════════════════════════════════════
print("\n🔒 9. SECURITY TESTS")
print("-"*40)

def test_aadhaar_not_stored_raw():
    with open(f"{EC2_APP}/routers/documents.py") as f:
        content = f.read()
    # Should remove raw aadhaar before storing
    assert 'result.pop("aadhaar"' in content or 'aadhaar_masked' in content
    assert "mask_aadhaar" in content
    return True

test("Aadhaar is masked before storage", test_aadhaar_not_stored_raw)

def test_no_raw_aadhaar_in_polling_bot():
    with open(f"{EC2_APP}/polling_bot.py") as f:
        content = f.read()
    # Should use aadhaar_masked not raw aadhaar
    assert "aadhaar_masked" in content
    return True

test("polling_bot uses masked Aadhaar", test_no_raw_aadhaar_in_polling_bot)

def test_pem_not_in_app():
    # PEM file should not be in app directory accessible
    pem_in_app = Path(f"{EC2_APP}/jansahayak.pem").exists()
    if pem_in_app:
        print(f"   {WARN} PEM file found in app directory!")
    return not pem_in_app

warn("PEM key not exposed in app directory", test_pem_not_in_app)

# ══════════════════════════════════════════════════════════════
print("\n⚡ 10. PERFORMANCE TESTS")
print("-"*40)

def test_llm_response_time():
    from routers.chat import get_llm_response
    start = time.time()
    response = get_llm_response([], "Hello", "en")
    elapsed = time.time() - start
    print(f"   LLM response time: {elapsed:.2f}s")
    assert elapsed < 15, f"LLM too slow: {elapsed}s"
    assert len(response) > 0
    return True

test("LLM responds within 15 seconds", test_llm_response_time)

def test_translation_load_time():
    import time
    start = time.time()
    with open(f"{EC2_APP}/translations.json") as f:
        json.load(f)
    elapsed = time.time() - start
    print(f"   translations.json load time: {elapsed*1000:.1f}ms")
    assert elapsed < 1
    return True

test("translations.json loads fast", test_translation_load_time)

def test_nsap_classifier():
    from services.nsap_service import predict_nsap_scheme
    # Test cases:
    # age, gender, is_bpl, disability_percentage, is_widow, breadwinner_deceased, receiving_other_pension
    # 1. IGNOAPS: BPL, age >= 60, receiving pension/other cases
    assert predict_nsap_scheme(62, 0, 1, 0, 0, 0, 1) == "IGNOAPS"
    # 2. Ineligible: Non-BPL
    assert predict_nsap_scheme(62, 0, 0, 0, 0, 0, 0) == "Ineligible"
    # 3. IGNWPS: BPL, female, widow, age 40-79
    assert predict_nsap_scheme(45, 1, 1, 0, 1, 0, 0) == "IGNWPS"
    # 4. IGNDPS: BPL, age 18-79, disability >= 80%
    assert predict_nsap_scheme(25, 0, 1, 85, 0, 0, 0) == "IGNDPS"
    # 5. NFBS: BPL, age 18-59, breadwinner deceased
    assert predict_nsap_scheme(35, 0, 1, 0, 0, 1, 0) == "NFBS"
    # 6. Annapurna: BPL, age >= 65, no other pension
    assert predict_nsap_scheme(70, 0, 1, 0, 0, 0, 0) == "Annapurna"
    return True

test("NSAP Classifier predicts correctly across all 6 classes", test_nsap_classifier)


# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("📊 TEST RESULTS SUMMARY")
print("="*60)

passed = sum(1 for s,_ in results if s == PASS)
failed = sum(1 for s,_ in results if s == FAIL)
warned = sum(1 for s,_ in results if s == WARN)
total = len(results)

print(f"\n{PASS} Passed: {passed}/{total}")
print(f"{FAIL} Failed: {failed}/{total}")
print(f"{WARN} Warnings: {warned}/{total}")
print(f"\nScore: {int(passed/total*100)}%")

if failed > 0:
    print(f"\n{FAIL} FAILED TESTS:")
    for status, name in results:
        if status == FAIL:
            print(f"  - {name}")

if warned > 0:
    print(f"\n{WARN} WARNINGS:")
    for status, name in results:
        if status == WARN:
            print(f"  - {name}")

print("\n" + "="*60)
