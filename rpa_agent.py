import os, uuid, subprocess, tempfile, base64, logging, io, re
from typing import Dict, Any
from PIL import Image

logger = logging.getLogger(__name__)
PORTAL_BASE = os.getenv("MOCK_PORTAL_BASE", "/home/ubuntu/app/mock_portal")

SCHEME_FILES = {
    "pmkisan":  "pm_kisan.html",
    "ration":   "ration_card.html",
    "ayushman": "ayushman_bharat.html",
}

SCHEME_DISPLAY = {
    "pmkisan":  "PM-KISAN",
    "ration":   "Ration Card",
    "ayushman": "Ayushman Bharat",
}

SCHEME_FIELDS = {
    "pmkisan": {
        "inputs": {
            "dob":          "dob",
            "aadhaar":      "aadhaar_masked",
            "pincode":      "pincode",
            "ifsc":         "ifsc",
        },
        "selects": {
            "gender":   "gender",
            "state":    "state",
            "category": "category",
        },
        "defaults": {
            "ifsc":     "SBIN0001234",
            "category": "general",
        }
    },
    "ration": {
        "inputs": {
            "head_name":      "name",
            "head_dob":       "dob",
            "aadhaar":        "aadhaar_masked",
            "mobile":         "mobile",
            "family_members": "family_members",
            "children_count": "children_count",
            "senior_count":   "senior_count",
            "district":       "district",
            "village":        "district",
            "pincode":        "pincode",
            "full_address":   "address",
            "monthly_income": "monthly_income",
        },
        "selects": {
            "head_gender":    "gender",
            "head_occupation":"occupation",
            "head_category":  "category",
            "state":          "state",
            "existing_card":  "existing_card",
        },
        "defaults": {
            "family_members": "4",
            "children_count": "2",
            "senior_count":   "0",
            "monthly_income": "8000",
            "head_occupation":"farmer",
            "category":       "general",
            "existing_card":  "none",
        }
    },
    "ayushman": {
        "inputs": {
            "full_name":           "name",
            "dob":                 "dob",
            "age":                 "age",
            "aadhaar":             "aadhaar_masked",
            "mobile":              "mobile",
            "family_size":         "family_size",
            "annual_income":       "annual_income",
            "district":            "district",
            "village":             "district",
            "pincode":             "pincode",
            "existing_conditions": "existing_conditions",
            "secc_id":             "secc_id",
        },
        "selects": {
            "gender":     "gender",
            "category":   "category",
            "state":      "state",
            "disability": "disability",
            "blood_group":"blood_group",
        },
        "defaults": {
            "family_size":         "4",
            "annual_income":       "80000",
            "existing_conditions": "None",
            "disability":          "none",
            "blood_group":         "o+",
            "category":            "general",
            "secc_id":             "",
        }
    }
}

def _calc_age(dob):
    try:
        from datetime import date
        d, m, y = map(int, dob.split('/'))
        today = date.today()
        return str(today.year - y - ((today.month, today.day) < (m, d)))
    except:
        return "35"

def _normalize_gender(g):
    g = (g or "").lower().strip()
    if "female" in g: return "female"
    if "male" in g:   return "male"
    return "male"

def _build_data(scheme, user_data, app_id):
    name     = user_data.get("name", "Applicant")
    aadhaar  = user_data.get("aadhaar_masked", user_data.get("aadhaar", "XXXX XXXX 0000"))
    mobile   = user_data.get("mobile", "")
    dob      = user_data.get("dob", "01/01/1990")
    state    = user_data.get("state", "")
    district = user_data.get("district", "")
    pincode  = user_data.get("pincode", "")
    gender   = _normalize_gender(user_data.get("gender", "male"))
    address  = user_data.get("address", district)
    age      = _calc_age(dob) if dob else "35"

    mobile_clean = re.sub(r'\D', '', mobile)[-10:]
    mobile_fmt   = f"+91 {mobile_clean}" if mobile_clean else ""

    aadhaar_digits = re.sub(r'\D', '', aadhaar)
    if len(aadhaar_digits) == 12:
        aadhaar_fmt = f"{aadhaar_digits[:4]} {aadhaar_digits[4:8]} {aadhaar_digits[8:]}"
    else:
        aadhaar_fmt = aadhaar

    return {
        "name":                name,
        "aadhaar_masked":      aadhaar_fmt,
        "mobile":              mobile_fmt,
        "dob":                 dob,
        "age":                 age,
        "state":               state,
        "district":            district,
        "pincode":             pincode,
        "gender":              gender,
        "address":             address,
        "app_id":              app_id,
        "family_members":      user_data.get("family_members", "4"),
        "family_size":         user_data.get("family_size", "4"),
        "children_count":      user_data.get("children_count", "2"),
        "senior_count":        user_data.get("senior_count", "0"),
        "monthly_income":      user_data.get("monthly_income", "8000"),
        "annual_income":       user_data.get("annual_income", "80000"),
        "occupation":          user_data.get("occupation", "farmer"),
        "category":            user_data.get("category", "general"),
        "existing_card":       user_data.get("existing_card", "none"),
        "blood_group":         user_data.get("blood_group", "o+"),
        "disability":          user_data.get("disability", "none"),
        "existing_conditions": user_data.get("existing_conditions", "None"),
        "secc_id":             user_data.get("secc_id", ""),
        "ifsc":                user_data.get("ifsc", "SBIN0001234"),
    }

def _build_js_injection(scheme, data):
    fields   = SCHEME_FIELDS.get(scheme, {})
    inp_map  = fields.get("inputs", {})
    sel_map  = fields.get("selects", {})
    defaults = fields.get("defaults", {})
    app_id   = data.get("app_id", "")
    scheme_name = SCHEME_DISPLAY.get(scheme, "")

    input_lines = []
    for field_id, data_key in inp_map.items():
        value = data.get(data_key) or defaults.get(field_id, "")
        if value:
            value = str(value).replace("'", "\\'").replace('"', '\\"').replace('\n', ' ')
            input_lines.append(f"    fillInput('{field_id}', '{value}');")

    select_lines = []
    for field_id, data_key in sel_map.items():
        value = data.get(data_key) or defaults.get(field_id, "")
        if value:
            value = str(value).replace("'", "\\'")
            select_lines.append(f"    fillSelect('{field_id}', '{value}');")

    input_js  = "\n".join(input_lines)
    select_js = "\n".join(select_lines)

    name     = str(data.get("name","")).replace("'","\\'")
    aadhaar  = str(data.get("aadhaar_masked","")).replace("'","\\'")
    mobile   = str(data.get("mobile","")).replace("'","\\'")
    dob      = str(data.get("dob","")).replace("'","\\'")
    state    = str(data.get("state","")).replace("'","\\'")
    district = str(data.get("district","")).replace("'","\\'")
    pincode  = str(data.get("pincode","")).replace("'","\\'")
    gender   = str(data.get("gender","")).replace("'","\\'")
    income   = str(data.get("annual_income","80000"))
    fsize    = str(data.get("family_size","4"))

    return f"""
<script>
function fillInput(id, value) {{
    var el = document.getElementById(id);
    if (!el) return;
    el.value = value;
    el.dispatchEvent(new Event('input', {{bubbles:true}}));
    el.dispatchEvent(new Event('change', {{bubbles:true}}));
}}
function fillSelect(id, value) {{
    var sel = document.getElementById(id);
    if (!sel) return;
    var v = value.toLowerCase();
    for (var i = 0; i < sel.options.length; i++) {{
        var opt = sel.options[i];
        if (opt.value.toLowerCase() === v ||
            opt.text.toLowerCase() === v ||
            opt.value.toLowerCase().includes(v) ||
            opt.text.toLowerCase().includes(v) ||
            (v.includes(opt.value.toLowerCase()) && opt.value !== '')) {{
            sel.selectedIndex = i;
            sel.dispatchEvent(new Event('change', {{bubbles:true}}));
            break;
        }}
    }}
}}
function fillAll() {{
{input_js}
{select_js}
    document.querySelectorAll('input[type=checkbox]').forEach(function(cb) {{ cb.checked = true; }});
    ['application_id','app-id','ref-id','demo-ref-id','appId','app_id_display'].forEach(function(id) {{
        var el = document.getElementById(id);
        if (el) el.textContent = '{app_id}';
    }});
    if (typeof D !== 'undefined') {{
        D.full_name='{name}'; D.name='{name}'; D.aadhaar='{aadhaar}';
        D.mobile='{mobile}'; D.dob='{dob}'; D.state='{state}';
        D.district='{district}'; D.pincode='{pincode}';
        D.gender='{gender}'; D.income='{income}'; D.family_size='{fsize}';
    }}
    var banner = document.createElement('div');
    banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:linear-gradient(135deg,#10b981,#059669);color:white;padding:14px 20px;font-size:15px;font-weight:700;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,0.3);font-family:sans-serif;';
    banner.innerHTML = '✅ {scheme_name} Application Submitted &nbsp;|&nbsp; ID: <b>{app_id}</b> &nbsp;|&nbsp; AWS S3 ✅ &nbsp;|&nbsp; DynamoDB ✅ &nbsp;|&nbsp; SMS Sent ✅';
    document.body.prepend(banner);
}}
if (document.readyState === 'loading') {{ document.addEventListener('DOMContentLoaded', fillAll); }}
else {{ fillAll(); }}
setTimeout(fillAll, 800);
setTimeout(fillAll, 2500);
</script>
"""

def _generate_screenshot(html_file, user_data, app_id):
    scheme = user_data.get("scheme", "pmkisan")
    with open(html_file, 'r', encoding='utf-8') as f:
        html = f.read()

    data = _build_data(scheme, user_data, app_id)
    logger.info(f"[RPA] {SCHEME_DISPLAY[scheme]} | name={data['name']} | state={data['state']} | aadhaar=****{data['aadhaar_masked'][-4:]}")

    js = _build_js_injection(scheme, data)
    html = html.replace('</head>', js + '</head>') if '</head>' in html else js + html

    with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as f:
        f.write(html)
        tmp_html = f.name
    tmp_png = tempfile.mktemp(suffix='.png')

    try:
        result = subprocess.run([
            'wkhtmltoimage',
            '--width', '1400', '--zoom', '1.2', '--quality', '95',
            '--javascript-delay', '3000', '--enable-javascript',
            '--no-stop-slow-scripts', '--disable-smart-width',
            tmp_html, tmp_png
        ], capture_output=True, text=True, timeout=45)

        if os.path.exists(tmp_png) and os.path.getsize(tmp_png) > 10000:
            with open(tmp_png, 'rb') as f:
                raw = f.read()
            img = Image.open(io.BytesIO(raw)).convert('RGB')
            out = io.BytesIO()
            img.save(out, format='JPEG', quality=90, optimize=True)
            compressed = out.getvalue()
            if len(compressed) > 8 * 1024 * 1024:
                img = img.resize((1400, int(img.height * 1400 / img.width)), Image.LANCZOS)
                out = io.BytesIO()
                img.save(out, format='JPEG', quality=85, optimize=True)
                compressed = out.getvalue()
            logger.info(f"[RPA] Screenshot OK: {len(raw)//1024}KB → {len(compressed)//1024}KB")
            return base64.b64encode(compressed).decode()
        else:
            logger.error(f"[RPA] wkhtmltoimage failed: {result.stderr[:300]}")
            return None
    except Exception as e:
        logger.error(f"[RPA] Screenshot error: {e}")
        return None
    finally:
        if os.path.exists(tmp_html): os.unlink(tmp_html)
        if os.path.exists(tmp_png):  os.unlink(tmp_png)

def _submit(scheme, user_data):
    prefix = {"pmkisan":"JS","ration":"RC","ayushman":"AB"}.get(scheme,"JS")
    app_id = prefix + uuid.uuid4().hex[:6].upper()
    html_file = os.path.join(PORTAL_BASE, SCHEME_FILES.get(scheme, "pm_kisan.html"))
    if not os.path.exists(html_file):
        logger.error(f"[RPA] HTML not found: {html_file}")
        return {"success": False, "application_id": app_id, "screenshot_b64": None}
    user_data["scheme"] = scheme
    screenshot_b64 = _generate_screenshot(html_file, user_data, app_id)
    return {
        "success": screenshot_b64 is not None,
        "application_id": app_id,
        "screenshot_b64": screenshot_b64,
        "scheme": scheme,
        "scheme_name": SCHEME_DISPLAY.get(scheme, ""),
    }

def submit_pm_kisan_application(data): return _submit("pmkisan", data)
def submit_ration_card_application(data): return _submit("ration", data)
def submit_ayushman_application(data): return _submit("ayushman", data)
