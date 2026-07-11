import os, uuid, subprocess, tempfile, base64, logging, io
from typing import Dict, Any
from PIL import Image

from pathlib import Path
PORTAL_BASE = os.getenv("MOCK_PORTAL_BASE", str((Path(__file__).parent / "mock_portal").resolve()))

SCHEME_FILES = {
    "pmkisan": "pm_kisan.html",
    "ration": "ration_card.html",
    "ayushman": "ayushman_bharat.html",
}

SCHEME_DISPLAY = {
    "pmkisan": "PM-KISAN",
    "ration": "Ration Card",
    "ayushman": "Ayushman Bharat",
}

def _generate_screenshot(html_file, user_data, app_id):
    with open(html_file, 'r') as f:
        html = f.read()

    name    = user_data.get("name", "Applicant")
    aadhaar = user_data.get("aadhaar_masked", "XXXX XXXX ****")
    mobile  = user_data.get("mobile", "")
    dob     = user_data.get("dob", "")
    state   = user_data.get("state", "")
    district= user_data.get("district", "")
    pincode = user_data.get("pincode", "")
    gender  = user_data.get("gender", "")
    scheme  = user_data.get("scheme", "pmkisan")
    scheme_name = SCHEME_DISPLAY.get(scheme, "PM-KISAN")

    inject = f"""
    <script>
    window.addEventListener('load', function() {{
        // Fill all input fields
        var inputs = {{
            'full_name': '{name}', 'applicant_name': '{name}',
            'name': '{name}', 'aadhaar': '{aadhaar}',
            'aadhaar_number': '{aadhaar}', 
            'mobile': '+91 {mobile}', 'mobile_number': '{mobile}',
            'dob': '{dob}', 'date_of_birth': '{dob}',
            'district': '{district}', 'pincode': '{pincode}',
            'pin_code': '{pincode}', 'application_id': '{app_id}',
            'annual_income': '80000', 'family_size': '4',
            'family_members': '4', 'income': '80000',
            'village': '{district}', 'ward': '{district}',
            'bank_name': 'State Bank of India',
            'account_number': '31290481673',
            'ifsc': 'SBIN0001234', 'bank_account': '31290481673',
            'land_area': '2.5', 'survey_number': 'KH/142/2023',
        }};
        for (var id in inputs) {{
            var el = document.getElementById(id);
            if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {{
                el.value = inputs[id];
            }}
        }};

        // Fill SELECT dropdowns
        var selects = {{
            'gender': '{gender.upper()}',
            'state': '{state}',
            'category': 'general',
            'social_category': 'general', 
            'blood_group': 'O+',
            'disability_status': 'None',
            'card_type': 'PHH',
        }};
        for (var sid in selects) {{
            var sel = document.getElementById(sid);
            if (sel && sel.tagName === 'SELECT') {{
                var val = selects[sid].toLowerCase();
                for (var i=0; i<sel.options.length; i++) {{
                    var opt = sel.options[i];
                    if (opt.value.toLowerCase().includes(val) || 
                        opt.text.toLowerCase().includes(val) ||
                        val.includes(opt.value.toLowerCase())) {{
                        sel.selectedIndex = i;
                        break;
                    }}
                }}
            }}
        }};

        // Override D object for demo animation
        if (typeof D !== 'undefined') {{
            D.full_name = '{name}';
            D.name      = '{name}';
            D.aadhaar   = '{aadhaar}';
            D.mobile    = '+91 {mobile}';
            D.dob       = '{dob}';
            D.state     = '{state}';
            D.district  = '{district}';
            D.pincode   = '{pincode}';
            D.gender    = '{gender.lower()}';
            D.income    = '80000';
            D.family_size = '4';
            D.bank_name = 'State Bank of India';
            D.account_number = '31290481673';
            D.ifsc = 'SBIN0001234';
            D.land_area = '2.5';
        }};

        // Set application ID in any display element
        ['{app_id}'].forEach(function(v) {{
            ['application_id','app-id','ref-id','demo-ref-id','appId'].forEach(function(id) {{
                var el = document.getElementById(id);
                if (el) el.textContent = '{app_id}';
            }});
        }});

        // Check declaration checkbox if exists
        var checkboxes = document.querySelectorAll('input[type=checkbox]');
        checkboxes.forEach(function(cb) {{ cb.checked = true; }});

    }});
    </script>
    """
    html = html.replace('</head>', inject + '</head>')

    with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as f:
        f.write(html)
        tmp_html = f.name

    tmp_png = tempfile.mktemp(suffix='.png')

    try:
        result = subprocess.run([
            'wkhtmltoimage',
            '--width', '1400',
            '--zoom', '1.3',
            '--quality', '95',
            '--javascript-delay', '2000',
            '--enable-javascript',
            '--no-stop-slow-scripts',
            '--disable-smart-width',
            tmp_html, tmp_png
        ], capture_output=True, text=True, timeout=40)

        if os.path.exists(tmp_png) and os.path.getsize(tmp_png) > 10000:
            with open(tmp_png, 'rb') as f:
                raw = f.read()
            # Compress but keep quality high
            img = Image.open(io.BytesIO(raw)).convert('RGB')
            # Keep full width, don't downscale
            out = io.BytesIO()
            img.save(out, format='JPEG', quality=90, optimize=True)
            compressed = out.getvalue()
            # If too large for Telegram (>10MB), resize
            if len(compressed) > 8 * 1024 * 1024:
                img = img.resize((1400, int(img.height * 1400 / img.width)), Image.LANCZOS)
                out = io.BytesIO()
                img.save(out, format='JPEG', quality=85, optimize=True)
                compressed = out.getvalue()
            logger.info(f"Screenshot: {len(raw)//1024}KB → {len(compressed)//1024}KB")
            return base64.b64encode(compressed).decode()
        else:
            logger.error(f"wkhtmltoimage failed: {result.stderr[:200]}")
            return None
    finally:
        if os.path.exists(tmp_html): os.unlink(tmp_html)
        if os.path.exists(tmp_png): os.unlink(tmp_png)

def _submit(scheme, user_data, app_id=None):
    if not app_id:
        prefix = {"pmkisan":"JS","ration":"RC","ayushman":"AB"}.get(scheme,"JS")
        app_id = prefix + uuid.uuid4().hex[:6].upper()
    html_file = os.path.join(PORTAL_BASE, SCHEME_FILES.get(scheme, "pm_kisan.html"))
    
    if not os.path.exists(html_file):
        logger.error(f"HTML file not found: {html_file}")
        return {"success": False, "application_id": app_id, "screenshot_b64": None}

    user_data["scheme"] = scheme
    screenshot_b64 = _generate_screenshot(html_file, user_data, app_id)
    
    return {
        "success": True,
        "application_id": app_id,
        "screenshot_b64": screenshot_b64,
        "scheme": scheme,
    }

def submit_pm_kisan_application(data, app_id=None): return _submit("pmkisan", data, app_id)
def submit_ration_card_application(data, app_id=None): return _submit("ration", data, app_id)
def submit_ayushman_application(data, app_id=None): return _submit("ayushman", data, app_id)
