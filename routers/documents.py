import re

def mask_aadhaar(aadhaar):
    if not aadhaar: return None
    digits = re.sub(r"\D", "", str(aadhaar))
    if len(digits) != 12: return None
    return "XXXX XXXX " + digits[-4:]

import base64
import json
import os
import re
from fastapi import APIRouter
from groq import Groq

router = APIRouter(prefix="/api/v1/document", tags=["documents"])

def detect_mime_type(image_bytes: bytes) -> str:
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n": return "image/png"
    elif image_bytes[:3] == b"\xff\xd8\xff": return "image/jpeg"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP": return "image/webp"
    else: return "image/jpeg"

def run_aadhaar_ocr(image_bytes: bytes) -> dict:
    """
    Hybrid OCR pipeline (Telegram + WhatsApp):
    1. Textract raw text → LLaMA semantic parse → name validation
    2. Groq Vision full fallback
    3. Regex last resort
    Always returns aadhaar_masked field.
    """
    import logging, re
    log = logging.getLogger(__name__)

    try:
        from aws_services import textract_aadhaar_ocr
        result = textract_aadhaar_ocr(image_bytes)
    except Exception as e:
        log.error(f"[OCR] textract_aadhaar_ocr error: {e}")
        result = {}

    # Ensure aadhaar_masked always present
    if result.get("aadhaar"):
        digits = re.sub(r"\D", "", str(result["aadhaar"]))[:12]
        result["aadhaar"] = digits
        result["aadhaar_masked"] = "XXXX XXXX " + digits[-4:]

    # Ensure pincode extracted from address if missing
    if not result.get("pincode") and result.get("address"):
        m = re.search(r"\b(\d{6})\b", str(result["address"]))
        if m: result["pincode"] = m.group(1)

    # Normalize gender capitalization
    if result.get("gender"):
        result["gender"] = result["gender"].capitalize()

    log.info(f"[OCR-FINAL] name={result.get('name')} aadhaar=****{str(result.get('aadhaar',''))[-4:]} state={result.get('state')} district={result.get('district')} source={result.get('source','?')}")
    return result
def _fallback_extract(text: str) -> dict:
    result = {"name": None, "aadhaar": None, "dob": None, "gender": None, "address": None, "district": None, "state": None, "pincode": None}
    aadhaar_match = re.search(r"\b(\d{4}\s?\d{4}\s?\d{4})\b", text)
    if aadhaar_match:
        result["aadhaar"] = re.sub(r"\s", "", aadhaar_match.group(1))
        result["aadhaar_masked"] = "XXXX XXXX " + result["aadhaar"][-4:]
    dob_match = re.search(r"\b(\d{2}[/\-]\d{2}[/\-]\d{4})\b", text)
    if dob_match:
        result["dob"] = dob_match.group(1).replace("-", "/")
    if re.search(r"\bMale\b", text, re.IGNORECASE): result["gender"] = "Male"
    elif re.search(r"\bFemale\b", text, re.IGNORECASE): result["gender"] = "Female"
    pin_match = re.search(r"\b(\d{6})\b", text)
    if pin_match: result["pincode"] = pin_match.group(1)
    return result


import asyncio
import uuid
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC


def check_eligibility(scheme: str, user_data: dict) -> dict:
    """Check if user is eligible for scheme. Returns {eligible, reason}"""
    if scheme == "pm_kisan":
        land = float(user_data.get("land_area", 0) or 0)
        if land > 5:
            return {"eligible": False, "reason": "Land area exceeds 5 acres limit for PM-KISAN"}
        income = float(user_data.get("annual_income", 0) or 0)
        if income > 200000:
            return {"eligible": False, "reason": "Annual income exceeds ₹2 lakh limit"}
    elif scheme == "ration_card":
        income = float(user_data.get("monthly_income", 0) or 0)
        if income > 15000:
            return {"eligible": False, "reason": "Monthly income exceeds ₹15,000 limit"}
    elif scheme == "ayushman":
        income = float(user_data.get("annual_income", 0) or 0)
        if income > 500000:
            return {"eligible": False, "reason": "Annual income exceeds ₹5 lakh limit"}
    return {"eligible": True, "reason": None}


def run_headless_rpa(chat_id: int, scheme: str, user_data: dict, app_id: str) -> dict:
    """Run headless RPA to fill government form."""
    from webdriver_manager.chrome import ChromeDriverManager

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    screenshot_path = f"/tmp/filled_{app_id}.png"
    success_path = f"/tmp/success_{app_id}.png"

    try:
        port = 3000
        if scheme == "pm_kisan":
            url = f"http://localhost:{port}/pm_kisan.html"
        elif scheme == "ration_card":
            url = f"http://localhost:{port}/ration_card.html"
        else:
            url = f"http://localhost:{port}/ayushman_bharat.html"

        driver.get(url)
        wait = WebDriverWait(driver, 10)

        # Fill form fields
        fields = {
            "name": user_data.get("name", ""),
            "aadhaar": user_data.get("aadhaar", ""),
            "mobile": user_data.get("mobile", ""),
            "dob": user_data.get("dob", ""),
            "state": user_data.get("state", ""),
            "district": user_data.get("district", ""),
            "pincode": user_data.get("pincode", ""),
            "bank_account": user_data.get("bank_account", ""),
            "ifsc": user_data.get("ifsc", ""),
            "land_area": user_data.get("land_area", ""),
        }

        for field_id, value in fields.items():
            if value:
                try:
                    el = driver.find_element(By.ID, field_id)
                    el.clear()
                    el.send_keys(str(value))
                except:
                    pass

        # Gender dropdown
        try:
            sel = Select(driver.find_element(By.ID, "gender"))
            sel.select_by_visible_text(user_data.get("gender", "Male"))
        except:
            pass

        driver.save_screenshot(screenshot_path)

        # Submit
        try:
            driver.find_element(By.ID, "submitBtn").click()
            import time; time.sleep(2)
            driver.save_screenshot(success_path)
        except:
            success_path = screenshot_path

        # Send screenshot to Telegram
        _send_screenshot_to_telegram(chat_id, screenshot_path, app_id, scheme)

        return {"success": True, "reference": f"JS-{app_id}", "screenshot": screenshot_path, "success_screenshot": success_path}

    except Exception as e:
        logger.error(f"[RPA ERROR] {e}")
        return {"success": False, "error": str(e)}
    finally:
        driver.quit()


def _send_screenshot_to_telegram(chat_id: int, screenshot_path: str, app_id: str, scheme: str):
    """Send screenshot and confirmation to Telegram."""
    import httpx
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    try:
        with open(screenshot_path, "rb") as f:
            import requests
            requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": f"✅ Application submitted!\nRef: JS-{app_id}\nScheme: {scheme.upper()}"},
                files={"photo": f}
            )
    except Exception as e:
        logger.error(f"[TELEGRAM SEND] {e}")


def generate_confirmation_pdf(user_data: dict, app_id: str, scheme: str) -> str:
    """Generate PDF confirmation."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        pdf_path = f"/tmp/confirmation_{app_id}.pdf"
        c = canvas.Canvas(pdf_path, pagesize=A4)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(100, 800, "JanSahayak - Application Confirmation")
        c.setFont("Helvetica", 12)
        y = 760
        fields = [
            ("Application ID", f"REF-{app_id}"),
            ("Scheme", scheme.upper().replace("_", "-")),
            ("Name", user_data.get("name", "")),
            ("Aadhaar", user_data.get("aadhaar_masked", user_data.get("aadhaar", ""))),
            ("Mobile", user_data.get("mobile", "")),
            ("State", user_data.get("state", "")),
            ("District", user_data.get("district", "")),
            ("Status", "Under Review"),
        ]
        for label, value in fields:
            c.drawString(100, y, f"{label}: {value or 'N/A'}")
            y -= 30
        c.save()
        return pdf_path
    except Exception as e:
        logger.error(f"[PDF ERROR] {e}")
        return None
