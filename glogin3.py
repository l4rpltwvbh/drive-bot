import os, json, time, sys
from playwright.sync_api import sync_playwright
import pyotp

import glob as _glob
_chromium_candidates = [
    "/home/runner/workspace/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome",
    "/nix/store/kcvsxrmgwp3ffz5jijyy7wn9fcsjl4hz-playwright-browsers-1.55.0-with-cjk/chromium-1187/chrome-linux/chrome",
]
_chromium_candidates += _glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium*/chrome-linux64/chrome"))
_chromium_candidates += _glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium*/chrome-linux/chrome"))
CHROMIUM = next((p for p in _chromium_candidates if os.path.exists(p)), None)
EMAIL    = "ftmdeveloperz006@gmail.com"
PASSWORD = "ftm@2026"
TOTP_SEC = "KRGXVJCITW7YE5X7G5SPCF6R5LLBGKVY"
PHONE_10 = "6206213510"
OTP_FILE = "/tmp/sms_code.txt"
STATUS_F = "/tmp/login_status.txt"
RESULT_F = "/tmp/login_result.json"

def log(msg):
    print(f"[LOGIN] {msg}", flush=True)
    with open(STATUS_F,"w") as f: f.write(msg)

def nw(pg, t=20000):
    try: pg.wait_for_load_state("networkidle", timeout=t)
    except: pass
    time.sleep(2)

def wait_otp(timeout=300):
    for _ in range(timeout):
        if os.path.exists(OTP_FILE):
            with open(OTP_FILE) as f: val=f.read().strip()
            if val:
                try: os.remove(OTP_FILE)
                except: pass
                return val
        time.sleep(1)
    return None

with sync_playwright() as pw:
    br = pw.chromium.launch(
        executable_path=CHROMIUM, headless=True,
        args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
              "--disable-blink-features=AutomationControlled"],
    )
    ctx = br.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        viewport={"width":1280,"height":720},
    )
    pg = ctx.new_page()
    pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

    # Email
    log("STEP1_EMAIL")
    pg.goto("https://accounts.google.com/signin/v2/identifier?service=wise&continue=https://drive.google.com", timeout=40000)
    nw(pg)
    pg.locator('input[type="email"]').first.fill(EMAIL)
    pg.keyboard.press("Enter")
    nw(pg, 25000)
    log(f"AFTER_EMAIL: {pg.url[:80]}")

    # Password
    log("STEP2_PASSWORD")
    try:
        pg.wait_for_selector('input[type="password"]', timeout=15000)
        inps = pg.query_selector_all('input[type="password"]')
        for inp in inps:
            if inp.is_visible() and inp.bounding_box():
                inp.click(); time.sleep(0.3)
                inp.type(PASSWORD, delay=60); time.sleep(0.5)
                pg.keyboard.press("Enter")
                break
    except Exception as e:
        log(f"PWD_ERR: {e}")
    nw(pg, 25000)
    log(f"AFTER_PWD: {pg.url[:100]}")

    # Challenge loop
    for loop in range(10):
        cur = pg.url
        body = pg.inner_text("body")
        body_l = body.lower()
        log(f"LOOP{loop}: {cur[:80]}")

        if "drive.google.com" in cur and "accounts" not in cur:
            log("LOGGED_IN!"); break
        if "workspace.google.com" in cur and "products/drive" not in cur:
            log("WORKSPACE_LOGGED_IN"); break

        # OTP entry page (after SMS sent)
        if "enter the code" in body_l or ("verification code" in body_l and "enter a phone" not in body_l and "choose how" not in body_l and "verify it" in body_l):
            log("OTP_INPUT_PAGE: SMS aaya!")
            sms = wait_otp(300)
            if not sms: log("OTP_TIMEOUT"); break
            log(f"SMS_CODE: {sms}")
            oi = pg.locator('input[type="tel"]').first
            oi.wait_for(state="visible", timeout=10000)
            oi.fill(sms); pg.keyboard.press("Enter")
            nw(pg, 25000); continue

        # Phone number entry page
        if "enter a phone" in body_l:
            log("PHONE_ENTRY: Phone number fill kar raha hoon...")
            inps = pg.query_selector_all('input[type="tel"]')
            for t in inps:
                if t.is_visible() and t.bounding_box():
                    t.click(); time.sleep(0.5)
                    t.press("Control+a"); t.press("Delete"); time.sleep(0.3)
                    t.fill("+91" + PHONE_10); time.sleep(1.0)
                    val = pg.evaluate("() => { const t=document.querySelector('input[type=\"tel\"]'); return t?t.value:''; }")
                    log(f"PHONE_VAL: '{val}'")
                    break
            try:
                pg.locator('button:has-text("Next")').first.click(timeout=8000)
                log("NEXT_CLICKED")
            except:
                pg.mouse.click(803, 388)
                log("NEXT_CLICKED_COORDS")
            nw(pg, 20000)
            log(f"AFTER_PHONE_NEXT: {pg.url[:100]} | {pg.inner_text('body')[:80]}")
            continue

        # Selection page
        if "choose how" in body_l or "how you want to sign" in body_l:
            log("SELECTION: Phone option click...")
            try:
                pg.get_by_text("Get a verification code sent to your phone").click(timeout=8000)
            except Exception as e:
                log(f"sel_err: {e}")
                try: pg.locator('[data-challengetype]').first.click(timeout=5000)
                except: pass
            nw(pg); continue

        # IAP - Try another way
        if "verify it" in body_l and ("iap" in cur or "selection" in cur):
            log("IAP: Try another way...")
            try:
                pg.locator('button, a').filter(has_text="Try another way").first.click(timeout=8000)
            except:
                try: pg.get_by_text("Try another way").click(timeout=8000)
                except: pass
            nw(pg); continue

        # TOTP
        if "totp" in cur or "authenticator" in body_l:
            log("TOTP")
            otp = pyotp.TOTP(TOTP_SEC.replace(" ","").upper()).now()
            pg.locator('input[type="tel"]').first.fill(otp)
            pg.keyboard.press("Enter")
            nw(pg, 20000); continue

        # Password again
        if "challenge/pwd" in cur or "enter your password" in body_l:
            log("PWD_AGAIN")
            inps = pg.query_selector_all('input[type="password"]')
            for inp in inps:
                if inp.is_visible() and inp.bounding_box():
                    inp.click(); time.sleep(0.3)
                    inp.type(PASSWORD, delay=60); pg.keyboard.press("Enter"); break
            nw(pg, 25000); continue

        log(f"UNHANDLED: {body_l[:100]}"); break

    # Extract cookies
    log("EXTRACTING")
    pg.goto("https://drive.google.com", timeout=30000)
    nw(pg)
    log(f"DRIVE: {pg.url[:100]}")

    cl = ctx.cookies(["https://drive.google.com","https://google.com","https://accounts.google.com"])
    cj = json.dumps({"url":"https://drive.google.com","cookies":[{"name":c["name"],"value":c["value"]} for c in cl]})
    br.close()

    with open(RESULT_F,"w") as f: f.write(cj)
    names=[c["name"] for c in json.loads(cj)["cookies"]]
    has_auth=any(n in names for n in ["SID","SAPISID","__Secure-1PSID","HSID","__Secure-3PSID"])
    log(f"{'SUCCESS' if has_auth else 'PARTIAL'}: {len(names)} cookies: {names[:10]}")
