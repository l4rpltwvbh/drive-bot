import os
import json
import uuid
import time
import threading
import queue
import subprocess
import tempfile
import hashlib
import requests

import base64
from flask import Flask, request, jsonify, render_template, redirect, Response, stream_with_context

import db

app = Flask(__name__)

# ── Persistent working directory (never /tmp — survives across sessions) ──────
FTM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ftm")
os.makedirs(FTM_DIR, exist_ok=True)
# Sub-directories created on first use; define helpers here for DRY paths
def _ftm(filename: str) -> str:
    """Return an absolute path inside FTM_DIR, creating the dir if needed."""
    return os.path.join(FTM_DIR, filename)
def _ftm_sub(subdir: str, filename: str = "") -> str:
    """Return a path inside a sub-directory of FTM_DIR, creating it if needed."""
    d = os.path.join(FTM_DIR, subdir)
    os.makedirs(d, exist_ok=True)
    return d if not filename else os.path.join(d, filename)

# ── In-memory state ──────────────────────────────────────────────────────────
_folder_tree_cache  = {}   # uid -> {folder_id, tree}
_download_callbacks = {}   # uid -> callable(files_list)
_cookie_callbacks   = {}   # uid -> callable(cookie_str)
_oauth_callbacks    = {}   # uid -> callable(user_info dict)
_global_oauth_callback = None # callable(uid: int, user_info: dict)
_status_callbacks   = {}   # uid -> callable(event, data)   ← for log channel

# Autologin sessions: sid -> {status, message, otp_type?, email, uid, logs:[]}
_autologin_sessions = {}
_sessions_lock = threading.Lock()

# Live frame store: sid -> {"data": bytes (jpeg), "seq": int}  — for SSE stream
_live_frames: dict = {}
_live_frames_lock = threading.Lock()

# Per-session interact lock — prevents concurrent Playwright calls
_interact_locks: dict = {}   # sid -> threading.Lock()

def _get_interact_lock(sid: str) -> threading.Lock:
    with _sessions_lock:
        if sid not in _interact_locks:
            _interact_locks[sid] = threading.Lock()
        return _interact_locks[sid]

# Per-session job queue — Playwright's sync API is NOT thread-safe. All calls
# on a given `page` MUST happen on the single thread that created it (the
# `_run_autologin` automation thread). The Flask request thread handling
# /api/autologin/interact must never touch `pg` directly — doing so corrupts
# Playwright's internal greenlet dispatcher ("cannot switch to a different
# thread") and silently wedges the automation loop even though the real
# browser keeps working. Instead, the Flask thread enqueues a job here and
# the automation thread drains/executes it between its own steps.
_interact_queues: dict = {}   # sid -> queue.Queue()

def _get_interact_queue(sid: str) -> "queue.Queue":
    with _sessions_lock:
        if sid not in _interact_queues:
            _interact_queues[sid] = queue.Queue()
        return _interact_queues[sid]

# ── Public API used by bot.py ─────────────────────────────────────────────────

def set_folder_tree_cache(uid: int, folder_id: str, tree: dict):
    _folder_tree_cache[uid] = {"folder_id": folder_id, "tree": tree}


def register_download_callback(uid: int, callback):
    _download_callbacks[uid] = callback


def register_callback(uid: int, callback):
    """Register callback for auto-login cookie result."""
    _cookie_callbacks[uid] = callback


def register_status_callback(uid: int, callback):
    """Register callback for autologin status events (start/challenge/success/fail).
    callback(event: str, data: dict)
    """
    _status_callbacks[uid] = callback


def register_oauth_callback(uid: int, callback):
    _oauth_callbacks[uid] = callback


def set_global_oauth_callback(callback):
    global _global_oauth_callback
    _global_oauth_callback = callback


def start_in_background(port: int = 8080):
    t = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False),
        daemon=True,
        name="flask-server",
    )
    t.start()
    print(f"[SERVER] Flask started on port {port}", flush=True)


# ── HTML Pages ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return "<h2>DriveGram Bot Server</h2><p>Running.</p>", 200


@app.route("/cookie")
def cookie_page():
    uid = request.args.get("uid", "")
    return render_template("cookie.html", uid=uid)


_bot_username: str = ""  # set by bot.py after get_me()

def set_bot_username(username: str):
    """Called by bot.py after bot.start() to cache the real bot username."""
    global _bot_username
    _bot_username = username.lstrip("@") if username else ""
    print(f"[SERVER] bot_username set → @{_bot_username}", flush=True)

def _get_bot_url() -> str:
    # Priority: runtime-fetched username > BOT_USERNAME env var
    username = _bot_username or os.environ.get("BOT_USERNAME", "").lstrip("@")
    return f"https://t.me/{username}" if username else ""


@app.route("/autologin")
def autologin_page():
    uid = request.args.get("uid", "")
    return render_template("autologin.html", uid=uid, bot_url=_get_bot_url())


@app.route("/showcookies")
def show_cookies_page():
    uid    = request.args.get("uid", "")
    cookies = request.args.get("c", "")
    if uid and cookies:
        try:
            db.save_google_cookies(int(uid), cookies)
            cb = _cookie_callbacks.pop(int(uid), None)
            if cb:
                threading.Thread(target=cb, args=(cookies,), daemon=True).start()
        except Exception as e:
            print(f"[SERVER] showcookies save error: {e}")
    return render_template("show_cookies.html", cookies=cookies)


@app.route("/browse")
def browse_page():
    uid       = request.args.get("uid", "")
    folder_id = request.args.get("folder", "")
    return render_template("browse.html", uid=uid, folder_id=folder_id)


# ── OAuth ─────────────────────────────────────────────────────────────────────

def _get_oauth_flow(uid: int):
    from google_auth_oauthlib.flow import Flow
    client_id     = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None
    base = _get_base_url()
    redirect_uri = f"{base}/oauth/callback"
    client_config = {
        "web": {
            "client_id":     client_id,
            "client_secret": client_secret,
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=[
            "https://www.googleapis.com/auth/drive.readonly",
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ],
        redirect_uri=redirect_uri,
    )
    return flow


def _get_base_url():
    if os.environ.get("PUBLIC_URL"):
        return os.environ["PUBLIC_URL"].rstrip("/")
    if os.environ.get("RENDER_EXTERNAL_URL"):
        return os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
    if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        return "https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"].rstrip("/")
    if os.environ.get("REPLIT_DEV_DOMAIN"):
        return "https://" + os.environ["REPLIT_DEV_DOMAIN"].rstrip("/")
    port = os.environ.get("PORT", "8080")
    return f"http://localhost:{port}"


_oauth_state_map = {}  # state -> (uid, code_verifier)

@app.route("/oauth/login")
def oauth_login():
    uid = request.args.get("uid", "")
    flow = _get_oauth_flow(uid)
    if not flow:
        return "Google OAuth not configured (missing GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET).", 503
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    _oauth_state_map[state] = (uid, getattr(flow, "code_verifier", None))
    return redirect(auth_url)


@app.route("/oauth/callback")
def oauth_callback():
    state = request.args.get("state", "")
    state_data = _oauth_state_map.pop(state, None)
    if not state_data:
        return render_template("oauth_result.html", success=False, error="Invalid OAuth state."), 400

    if isinstance(state_data, tuple):
        uid, code_verifier = state_data
    else:
        uid, code_verifier = state_data, None

    flow = _get_oauth_flow(uid)
    if not flow:
        return render_template("oauth_result.html", success=False, error="OAuth not configured."), 503

    if code_verifier:
        flow.code_verifier = code_verifier

    try:
        kwargs = {}
        if code_verifier:
            kwargs["code_verifier"] = code_verifier
        flow.fetch_token(
            authorization_response=request.url.replace("http://", "https://"),
            **kwargs
        )
        creds = flow.credentials

        import google.oauth2.credentials
        from googleapiclient.discovery import build as gbuild

        service = gbuild("oauth2", "v2", credentials=creds)
        user_info = service.userinfo().get().execute()

        name  = user_info.get("name", "")
        email = user_info.get("email", "")

        db.save_oauth_tokens(
            int(uid),
            access_token=creds.token,
            refresh_token=creds.refresh_token or "",
            expiry=creds.expiry.timestamp() if creds.expiry else 0.0,
            email=email,
            name=name,
        )

        cb = _oauth_callbacks.pop(int(uid), None)
        if cb:
            try:
                threading.Thread(target=cb, args=(user_info,), daemon=True).start()
            except Exception as _e:
                print(f"[OAUTH] User callback trigger error: {_e}")

        if _global_oauth_callback:
            try:
                threading.Thread(target=_global_oauth_callback, args=(int(uid), user_info), daemon=True).start()
            except Exception as _e:
                print(f"[OAUTH] Global callback trigger error: {_e}")

        bot_username = os.environ.get("BOT_USERNAME", "").lstrip("@")
        bot_url = f"https://t.me/{bot_username}" if bot_username else "https://t.me/ftm_drivebot"

        return render_template("oauth_result.html", success=True, name=name, email=email, bot_url=bot_url)
    except Exception as e:
        print(f"[OAUTH] Callback error: {e}")
        return render_template("oauth_result.html", success=False, error=str(e)), 500


# ── Drive Browser API ─────────────────────────────────────────────────────────

@app.route("/api/folder_tree")
def api_folder_tree():
    uid_str   = request.args.get("uid", "")
    folder_id = request.args.get("folder_id", "")
    try:
        uid = int(uid_str)
    except ValueError:
        return jsonify({"error": "invalid uid"}), 400

    cached = _folder_tree_cache.get(uid)
    if cached and cached.get("folder_id") == folder_id:
        return jsonify(cached["tree"])

    cached_tree = db.get_drive_folder_tree(folder_id)
    if cached_tree:
        return jsonify(cached_tree)

    return jsonify({"error": "tree_not_ready", "message": "Folder tree not loaded yet. Please wait."}), 404


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(silent=True) or {}
    uid_str = data.get("uid", "")
    files   = data.get("files", [])
    try:
        uid = int(uid_str)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "invalid uid"}), 400

    cb = _download_callbacks.get(uid)
    if not cb:
        return jsonify({"ok": False, "error": "No active browse session for this user."}), 404

    threading.Thread(target=cb, args=(files,), daemon=True).start()
    return jsonify({"ok": True, "count": len(files)})


# ── Screenshot / Live stream ───────────────────────────────────────────────────

@app.route("/api/autologin/screenshot")
def autologin_screenshot():
    from flask import send_file
    sid = request.args.get("sid", "")
    # Try in-memory frame first (fastest)
    with _live_frames_lock:
        frame = _live_frames.get(sid)
    if frame:
        from io import BytesIO
        return Response(BytesIO(frame["data"]), mimetype="image/jpeg")
    # Fallback to file
    ss_file = _ftm(f"al_ss_{sid}.jpg")
    if not os.path.exists(ss_file):
        ss_file = _ftm(f"al_ss_{sid}.png")
    if os.path.exists(ss_file):
        mime = "image/jpeg" if ss_file.endswith(".jpg") else "image/png"
        return send_file(ss_file, mimetype=mime)
    return "", 404


@app.route("/api/autologin/stream")
def autologin_stream():
    """SSE endpoint — pushes JPEG frames as base64 as fast as they arrive (~5fps)."""
    sid = request.args.get("sid", "")

    def _generate():
        last_seq = -1
        missed = 0
        while True:
            with _live_frames_lock:
                frame = _live_frames.get(sid)
            if frame and frame["seq"] != last_seq:
                last_seq = frame["seq"]
                missed = 0
                b64 = base64.b64encode(frame["data"]).decode()
                yield f"data: {b64}\n\n"
            else:
                missed += 1
                # Only close if session has actually ended (not just waiting for user input)
                if missed > 50:   # 10s with no frame — check session status
                    with _sessions_lock:
                        sess = _autologin_sessions.get(sid, {})
                    status = sess.get("status", "")
                    if status in ("done", "error", "success", ""):
                        yield "event: end\ndata: done\n\n"
                        return
                    # Session still active (running/need_otp) — keep stream open, just ping
                    missed = 40   # reset to just below threshold so we keep checking
                yield ": ping\n\n"
            time.sleep(0.2)

    return Response(
        stream_with_context(_generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _execute_interact_job(pg, sess, sid, data):
    """Runs ONLY on the automation thread that owns `pg`. Never call this
    from the Flask request thread — Playwright's sync API is not thread-safe
    and cross-thread calls corrupt its greenlet dispatcher, silently wedging
    the whole automation loop."""
    action = data.get("action", "")
    vp_w, vp_h = sess.get("_page_vp", (1366, 768))
    is_field = False

    if action == "click":
        x = float(data.get("x", 0))
        y = float(data.get("y", 0))
        x = max(0, min(x, vp_w - 1))
        y = max(0, min(y, vp_h - 1))
        pg.mouse.click(x, y)
        try:
            is_field = bool(pg.evaluate(
                """([px, py]) => {
                    const el = document.elementFromPoint(px, py);
                    if (!el) return false;
                    const tag = el.tagName;
                    if (tag === 'TEXTAREA') return true;
                    if (tag === 'INPUT') {
                        const t = (el.getAttribute('type') || 'text').toLowerCase();
                        return !['button','submit','checkbox','radio','range','color','file','image','reset','hidden'].includes(t);
                    }
                    if (el.isContentEditable) return true;
                    return false;
                }""",
                [x, y],
            ))
        except Exception:
            is_field = False

    elif action == "type":
        text = str(data.get("text", ""))
        if text:
            pg.keyboard.type(text, delay=30)

    elif action == "key":
        key = str(data.get("key", "Enter"))
        _safe = {"Enter","Backspace","Tab","Escape","ArrowUp","ArrowDown",
                 "ArrowLeft","ArrowRight","Delete","Home","End","PageUp","PageDown",
                 "Control+a","Control+c","Control+v","Control+x","Shift+Tab",
                 "F5","Space"}
        if key not in _safe:
            return {"ok": False, "error": "Key not allowed", "_status": 400}
        pg.keyboard.press(key)

    elif action == "scroll":
        dx = float(data.get("dx", 0))
        dy = float(data.get("dy", 0))
        pg.mouse.wheel(dx, dy)

    else:
        return {"ok": False, "error": "Unknown action", "_status": 400}

    time.sleep(0.35)
    try:
        frame_data = pg.screenshot(full_page=False, type="jpeg", quality=65)
        with _live_frames_lock:
            seq = _live_frames.get(sid, {}).get("seq", 0) + 1
            _live_frames[sid] = {"data": frame_data, "seq": seq}
    except Exception:
        pass

    return {"ok": True, "is_field": is_field}


def _drain_interact_queue(sid, pg, sess):
    """Call frequently from the automation thread (the ONLY thread allowed to
    touch `pg`) to execute any pending live-view interactions queued up by
    the Flask request thread."""
    q = _get_interact_queue(sid)
    while True:
        try:
            job = q.get_nowait()
        except queue.Empty:
            break
        try:
            job["result"] = _execute_interact_job(pg, sess, sid, job["data"])
        except Exception as e:
            job["result"] = {"ok": False, "error": str(e), "_status": 500}
        finally:
            job["event"].set()


@app.route("/api/autologin/interact", methods=["POST"])
def autologin_interact():
    """Queue a click/keystroke/typed-text job for the live Playwright browser.
    The actual Playwright calls run on the automation thread that owns the
    page (see `_drain_interact_queue`) — this route must NEVER call `pg.*`
    itself, since Playwright's sync API is not thread-safe across threads."""
    data   = request.get_json(silent=True) or {}
    sid    = data.get("sid", "")

    with _sessions_lock:
        sess = _autologin_sessions.get(sid)
    if not sess:
        return jsonify({"ok": False, "error": "Session not found"}), 404

    pg = sess.get("_page")
    if not pg:
        return jsonify({"ok": False, "error": "Browser not ready yet"}), 400

    lock = _get_interact_lock(sid)
    acquired = lock.acquire(timeout=2.0)
    if not acquired:
        return jsonify({"ok": False, "error": "Browser busy — try again"}), 429

    try:
        job = {"data": data, "event": threading.Event(), "result": None}
        _get_interact_queue(sid).put(job)
        # Automation thread drains its queue at least every ~400ms even
        # while idle/waiting, so a short wait here is enough.
        finished = job["event"].wait(timeout=6.0)
        if not finished:
            return jsonify({"ok": False, "error": "Browser busy — try again"}), 429

        result = job["result"] or {"ok": False, "error": "No result"}
        status = result.pop("_status", 200)
        return jsonify(result), status

    finally:
        lock.release()


# ── Auto Login API ────────────────────────────────────────────────────────────

# Device / browser presets the user can pick before starting a login — each
# one drives the Playwright context's user-agent + viewport + touch/mobile
# flags so the emulated session actually looks like that device to Google.
DEVICE_PRESETS = {
    "win_chrome": {
        "label": "🖥️ Windows · Chrome", "platform": "Windows",
        "ua_template": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
        "viewport": {"width": 1366, "height": 768}, "is_mobile": False, "has_touch": False,
        "device_scale_factor": 1, "sec_ch_ua_platform": "Windows",
    },
    "win_edge": {
        "label": "🖥️ Windows · Edge", "platform": "Windows",
        "ua_template": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36 Edg/{ver}",
        "viewport": {"width": 1366, "height": 768}, "is_mobile": False, "has_touch": False,
        "device_scale_factor": 1, "sec_ch_ua_platform": "Windows",
    },
    "mac_chrome": {
        "label": "🍎 macOS · Chrome", "platform": "macOS",
        "ua_template": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
        "viewport": {"width": 1440, "height": 900}, "is_mobile": False, "has_touch": False,
        "device_scale_factor": 2, "sec_ch_ua_platform": "macOS",
    },
    "mac_safari": {
        "label": "🍎 macOS · Safari", "platform": "macOS",
        "ua_template": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "viewport": {"width": 1440, "height": 900}, "is_mobile": False, "has_touch": False,
        "device_scale_factor": 2, "sec_ch_ua_platform": "macOS",
    },
    "linux_chrome": {
        "label": "🐧 Linux · Chrome", "platform": "Linux",
        "ua_template": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
        "viewport": {"width": 1366, "height": 768}, "is_mobile": False, "has_touch": False,
        "device_scale_factor": 1, "sec_ch_ua_platform": "Linux",
    },
    "android_chrome": {
        "label": "🤖 Android · Chrome", "platform": "Android",
        "ua_template": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Mobile Safari/537.36",
        "viewport": {"width": 412, "height": 915}, "is_mobile": True, "has_touch": True,
        "device_scale_factor": 2.6, "sec_ch_ua_platform": "Android",
    },
    "ios_safari": {
        "label": "🍏 iPhone · Safari", "platform": "iOS",
        "ua_template": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True,
        "device_scale_factor": 3, "sec_ch_ua_platform": "iOS",
    },
    "ipad_safari": {
        "label": "🍏 iPad · Safari", "platform": "iOS",
        "ua_template": "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 820, "height": 1180}, "is_mobile": True, "has_touch": True,
        "device_scale_factor": 2, "sec_ch_ua_platform": "iOS",
    },
}
DEFAULT_DEVICE = "win_chrome"


@app.route("/api/autologin/devices")
def autologin_devices():
    """Expose the list of selectable device/browser presets to the frontend."""
    return jsonify({
        "ok": True,
        "default": DEFAULT_DEVICE,
        "devices": [{"id": k, "label": v["label"], "platform": v["platform"]} for k, v in DEVICE_PRESETS.items()],
    })


@app.route("/api/autologin/start", methods=["POST"])
def autologin_start():
    data        = request.get_json(silent=True) or {}
    uid         = data.get("uid", "")
    email       = data.get("email", "")
    password    = data.get("password", "")
    totp_secret = data.get("totp_secret", "")
    device      = data.get("device", DEFAULT_DEVICE)
    if device not in DEVICE_PRESETS:
        device = DEFAULT_DEVICE

    if not email or not password:
        return jsonify({"ok": False, "error": "Email aur password chahiye."}), 400

    sid = str(uuid.uuid4())
    vp  = DEVICE_PRESETS[device]["viewport"]
    with _sessions_lock:
        _autologin_sessions[sid] = {
            "status":     "running",
            "message":    "Login shuru ho raha hai...",
            "raw_status": "",
            "uid":        uid,
            "email":      email,
            "device":     device,
            "numbers":    [],
            "logs":       [{"ts": time.time(), "lvl": "info", "msg": f"🚀 Login shuru — {email} · {DEVICE_PRESETS[device]['label']}"}],
        }

    # Notify log channel: login started
    cb = _status_callbacks.get(int(uid) if str(uid).lstrip('-').isdigit() else uid)
    if cb:
        try:
            threading.Thread(target=cb, args=("start", {"email": email}), daemon=True).start()
        except Exception:
            pass
    else:
        # Direct WebApp open — no bot callback registered; notify log channel via HTTP
        def _http_log_start(uid=uid, email=email):
            _bt = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
            _lc = os.environ.get("LOG_CHANNEL_ID", "").strip()
            if not _bt or not _lc or not _lc.lstrip("-").isdigit():
                return
            try:
                _now = __import__("datetime").datetime.now().strftime("%d %b %Y %H:%M:%S")
                _tg_http(_bt, "sendMessage", {
                    "chat_id":                  _lc,
                    "text": (
                        f"🔐 #AutoLogin #Start #uid_{uid}\n\n"
                        f"👤 User: <a href=\"tg://user?id={uid}\">{uid}</a> (<code>{uid}</code>)\n"
                        f"📧 Email: <code>{_tg_escape(email)}</code>\n"
                        f"⏰ {_now}"
                    ),
                    "parse_mode":               "HTML",
                    "disable_web_page_preview": "true",
                })
            except Exception as _e:
                print(f"[SERVER] http_log_start error: {_e}")
        threading.Thread(target=_http_log_start, daemon=True).start()

    threading.Thread(
        target=_run_autologin,
        args=(sid, uid, email, password, totp_secret, device),
        daemon=True,
    ).start()

    return jsonify({"ok": True, "session_id": sid, "viewport": vp, "device": device})


def _run_autologin(sid: str, uid, email: str, password: str, totp_secret: str, device: str = DEFAULT_DEVICE):
    """Run Playwright-based Google login in a thread (not subprocess) for full challenge support."""
    status_file  = _ftm(f"al_status_{sid}.txt")
    result_file  = _ftm(f"al_result_{sid}.json")
    otp_file     = _ftm(f"al_otp_{sid}.txt")
    phone_file   = _ftm(f"al_phone_{sid}.txt")
    number_file  = _ftm(f"al_num_{sid}.txt")
    manual_file  = _ftm(f"al_manual_{sid}.txt")
    choice_file  = _ftm(f"al_choice_{sid}.txt")
    ss_file      = _ftm(f"al_ss_{sid}.jpg")

    # Per-account "device memory" — reusing the same browser storage/fingerprint
    # across logins makes Google see this as a returning, already-trusted device
    # instead of a brand-new one every single time (a major suspicion trigger).
    if device not in DEVICE_PRESETS:
        device = DEFAULT_DEVICE
    _device_preset = DEVICE_PRESETS[device]
    _profile_dir = _ftm_sub("profiles")
    # Key the saved "device memory" by account + device — reusing cookies
    # from a Windows profile on an Android UA (or vice-versa) is itself a
    # red flag, so each device preset gets its own persisted profile.
    _profile_key = hashlib.sha256(f"{email.strip().lower()}::{device}".encode()).hexdigest()[:24]
    profile_file = os.path.join(_profile_dir, f"{_profile_key}.json")

    # ── Human-readable translations of raw log codes ───────────────────────
    _LOG_LABELS = {
        "STEP1_EMAIL":        ("info",    "📧 Google login page khul raha hai..."),
        "AFTER_EMAIL":        ("ok",      "✅ Email submit ho gayi — aage badh raha hai"),
        "STEP2_PASSWORD":     ("info",    "🔑 Password enter ho raha hai..."),
        "AFTER_PWD":          ("ok",      "✅ Password submit ho gayi"),
        "EXTRACTING":         ("info",    "🍪 Drive cookies extract ho rahi hain..."),
        "LOGGED_IN!":         ("ok",      "🎉 Login successful — cookies collect ho rahi hain"),
        "WORKSPACE_LOGGED_IN":("ok",      "🎉 Workspace login successful"),
        "NUMBER_TIMEOUT":     ("warn",    "⏱️ Number match challenge timeout — try again"),
        "OTP_TIMEOUT":        ("warn",    "⏱️ OTP timeout — try again"),
        "BACKUP_TIMEOUT":     ("warn",    "⏱️ Backup code timeout"),
        "PHONE_TIMEOUT":      ("warn",    "⏱️ Phone entry timeout"),
        "MANUAL_TIMEOUT":     ("warn",    "⏱️ Manual challenge timeout"),
        "TOTP_TIMEOUT":       ("warn",    "⏱️ TOTP timeout"),
        "NEED_DEVICE_APPROVAL":("warn",   "📲 Phone pe Google notification aaya — Tap Yes!"),
        "ACCOUNT_LOCKED":      ("error",  "❌ Account disabled/locked/suspended — login possible nahi"),
        "ACCOUNT_REJECTED":    ("error",  "❌ Google ne login reject kiya — 'Couldn't sign you in' (real device pe pehle login karein)"),
        "SECURITY_KEY":        ("info",   "🔑 Security key prompt — dusra tarika dhundh raha hai"),
    }

    def _sess_update(**kw):
        with _sessions_lock:
            if sid in _autologin_sessions:
                _autologin_sessions[sid].update(kw)

    def _append_log(lvl: str, human_msg: str):
        ts = time.time()
        entry = {"ts": ts, "lvl": lvl, "msg": human_msg}
        with _sessions_lock:
            if sid in _autologin_sessions:
                logs = _autologin_sessions[sid].setdefault("logs", [])
                logs.append(entry)
                if len(logs) > 200:
                    _autologin_sessions[sid]["logs"] = logs[-200:]

    def log(raw: str):
        print(f"[AL:{sid[:8]}] {raw}", flush=True)
        _sess_update(raw_status=raw)
        try:
            with open(status_file, "w") as f:
                f.write(raw)
        except Exception:
            pass

        # Translate to human message
        raw_key = raw.split(":")[0] if ":" in raw else raw
        if raw_key in _LOG_LABELS:
            lvl, human = _LOG_LABELS[raw_key]
        elif raw.startswith("LOOP"):
            try:
                loop_n  = int(raw.split(":")[0].replace("LOOP",""))
                url_part = raw.split(":", 1)[1] if ":" in raw else ""
                short    = url_part.replace("https://","").split("?")[0][:60]
                human    = f"🔄 Loop {loop_n}: {short}"
                lvl      = "info"
            except Exception:
                human, lvl = raw, "info"
        elif raw.startswith("NEED_OTP:"):
            t = raw.split(":")[1]
            tmap = {
                "sms":              "SMS verification code",
                "email":            "Email verification code",
                "backup":           "Backup code",
                "totp":             "Authenticator OTP",
                "security_code":    "Security code (trusted device)",
                "phone_last_digits":"Phone number last digits",
                "recovery_email":   "Recovery email address",
            }
            human = f"⚠️ Challenge: {tmap.get(t, t)} chahiye!"
            lvl   = "warn"
        elif raw.startswith("NEED_PHONE"):
            human, lvl = "⚠️ Challenge: Phone number chahiye!", "warn"
        elif raw.startswith("NEED_NUMBER_MATCH"):
            nums = raw.split(":")[1] if ":" in raw else "?"
            human = f"⚠️ Challenge: Number match — options: {nums}"
            lvl   = "warn"
        elif raw.startswith("NEED_MANUAL"):
            t = raw.split(":")[1] if ":" in raw else "unknown"
            human = f"⚠️ Challenge: Manual action needed ({t})"
            lvl   = "warn"
        elif raw.startswith("NEED_CHOICE"):
            opts = raw.split(":", 1)[1] if ":" in raw else "?"
            human = f"⚠️ Google ne 'Try another way' options diye — chunein: {opts}"
            lvl   = "warn"
        elif raw.startswith("CHOICE_TIMEOUT"):
            human, lvl = "⏱️ Option select karne ka time khatam ho gaya", "warn"
        elif raw.startswith("TOTP_AUTO"):
            human, lvl = "🔐 TOTP code auto-generate ho gaya", "ok"
        elif raw.startswith("SUCCESS"):
            human, lvl = f"✅ {raw}", "ok"
        elif raw.startswith("PARTIAL"):
            human, lvl = f"⚠️ {raw} — kuch cookies missing", "warn"
        elif raw.startswith("PWD_ERR"):
            human, lvl = f"❌ Password error: {raw[8:]}", "error"
        else:
            human, lvl = raw, "info"

        _append_log(lvl, human)

    def wait_file(fpath, timeout=300):
        """Wait for a file to appear with content, pushing frames every 3s so SSE stays live."""
        for i in range(timeout):
            if os.path.exists(fpath):
                try:
                    with open(fpath) as f:
                        val = f.read().strip()
                    if val:
                        try:
                            os.remove(fpath)
                        except Exception:
                            pass
                        return val
                except Exception:
                    pass
            time.sleep(1)
            # Push a fresh frame every 3s so SSE stream stays alive during user input waits
            if i % 3 == 2:
                try:
                    _push_frame(pg)
                except Exception:
                    pass
            try:
                _drain_interact_queue(sid, pg, _autologin_sessions.get(sid, {}))
            except Exception:
                pass
        return None

    _frame_seq = [0]

    def _push_frame(pg):
        """Take a screenshot on the MAIN Playwright thread and push to SSE store."""
        try:
            data = pg.screenshot(full_page=False, type="jpeg", quality=55)
            _frame_seq[0] += 1
            with _live_frames_lock:
                _live_frames[sid] = {"data": data, "seq": _frame_seq[0]}
        except Exception:
            pass

    def _drain():
        """Drain any queued live-view interactions (clicks/keys/typing) sent
        via /api/autologin/interact. MUST only be called from this automation
        thread (the one that owns `pg`) — see `_drain_interact_queue` docstring."""
        try:
            _drain_interact_queue(sid, pg, _autologin_sessions.get(sid, {}))
        except Exception:
            pass

    def nw(pg, t=20000):
        """Wait for network-idle, taking a frame every ~400ms so SSE stream stays live."""
        deadline = time.time() + t / 1000
        while time.time() < deadline:
            remaining_ms = max(100, int((deadline - time.time()) * 1000))
            try:
                pg.wait_for_load_state("networkidle", timeout=min(400, remaining_ms))
                break   # page idle — exit wait
            except Exception:
                pass    # timeout hit → take frame and loop
            _push_frame(pg)
            _drain()
        _push_frame(pg)   # final frame after load settles
        _drain()
        time.sleep(0.3)

    def tick(secs):
        """Sleep for `secs` seconds while pushing frames every 400ms."""
        remaining = float(secs)
        while remaining > 0:
            wait = min(0.4, remaining)
            time.sleep(wait)
            remaining -= wait
            _drain()

    def screenshot(pg):
        """Legacy helper — now just calls _push_frame (also writes fallback file)."""
        _push_frame(pg)
        try:
            data = _live_frames.get(sid, {}).get("data")
            if data:
                with open(ss_file, "wb") as f:
                    f.write(data)
        except Exception:
            pass

    def extract_numbers(pg):
        """Extract 2-3 digit numbers from the number-match challenge page."""
        nums = []
        try:
            # Google uses various selectors; try multiple approaches
            for sel in [
                'li[data-challengeindex]',
                '[jsname="EKvSSd"] li',
                '.zHKKxf li',
                '[data-number]',
                'li.ZFr60d',
            ]:
                els = pg.query_selector_all(sel)
                for el in els:
                    try:
                        txt = el.inner_text().strip()
                        if txt.isdigit() and 1 <= len(txt) <= 3:
                            nums.append(txt)
                    except Exception:
                        pass
                if nums:
                    break

            if not nums:
                # Fallback: scan all visible text nodes for 2-digit isolated numbers
                raw = pg.inner_text("body")
                import re as _re
                found = _re.findall(r'(?<!\d)(\d{2})(?!\d)', raw)
                # keep up to 3 distinct numbers that look like options
                seen = []
                for n in found:
                    if n not in seen:
                        seen.append(n)
                    if len(seen) == 3:
                        break
                nums = seen
        except Exception as e:
            log(f"extract_numbers error: {e}")
        return nums

    def extract_choice_options(pg):
        """Extract the list of alternate-verification options shown after
        clicking 'Try another way' (e.g. 'Get a verification code at ***1234',
        'Enter your password', 'Confirm your recovery email address')."""
        opts = []
        try:
            for sel in [
                'li[data-challengetype]',
                'ul[jsname] li',
                '[role="link"]',
                'li',
            ]:
                for el in pg.query_selector_all(sel):
                    try:
                        if not el.is_visible():
                            continue
                        txt = " ".join(el.inner_text().strip().split())
                        if txt and 3 <= len(txt) <= 90 and txt not in opts:
                            opts.append(txt)
                    except Exception:
                        pass
                if opts:
                    break
        except Exception as e:
            log(f"extract_choice_options error: {e}")
        return opts[:8]

    try:
        from playwright.sync_api import sync_playwright
        import pyotp as _pyotp
    except ImportError as e:
        _sess_update(status="error", message=f"Import error: {e}")
        return

    import glob as _glob

    # ── Patch LD_LIBRARY_PATH so Chromium can find libnspr4/libnss3 on NixOS ──
    # System Chromium has libs in its own rpath — no nix store scanning needed.
    # Only inherit REPLIT_LD_LIBRARY_PATH (mesa/vulkan etc) if set.
    _replit_ld = os.environ.get("REPLIT_LD_LIBRARY_PATH", "")
    if _replit_ld and _replit_ld not in os.environ.get("LD_LIBRARY_PATH", ""):
        os.environ["LD_LIBRARY_PATH"] = _replit_ld + ":" + os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH"].strip(":")

    # ── Find best Chromium: Windows official Chrome + Linux paths ──
    def _find_best_chromium():
        candidates = [
            # Windows official Chrome & Edge
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            # NixOS system chromium — self-contained, all libs in rpath (newest first)
            "/nix/store/qa9cnw4v5xkxyip6mb9kxqfq1z4x2dx1-chromium-138.0.7204.100/bin/chromium",
            "/nix/store/khk7xpgsm5insk81azy9d560yq4npf77-chromium-131.0.6778.204/bin/chromium",
            "/nix/store/zi4f80l169xlmivz8vja8wlphq74qqk0-chromium-125.0.6422.141/bin/chromium",
            "/nix/store/gasnw5878924jbw6bql257ll29hkm4fd-chromium-123.0.6312.105/bin/chromium",
            # Standard system paths
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            # Playwright workspace cache (needs LD_LIBRARY_PATH, last resort)
            "/home/runner/workspace/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome",
        ]
        # Also check any workspace playwright cache dynamically (fast — limited scope)
        candidates += _glob.glob("/home/runner/workspace/.cache/ms-playwright/chromium*/chrome-linux64/chrome")
        for p in candidates:
            if os.path.isfile(p) and (os.name == "nt" or os.access(p, os.X_OK)):
                return p
        return None

    chromium = _find_best_chromium()
    log(f"Chromium: {chromium or 'NOT FOUND — playwright default'}")

    is_windows = os.name == "nt"
    launch_kwargs = dict(
        headless=False if is_windows else True,
        ignore_default_args=["--enable-automation"],
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
              "--disable-blink-features=AutomationControlled",
              "--lang=en-IN,en"],
    )
    if chromium:
        launch_kwargs["executable_path"] = chromium

    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(**launch_kwargs)

            # Build a User-Agent string that actually matches the bundled
            # Chromium version — a mismatched UA (e.g. claiming Chrome/124 while
            # really running 138) is one of the biggest automated-login red
            # flags for Google's risk engine.
            try:
                _real_ver = br.version  # e.g. "138.0.7204.100"
            except Exception:
                _real_ver = "124.0.0.0"
            # Build the UA string from the chosen device preset, but keep the
            # Chrome version in sync with the real bundled Chromium — a
            # mismatched UA version is one of the biggest automated-login red
            # flags for Google's risk engine. Safari-only presets don't carry
            # a Chrome version so they're used as-is.
            _ua = _device_preset["ua_template"].format(ver=_real_ver) \
                if "{ver}" in _device_preset["ua_template"] else _device_preset["ua_template"]
            _vp = _device_preset["viewport"]

            # Reuse the same "device" (cookies/localStorage) across logins for
            # this account so Google recognizes it as a returning device
            # instead of flagging a brand-new one on every single attempt.
            _ctx_kwargs = dict(
                user_agent=_ua,
                viewport=_vp,
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                device_scale_factor=_device_preset["device_scale_factor"],
                is_mobile=_device_preset["is_mobile"],
                has_touch=_device_preset["has_touch"],
            )
            if os.path.exists(profile_file):
                try:
                    _ctx_kwargs["storage_state"] = profile_file
                    log("DEVICE_MEMORY: purana device profile reuse ho raha hai")
                except Exception:
                    pass
            ctx = br.new_context(**_ctx_kwargs)
            pg = ctx.new_page()
            try:
                from playwright_stealth.stealth import Stealth
                Stealth().apply_stealth_sync(pg)
            except Exception as _st_err:
                print(f"[STEALTH] Stealth apply warning: {_st_err}", flush=True)
            # Expose page object so /api/autologin/interact can forward clicks/keys
            _sess_update(_page=pg, _page_vp=(_vp["width"], _vp["height"]))

            # ── Stealth patches — hide the usual automated-browser fingerprints ──
            pg.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-IN', 'en-US', 'en']});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                window.chrome = window.chrome || { runtime: {} };
                const origQuery = window.navigator.permissions && window.navigator.permissions.query;
                if (origQuery) {
                    window.navigator.permissions.query = (params) => (
                        params && params.name === 'notifications'
                            ? Promise.resolve({ state: Notification.permission })
                            : origQuery(params)
                    );
                }
            """)

            # ── Step 1: Email ──────────────────────────────────────────────
            log("STEP1_EMAIL")
            _sess_update(status="running", message="📧 Email verify ho raha hai...")
            pg.goto("https://accounts.google.com/signin/v2/identifier?service=wise&continue=https://drive.google.com", timeout=40000)
            nw(pg)

            # ── Case A: saved session already landed us on Drive ──────────
            # Also check if a redirect happened DURING nw() but pg.url didn't
            # update in time — re-check after a short wait.
            _cur_url_after_nw = pg.url
            if "accounts.google.com" in _cur_url_after_nw and "drive.google" not in _cur_url_after_nw:
                # Could be mid-redirect — give it 3 more seconds
                try:
                    pg.wait_for_url("**/drive.google.com/**", timeout=3000)
                except Exception:
                    pass
            if "drive.google.com" in pg.url and "accounts" not in pg.url:
                log("ALREADY_LOGGED_IN: Profile me session detect hua — account verify ho raha hai...")
                _sess_update(status="running", message="🔍 Logged-in account verify ho raha hai...")

                # Stabilise on Drive
                try:
                    pg.goto("https://drive.google.com", timeout=30000)
                    nw(pg)
                except Exception:
                    pass

                # ── Email verification ──────────────────────────────────────
                # If the saved profile holds a DIFFERENT account (e.g. user
                # has multiple Google accounts), we must not silently extract
                # the wrong cookies — logout, clear profile, and fall through
                # to a fresh email+password flow instead.
                _email_lower = email.strip().lower()
                _email_in_page = False          # fail-closed: only True on confirmed match
                _eval_err = None
                try:
                    _email_in_page = pg.evaluate(f"""() => {{
                        const check = {repr(_email_lower)};
                        // aria-label attributes on header/account-switcher buttons
                        for (const el of document.querySelectorAll('[aria-label]'))
                            if (el.getAttribute('aria-label').toLowerCase().includes(check)) return true;
                        // data-email attributes (account tiles, Drive header)
                        for (const el of document.querySelectorAll('[data-email]'))
                            if (el.getAttribute('data-email').toLowerCase() === check) return true;
                        // href that contains the email (some Google pages)
                        for (const a of document.querySelectorAll('a[href]'))
                            if (a.href.toLowerCase().includes(check)) return true;
                        // Plain text fallback
                        return document.body.innerText.toLowerCase().includes(check);
                    }}""")
                except Exception as _ev_exc:
                    _eval_err = str(_ev_exc)
                    log(f"EMAIL_VERIFY_ERR: JS eval fail — {_eval_err[:120]}; fresh login karenge")
                    # Treat as mismatch: force fresh login rather than
                    # silently extracting cookies for an unverified account.

                if _email_in_page:
                    log("ALREADY_LOGGED_IN: Email verified — cookies extract ho rahi hain")
                    _sess_update(status="running", message="✅ Session valid hai — cookies extract ho rahi hain...")
                    log("EXTRACTING")
                    _sess_update(status="running", message="🍪 Drive cookies extract ho rahi hain...")
                    all_cookies = ctx.cookies([
                        "https://drive.google.com",
                        "https://google.com",
                        "https://accounts.google.com",
                    ])
                    result_data = {
                        "url": "https://drive.google.com",
                        "cookies": [{"name": c["name"], "value": c["value"]} for c in all_cookies],
                    }
                    try:
                        ctx.storage_state(path=profile_file)
                    except Exception as e:
                        log(f"PROFILE_SAVE_ERR: {e}")
                    br.close()
                    with open(result_file, "w") as f:
                        import json as _json2
                        _json2.dump(result_data, f)
                    names = [c["name"] for c in result_data["cookies"]]
                    has_auth = any(n in names for n in ["SID", "SAPISID", "__Secure-1PSID", "HSID", "__Secure-3PSID"])
                    if not has_auth:
                        # Stale/expired session — delete profile so next attempt is fresh
                        log("ALREADY_LOGGED_IN: Auth cookies missing — profile clear kar raha hai")
                        try:
                            if os.path.exists(profile_file):
                                os.remove(profile_file)
                        except Exception:
                            pass
                    log(f"{'SUCCESS' if has_auth else 'PARTIAL'}: {len(names)} cookies")
                    _finalize_autologin(sid, uid, result_file)
                    return
                else:
                    # Wrong account in profile — logout + clear profile + fresh login
                    log(f"ALREADY_LOGGED_IN: Alag account detect hua (expected {_email_lower}) — logout + fresh login")
                    _sess_update(status="running", message="⚠️ Profile mein alag account tha — logout ho raha hai...")
                    try:
                        if os.path.exists(profile_file):
                            os.remove(profile_file)
                    except Exception:
                        pass
                    try:
                        pg.goto("https://accounts.google.com/Logout", timeout=15000)
                        nw(pg, 8000)
                    except Exception:
                        pass
                    # Re-navigate to fresh email identifier — fall through below
                    try:
                        pg.goto("https://accounts.google.com/signin/v2/identifier?service=wise&continue=https://drive.google.com", timeout=40000)
                        nw(pg)
                    except Exception:
                        pass
                    log("FRESH_LOGIN_AFTER_MISMATCH: Fresh signin page pe aa gaye")

            # ── Case B: account chooser page (stored cookies → Google shows
            # an account picker instead of the email field) ────────────────
            _cur_url = pg.url
            _body_text = pg.inner_text("body").lower()
            _account_chooser = (
                "accountchooser" in _cur_url
                or "signinchooser" in _cur_url
                or "choose an account" in _body_text
                or "select an account" in _body_text
                or "use another account" in _body_text
            )
            if _account_chooser:
                log("ACCOUNT_CHOOSER: Account picker detect hua — target email click karte hain")
                _clicked_account = False
                # Try clicking the tile that matches our email
                for _tile_sel in [
                    f'[data-email="{email}"]',
                    f'[data-identifier="{email}"]',
                    f'li:has-text("{email}")',
                    f'div[role="link"]:has-text("{email}")',
                ]:
                    try:
                        pg.locator(_tile_sel).first.click(timeout=5000)
                        _clicked_account = True
                        break
                    except Exception:
                        pass
                if not _clicked_account:
                    # Try "Use another account" link → brings us back to email input
                    for _txt in ["Use another account", "Add account", "Sign in with a different account"]:
                        try:
                            pg.get_by_text(_txt, exact=False).first.click(timeout=5000)
                            _clicked_account = True
                            break
                        except Exception:
                            pass
                nw(pg, 15000)
                log(f"AFTER_CHOOSER: {pg.url[:80]}")

            # ── Try to find email input (normal path or after account chooser) ──
            _email_sel = None
            for _sel in ['#identifierId', 'input[type="email"]', '[name="identifier"]', 'input[autocomplete="username"]']:
                try:
                    pg.wait_for_selector(_sel, state="visible", timeout=8000)
                    _email_sel = _sel
                    break
                except Exception:
                    pass

            if _email_sel is None:
                # Last resort: clear the stored profile (stale/corrupted) and
                # reload with a fresh context. Stale Google cookies trigger
                # account choosers and other redirects that break the flow.
                log("EMAIL_INPUT_NOT_FOUND: Profile clear karke fresh retry...")
                try:
                    if os.path.exists(profile_file):
                        os.remove(profile_file)
                except Exception:
                    pass
                pg.goto("https://accounts.google.com/ServiceLogin?service=wise&continue=https://drive.google.com&hl=en", timeout=40000)
                nw(pg)
                for _sel in ['#identifierId', 'input[type="email"]', '[name="identifier"]']:
                    try:
                        pg.wait_for_selector(_sel, state="visible", timeout=10000)
                        _email_sel = _sel
                        break
                    except Exception:
                        pass

            if _email_sel:
                pg.locator(_email_sel).first.fill(email)
                # Click Next/identifierNext explicitly
                _id_clicked = False
                for _btn in ['#identifierNext', 'button[jsname="LgbsSe"]', 'button[type="submit"]']:
                    try:
                        b = pg.locator(_btn).first
                        b.wait_for(state="visible", timeout=3000)
                        b.click()
                        _id_clicked = True
                        break
                    except Exception:
                        pass
                if not _id_clicked:
                    pg.keyboard.press("Enter")
            else:
                log("EMAIL_INPUT_NOT_FOUND: Koi bhi email selector nahi mila")
                _sess_update(status="error", message="❌ Google login page load nahi hua — dobara try karein")
                br.close()
                return
            nw(pg, 25000)
            log("AFTER_EMAIL")

            # ── Step 2: Password ───────────────────────────────────────────
            log("STEP2_PASSWORD")
            _sess_update(status="running", message="🔑 Password check ho raha hai...")

            # Helper: check if current URL/body looks like a challenge Google
            # already sent us to (Safari UA often skips the standard password
            # page and lands directly on a challenge or 2FA screen).
            # IMPORTANT: must NOT match the email identifier page itself —
            # that page's body can contain "get a verification code" in help
            # text, causing false positives that skip the password step.
            def _already_in_challenge():
                _c = pg.url.lower()
                # Never treat the identifier/email-input page as a challenge
                if "signin/identifier" in _c or "serviclogin" in _c:
                    return False
                # URL-based evidence is the most reliable signal
                if any(x in _c for x in ["challenge/", "drive.google.com", "workspace.google.com"]):
                    return True
                # Body-based only when we are clearly NOT on an account/sign-in
                # landing page (e.g. we are on accounts.google.com but past email)
                if "accounts.google.com" in _c and "signin" in _c:
                    _b = pg.inner_text("body").lower()
                    return any(x in _b for x in [
                        "verify it's you", "check your phone", "authenticator",
                        "choose how you want to sign", "match the number",
                        "confirm your recovery",
                    ])
                return False

            _skip_pwd = False
            _pwd_attempts = 0   # always initialise — referenced later in challenge loop
            if _already_in_challenge():
                log("PWD_SKIP: Already on challenge/drive page — skipping password step")
                _sess_update(status="running", message="🔄 Challenge page detect hua — password step skip...")
                _skip_pwd = True

            # ── Robust password-fill helper ──────────────────────────────────
            # Uses pg.locator() which re-queries the DOM on every call — immune
            # to "Element is not attached to the DOM" that happens when Google
            # re-renders the page between the element-find and the click.
            # Returns True when the field was found, filled, and submit clicked.
            def _do_fill_password(pwd_value):
                _pwd_selectors = [
                    'input[type="password"]',
                    'input[autocomplete="current-password"]',
                    'input[name="Passwd"]',
                    'input[jsname="YPqjbf"]',
                ]
                _submit_selectors = [
                    '#passwordNext',
                    'button[jsname="LgbsSe"]',
                    'button[type="submit"]',
                    '[data-primary-action-label]',
                ]
                for _psel in _pwd_selectors:
                    try:
                        loc = pg.locator(_psel).first
                        loc.wait_for(state="visible", timeout=5000)
                        # Focus by clicking the locator (re-queries DOM each time)
                        loc.click()
                        time.sleep(0.3)
                        loc.press("Control+a")
                        time.sleep(0.15)
                        loc.press("Delete")
                        time.sleep(0.15)
                        loc.fill(pwd_value)
                        time.sleep(0.4)
                        # Verify fill actually landed before submitting
                        actual = loc.input_value()
                        if actual != pwd_value:
                            log(f"PWD_FILL_MISMATCH: selector={_psel} got '{actual[:4]}...' expected '{pwd_value[:4]}...'")
                            continue
                        # Click Next explicitly; fall back to Enter
                        _submitted = False
                        for _ssel in _submit_selectors:
                            try:
                                _btn = pg.locator(_ssel).first
                                _btn.wait_for(state="visible", timeout=2500)
                                _btn.click()
                                _submitted = True
                                break
                            except Exception:
                                pass
                        if not _submitted:
                            pg.keyboard.press("Enter")
                        return True
                    except Exception as _fe:
                        log(f"PWD_FILL_TRY: selector={_psel} err={str(_fe)[:80]}")
                        continue
                return False

            if not _skip_pwd:
                try:
                    # Poll until a visible password field appears or we land on a
                    # challenge page (Google sometimes skips the standalone pwd page).
                    _deadline = time.time() + 25
                    _pwd_ready = False
                    while time.time() < _deadline:
                        if _already_in_challenge():
                            log("PWD_SKIP_MID: Challenge page mid-poll — skip password")
                            _skip_pwd = True
                            break
                        # Check any of our selectors has a visible element
                        for _psel in ['input[type="password"]', 'input[autocomplete="current-password"]',
                                      'input[name="Passwd"]', 'input[jsname="YPqjbf"]']:
                            try:
                                if pg.locator(_psel).first.is_visible():
                                    _pwd_ready = True
                                    break
                            except Exception:
                                pass
                        if _pwd_ready:
                            break
                        time.sleep(0.3)

                    if not _skip_pwd:
                        if not _pwd_ready:
                            screenshot(pg)
                            raise TimeoutError('input[type="password"] visible nahi hua 25s me')
                        _filled = _do_fill_password(password)
                        if not _filled:
                            screenshot(pg)
                            raise RuntimeError("Password fill karna fail hua — field nahi mila ya mismatch")
                        nw(pg, 28000)
                        log("AFTER_PWD")

                except Exception as e:
                    log(f"PWD_ERR: {e}")
                    screenshot(pg)
                    if _already_in_challenge():
                        log("PWD_SKIP_EX: Challenge page after error — continuing")
                        _skip_pwd = True
                    else:
                        _sess_update(status="error", message=f"❌ Password field load nahi hua: {e}")
                        br.close()
                        return

            if _skip_pwd:
                log("AFTER_PWD_SKIP")

            # ── Challenge loop ─────────────────────────────────────────────
            for loop in range(20):
                _drain()
                cur    = pg.url
                body   = pg.inner_text("body")
                body_l = body.lower()
                log(f"LOOP{loop}: {cur[:80]}")
                # Live screenshot at every loop iteration
                screenshot(pg)
                _sess_update(ss_ts=time.time())

                # ── SUCCESS ──────────────────────────────────────
                if "drive.google.com" in cur and "accounts" not in cur:
                    log("LOGGED_IN!")
                    _sess_update(status="running", message="✅ Login hua! Cookies extract ho rahi hain...")
                    break
                if "workspace.google.com" in cur and "products/drive" not in cur:
                    log("WORKSPACE_LOGGED_IN")
                    _sess_update(status="running", message="✅ Login hua! Cookies extract ho rahi hain...")
                    break

                # ── TRY ANOTHER WAY (checked FIRST, before any specific
                # challenge like phone/OTP) — many challenge screens (phone
                # entry, OTP, etc.) also show a "Try another way" escape
                # hatch. We must offer the user that choice up front instead
                # of railroading them into a path they may not be able to
                # complete (e.g. they don't have the phone Google wants).
                # IMPORTANT: skip this block when already on /challenge/totp
                # — that page also shows "Try another way" but we must enter
                # the OTP directly; clicking "Try another way" here loops us
                # back to selection → authenticator → totp endlessly.
                # challenge/ipp is also a TOTP variant (Google Authenticator
                # in-place prompt) — guard it too, but only when body confirms
                # it's an authenticator/6-digit context. ──
                cur_l = cur.lower()
                _on_totp_page = ("challenge/totp" in cur_l or
                                 ("challenge/ipp" in cur_l and
                                  ("authenticator" in body_l or "6-digit" in body_l or "enter the code" in body_l)))
                if not _on_totp_page and ("try another way" in body_l or ("verify it" in body_l and ("iap" in cur or "selection" in cur))):
                    try:
                        pg.locator('button, a').filter(has_text="Try another way").first.click(timeout=6000)
                    except Exception:
                        try:
                            pg.get_by_text("Try another way").click(timeout=6000)
                        except Exception:
                            pass
                    nw(pg)

                    # ── Re-check URL after clicking "Try another way" ──
                    # If the password was already accepted, Google may redirect
                    # straight to Drive instead of showing a 2FA selection page.
                    # In that case treat it as success and stop the loop now —
                    # otherwise extract_choice_options() would run on Drive's
                    # sidebar <li> elements and report "Home | My Drive | …"
                    # as if they were 2FA options.
                    _cur_after_taw = pg.url
                    if "drive.google.com" in _cur_after_taw and "accounts" not in _cur_after_taw:
                        log("LOGGED_IN!")
                        _sess_update(status="running", message="✅ Login hua! Cookies extract ho rahi hain...")
                        break
                    if "workspace.google.com" in _cur_after_taw and "products/drive" not in _cur_after_taw:
                        log("WORKSPACE_LOGGED_IN")
                        _sess_update(status="running", message="✅ Login hua! Cookies extract ho rahi hain...")
                        break

                    # Give the user a real choice instead of blindly picking
                    # whatever option Google shows first — UNLESS the user
                    # already gave us a TOTP secret, in which case "Google
                    # Authenticator" / "Get a verification code from the
                    # Google Authenticator app" is always the fastest, most
                    # reliable option we can complete ourselves — pick it
                    # automatically instead of waiting on the user.
                    # Guard: skip option extraction if we've already landed on a
                    # Google app surface (Drive, Workspace, etc.) — extracting
                    # <li> elements there returns sidebar nav items, not 2FA
                    # choices.  All other URLs (accounts.google.com, google.com/
                    # signin, workspace sign-in pages, etc.) are still valid
                    # challenge hosts and should proceed normally.
                    _taw_url = pg.url
                    _on_app_surface = (
                        ("drive.google.com" in _taw_url and "accounts" not in _taw_url) or
                        ("workspace.google.com" in _taw_url and "products/drive" not in _taw_url) or
                        ("mail.google.com" in _taw_url) or
                        ("docs.google.com" in _taw_url) or
                        ("calendar.google.com" in _taw_url)
                    )
                    options = [] if _on_app_surface else extract_choice_options(pg)
                    if options:
                        screenshot(pg)
                        picked = None
                        if totp_secret:
                            for opt in options:
                                _o = opt.lower()
                                if "authenticator" in _o or ("google" in _o and "app" in _o):
                                    picked = opt
                                    break
                            if picked:
                                log(f"AUTO_PICK_AUTHENTICATOR:{picked}")
                                _sess_update(status="running", message="🔐 Authenticator app option auto-select ho raha hai...")
                        if not picked:
                            try:
                                if os.path.exists(choice_file):
                                    os.remove(choice_file)
                            except Exception:
                                pass
                            log(f"NEED_CHOICE:{' | '.join(options)}")
                            with _sessions_lock:
                                _autologin_sessions[sid].update({
                                    "status": "need_choice",
                                    "choices": options,
                                    "message": "🔀 Google ne alternate verification options diye — ek chunein.",
                                })
                            picked = wait_file(choice_file, 300)
                        if not picked:
                            log("CHOICE_TIMEOUT")
                            break
                        _sess_update(status="running", message="🔀 Option select hua, aage badh rahe hain...")
                        clicked = False
                        try:
                            pg.get_by_text(picked, exact=False).first.click(timeout=6000)
                            clicked = True
                        except Exception:
                            pass
                        if not clicked:
                            # Fall back to matching by index among the same options
                            try:
                                idx = options.index(picked)
                                els = pg.query_selector_all('li[data-challengetype]') or pg.query_selector_all('li')
                                if idx < len(els):
                                    els[idx].click(timeout=6000)
                            except Exception:
                                pass
                        nw(pg)
                    continue

                # ── NUMBER MATCH challenge ────────────────────────
                if "match the number" in body_l or "tap the number" in body_l:
                    screenshot(pg)
                    nums = extract_numbers(pg)
                    log(f"NEED_NUMBER_MATCH:{','.join(nums)}")
                    _sess_update(
                        status="need_number_match",
                        message="🔢 Number match challenge — apne device pe dikhne wala number tap karein.",
                        numbers=nums,
                    )
                    chosen = wait_file(number_file, 300)
                    if not chosen:
                        log("NUMBER_TIMEOUT")
                        break
                    # Click the matching number button on the page
                    clicked = False
                    for sel in ['li[data-challengeindex]', '[jsname="EKvSSd"] li', '.zHKKxf li', 'li']:
                        for el in pg.query_selector_all(sel):
                            try:
                                if el.inner_text().strip() == chosen.strip() and el.is_visible():
                                    el.click()
                                    clicked = True
                                    break
                            except Exception:
                                pass
                        if clicked:
                            break
                    if not clicked:
                        # fallback: try keyboard
                        pg.keyboard.press(chosen)
                    nw(pg, 25000)
                    _sess_update(status="running", message="🔢 Number submit hua, verify ho raha hai...")
                    continue

                # ── SMS / EMAIL verification code ─────────────────
                if ("enter the code" in body_l
                        or ("enter a verification code" in body_l)
                        or ("verification code" in body_l and "verify it" in body_l
                            and "enter a phone" not in body_l and "choose how" not in body_l)):
                    screenshot(pg)
                    otp_type = "email" if "recovery email" in body_l or "alternate email" in body_l else "sms"
                    log(f"NEED_OTP:{otp_type}")
                    _sess_update(
                        status="need_otp",
                        message="📱 Verification code chahiye.",
                        otp_type=otp_type,
                        otp_file=otp_file,
                    )
                    code = wait_file(otp_file, 300)
                    if not code:
                        log("OTP_TIMEOUT")
                        break
                    try:
                        oi = pg.locator('input[type="tel"], input[type="text"]').first
                        oi.wait_for(state="visible", timeout=10000)
                        oi.fill(code)
                        pg.keyboard.press("Enter")
                    except Exception:
                        pg.keyboard.type(code)
                        pg.keyboard.press("Enter")
                    nw(pg, 25000)
                    _sess_update(status="running", message="✅ Code submit hua, verify ho raha hai...")
                    continue

                # ── BACKUP CODE ───────────────────────────────────
                if "backup code" in body_l or "enter a backup" in body_l:
                    screenshot(pg)
                    log("NEED_OTP:backup")
                    _sess_update(
                        status="need_otp",
                        message="🔑 Google backup code chahiye.",
                        otp_type="backup",
                        otp_file=otp_file,
                    )
                    code = wait_file(otp_file, 300)
                    if not code:
                        log("BACKUP_TIMEOUT")
                        break
                    try:
                        oi = pg.locator('input[type="tel"], input[type="text"]').first
                        oi.wait_for(state="visible", timeout=8000)
                        oi.fill(code)
                        pg.keyboard.press("Enter")
                    except Exception:
                        pg.keyboard.type(code)
                        pg.keyboard.press("Enter")
                    nw(pg, 25000)
                    _sess_update(status="running", message="✅ Backup code submit hua...")
                    continue

                # ── PHONE NUMBER entry ────────────────────────────
                if "enter a phone" in body_l or "enter your phone" in body_l:
                    screenshot(pg)
                    log("NEED_PHONE")
                    _sess_update(
                        status="need_phone",
                        message="📞 Google phone number maang raha hai.",
                        phone_file=phone_file,
                    )
                    phone_val = wait_file(phone_file, 300)
                    if not phone_val:
                        log("PHONE_TIMEOUT")
                        break
                    for inp in pg.query_selector_all('input[type="tel"]'):
                        if inp.is_visible() and inp.bounding_box():
                            inp.click()
                            time.sleep(0.5)
                            inp.press("Control+a")
                            inp.press("Delete")
                            time.sleep(0.3)
                            inp.fill(phone_val)
                            time.sleep(0.8)
                            break
                    try:
                        pg.locator('button:has-text("Next")').first.click(timeout=8000)
                    except Exception:
                        pg.keyboard.press("Enter")
                    nw(pg, 20000)
                    _sess_update(status="running", message="📞 Phone submit hua, SMS aane ka wait...")
                    continue

                # ── DEVICE APPROVAL (Tap Yes on phone) ───────────
                if ("a sign-in attempt" in body_l or "check your phone" in body_l
                        or "tap yes" in body_l or "google prompt" in body_l
                        or ("verify" in body_l and "your phone" in body_l and "notification" in body_l)):
                    screenshot(pg)
                    log("NEED_DEVICE_APPROVAL")
                    _sess_update(
                        status="need_device_approval",
                        message="📲 Apne phone pe Google ka notification aaya — 'Yes, it's me' tap karein.",
                    )
                    # Poll for up to 3 minutes — page will auto-advance when user taps Yes
                    for _ in range(90):
                        time.sleep(2)
                        try:
                            new_url = pg.url
                            new_body = pg.inner_text("body").lower()
                            if ("drive.google.com" in new_url and "accounts" not in new_url) or \
                               ("workspace.google.com" in new_url and "products/drive" not in new_url):
                                break
                            if "accounts.google.com" not in new_url and "google.com/signin" not in new_url:
                                break
                            # Check if challenge changed
                            if "a sign-in attempt" not in new_body and "check your phone" not in new_body:
                                break
                        except Exception:
                            break
                    nw(pg, 10000)
                    _sess_update(status="running", message="✅ Device approval done, continue...")
                    continue

                # ── TOTP / AUTHENTICATOR ──────────────────────────
                if "totp" in cur or "authenticator" in body_l or ("enter the 6-digit" in body_l and "authenticator" in body_l):
                    if totp_secret:
                        try:
                            otp_val = _pyotp.TOTP(totp_secret.replace(" ", "").upper()).now()
                            log(f"TOTP_AUTO: {otp_val}")
                            _sess_update(status="running", message="🔐 Authenticator OTP auto-generate ho raha hai...")
                        except Exception:
                            otp_val = None
                    else:
                        otp_val = None

                    if not otp_val:
                        screenshot(pg)
                        log("NEED_OTP:totp")
                        _sess_update(
                            status="need_otp",
                            message="🔐 Authenticator app ka 6-digit code chahiye.",
                            otp_type="totp",
                            otp_file=otp_file,
                        )
                        otp_val = wait_file(otp_file, 180)
                        if not otp_val:
                            log("TOTP_TIMEOUT")
                            break

                    url_before = pg.url
                    # Clear + fill the OTP input
                    try:
                        inp = pg.locator('input[type="tel"]').first
                        inp.click(timeout=5000)
                        inp.press("Control+a")
                        inp.fill("")
                        time.sleep(0.2)
                        inp.fill(otp_val)
                    except Exception:
                        try:
                            pg.keyboard.press("Control+a")
                            pg.keyboard.type(otp_val)
                        except Exception:
                            pass
                    # Try clicking Next/Verify button, fallback to Enter
                    clicked_btn = False
                    for btn_txt in ["Next", "Verify", "Continue", "Submit"]:
                        try:
                            pg.get_by_role("button", name=btn_txt).first.click(timeout=3000)
                            clicked_btn = True
                            break
                        except Exception:
                            pass
                    if not clicked_btn:
                        pg.keyboard.press("Enter")
                    _sess_update(status="running", message="🔐 TOTP submit hua, verify ho raha hai...")
                    # Actively poll for URL change (up to 25s) + push frames while waiting
                    for _w in range(50):
                        time.sleep(0.5)
                        _push_frame(pg)
                        if pg.url != url_before:
                            break
                    nw(pg, 5000)
                    continue

                # ── SELECTION PAGE (choose method) ────────────────
                if "choose how" in body_l or "how you want to sign" in body_l or "select a verification" in body_l:
                    # Prefer SMS/phone over others
                    clicked = False
                    for txt in ["Get a text message", "Text message", "SMS", "Phone"]:
                        try:
                            pg.get_by_text(txt, exact=False).first.click(timeout=5000)
                            clicked = True
                            break
                        except Exception:
                            pass
                    if not clicked:
                        try:
                            pg.locator('[data-challengetype]').first.click(timeout=5000)
                        except Exception:
                            pass
                    nw(pg)
                    continue

                # ── SECURITY CODE (from trusted device / Google app) ──
                if ("security code" in body_l or "enter your security" in body_l
                        or ("enter a code" in body_l and "trusted" in body_l)):
                    screenshot(pg)
                    log("NEED_OTP:security_code")
                    _sess_update(
                        status="need_otp",
                        message="🔐 Security code chahiye — apne trusted Google device ya Google app pe dekho.",
                        otp_type="security_code",
                        otp_file=otp_file,
                    )
                    code = wait_file(otp_file, 300)
                    if not code:
                        log("OTP_TIMEOUT")
                        break
                    try:
                        oi = pg.locator('input[type="tel"], input[type="text"], input[type="number"]').first
                        oi.wait_for(state="visible", timeout=10000)
                        oi.fill(code)
                        pg.keyboard.press("Enter")
                    except Exception:
                        pg.keyboard.type(code)
                        pg.keyboard.press("Enter")
                    nw(pg, 25000)
                    _sess_update(status="running", message="✅ Security code submit hua...")
                    continue

                # ── CONFIRM PHONE LAST DIGITS ─────────────────────────
                if (("last" in body_l and "digits" in body_l) or
                        ("ending in" in body_l and "phone" in body_l) or
                        ("confirm your phone" in body_l)):
                    screenshot(pg)
                    log("NEED_OTP:phone_last_digits")
                    _sess_update(
                        status="need_otp",
                        message="📱 Apne phone number ke last digits enter karein (jaise page pe dikh raha hai).",
                        otp_type="phone_last_digits",
                        otp_file=otp_file,
                    )
                    code = wait_file(otp_file, 300)
                    if not code:
                        log("OTP_TIMEOUT")
                        break
                    try:
                        oi = pg.locator('input[type="tel"], input[type="text"], input[type="number"]').first
                        oi.wait_for(state="visible", timeout=10000)
                        oi.fill(code)
                        pg.keyboard.press("Enter")
                    except Exception:
                        pg.keyboard.type(code)
                        pg.keyboard.press("Enter")
                    nw(pg, 25000)
                    _sess_update(status="running", message="✅ Phone digits submit hua...")
                    continue

                # ── CONFIRM RECOVERY EMAIL ADDRESS ────────────────────
                if (("recovery email" in body_l and "enter" in body_l) or
                        ("alternate email" in body_l and "enter" in body_l) or
                        ("verify your email" in body_l and "@" not in (pg.url))):
                    screenshot(pg)
                    log("NEED_OTP:recovery_email")
                    _sess_update(
                        status="need_otp",
                        message="📧 Google apna recovery email address maang raha hai — poora email type karein.",
                        otp_type="recovery_email",
                        otp_file=otp_file,
                    )
                    code = wait_file(otp_file, 300)
                    if not code:
                        log("OTP_TIMEOUT")
                        break
                    try:
                        oi = pg.locator('input[type="email"], input[type="text"]').first
                        oi.wait_for(state="visible", timeout=10000)
                        oi.fill(code)
                        pg.keyboard.press("Enter")
                    except Exception:
                        pg.keyboard.type(code)
                        pg.keyboard.press("Enter")
                    nw(pg, 25000)
                    _sess_update(status="running", message="✅ Recovery email submit hua...")
                    continue

                # ── EMAIL LINK SENT (check inbox) ─────────────────────
                if (("check your email" in body_l or "check your gmail" in body_l)
                        and ("link" in body_l or "sent" in body_l or "click" in body_l)):
                    screenshot(pg)
                    log("NEED_MANUAL:email_link")
                    _sess_update(
                        status="need_manual",
                        message="📧 Google ne recovery email pe ek link bheja hai — email kholein, link click karein, phir yahan 'done' type karein.",
                    )
                    wait_file(manual_file, 600)
                    nw(pg, 15000)
                    _sess_update(status="running", message="✅ Email link action complete, continue...")
                    continue

                # ── SECURITY KEY prompt ───────────────────────────────
                if "security key" in body_l or "use your security key" in body_l or "insert your security key" in body_l:
                    log("SECURITY_KEY: Try another way dhundh raha hai...")
                    _append_log("info", "🔑 Security key prompt — dusra tarika dhundh raha hai...")
                    _clicked = False
                    for _txt in ["Try another way", "Use another method", "More options", "Choose another"]:
                        try:
                            pg.get_by_text(_txt, exact=False).first.click(timeout=5000)
                            _clicked = True
                            break
                        except Exception:
                            pass
                    if not _clicked:
                        screenshot(pg)
                        log("NEED_MANUAL:security_key")
                        _sess_update(
                            status="need_manual",
                            message="🔑 Security key maanga ja raha hai. 'skip' type karo dusra tarika try karne ke liye.",
                        )
                        wait_file(manual_file, 120)
                    nw(pg)
                    continue

                # ── CAN'T ACCESS / LOST ACCESS ────────────────────────
                if ("can't get" in body_l or "don't have access" in body_l
                        or "lost access" in body_l or "can't receive" in body_l
                        or "no longer have" in body_l):
                    for _txt in ["Try another way", "Use another method", "More options", "Use another account"]:
                        try:
                            pg.get_by_text(_txt, exact=False).first.click(timeout=5000)
                            break
                        except Exception:
                            pass
                    nw(pg)
                    continue

                # ── TERMS OF SERVICE / AGREE ──────────────────────────
                if (("terms of service" in body_l or "terms of use" in body_l)
                        and ("agree" in body_l or "accept" in body_l)):
                    for _txt in ["I agree", "Accept", "Agree", "Continue"]:
                        try:
                            pg.get_by_text(_txt, exact=False).first.click(timeout=5000)
                            break
                        except Exception:
                            pass
                    nw(pg)
                    continue

                # ── ACCOUNT LOCKED / SUSPENDED ────────────────────────
                if ("account has been" in body_l and
                        ("disabled" in body_l or "locked" in body_l or "suspended" in body_l)):
                    screenshot(pg)
                    log("ACCOUNT_LOCKED")
                    _sess_update(status="error", message="❌ Google account locked/disabled/suspended hai. Login possible nahi.")
                    break

                # ── HARD REJECTED: "Couldn't sign you in" ─────────────
                # Google's /signin/rejected page — not a solvable challenge.
                # Triggers when Google detects automated login or the account
                # hasn't been used/verified on a real device recently.
                _rejected = (
                    "signin/rejected" in cur
                    or "couldn't sign you in" in body_l
                    or ("google couldn't verify" in body_l and "belongs to you" in body_l)
                )
                if _rejected:
                    screenshot(pg)
                    log("ACCOUNT_REJECTED")
                    _append_log("error", "❌ Google ne login reject kar diya — 'Couldn't sign you in'")
                    _append_log("warn",  "💡 Wajah: Google ne is account ki automated login block ki. Ye tab hota hai jab account naya ho, ya kaafi time se real device pe use na hua ho.")
                    _append_log("warn",  "✅ Kya karein: Pehle apne phone ya PC pe is Gmail account se manually login karein, phir yahan dobara try karein.")
                    _sess_update(
                        status="error",
                        message="❌ Google ne login reject kar diya — pehle real device pe manually login karein, phir bot se try karein.",
                    )
                    break

                # ── ACCOUNT RECOVERY / IDENTITY VERIFICATION ──────────
                if ("verify your identity" in body_l or "account recovery" in body_l
                        or "couldn't verify" in body_l or "more details needed" in body_l
                        or "suspicious activity" in body_l or "suspicious sign-in" in body_l
                        or ("recover your account" in body_l)):
                    screenshot(pg)
                    log("NEED_MANUAL:identity_verify")
                    _sess_update(
                        status="need_manual",
                        message="🔒 Google identity verify maang raha hai — screenshot dekho. Koi code ya info type karo, ya 'skip' likhkar aage badho.",
                    )
                    user_input = wait_file(manual_file, 300)
                    if not user_input:
                        log("MANUAL_TIMEOUT")
                        break
                    if user_input.lower() in ("skip", "next", "continue", "done"):
                        for _btn in ["Skip", "Not now", "No thanks", "Continue", "Next", "Done", "Try another way"]:
                            try:
                                pg.get_by_text(_btn, exact=False).first.click(timeout=3000)
                                break
                            except Exception:
                                pass
                    else:
                        for _sel in ['input[type="text"]', 'input[type="tel"]', 'input[type="email"]']:
                            try:
                                _inp = pg.locator(_sel).first
                                _inp.wait_for(state="visible", timeout=3000)
                                _inp.fill(user_input)
                                pg.keyboard.press("Enter")
                                break
                            except Exception:
                                pass
                    nw(pg, 20000)
                    _sess_update(status="running", message="✅ Identity action submit hua...")
                    continue

                # ── PASSWORD again ────────────────────────────────
                if "challenge/pwd" in cur or ("enter your password" in body_l and 'input[type="password"]' in pg.content()):
                    _pwd_attempts += 1

                    if _pwd_attempts > 3:
                        # Stuck on pwd challenge — take screenshot and show as manual
                        screenshot(pg)
                        log("NEED_MANUAL:stuck_on_pwd")
                        _append_log("warn", f"⚠️ Password challenge pe {_pwd_attempts} baar stuck — screenshot dekho")
                        _sess_update(
                            status="need_manual",
                            message=f"⚠️ Password {_pwd_attempts} baar try kiya — Google kuch aur maang raha hai. Screenshot dekho.",
                        )
                        user_input = wait_file(manual_file, 300)
                        if not user_input:
                            log("MANUAL_TIMEOUT")
                            break
                        nw(pg, 15000)
                        _pwd_attempts = 0
                        continue

                    # Use the same locator-based helper (immune to DOM detachment)
                    _filled = _do_fill_password(password)
                    if not _filled:
                        log(f"PWD_FILL_FAIL: attempt {_pwd_attempts} — visible field nahi mila")
                        screenshot(pg)

                    _append_log("info", f"🔑 Password submitted (attempt {_pwd_attempts})...")
                    nw(pg, 28000)
                    _sess_update(status="running", message=f"🔑 Password submit hua (try {_pwd_attempts})...")
                    continue

                # ── SECURITY QUESTION ─────────────────────────────
                if "security question" in body_l or "answer the security" in body_l:
                    screenshot(pg)
                    log("NEED_MANUAL:security_question")
                    _sess_update(
                        status="need_manual",
                        message="🔒 Security question ka jawab chahiye.",
                    )
                    answer = wait_file(manual_file, 300)
                    if not answer:
                        log("MANUAL_TIMEOUT")
                        break
                    try:
                        inp = pg.locator('input[type="text"]').first
                        inp.fill(answer)
                        pg.keyboard.press("Enter")
                    except Exception:
                        pass
                    nw(pg, 20000)
                    _sess_update(status="running", message="✅ Jawab submit hua...")
                    continue

                # ── POST-LOGIN PROMPTS (profile pic, storage, etc.) ──────
                if ("add a profile picture" in body_l or "add profile picture" in body_l
                        or "skip for now" in body_l or "not now" in body_l
                        or "get more storage" in body_l or "pgc" in cur):
                    log("SKIP_POSTLOGIN")
                    _append_log("ok", "✅ Post-login prompt skip ho raha hai...")
                    for skip_txt in ["Skip", "Not now", "No thanks", "Skip for now"]:
                        try:
                            pg.get_by_text(skip_txt, exact=False).first.click(timeout=4000)
                            break
                        except Exception:
                            pass
                    nw(pg, 10000)
                    continue

                # ── CAPTCHA ───────────────────────────────────────
                if "captcha" in body_l or "recaptcha" in body_l or "i'm not a robot" in body_l:
                    screenshot(pg)
                    log("NEED_MANUAL:captcha")
                    _sess_update(
                        status="need_manual",
                        message="🤖 CAPTCHA solve karna hai — screenshot dekho.",
                    )
                    answer = wait_file(manual_file, 300)
                    if not answer:
                        log("CAPTCHA_TIMEOUT")
                        break
                    try:
                        inp = pg.locator('input[type="text"]').first
                        inp.fill(answer)
                        pg.keyboard.press("Enter")
                    except Exception:
                        pass
                    nw(pg, 20000)
                    continue

                # ── UNKNOWN CHALLENGE — take screenshot ───────────
                if loop >= 2:
                    screenshot(pg)
                    log(f"NEED_MANUAL:unknown")
                    _sess_update(
                        status="need_manual",
                        message="⚠️ Unknown challenge — screenshot dekh kar action karein.",
                    )
                    user_input = wait_file(manual_file, 300)
                    if not user_input:
                        log("MANUAL_TIMEOUT")
                        break
                    # Special commands
                    if user_input.startswith("goto:"):
                        dest = user_input[5:].strip()
                        url_map = {"drive": "https://drive.google.com", "gmail": "https://mail.google.com"}
                        dest_url = url_map.get(dest, dest if dest.startswith("http") else "https://drive.google.com")
                        try:
                            pg.goto(dest_url, timeout=20000)
                            nw(pg, 15000)
                        except Exception:
                            pass
                    elif user_input.lower() in ("skip", "next", "continue"):
                        # Try to click Skip/Next/Continue buttons
                        for btn_txt in ["Skip", "Not now", "No thanks", "Continue", "Next", "Done"]:
                            try:
                                pg.get_by_text(btn_txt, exact=False).first.click(timeout=3000)
                                break
                            except Exception:
                                pass
                        nw(pg, 12000)
                    else:
                        # Try to find input and type
                        try:
                            for sel in ['input[type="text"]', 'input[type="tel"]', 'input[type="number"]', 'textarea']:
                                inp = pg.locator(sel).first
                                try:
                                    inp.wait_for(state="visible", timeout=3000)
                                    inp.fill(user_input)
                                    pg.keyboard.press("Enter")
                                    break
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        nw(pg, 20000)
                    _sess_update(status="running", message="📤 Action submit hua, continue...")
                    continue

                nw(pg, 8000)

            # ── Extract cookies ────────────────────────────────────────────
            log("EXTRACTING")
            _sess_update(status="running", message="🍪 Drive cookies extract ho rahi hain...")
            try:
                pg.goto("https://drive.google.com", timeout=30000)
                nw(pg)
            except Exception:
                pass

            all_cookies = ctx.cookies([
                "https://drive.google.com",
                "https://google.com",
                "https://accounts.google.com",
            ])
            result_data = {
                "url": "https://drive.google.com",
                "cookies": [{"name": c["name"], "value": c["value"]} for c in all_cookies],
            }

            # Save the device/session state so the NEXT login for this same
            # account looks like a returning trusted device instead of a
            # fresh, suspicious one.
            try:
                ctx.storage_state(path=profile_file)
            except Exception as e:
                log(f"PROFILE_SAVE_ERR: {e}")

            br.close()

            with open(result_file, "w") as f:
                json.dump(result_data, f)

            names    = [c["name"] for c in result_data["cookies"]]
            has_auth = any(n in names for n in ["SID", "SAPISID", "__Secure-1PSID", "HSID", "__Secure-3PSID"])
            log(f"{'SUCCESS' if has_auth else 'PARTIAL'}: {len(names)} cookies")

    except Exception as e:
        # Take a final screenshot so the failure panel in the UI has something to show
        try:
            _push_frame(pg)
            with _live_frames_lock:
                frame = _live_frames.get(sid)
            if frame:
                with open(ss_file, "wb") as _f:
                    _f.write(frame["data"])
        except Exception:
            pass
        _sess_update(status="error", message=f"Playwright error: {e}")
        print(f"[AL:{sid[:8]}] EXCEPTION: {e}", flush=True)
        return

    # Keep final frame in memory briefly so SSE stream shows last state, then clean up
    def _delayed_frame_cleanup():
        time.sleep(8)
        with _live_frames_lock:
            _live_frames.pop(sid, None)
    threading.Thread(target=_delayed_frame_cleanup, daemon=True).start()

    if not os.path.exists(result_file):
        return

    _finalize_autologin(sid, uid, result_file)

    # cleanup
    for fp in [status_file, otp_file, phone_file, number_file, manual_file, ss_file]:
        try:
            os.remove(fp)
        except Exception:
            pass


def _tg_escape(text: str) -> str:
    """Escape special HTML chars for Telegram HTML parse_mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _tg_http(bot_token: str, method: str, payload: dict, timeout: int = 10) -> dict:
    """POST to Telegram Bot API and return the parsed JSON response dict.
    Always returns a dict; on network error returns {'ok': False, 'description': str(e)}."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/{method}",
            data=payload, timeout=timeout,
        )
        try:
            return resp.json()
        except Exception:
            return {"ok": False, "description": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "description": str(e)}


def _send_tg_login_success(uid, email: str, cookie_count: int) -> bool:
    """Send a Telegram bot message directly via HTTP when no callback is registered
    (e.g. user opened the autologin WebApp link directly, not via /login command).
    Also notifies the log channel if LOG_CHANNEL_ID is configured.
    Returns True if the user message was sent successfully."""
    bot_token = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token or not str(uid).lstrip('-').isdigit():
        print(f"[SERVER] _send_tg_login_success: no bot_token or invalid uid={uid}")
        return False

    bot_url = _get_bot_url()  # uses runtime-fetched username
    safe_email   = _tg_escape(email) if email else "—"

    # ── Message to the user ──────────────────────────────────────────────────
    user_text = (
        f"✅ <b>Auto Login Successful!</b>\n\n"
        f"<pre>"
        f"╭━━━━〔 GOOGLE ACCOUNT 〕━━━━╮\n"
        f"│  📧 Email  : {safe_email}\n"
        f"│  🍪 Cookies: {cookie_count} saved\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
        f"</pre>\n\n"
        f"🎉 Ab private Drive files access kar sakte ho!\n"
        f"Bot pe wapas jao aur apni files enjoy karo 🚀"
    )
    user_payload: dict = {
        "chat_id":    int(uid),
        "text":       user_text,
        "parse_mode": "HTML",
    }
    if bot_url:
        user_payload["reply_markup"] = json.dumps({
            "inline_keyboard": [[{"text": "📱 Bot mein Jaao", "url": bot_url}]]
        })
    result = _tg_http(bot_token, "sendMessage", user_payload)
    if not result.get("ok"):
        print(f"[SERVER] _send_tg_login_success user msg failed: {result.get('description', result)}")

    # ── Log channel notification ─────────────────────────────────────────────
    log_ch = os.environ.get("LOG_CHANNEL_ID", "").strip()
    if log_ch and log_ch.lstrip("-").isdigit():
        try:
            mention   = f'<a href="tg://user?id={uid}">{uid}</a>'
            _now      = __import__("datetime").datetime.now().strftime("%d %b %Y %H:%M:%S")
            log_text  = (
                f"✅ #AutoLogin #Success #uid_{uid}\n\n"
                f"👤 User: {mention} (<code>{uid}</code>)\n"
                f"📧 Email: <code>{safe_email}</code>\n"
                f"🍪 Cookies saved: <b>{cookie_count}</b>\n"
                f"⏰ {_now}"
            )
            _tg_http(bot_token, "sendMessage", {
                "chat_id":                  log_ch,
                "text":                     log_text,
                "parse_mode":               "HTML",
                "disable_web_page_preview": "true",
            })
        except Exception as _lce:
            print(f"[SERVER] _send_tg_login_success log_ch error: {_lce}")

    return bool(result.get("ok"))


def _finalize_autologin(sid, uid, result_file):
    if not os.path.exists(result_file):
        with _sessions_lock:
            if sid in _autologin_sessions:
                _autologin_sessions[sid].update({
                    "status": "error",
                    "message": "Login fail hua — result file missing.",
                })
        return

    try:
        with open(result_file) as f:
            data = json.load(f)

        cookies  = data.get("cookies", [])
        names    = [c["name"] for c in cookies]
        has_auth = any(n in names for n in ["SID", "SAPISID", "__Secure-1PSID", "HSID", "__Secure-3PSID"])
        if not has_auth:
            err_msg = "Auth cookies nahi mili — login successful nahi hua."
            with _sessions_lock:
                if sid in _autologin_sessions:
                    logs = _autologin_sessions[sid].setdefault("logs", [])
                    logs.append({"ts": time.time(), "lvl": "error", "msg": f"❌ {err_msg}"})
                    _autologin_sessions[sid].update({
                        "status": "error",
                        "message": err_msg,
                    })
            # Notify log channel: failed
            try:
                scb = _status_callbacks.get(int(uid) if str(uid).lstrip('-').isdigit() else uid)
                if scb:
                    threading.Thread(target=scb, args=("fail", {"reason": err_msg, "email": ""}), daemon=True).start()
            except Exception:
                pass
            return

        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        _uid_int = int(uid) if str(uid).lstrip('-').isdigit() else None
        _sess_email = ""
        with _sessions_lock:
            _sess_email = _autologin_sessions.get(sid, {}).get("email", "")

        _bot_msg_sent = False
        try:
            if _uid_int:
                db.save_google_cookies(_uid_int, cookie_str)
            cb = _cookie_callbacks.pop(_uid_int, None) if _uid_int else None
            if cb:
                # /login command flow: callback sends detailed message (with Drive info)
                threading.Thread(target=cb, args=(cookie_str,), daemon=True).start()
                _bot_msg_sent = True
            else:
                # WebApp direct-open: no callback registered → send bot message via HTTP
                _bot_msg_sent = _send_tg_login_success(uid, _sess_email, len(cookies))
        except Exception as e:
            print(f"[SERVER] autologin save error: {e}")

        with _sessions_lock:
            if sid in _autologin_sessions:
                logs = _autologin_sessions[sid].setdefault("logs", [])
                logs.append({"ts": time.time(), "lvl": "ok", "msg": "🎉 Login ho gaya! Cookies save ho gayi — bot pe wapas jaayein."})
                _autologin_sessions[sid].update({
                    "status":          "success",
                    "message":         "Login successful! Cookies save ho gayi hain.",
                    "cookie_count":    len(cookies),
                    "email":           _sess_email,
                    "bot_msg_sent":    _bot_msg_sent,
                })

        # Notify log channel: success
        try:
            scb = _status_callbacks.get(_uid_int) if _uid_int else None
            if scb:
                threading.Thread(target=scb, args=("success", {"cookie_count": len(cookies)}), daemon=True).start()
        except Exception:
            pass
    except Exception as e:
        err_str = str(e)
        with _sessions_lock:
            if sid in _autologin_sessions:
                logs = _autologin_sessions[sid].setdefault("logs", [])
                logs.append({"ts": time.time(), "lvl": "error", "msg": f"❌ Error: {err_str}"})
                _autologin_sessions[sid].update({"status": "error", "message": err_str})
        try:
            scb = _status_callbacks.get(int(uid) if str(uid).lstrip('-').isdigit() else uid)
            if scb:
                threading.Thread(target=scb, args=("fail", {"reason": err_str}), daemon=True).start()
        except Exception:
            pass


# ── Status & Challenge endpoints ──────────────────────────────────────────────

@app.route("/api/autologin/status")
def autologin_status():
    sid    = request.args.get("sid", "")
    try:
        since = float(request.args.get("since", 0))
    except (TypeError, ValueError):
        since = 0.0
    with _sessions_lock:
        sess = dict(_autologin_sessions.get(sid, {}))
        all_logs = list(sess.get("logs", []))
    if not sess:
        return jsonify({"status": "error", "message": "Session not found."}), 404
    new_logs = [e for e in all_logs if e["ts"] > since]
    return jsonify({
        "status":       sess.get("status", "running"),
        "message":      sess.get("message", ""),
        "raw_status":   sess.get("raw_status", ""),
        "otp_type":     sess.get("otp_type", ""),
        "numbers":      sess.get("numbers", []),
        "logs":         new_logs,
        "ss_ts":        sess.get("ss_ts", 0),
        "email":        sess.get("email", ""),
        "cookie_count": sess.get("cookie_count", 0),
        "bot_msg_sent": sess.get("bot_msg_sent", False),
    })


@app.route("/api/autologin/otp", methods=["POST"])
def autologin_otp():
    data = request.get_json(silent=True) or {}
    sid  = data.get("session_id", "")
    otp  = data.get("otp", "").strip()
    with _sessions_lock:
        sess = _autologin_sessions.get(sid)
    if not sess:
        return jsonify({"ok": False, "error": "Session not found."}), 404
    otp_file = sess.get("otp_file", _ftm(f"al_otp_{sid}.txt"))
    with open(otp_file, "w") as f:
        f.write(otp)
    with _sessions_lock:
        _autologin_sessions[sid].update({"status": "running", "message": "✅ Code submit hua, verify ho raha hai..."})
    return jsonify({"ok": True})


@app.route("/api/autologin/phone", methods=["POST"])
def autologin_phone():
    data  = request.get_json(silent=True) or {}
    sid   = data.get("session_id", "")
    phone = data.get("phone", "").strip()
    with _sessions_lock:
        sess = _autologin_sessions.get(sid)
    if not sess:
        return jsonify({"ok": False, "error": "Session not found."}), 404
    phone_file = sess.get("phone_file", _ftm(f"al_phone_{sid}.txt"))
    with open(phone_file, "w") as f:
        f.write(phone)
    with _sessions_lock:
        _autologin_sessions[sid].update({"status": "running", "message": "📞 Phone submit hua, SMS aane ka wait..."})
    return jsonify({"ok": True})


@app.route("/api/autologin/number_match", methods=["POST"])
def autologin_number_match():
    data   = request.get_json(silent=True) or {}
    sid    = data.get("session_id", "")
    number = str(data.get("number", "")).strip()
    with _sessions_lock:
        sess = _autologin_sessions.get(sid)
    if not sess:
        return jsonify({"ok": False, "error": "Session not found."}), 404
    num_file = _ftm(f"al_num_{sid}.txt")
    with open(num_file, "w") as f:
        f.write(number)
    with _sessions_lock:
        _autologin_sessions[sid].update({"status": "running", "message": "🔢 Number select hua, verify ho raha hai..."})
    return jsonify({"ok": True})


@app.route("/api/autologin/choice", methods=["POST"])
def autologin_choice():
    data  = request.get_json(silent=True) or {}
    sid   = data.get("session_id", "")
    text  = str(data.get("text", "")).strip()
    with _sessions_lock:
        sess = _autologin_sessions.get(sid)
    if not sess:
        return jsonify({"ok": False, "error": "Session not found."}), 404
    if not text:
        return jsonify({"ok": False, "error": "Option required."}), 400
    choice_file = _ftm(f"al_choice_{sid}.txt")
    with open(choice_file, "w") as f:
        f.write(text)
    with _sessions_lock:
        _autologin_sessions[sid].update({"status": "running", "message": "🔀 Option submit hua, continue ho raha hai..."})
    return jsonify({"ok": True})


@app.route("/api/autologin/manual", methods=["POST"])
def autologin_manual():
    data = request.get_json(silent=True) or {}
    sid  = data.get("session_id", "")
    text = data.get("text", "").strip()
    with _sessions_lock:
        sess = _autologin_sessions.get(sid)
    if not sess:
        return jsonify({"ok": False, "error": "Session not found."}), 404
    manual_file = _ftm(f"al_manual_{sid}.txt")
    with open(manual_file, "w") as f:
        f.write(text)
    with _sessions_lock:
        _autologin_sessions[sid].update({"status": "running", "message": "📤 Input submit hua, continue ho raha hai..."})
    return jsonify({"ok": True})
