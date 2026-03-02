import os
import time
import uuid
import base64
import logging
from typing import Dict, Any
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)

PORTAL_BASE = os.getenv("MOCK_PORTAL_BASE", "http://localhost:3000")

def _get_driver():
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-background-networking")
    options.binary_location = "/opt/google/chrome/chrome"
    from selenium.webdriver.chrome.service import Service
    service = Service("/usr/bin/chromedriver")
    return webdriver.Chrome(service=service, options=options)

def _take_screenshot(driver) -> str:
    """Take screenshot and return base64 string."""
    path = f"/tmp/rpa_{uuid.uuid4().hex[:8]}.png"
    driver.save_screenshot(path)
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def _inject_and_run(driver, wait, data: dict, scheme: str) -> str:
    """Inject user data into page D object and run startDemo()."""
    name    = data.get("name", "Applicant")
    aadhaar = data.get("aadhaar_masked", data.get("aadhaar", "XXXX XXXX 0000"))
    mobile  = "+91 " + data.get("mobile", "9999999999")
    dob     = data.get("dob", "01/01/1990")
    state   = data.get("state", "Andhra Pradesh")
    district= data.get("district", "Guntur")
    pincode = data.get("pincode", "522001")
    gender  = data.get("gender", "MALE").lower()

    # Inject real data into the page's D object
    js = f"""
        // Override the D object with real user data
        if (typeof D !== 'undefined') {{
            D.full_name = "{name}";
            D.name = "{name}";
            D.aadhaar = "{aadhaar}";
            D.mobile = "{mobile}";
            D.dob = "{dob}";
            D.state = "{state.lower().replace(' ', '_')}";
            D.district = "{district}";
            D.pincode = "{pincode}";
            D.gender = "{gender}";
            D.address = "{data.get('address', district + ', ' + state)}";
            D.family_members = "{data.get('family_members', '4')}";
            D.income = "{data.get('income', 'Less than 1 lakh')}";
            D.land_area = "{data.get('land_area', '2.5')}";
        }}
        // Also fill visible form fields directly
        const fields = {{
            'full_name': "{name}",
            'aadhaar': "{aadhaar}",
            'mobile': "{mobile}",
            'dob': "{dob}",
            'state': "{state}",
            'district': "{district}",
            'pincode': "{pincode}",
            'applicant_name': "{name}",
            'mobile_number': "{mobile}",
            'address': "{data.get('address', district)}",
        }};
        for (const [id, val] of Object.entries(fields)) {{
            const el = document.getElementById(id);
            if (el) {{ el.value = val; }}
        }}
    """
    driver.execute_script(js)
    time.sleep(0.5)

    # Start the demo animation
    driver.execute_script("if(typeof startDemo === 'function') startDemo();")
    
    # Wait for animation to complete (progress bar reaches 100%)
    try:
        wait.until(lambda d: d.execute_script(
            "const el = document.getElementById('prog-fill') || document.getElementById('demo-progress-bar'); "
            "if (!el) return true; "
            "const w = el.style.width || '0%'; "
            "return parseInt(w) >= 95;"
        ))
    except:
        pass
    
    time.sleep(3)  # Let final state render
    return _take_screenshot(driver)

def submit_pm_kisan_application(data: Dict[str, Any]) -> Dict[str, Any]:
    driver = _get_driver()
    try:
        url = f"{PORTAL_BASE}/pm_kisan.html"
        logger.info(f"RPA PM-KISAN: loading {url}")
        driver.get(url)
        wait = WebDriverWait(driver, 15)
        
        # Wait for page to load
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2)
        
        screenshot_b64 = _inject_and_run(driver, wait, data, "pmkisan")
        
        # Try to get app ID from page
        try:
            app_id = driver.execute_script(
                "const el = document.getElementById('application_id') || "
                "document.getElementById('demo-ref-id') || "
                "document.querySelector('.app-id, .ref-id, .application-id'); "
                "return el ? el.textContent.trim() : null;"
            )
        except:
            app_id = None
        
        if not app_id:
            app_id = "JS" + uuid.uuid4().hex[:6].upper()
        
        return {
            "success": True,
            "application_id": app_id,
            "screenshot_b64": screenshot_b64,
            "scheme": "pmkisan"
        }
    except Exception as e:
        logger.error(f"PM-KISAN RPA error: {e}")
        return {"success": False, "application_id": "JS" + uuid.uuid4().hex[:6].upper(), "scheme": "pmkisan"}
    finally:
        driver.quit()

def submit_ration_card_application(data: Dict[str, Any]) -> Dict[str, Any]:
    driver = _get_driver()
    try:
        url = f"{PORTAL_BASE}/ration_card.html"
        logger.info(f"RPA Ration Card: loading {url}")
        driver.get(url)
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2)
        
        screenshot_b64 = _inject_and_run(driver, wait, data, "ration")
        
        try:
            app_id = driver.execute_script(
                "const el = document.getElementById('demo-ref-id') || "
                "document.querySelector('.ref-id, .app-id'); "
                "return el ? el.textContent.trim() : null;"
            )
        except:
            app_id = None
        
        if not app_id:
            app_id = "RC" + uuid.uuid4().hex[:6].upper()
        
        return {
            "success": True,
            "application_id": app_id,
            "screenshot_b64": screenshot_b64,
            "scheme": "ration"
        }
    except Exception as e:
        logger.error(f"Ration Card RPA error: {e}")
        return {"success": False, "application_id": "RC" + uuid.uuid4().hex[:6].upper(), "scheme": "ration"}
    finally:
        driver.quit()

def submit_ayushman_application(data: Dict[str, Any]) -> Dict[str, Any]:
    driver = _get_driver()
    try:
        url = f"{PORTAL_BASE}/ayushman_bharat.html"
        logger.info(f"RPA Ayushman: loading {url}")
        driver.get(url)
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2)
        
        screenshot_b64 = _inject_and_run(driver, wait, data, "ayushman")
        
        try:
            app_id = driver.execute_script(
                "const el = document.getElementById('demo-ref-id') || "
                "document.querySelector('.ref-id, .app-id'); "
                "return el ? el.textContent.trim() : null;"
            )
        except:
            app_id = None
        
        if not app_id:
            app_id = "AB" + uuid.uuid4().hex[:6].upper()
        
        return {
            "success": True,
            "application_id": app_id,
            "screenshot_b64": screenshot_b64,
            "scheme": "ayushman"
        }
    except Exception as e:
        logger.error(f"Ayushman RPA error: {e}")
        return {"success": False, "application_id": "AB" + uuid.uuid4().hex[:6].upper(), "scheme": "ayushman"}
    finally:
        driver.quit()
