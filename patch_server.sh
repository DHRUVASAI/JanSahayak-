#!/bin/bash
# JanSahayak Server Patch Script
# Run this on the EC2 server: bash patch_server.sh

set -e
cd ~/app

echo "=== Step 1: Stopping all uvicorn processes ==="
sudo systemctl stop jansahayak-whatsapp 2>/dev/null || true
pkill -9 -f uvicorn 2>/dev/null || true
sleep 2
echo "All processes stopped."

echo "=== Step 2: Patching main.py ==="
python3 << 'PYEOF'
import re

with open("main.py", "r") as f:
    content = f.read()

# 1. Add logging config after load_dotenv line
if "logging.basicConfig" not in content:
    old = 'load_dotenv(dotenv_path=Path(__file__).parent / ".env")'
    new = old + """

# -- Logging config -- capture logger.info() from all modules --
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)"""
    content = content.replace(old, new)
    print("  Added logging.basicConfig")
else:
    print("  logging.basicConfig already present")

# 2. Guard Firebase init in lifespan
if "if not firebase_admin._apps:" not in content:
    # Replace the lifespan function
    old_lifespan = '''async def lifespan(app: FastAPI):
    cred_path = os.getenv("FIREBASE_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        try:
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            print("Successfully connected to Firebase!")
        except Exception as e:
            print(f"Error initializing Firebase: {e}")
    else:
        print("Warning: Firebase credentials not found.")
    yield'''

    new_lifespan = '''async def lifespan(app: FastAPI):
    # Guard: whatsapp_webhook.py already initializes Firebase at import time
    if not firebase_admin._apps:
        cred_path = os.getenv("FIREBASE_CREDENTIALS")
        if cred_path and os.path.exists(cred_path):
            try:
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                print("Successfully connected to Firebase!")
            except Exception as e:
                print(f"Error initializing Firebase: {e}")
        else:
            print("Warning: Firebase credentials not found.")
    else:
        print("Firebase already initialized (by router import)")
    yield'''

    if old_lifespan in content:
        content = content.replace(old_lifespan, new_lifespan)
        print("  Added Firebase guard to lifespan")
    else:
        print("  WARNING: Could not find exact lifespan block to patch")
        print("  Trying alternate pattern...")
        # Try a simpler patch - just add guard before cred_path line
        old2 = '    cred_path = os.getenv("FIREBASE_CREDENTIALS")'
        new2 = '    if not firebase_admin._apps:\n      cred_path = os.getenv("FIREBASE_CREDENTIALS")'
        if old2 in content and 'firebase_admin._apps' not in content:
            content = content.replace(old2, new2)
            print("  Applied alternate Firebase guard")
else:
    print("  Firebase guard already present")

with open("main.py", "w") as f:
    f.write(content)
print("  main.py patched!")
PYEOF

echo "=== Step 3: Patching whatsapp_webhook.py ==="
python3 << 'PYEOF'
with open("routers/whatsapp_webhook.py", "r") as f:
    content = f.read()

changes = 0

# 1. Add Twilio credential check after TWILIO_FROM line
if "[WA-STARTUP]" not in content:
    old = 'TWILIO_FROM  = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")'
    new = old + '''

if not TWILIO_SID or not TWILIO_TOKEN:
    print("[WA-STARTUP] WARNING: TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN is empty! Media downloads will fail.")'''
    content = content.replace(old, new)
    changes += 1
    print("  Added Twilio credential check")

# 2. Add print diagnostic at webhook entry (after phone normalization)
if "[WA-HOOK]" not in content:
    old = '    logger.info("[WA] from=%s body=%r media=%s", phone, body, num_media)'
    new = '    print(f"[WA-HOOK] from={phone} body={body!r} num_media={num_media} media_type={media_type} media_url={media_url}")\n    logger.info("[WA] from=%s body=%r media=%s type=%s url=%s", phone, body, num_media, media_type, media_url)'
    if old in content:
        content = content.replace(old, new)
        changes += 1
        print("  Added [WA-HOOK] print diagnostic")
    else:
        print("  WARNING: Could not find logger.info WA line to patch")

# 3. Add try/except and print diagnostics around audio download
if "[AUDIO] Downloading" not in content:
    old = '''    if num_media > 0 and media_url and "audio" in media_type:
        async with httpx.AsyncClient() as client:
            r = await client.get(media_url,
                                 auth=(TWILIO_SID, TWILIO_TOKEN),
                                 timeout=30.0, follow_redirects=True)
            audio_bytes = r.content
        transcript = await transcribe_voice(audio_bytes, lang)'''
    new = '''    if num_media > 0 and media_url and "audio" in media_type:
        print(f"[AUDIO] Downloading voice from: {media_url}")
        print(f"[AUDIO] Using auth SID={TWILIO_SID[:8]}... TOKEN={'set' if TWILIO_TOKEN else 'EMPTY'}")
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(media_url,
                                     auth=(TWILIO_SID, TWILIO_TOKEN),
                                     timeout=30.0, follow_redirects=True)
                audio_bytes = r.content
            print(f"[AUDIO] Downloaded {len(audio_bytes)} bytes, status={r.status_code}, content-type={r.headers.get('content-type', '?')}")
            if len(audio_bytes) < 100:
                print(f"[AUDIO] WARNING: tiny/empty response body: {audio_bytes[:200]}")
        except Exception as dl_err:
            print(f"[AUDIO] Download FAILED: {dl_err}")
            return twiml(m("error", lang))
        transcript = await transcribe_voice(audio_bytes, lang)
        print(f"[STT] Transcript result: {transcript!r}")'''
    if old in content:
        content = content.replace(old, new)
        changes += 1
        print("  Added [AUDIO] diagnostics and try/except")
    else:
        print("  WARNING: Could not find exact audio block to patch")

with open("routers/whatsapp_webhook.py", "w") as f:
    f.write(content)
print(f"  whatsapp_webhook.py patched! ({changes} changes)")
PYEOF

echo "=== Step 4: Verifying patches ==="
echo "--- main.py logging check ---"
grep -n "logging.basicConfig" main.py || echo "WARNING: logging.basicConfig NOT found!"
echo "--- main.py Firebase guard check ---"
grep -n "firebase_admin._apps" main.py || echo "WARNING: Firebase guard NOT found!"
echo "--- webhook print diagnostics check ---"
grep -n "WA-HOOK\|AUDIO.*Downloading\|WA-STARTUP" routers/whatsapp_webhook.py | head -5

echo ""
echo "=== Step 5: Starting server ==="
pkill -9 -f uvicorn 2>/dev/null || true
sleep 1
cd ~/app
nohup /home/ubuntu/.local/bin/uvicorn main:app --host 0.0.0.0 --port 8000 >> ~/app/whatsapp.log 2>&1 &
sleep 3

echo "=== Step 6: Testing ==="
curl -s -X POST http://localhost:8000/whatsapp/webhook \
  -d "From=whatsapp:+918074142645&Body=hi&NumMedia=0" \
  -H "Content-Type: application/x-www-form-urlencoded"
echo ""
sleep 1
echo "=== Last 10 lines of whatsapp.log ==="
tail -10 ~/app/whatsapp.log
echo ""
echo "=== DONE! Look for [WA-HOOK] in the output above ==="
