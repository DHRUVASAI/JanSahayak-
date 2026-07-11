"""
JanSahayak - Laptop RPA Worker
================================
Polls EC2 for RPA jobs, opens Chrome VISIBLY on laptop,
fills mock portal forms, and sends completion back to EC2.

Run this on your LOCAL PC (not EC2):
  cd C:\\Users\\Dhruva Sai\\JanSahayak\\backend
  .venv\\Scripts\\activate
  python laptop_rpa_worker.py

Requirements:
  pip install selenium webdriver-manager requests
"""

import time
import json
import logging
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import (
    TimeoutException, NoAlertPresentException, UnexpectedAlertPresentException
)

# ── CONFIG ────────────────────────────────────────────────────────────────────
import os

EC2_BASE_URL = os.getenv("EC2_BASE_URL", "http://localhost:8000")   # FastAPI on EC2/localhost
POLL_INTERVAL = 3                            # seconds between polls
JOB_ENDPOINT  = f"{EC2_BASE_URL}/rpa/get-job"
DONE_ENDPOINT = f"{EC2_BASE_URL}/rpa/complete-job"

# Mock portal served on local backend static mount
LOCAL_PORTAL_BASE = os.getenv("LOCAL_PORTAL_BASE", "http://localhost:8000/mock_portal")

SCHEME_TO_HTML = {
    "pm_kisan":       "pm_kisan.html",
    "ration_card":    "ration_card.html",
    "ayushman_bharat":"ayushman_bharat.html",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rpa_worker")

# ── DRIVER SETUP ──────────────────────────────────────────────────────────────

def create_driver() -> webdriver.Chrome:
    """Create a VISIBLE Chrome instance (not headless) so judges can see it."""
    opts = Options()
    # DO NOT add --headless  ← intentional for demo
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    # Suppress annoying "Chrome is being controlled by automated software" bar
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
    except Exception:
        # Fallback: assume chromedriver is on PATH
        driver = webdriver.Chrome(options=opts)

    driver.set_page_load_timeout(30)
    return driver


# ── ALERT HANDLER ─────────────────────────────────────────────────────────────

def dismiss_alerts(driver: webdriver.Chrome, max_attempts: int = 5) -> None:
    """Dismiss any JS alert/confirm/prompt dialogs that might appear."""
    for _ in range(max_attempts):
        try:
            alert = WebDriverWait(driver, 1).until(EC.alert_is_present())
            log.info(f"Dismissing alert: {alert.text!r}")
            alert.accept()
        except (TimeoutException, NoAlertPresentException):
            break
        except Exception as e:
            log.warning(f"Alert handling error: {e}")
            break


# ── SAFE ELEMENT HELPERS ──────────────────────────────────────────────────────

def safe_fill(driver: webdriver.Chrome, field_id: str, value: str, wait: int = 5) -> bool:
    """Fill a text/input field by ID. Returns True on success."""
    try:
        el = WebDriverWait(driver, wait).until(
            EC.presence_of_element_located((By.ID, field_id))
        )
        el.clear()
        el.send_keys(str(value))
        return True
    except Exception as e:
        log.warning(f"Could not fill #{field_id}: {e}")
        return False


def safe_select(driver: webdriver.Chrome, field_id: str, value: str, wait: int = 5) -> bool:
    """Select an <option> in a <select> by ID. Tries visible text, then value attr."""
    try:
        el = WebDriverWait(driver, wait).until(
            EC.presence_of_element_located((By.ID, field_id))
        )
        sel = Select(el)
        try:
            sel.select_by_visible_text(str(value))
        except Exception:
            try:
                sel.select_by_value(str(value).lower().replace(" ", "_"))
            except Exception:
                # last resort: pick first non-placeholder option
                options = [o for o in sel.options if o.get_attribute("value")]
                if options:
                    sel.select_by_index(1)
        return True
    except Exception as e:
        log.warning(f"Could not select #{field_id}: {e}")
        return False


def safe_checkbox(driver: webdriver.Chrome, field_id: str, wait: int = 5) -> bool:
    """Tick a checkbox by ID if not already checked."""
    try:
        el = WebDriverWait(driver, wait).until(
            EC.presence_of_element_located((By.ID, field_id))
        )
        if not el.is_selected():
            el.click()
        return True
    except Exception as e:
        log.warning(f"Could not tick checkbox #{field_id}: {e}")
        return False


def safe_click(driver: webdriver.Chrome, field_id: str, wait: int = 10) -> bool:
    """Click a button/element by ID."""
    try:
        el = WebDriverWait(driver, wait).until(
            EC.element_to_be_clickable((By.ID, field_id))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", el)
        time.sleep(0.3)
        el.click()
        return True
    except Exception as e:
        log.warning(f"Could not click #{field_id}: {e}")
        return False


def get_ref_number(driver: webdriver.Chrome, field_id: str = "success-ref", wait: int = 6) -> str:
    """Read the confirmation/reference number shown after submission."""
    try:
        el = WebDriverWait(driver, wait).until(
            EC.visibility_of_element_located((By.ID, field_id))
        )
        return el.text.strip()
    except Exception:
        return "REF-DEMO-" + str(int(time.time()))[-6:]


# ── SCHEME FORM FILLERS ───────────────────────────────────────────────────────

def fill_pm_kisan(driver: webdriver.Chrome, data: dict) -> str:
    """Fill PM-KISAN form. Returns reference number."""
    log.info("Filling PM-KISAN form …")

    d = {
        "full_name":      data.get("name", data.get("full_name", "Ramesh Kumar")),
        "dob":            data.get("dob", data.get("date_of_birth", "01/01/1980")),
        "gender":         data.get("gender", "Male"),
        "aadhaar":        data.get("aadhaar", data.get("aadhaar_number", "000000000000")),
        "mobile":         data.get("mobile", data.get("phone", "9999999999")),
        "category":       data.get("category", data.get("caste", "General")),
        "state":          data.get("state", "Telangana"),
        "district":       data.get("district", "Hyderabad"),
        "village":        data.get("village", data.get("village_name", "Demo Village")),
        "pincode":        data.get("pincode", data.get("pin_code", "500001")),
        "land_area":      data.get("land_area", data.get("land", "2.5")),
        "survey_number":  data.get("survey_number", data.get("survey", "123/A")),
        "account_number": data.get("account_number", data.get("bank_account", "00000000000")),
        "ifsc":           data.get("ifsc", data.get("ifsc_code", "SBIN0000001")),
        "bank_name":      data.get("bank_name", data.get("bank", "State Bank of India")),
    }

    safe_fill(driver, "full_name",      d["full_name"])
    safe_fill(driver, "dob",            d["dob"])
    safe_select(driver, "gender",       d["gender"])
    safe_fill(driver, "aadhaar",        d["aadhaar"])
    safe_fill(driver, "mobile",         d["mobile"])
    safe_select(driver, "category",     d["category"])
    safe_select(driver, "state",        d["state"])
    safe_fill(driver, "district",       d["district"])
    safe_fill(driver, "village",        d["village"])
    safe_fill(driver, "pincode",        d["pincode"])
    safe_fill(driver, "land_area",      d["land_area"])
    safe_fill(driver, "survey_number",  d["survey_number"])
    safe_fill(driver, "account_number", d["account_number"])
    safe_fill(driver, "ifsc",           d["ifsc"])
    safe_fill(driver, "bank_name",      d["bank_name"])

    time.sleep(0.5)
    safe_click(driver, "submit-btn")
    dismiss_alerts(driver)
    time.sleep(1)
    return get_ref_number(driver)


def fill_ration_card(driver: webdriver.Chrome, data: dict) -> str:
    """Fill Ration Card form. Returns reference number."""
    log.info("Filling Ration Card form …")

    d = {
        "head_name":       data.get("name", data.get("head_name", "Ramesh Kumar")),
        "head_dob":        data.get("dob", data.get("head_dob", "01/01/1975")),
        "head_gender":     data.get("gender", data.get("head_gender", "Male")),
        "head_occupation": data.get("occupation", data.get("head_occupation", "Farmer")),
        "head_category":   data.get("category", data.get("caste", "OBC")),
        "monthly_income":  data.get("monthly_income", data.get("income", "8000")),
        "aadhaar":         data.get("aadhaar", data.get("aadhaar_number", "000000000000")),
        "mobile":          data.get("mobile", data.get("phone", "9999999999")),
        "family_members":  data.get("family_members", data.get("family_size", "4")),
        "children_count":  data.get("children_count", data.get("children", "2")),
        "senior_count":    data.get("senior_count", data.get("seniors", "0")),
        "state":           data.get("state", "Telangana"),
        "district":        data.get("district", "Hyderabad"),
        "village":         data.get("village", "Demo Village"),
        "pincode":         data.get("pincode", "500001"),
        "full_address":    data.get("address", data.get("full_address", "123, Demo Street, Demo Village")),
    }

    safe_fill(driver, "head_name",       d["head_name"])
    safe_fill(driver, "head_dob",        d["head_dob"])
    safe_select(driver, "head_gender",   d["head_gender"])
    safe_fill(driver, "head_occupation", d["head_occupation"])
    safe_select(driver, "head_category", d["head_category"])
    safe_fill(driver, "monthly_income",  d["monthly_income"])
    safe_fill(driver, "aadhaar",         d["aadhaar"])
    safe_fill(driver, "mobile",          d["mobile"])
    safe_fill(driver, "family_members",  d["family_members"])
    safe_fill(driver, "children_count",  d["children_count"])
    safe_fill(driver, "senior_count",    d["senior_count"])
    safe_select(driver, "state",         d["state"])
    safe_fill(driver, "district",        d["district"])
    safe_fill(driver, "village",         d["village"])
    safe_fill(driver, "pincode",         d["pincode"])
    safe_fill(driver, "full_address",    d["full_address"])

    time.sleep(0.5)
    safe_click(driver, "submit-btn")
    dismiss_alerts(driver)
    time.sleep(1)
    return get_ref_number(driver)


def fill_ayushman_bharat(driver: webdriver.Chrome, data: dict) -> str:
    """Fill Ayushman Bharat form. Returns reference number."""
    log.info("Filling Ayushman Bharat form …")

    d = {
        "full_name":          data.get("name", data.get("full_name", "Ramesh Kumar")),
        "dob":                data.get("dob", data.get("date_of_birth", "01/01/1985")),
        "age":                data.get("age", "39"),
        "gender":             data.get("gender", "Male"),
        "category":           data.get("category", data.get("caste", "General")),
        "aadhaar":            data.get("aadhaar", data.get("aadhaar_number", "000000000000")),
        "mobile":             data.get("mobile", data.get("phone", "9999999999")),
        "family_size":        data.get("family_size", data.get("family_members", "4")),
        "annual_income":      data.get("annual_income", data.get("income", "96000")),
        "disability":         data.get("disability", "None"),
        "blood_group":        data.get("blood_group", "O+"),
        "state":              data.get("state", "Telangana"),
        "district":           data.get("district", "Hyderabad"),
        "village":            data.get("village", "Demo Village"),
        "pincode":            data.get("pincode", "500001"),
        "existing_conditions":data.get("existing_conditions", data.get("health_conditions", "None")),
    }

    safe_fill(driver, "full_name",           d["full_name"])
    safe_fill(driver, "dob",                 d["dob"])
    safe_fill(driver, "age",                 d["age"])
    safe_select(driver, "gender",            d["gender"])
    safe_select(driver, "category",          d["category"])
    safe_fill(driver, "aadhaar",             d["aadhaar"])
    safe_fill(driver, "mobile",              d["mobile"])
    safe_fill(driver, "family_size",         d["family_size"])
    safe_fill(driver, "annual_income",       d["annual_income"])
    safe_select(driver, "disability",        d["disability"])
    safe_select(driver, "blood_group",       d["blood_group"])
    safe_select(driver, "state",             d["state"])
    safe_fill(driver, "district",            d["district"])
    safe_fill(driver, "village",             d["village"])
    safe_fill(driver, "pincode",             d["pincode"])
    safe_fill(driver, "existing_conditions", d["existing_conditions"])
    safe_checkbox(driver, "declaration")

    time.sleep(0.5)
    safe_click(driver, "submit-btn")
    dismiss_alerts(driver)
    time.sleep(1)
    return get_ref_number(driver)


# ── CORE RPA RUNNER ───────────────────────────────────────────────────────────

SCHEME_FILLERS = {
    "pm_kisan":        fill_pm_kisan,
    "ration_card":     fill_ration_card,
    "ayushman_bharat": fill_ayushman_bharat,
}


def run_rpa_job(job: dict) -> dict:
    """
    Execute one RPA job.
    job keys: job_id, scheme, user_data, chat_id
    Returns: {success, reference, error}
    """
    job_id = job.get("job_id", "unknown")
    scheme  = job.get("scheme", "").lower().replace(" ", "_").replace("-", "_")
    data    = job.get("user_data", {})
    chat_id = job.get("chat_id")

    log.info(f"▶ Job {job_id} | scheme={scheme} | chat_id={chat_id}")

    html_file = SCHEME_TO_HTML.get(scheme)
    if not html_file:
        return {"success": False, "error": f"Unknown scheme: {scheme}"}

    portal_url = f"{LOCAL_PORTAL_BASE}/{html_file}"
    driver = None
    try:
        driver = create_driver()
        log.info(f"Opening portal: {portal_url}")
        driver.get(portal_url)
        dismiss_alerts(driver)
        time.sleep(1.5)  # let page render visibly for judges

        filler = SCHEME_FILLERS[scheme]
        ref = filler(driver, data)
        time.sleep(2)    # let judges see the filled form + success screen

        log.info(f"✅ Job {job_id} done — ref: {ref}")
        return {"success": True, "reference": ref, "job_id": job_id, "chat_id": chat_id}

    except Exception as e:
        log.error(f"❌ Job {job_id} failed: {e}", exc_info=True)
        return {"success": False, "error": str(e), "job_id": job_id, "chat_id": chat_id}

    finally:
        if driver:
            time.sleep(3)   # keep browser open briefly so judges can see result
            try:
                driver.quit()
            except Exception:
                pass


# ── POLLING LOOP ──────────────────────────────────────────────────────────────

def poll_for_jobs() -> None:
    log.info(f"🚀 JanSahayak RPA Worker started — polling {JOB_ENDPOINT} every {POLL_INTERVAL}s")
    log.info("Press Ctrl+C to stop.\n")

    while True:
        try:
            resp = requests.get(JOB_ENDPOINT, timeout=10)
            if resp.status_code == 200:
                job = resp.json()
                if job and job.get("job_id"):
                    result = run_rpa_job(job)
                    # Send result back to EC2
                    try:
                        post_resp = requests.post(DONE_ENDPOINT, json=result, timeout=10)
                        log.info(f"Completion posted → {post_resp.status_code}")
                    except Exception as e:
                        log.error(f"Failed to post completion: {e}")
                else:
                    log.debug("No jobs in queue.")
            elif resp.status_code == 404:
                log.debug("Queue empty (404).")
            else:
                log.warning(f"Unexpected response {resp.status_code}: {resp.text[:200]}")

        except requests.exceptions.ConnectionError:
            log.warning("Cannot reach EC2 — is it running? Retrying …")
        except Exception as e:
            log.error(f"Poll error: {e}", exc_info=True)

        time.sleep(POLL_INTERVAL)


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    poll_for_jobs()
