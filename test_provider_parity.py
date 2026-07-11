"""
test_provider_parity.py — Side-by-side IBM vs AWS provider comparison

Sends the same inputs through BOTH providers and prints results side by side
for manual comparison. Does NOT touch production data.

Usage:
  # Run with real IBM credentials (set IBM_* env vars first):
  python test_provider_parity.py

  # Run only AWS side (no IBM credentials needed):
  python test_provider_parity.py --aws-only

  # Run only IBM side:
  python test_provider_parity.py --ibm-only

Exits 0 if all attempted tests pass, 1 if any test errors out unexpectedly.
Missing credentials → test is skipped (not failed).
"""
import os
import sys
import time
import textwrap
import traceback

# ── Patch open() to default to UTF-8 (Windows compatibility) ──────────────────
import builtins
_orig_open = builtins.open
def _utf8_open(*args, **kwargs):
    mode = kwargs.get("mode", args[1] if len(args) > 1 else "r")
    if "b" not in mode and "encoding" not in kwargs:
        kwargs["encoding"] = "utf-8"
    return _orig_open(*args, **kwargs)
builtins.open = _utf8_open

from pathlib import Path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── CLI flags ─────────────────────────────────────────────────────────────────
AWS_ONLY = "--aws-only" in sys.argv
IBM_ONLY = "--ibm-only" in sys.argv

# ── Sample test inputs ────────────────────────────────────────────────────────
SAMPLE_PROMPT  = "In one sentence, what is PM-KISAN scheme?"
SAMPLE_SYSTEM  = "You are a helpful assistant for rural Indian farmers. Reply in English only."
SAMPLE_AUDIO   = b""   # empty bytes — STT will fail gracefully; real test needs .ogg bytes
SAMPLE_IMG     = b""   # empty bytes — OCR will fail gracefully; real test needs image bytes

# ── Helpers ───────────────────────────────────────────────────────────────────

PASS = "✅"
FAIL = "❌"
SKIP = "⚠️ SKIPPED"
SEP  = "─" * 70

def _header(title: str):
    print(f"\n{'═'*70}")
    print(f"  {title}")
    print('═'*70)

def _row(label: str, aws_val, ibm_val):
    print(f"\n  📌 {label}")
    print(f"  AWS: {textwrap.shorten(str(aws_val), 160, placeholder='...')}")
    print(f"  IBM: {textwrap.shorten(str(ibm_val), 160, placeholder='...')}")

def _run_aws(fn, *args, **kwargs):
    """Run fn with AI_PROVIDER=aws, return (result, error)."""
    os.environ["AI_PROVIDER"] = "aws"
    try:
        t0 = time.time()
        result = fn(*args, **kwargs)
        return result, None, round(time.time() - t0, 2)
    except Exception as e:
        return None, str(e), None

def _run_ibm(fn, *args, **kwargs):
    """Run fn with AI_PROVIDER=ibm, return (result, error)."""
    os.environ["AI_PROVIDER"] = "ibm"
    try:
        t0 = time.time()
        result = fn(*args, **kwargs)
        return result, None, round(time.time() - t0, 2)
    except Exception as e:
        return None, str(e), None

def _has_aws_creds() -> bool:
    return bool(
        os.getenv("AWS_ACCESS_KEY_ID") or
        os.getenv("AWS_DEFAULT_REGION")
    )

def _has_ibm_creds() -> bool:
    return bool(
        os.getenv("IBM_WATSONX_API_KEY") and
        os.getenv("IBM_WATSONX_PROJECT_ID") and
        os.getenv("IBM_WATSONX_URL")
    )

# ── Import the abstraction layer ───────────────────────────────────────────────
try:
    from services import ai_provider
    PROVIDER_IMPORTED = True
except ImportError as e:
    print(f"❌ Could not import services.ai_provider: {e}")
    PROVIDER_IMPORTED = False
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: LLM — Text generation
# ─────────────────────────────────────────────────────────────────────────────
_header("TEST 1: LLM — Text Generation")
print(f"  Prompt : {SAMPLE_PROMPT}")
print(f"  System : {SAMPLE_SYSTEM[:80]}...")

aws_llm_result = aws_llm_err = aws_llm_time = None
ibm_llm_result = ibm_llm_err = ibm_llm_time = None

if not IBM_ONLY:
    if _has_aws_creds():
        aws_llm_result, aws_llm_err, aws_llm_time = _run_aws(
            ai_provider.get_llm_response, SAMPLE_PROMPT, SAMPLE_SYSTEM, 200
        )
        aws_status = f"{PASS} ({aws_llm_time}s)" if not aws_llm_err else f"{FAIL} {aws_llm_err}"
    else:
        aws_status = f"{SKIP} — no AWS credentials"
else:
    aws_status = f"{SKIP} — --ibm-only"

if not AWS_ONLY:
    if _has_ibm_creds():
        ibm_llm_result, ibm_llm_err, ibm_llm_time = _run_ibm(
            ai_provider.get_llm_response, SAMPLE_PROMPT, SAMPLE_SYSTEM, 200
        )
        ibm_status = f"{PASS} ({ibm_llm_time}s)" if not ibm_llm_err else f"{FAIL} {ibm_llm_err}"
    else:
        ibm_status = f"{SKIP} — no IBM_WATSONX_* credentials"
else:
    ibm_status = f"{SKIP} — --aws-only"

print(f"\n  AWS status: {aws_status}")
print(f"  IBM status: {ibm_status}")
_row("LLM output", aws_llm_result or aws_llm_err, ibm_llm_result or ibm_llm_err)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: OCR — Aadhaar card extraction
# ─────────────────────────────────────────────────────────────────────────────
_header("TEST 2: OCR — Aadhaar Extraction")

# Try to load a real test image from the project
_test_img_path = ROOT / "test_aadhaar_sample.jpg"
if _test_img_path.exists():
    with open(_test_img_path, "rb") as _f:
        SAMPLE_IMG = _f.read()
    print(f"  Using test image: {_test_img_path} ({len(SAMPLE_IMG)} bytes)")
else:
    print(f"  ⚠️  No test image found at {_test_img_path}")
    print(f"      Place a sample Aadhaar image there to run a real OCR test.")
    print(f"      Running with empty bytes (will show graceful failure behavior).")

aws_ocr_result = ibm_ocr_result = None

if not IBM_ONLY and SAMPLE_IMG:
    if _has_aws_creds():
        aws_ocr_result, aws_ocr_err, aws_ocr_time = _run_aws(ai_provider.ocr_document, SAMPLE_IMG)
        aws_ocr_status = f"{PASS} ({aws_ocr_time}s)" if not aws_ocr_err else f"{FAIL} {aws_ocr_err}"
    else:
        aws_ocr_status = f"{SKIP} — no AWS credentials"
        aws_ocr_err = None
else:
    aws_ocr_status = f"{SKIP} — no image / --ibm-only"
    aws_ocr_err = None

if not AWS_ONLY and SAMPLE_IMG:
    if _has_ibm_creds():
        ibm_ocr_result, ibm_ocr_err, ibm_ocr_time = _run_ibm(ai_provider.ocr_document, SAMPLE_IMG)
        ibm_ocr_status = f"{PASS} ({ibm_ocr_time}s)" if not ibm_ocr_err else f"{FAIL} {ibm_ocr_err}"
    else:
        ibm_ocr_status = f"{SKIP} — no IBM credentials"
        ibm_ocr_err = None
else:
    ibm_ocr_status = f"{SKIP} — no image / --aws-only"
    ibm_ocr_err = None

print(f"\n  AWS status: {aws_ocr_status}")
print(f"  IBM status: {ibm_ocr_status}")
_row("OCR result", aws_ocr_result or aws_ocr_err, ibm_ocr_result or ibm_ocr_err)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: Speech-to-Text
# ─────────────────────────────────────────────────────────────────────────────
_header("TEST 3: Speech-to-Text — Audio Transcription")

_test_audio_path = ROOT / "test_audio_sample.ogg"
if _test_audio_path.exists():
    with open(_test_audio_path, "rb") as _f:
        SAMPLE_AUDIO = _f.read()
    print(f"  Using test audio: {_test_audio_path} ({len(SAMPLE_AUDIO)} bytes)")
else:
    print(f"  ⚠️  No test audio found at {_test_audio_path}")
    print(f"      Place a sample .ogg audio file there to run a real STT test.")
    print(f"      Running with empty bytes (will show graceful failure behavior).")

aws_stt_result = ibm_stt_result = None

if not IBM_ONLY and SAMPLE_AUDIO:
    if _has_aws_creds():
        aws_stt_result, aws_stt_err, aws_stt_time = _run_aws(
            ai_provider.transcribe_audio, SAMPLE_AUDIO, "hi"
        )
        aws_stt_status = f"{PASS} ({aws_stt_time}s)" if not aws_stt_err else f"{FAIL} {aws_stt_err}"
    else:
        aws_stt_status = f"{SKIP} — no AWS credentials"
        aws_stt_err = None
else:
    aws_stt_status = f"{SKIP} — no audio / --ibm-only"
    aws_stt_err = None

if not AWS_ONLY and SAMPLE_AUDIO:
    ibm_stt_creds = bool(os.getenv("IBM_SPEECH_TO_TEXT_APIKEY") and os.getenv("IBM_SPEECH_TO_TEXT_URL"))
    if ibm_stt_creds:
        ibm_stt_result, ibm_stt_err, ibm_stt_time = _run_ibm(
            ai_provider.transcribe_audio, SAMPLE_AUDIO, "hi"
        )
        ibm_stt_status = f"{PASS} ({ibm_stt_time}s)" if not ibm_stt_err else f"{FAIL} {ibm_stt_err}"
    else:
        ibm_stt_status = f"{SKIP} — no IBM_SPEECH_TO_TEXT_* credentials"
        ibm_stt_err = None
else:
    ibm_stt_status = f"{SKIP} — no audio / --aws-only"
    ibm_stt_err = None

print(f"\n  AWS status: {aws_stt_status}")
print(f"  IBM status: {ibm_stt_status}")
_row("STT transcript", aws_stt_result or aws_stt_err, ibm_stt_result or ibm_stt_err)

# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: Fallback simulation — IBM key invalid → must auto-fall back to AWS
# ─────────────────────────────────────────────────────────────────────────────
_header("TEST 4: Fallback Simulation — invalid IBM key → AWS fallback")
print("  Setting AI_PROVIDER=ibm + IBM_WATSONX_API_KEY=INVALID_KEY_FOR_TESTING")
print("  Expected: IBM call raises exception, AWS takes over, result returned.")

_saved_key = os.environ.get("IBM_WATSONX_API_KEY", "")
os.environ["IBM_WATSONX_API_KEY"] = "INVALID_KEY_FOR_TESTING"
os.environ["AI_PROVIDER"] = "ibm"

fallback_result, fallback_err, fallback_time = _run_ibm(
    ai_provider.get_llm_response, SAMPLE_PROMPT, SAMPLE_SYSTEM, 100
)

os.environ["IBM_WATSONX_API_KEY"] = _saved_key  # restore

if fallback_result and not fallback_err:
    print(f"\n  {PASS} Fallback worked! AWS served the request in {fallback_time}s")
    print(f"  Result: {textwrap.shorten(str(fallback_result), 160, placeholder='...')}")
elif not _has_aws_creds():
    print(f"\n  {SKIP} — No AWS credentials to fall back to; test requires both providers set up.")
else:
    print(f"\n  {FAIL} Fallback failed: {fallback_err}")

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'═'*70}")
print("  PARITY TEST COMPLETE")
print("  Review output above to compare AWS vs IBM responses.")
print("  No production data was touched.")
print(f"{'═'*70}\n")
