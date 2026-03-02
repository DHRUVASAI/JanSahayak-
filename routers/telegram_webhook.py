"""
routers/telegram_webhook.py
Telegram Bot webhook — handles text, voice notes, and images (Aadhaar OCR)
Uses Groq for LLM + Whisper STT. Triggers RPA when form data is complete.
"""
import os
import asyncio
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from routers.chat import get_llm_response, detect_language, extract_options_tag
from routers.memory import get_history, save_message
from models.message import ChatMessage

router = APIRouter(prefix="/telegram", tags=["telegram"])

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_API    = f"https://api.telegram.org/bot{BOT_TOKEN}"
TG_FILE   = f"https://api.telegram.org/file/bot{BOT_TOKEN}"


# ── Telegram API helpers ─────────────────────────────────────────────────────

async def send_message(chat_id: int, text: str):
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        })


async def get_file_url(file_id: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{TG_API}/getFile", params={"file_id": file_id})
        data = r.json()
        return f"{TG_FILE}/{data['result']['file_path']}"


async def download_file(file_id: str) -> bytes:
    url = await get_file_url(file_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url)
        return r.content


# ── Voice → Text via Groq Whisper ───────────────────────────────────────────

async def transcribe_voice(audio_bytes: bytes) -> str:
    import tempfile
    from groq import Groq

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        with open(tmp_path, "rb") as af:
            transcription = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=("voice.ogg", af, "audio/ogg"),
                response_format="text",
            )
        return transcription if isinstance(transcription, str) else transcription.text
    except Exception as e:
        print(f"[WHISPER ERROR] {e}")
        return ""
    finally:
        os.unlink(tmp_path)


# ── Extract user data from conversation history ──────────────────────────────

def extract_user_data(history: list) -> dict:
    data = {
        "name": "", "aadhaar": "", "mobile": "",
        "dob": "", "bank_account": "", "ifsc": "",
        "land_area": "", "state": "", "district": "",
        "family_members": "", "monthly_income": "",
        "annual_income": "", "village": "", "pincode": "",
    }

    STATES = [
        "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa",
        "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
        "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
        "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
        "Uttar Pradesh", "Uttarakhand", "West Bengal",
        "Delhi", "Jammu and Kashmir", "Ladakh", "Puducherry",
    ]
    state_lc = {s.lower(): s for s in STATES}

    SCHEME_KEYWORDS = ["ration", "pm kisan", "kisan", "ayushman", "eligible", "chahiye", "apply"]

    def _is_name_candidate(s: str) -> bool:
        s = (s or "").strip()
        if not s:
            return False
        if any(kw in s.lower() for kw in SCHEME_KEYWORDS):
            return False
        words = [w for w in s.split() if w]
        if not (2 <= len(words) <= 4):
            return False
        for ch in s:
            if ch.isalpha() or ch in (" ", "-", ".", "'"):
                continue
            return False
        return True

    def _extract_district(s: str) -> str:
        s_l = (s or "").lower()
        m = re.search(r"\bdistrict\b\s*[:\-]?\s*([a-zA-Z\s]{2,40})", s_l)
        if m:
            return m.group(1).strip().title()
        m = re.search(r"\bdist\b\.?\s*[:\-]?\s*([a-zA-Z\s]{2,40})", s_l)
        if m:
            return m.group(1).strip().title()
        return ""

    last_assistant = ""
    for m in history or []:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if not content:
            continue

        if role == "assistant":
            last_assistant = content.lower()
            continue

        if role != "user":
            continue

        msg = content
        msg_lower = msg.lower().strip()

        if (not data["name"]) and last_assistant and ("naam kya hai" in last_assistant or "poora naam kya hai" in last_assistant or "your name" in last_assistant):
            if _is_name_candidate(msg):
                data["name"] = msg.strip().title()

        if not data["state"]:
            for st_l, st in state_lc.items():
                if st_l in msg_lower:
                    data["state"] = st
                    break
        if (not data["state"]) and last_assistant and ("kis state" in last_assistant or "which state" in last_assistant):
            candidate = msg.strip().title()
            if 2 <= len(candidate) <= 40:
                data["state"] = candidate

        if not data["district"]:
            dist = _extract_district(msg)
            if dist:
                data["district"] = dist

        aadhaar_match = re.search(r"\b\d{4}\s?\d{4}\s?\d{4}\b", msg)
        if aadhaar_match and not data["aadhaar"]:
            data["aadhaar"] = aadhaar_match.group().replace(" ", "")

        ifsc_match = re.search(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", msg.upper())
        if ifsc_match and not data["ifsc"]:
            data["ifsc"] = ifsc_match.group()

        mobile_match = re.search(r"\b[6-9]\d{9}\b", msg)
        if mobile_match and not data["mobile"]:
            data["mobile"] = mobile_match.group()

        bank_match = re.search(r"\b\d{9,18}\b", msg)
        if bank_match and not data["bank_account"]:
            data["bank_account"] = bank_match.group()

        land_match = re.search(r"\b(\d+\.?\d*)\s*(acre|acres|एकड़)?\b", msg_lower)
        if land_match and not data["land_area"]:
            val = float(land_match.group(1))
            if 0 < val < 1000:
                data["land_area"] = str(val)

        dob_match = re.search(r"\b(\d{2})[/-](\d{2})[/-](\d{4})\b", msg)
        if dob_match and not data["dob"]:
            data["dob"] = dob_match.group()

        pincode_match = re.search(r"\b[1-9]\d{5}\b", msg)
        if pincode_match and not data["pincode"]:
            data["pincode"] = pincode_match.group()

        family_match = re.search(r"\b([1-9]|1[0-5])\b", msg_lower)
        if family_match and not data["family_members"] and last_assistant and ("family" in last_assistant or "members" in last_assistant or "सदस्य" in last_assistant):
            data["family_members"] = family_match.group(1)

        is_mobile = re.search(r"\b[6-9]\d{9}\b", msg.replace(" ", ""))
        is_bank_account = re.search(r"\b\d{9,18}\b", msg.replace(" ", ""))

        income_match = re.search(r"\b(\d{3,6})\b", msg_lower)
        if income_match and not (is_mobile or is_bank_account) and not data["monthly_income"] and last_assistant and ("income" in last_assistant or "आय" in last_assistant or "salary" in last_assistant):
            income_val = int(income_match.group(1))
            if 500 <= income_val <= 100000:
                data["monthly_income"] = str(income_val)
                data["annual_income"] = str(income_val * 12)

        if not data["name"] and re.match(r"^[A-Za-z\s]{5,50}$", msg.strip()):
            words = msg.strip().split()
            if 2 <= len(words) <= 4 and not any(kw in msg.lower() for kw in SCHEME_KEYWORDS):
                data["name"] = msg.strip().title()

    print(f"[EXTRACT] user_data={data}")
    return data


# ── Main webhook ─────────────────────────────────────────────────────────────

@router.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
        print(f"[TELEGRAM] Update: {update}")
    except Exception as e:
        print(f"[TELEGRAM] Invalid JSON: {e}")
        return JSONResponse({"ok": True})

    message = update.get("message") or update.get("edited_message")
    if not message:
        return JSONResponse({"ok": True})

    chat_id = message["chat"]["id"]
    user_id = f"telegram:{chat_id}"

    # ── IMAGE: Aadhaar OCR ───────────────────────────────────────────────────
    if "photo" in message:
        await send_message(chat_id, "📸 Scanning your Aadhaar card... please wait.")
        try:
            file_id     = message["photo"][-1]["file_id"]
            image_bytes = await download_file(file_id)

            from routers.documents import run_aadhaar_ocr
            result = run_aadhaar_ocr(image_bytes)

            name    = result.get("name")    or "Not found"
            aadhaar = result.get("aadhaar") or "Not found"
            dob     = result.get("dob")     or "Not found"
            gender  = result.get("gender")  or "Not found"
            masked  = ("XXXX XXXX " + aadhaar[-4:] if isinstance(aadhaar, str) and len(aadhaar) >= 4 else aadhaar)

            reply = (
                f"✅ <b>Aadhaar Scan Complete!</b>\n\n"
                f"👤 Name: {name}\n"
                f"🔢 Aadhaar: {masked}\n"
                f"📅 DOB: {dob}\n"
                f"⚧ Gender: {gender}\n\n"
                f"Reply <b>YES</b> to confirm or <b>NO</b> to resend."
            )
            await save_message(user_id, "user", f"My details from Aadhaar: name={name}, aadhaar={aadhaar}, dob={dob}, gender={gender}")
            await save_message(user_id, "assistant", reply)

        except Exception as e:
            print(f"[OCR ERROR] {e}")
            reply = "❌ Could not read Aadhaar. Please send a clearer photo in good lighting."

        await send_message(chat_id, reply)
        return JSONResponse({"ok": True})

    # ── VOICE: Groq Whisper ──────────────────────────────────────────────────
    if "voice" in message:
        await send_message(chat_id, "🎤 Processing voice message...")
        msg_channel = "telegram_voice"
        msg_language = "hi"
        try:
            audio_bytes = await download_file(message["voice"]["file_id"])
            text = await transcribe_voice(audio_bytes)
            if not text:
                await send_message(chat_id, "Sorry, couldn't understand. Please type your message.")
                return JSONResponse({"ok": True})
            print(f"[WHISPER] Transcribed: {text}")
            await send_message(chat_id, f"🎤 I heard: <i>{text}</i>")
        except Exception as e:
            print(f"[VOICE ERROR] {e}")
            await send_message(chat_id, "Voice processing failed. Please type your message.")
            return JSONResponse({"ok": True})

    elif "text" in message:
        text = message["text"]
        msg_channel = "telegram"
        msg_language = "auto"
    else:
        return JSONResponse({"ok": True})

    # ── LLM ──────────────────────────────────────────────────────────────────
    try:
        history = await get_history(user_id, limit=20)
        chat_msg = ChatMessage(
            userId=user_id,
            text=text,
            channel=msg_channel,
            language=msg_language,
            history=history,
        )
        result = await process_text_message(chat_msg)
        reply  = result.get("reply", "Namaste! Kuch gadbad ho gayi. 🙏")

        await save_message(user_id, "user", text)
        await save_message(user_id, "assistant", reply)

        # ── Trigger RPA when form is complete ─────────────────────────────────
        rpa_triggers = ["submit kar raha hoon", "submitting", "form submit", "jama kar raha"]
        if any(t in reply.lower() for t in rpa_triggers):
            print("[RPA] TRIGGER MATCHED!")
            user_data = extract_user_data(history)

            history_text = " ".join([m.get("content", "") for m in history]).lower()
            if "ration" in history_text:
                scheme = "ration_card"
            elif "ayushman" in history_text:
                scheme = "ayushman_bharat"
            else:
                scheme = "pm_kisan"

            user_data["scheme"] = scheme
            print(f"[RPA] scheme={scheme} data={user_data}")

            from routers.rpa_queue import add_rpa_job
            add_rpa_job(scheme, user_data, chat_id)
            await send_message(chat_id, "⚙️ RPA Agent is filling your form... please wait!")

    except Exception as e:
        print(f"[CHAT ERROR] {type(e).__name__}: {e}")
        reply = "Namaste! Kuch gadbad ho gayi. Thoda baad try karein. 🙏"

    await send_message(chat_id, reply)
    return JSONResponse({"ok": True})


# ── Register & info ──────────────────────────────────────────────────────────

@router.get("/set-webhook")
async def set_webhook(request: Request):
    base_url = request.query_params.get("url", "")
    if not base_url:
        return {"error": "Pass ?url=https://your-ngrok-url"}
    webhook_url = f"{base_url}/telegram/webhook"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{TG_API}/setWebhook", json={"url": webhook_url})
    return {"status": "ok", "telegram_response": r.json(), "webhook_set_to": webhook_url}


@router.get("/info")
async def bot_info():
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{TG_API}/getMe")
    return r.json()
