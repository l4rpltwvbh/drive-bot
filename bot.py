import os
from dotenv import load_dotenv
load_dotenv()
import aiohttp
import socket
import platform
import re
import math
import time
import random
import hashlib
import threading
import shutil
import subprocess
import itertools
import datetime
import glob
import queue as _queue_mod
import logging
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from zoneinfo import ZoneInfo
from collections import deque
import psutil
from html import escape as h
from urllib.parse import unquote

# ── Logging setup (show all logs in console) ──────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
    force=True,
)
logging.getLogger("pyrogram").setLevel(logging.INFO)
sys.stdout.flush()
# ─────────────────────────────────────────────────────────────────────────────

import requests
import gdown
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import ftmgram
import ftmgram as pyrogram
from ftmgram import Client, filters, enums, idle as pyrogram_idle, raw as raw_api
from ftmgram.errors import FloodWait
from ftmgram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, WebAppInfo
from ftmgram import utils as pyroutils

pyroutils.MIN_CHAT_ID = -999999999999
pyroutils.MIN_CHANNEL_ID = -100999999999999
import db
import server as cookie_server
from fallback.ftm_drive_fallback import ftm_drive_fallback as _ftm_fallback_run
import emoji_utils

# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────

BOT_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_ID         = int(os.environ.get("TELEGRAM_API_ID", "0") or "0")
API_HASH       = os.environ.get("TELEGRAM_API_HASH", "")
_db_group_raw  = os.environ.get("DB_GROUP_ID", "").strip()
DB_GROUP_ID    = int(_db_group_raw) if _db_group_raw else None
GDRIVE_API_KEY       = os.environ.get("GDRIVE_API_KEY", "")
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
OWNER_ID       = 7744665378
_env_admins    = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().lstrip("-").isdigit()]
ADMIN_IDS: set = set(_env_admins)   # augmented from DB after bot starts
# Accept channel IDs (integers like -1001234567890) or @usernames
FORCE_SUB_CHANNELS = []
for _fsc in os.environ.get("FORCE_SUB_CHANNELS", "").split(","):
    _fsc = _fsc.strip()
    if not _fsc:
        continue
    try:
        FORCE_SUB_CHANNELS.append(int(_fsc))
    except ValueError:
        FORCE_SUB_CHANNELS.append(_fsc)

# Generic public URL — works on Render, Railway, Replit, or any custom domain.
# Priority: explicit PUBLIC_URL > RENDER_EXTERNAL_URL > RAILWAY_PUBLIC_DOMAIN > REPLIT_DEV_DOMAIN
def _resolve_public_url() -> str:
    if os.environ.get("PUBLIC_URL"):
        return os.environ["PUBLIC_URL"].rstrip("/")
    if os.environ.get("RENDER_EXTERNAL_URL"):
        u = os.environ["RENDER_EXTERNAL_URL"]
        return (u if u.startswith("http") else f"https://{u}").rstrip("/")
    if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        return f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}".rstrip("/")
    if os.environ.get("REPLIT_DEV_DOMAIN"):
        return f"https://{os.environ['REPLIT_DEV_DOMAIN']}".rstrip("/")
    return ""

PUBLIC_URL = _resolve_public_url()

def _parse_channel_id(raw: str):
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None

DUMP_CHANNEL_ID      = _parse_channel_id(os.environ.get("DUMP_CHANNEL_ID", ""))
LOG_CHANNEL_ID       = _parse_channel_id(os.environ.get("LOG_CHANNEL_ID", ""))
FOLDER_DB_CHANNEL_ID = _parse_channel_id(os.environ.get("FOLDER_DB_CHANNEL_ID", "-1003908652765"))
BOT_VERSION     = os.environ.get("BOT_VERSION", "v7.5.0 [ Sᴛᴀʙʟᴇ ]")

# ── Ultra Plan config ─────────────────────────────────────────────────────────
ULTRA_PLAN_NAME          = os.environ.get("ULTRA_PLAN_NAME", "VIP Ultra Plan")
ULTRA_PLAN_PRICE         = os.environ.get("ULTRA_PLAN_PRICE", "₹1,500/month")
ULTRA_PLAN_DURATION_DAYS = int(os.environ.get("ULTRA_PLAN_DURATION_DAYS", "30"))
UPI_ID                   = os.environ.get("UPI_ID", "developerkumar@fam")
PLAN_CONTACT_URL         = os.environ.get("PLAN_CONTACT_URL", "https://t.me/ftmdevz")
FORCE_PLAN_REQUIRED      = os.environ.get("FORCE_PLAN_REQUIRED", "true").lower() == "true"
HOW_TO_USE_URL           = os.environ.get("HOW_TO_USE_URL", "https://t.me/ftmbotzx_tutorials/52")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
if not API_ID or not API_HASH:
    raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH are required")

# ── Pyrogram bot client ───────────────────────────────────────────────────────
# Bot token is all that's needed — Pyrogram creates a local .session file
# automatically. On cloud platforms (Render/Railway) this file lives in the
# container's working directory and is recreated on each deploy (fine for bots).
bot = Client("drive", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

DOWNLOADS_DIR    = "downloads"
THUMBS_DIR       = "thumbnails"
CHUNK_SIZE       = 16 * 1024 * 1024   # 16 MB — used for file merge/copy (large = fast I/O)
PROGRESS_CHUNK   = int(os.environ.get("DOWNLOAD_CHUNK_MB", "6")) * 1024 * 1024  # network read chunk
FTM_SIZE_THRESHOLD = 2 * 1024 * 1024 * 1024   # 2 GB — route via FTM user session above this
FTM_SIZE_MAX       = 4 * 1024 * 1024 * 1024   # 4 GB — hard cap for FTM uploads

# ── FTM user client (for large file uploads) ──────────────────────────────────
# We keep ONE persistent asyncio event loop running in a daemon thread.
# All FTM coroutines (start, stop, send_*) are submitted to that loop via
# run_coroutine_threadsafe so the session is never duplicated and there is no
# "awaitable required" crash from run_until_complete().
_ftm_client      = None
_ftm_client_lock = threading.Lock()
_ftm_loop        = None   # the persistent loop (set by get_ftm_client)

def get_ftm_client():
    import asyncio as _asyncio
    global _ftm_client, _ftm_loop
    with _ftm_client_lock:
        if _ftm_client is not None:
            return _ftm_client
        session_str = db.get_ftm_session()
        if not session_str:
            return None
        try:
            loop = _asyncio.new_event_loop()

            # Keep the loop alive forever in a background daemon thread
            def _run_forever():
                _asyncio.set_event_loop(loop)
                loop.run_forever()

            t = threading.Thread(target=_run_forever, daemon=True, name="ftm-loop")
            t.start()

            # Start the Pyrogram client INSIDE the loop (raw async call)
            async def _start():
                fc = Client(
                    "ftm_user",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    session_string=session_str,
                )
                await fc.start()
                return fc

            fut = _asyncio.run_coroutine_threadsafe(_start(), loop)
            _ftm_client = fut.result(timeout=60)
            _ftm_loop   = loop
            print("[FTM] User client started ✅")
            return _ftm_client
        except Exception as e:
            print(f"[FTM] Client start failed: {e}")
            _ftm_client = None
            _ftm_loop   = None
            return None

def stop_ftm_client():
    import asyncio as _asyncio
    global _ftm_client, _ftm_loop
    with _ftm_client_lock:
        if _ftm_client and _ftm_loop:
            try:
                fut = _asyncio.run_coroutine_threadsafe(
                    _ftm_client.stop(), _ftm_loop
                )
                fut.result(timeout=15)
            except Exception:
                pass
            try:
                _ftm_loop.call_soon_threadsafe(_ftm_loop.stop)
            except Exception:
                pass
            _ftm_client = None
            _ftm_loop   = None
            print("[FTM] User client stopped")

def _ftm_session_available() -> bool:
    """Check if a valid FTM session string is saved (no network call)."""
    return bool(db.get_ftm_session())

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".ts", ".m4v", ".3gp"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".heic", ".heif"}
AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".aac", ".opus", ".wma", ".aiff", ".alac"}

# ── Portable ffmpeg / ffprobe paths ──────────────────────────────────────────
# Priority: env-var override → PATH lookup → common fixed paths.
def _find_binary(name: str) -> str:
    """Return the best available path for a binary (ffmpeg, ffprobe, etc.)."""
    env_key = name.upper() + "_PATH"
    val = os.environ.get(env_key, "").strip()
    if val and os.path.isfile(val) and os.access(val, os.X_OK):
        return val
    found = shutil.which(name)
    if found:
        return found
    for prefix in ("/usr/bin", "/usr/local/bin", "/app/.apt/usr/bin",
                   "/nix/store"):
        p = os.path.join(prefix, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return name   # fall back to bare name and hope it's on PATH at runtime

_FFMPEG  = _find_binary("ffmpeg")
_FFPROBE = _find_binary("ffprobe")
print(f"[BINARY] ffmpeg={_FFMPEG}  ffprobe={_FFPROBE}")

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(THUMBS_DIR,    exist_ok=True)

thread_errors: list = []

# ─────────────────────────────────────────────
#  Global state
# ─────────────────────────────────────────────

PENDING_THUMB:     dict  = {}   # uid → True   (waiting for thumbnail photo)
PENDING_DELTA:     dict  = {}   # uid → True   (waiting for channel forward)
CANCEL_TASKS:      set   = set() # uid set whose current task should stop
CANCEL_EVENTS:     dict  = {}   # uid → threading.Event  (instant cancel signal)
RETRY_DATA:        dict  = {}   # uid → {type, file_id/folder_id, hint}
FALLBACK_DATA:     dict  = {}   # uid → {file_id, hint}  (ftm_drive_fallback trigger)
FOLDER_SELECTIONS: dict  = {}   # uid → {folder_id, files: [(fid,fname)], selected: set}
FOLDER_BROWSE:     dict  = {}   # uid → {root_id, root_name, path: [node], origin_msg}
ACTIVE_TASKS:      set   = set() # uid set currently running a download task
TASK_START_TIMES:  dict  = {}   # uid → start timestamp (for watchdog)
PENDING_CAPTION_TPL: dict = {}  # uid → True   (waiting for caption template text)
PENDING_RENAME:    dict  = {}   # uid → custom_name  (rename next uploaded file)
PENDING_COOKIES:   dict  = {}   # uid → True  (waiting for cookie paste)
PENDING_PDF_ORIENT: dict = {}   # uid → {file_id, hint_name, mime_type, cookies, status_msg, origin_msg, folder_url}
FORCE_SUB_MSGS:    dict  = {}   # uid → [msg_id, ...]  (force-sub warning messages to delete on join)
PENDING_BROADCAST: dict  = {}   # admin_uid → {text, from_msg, status_msg}
PENDING_FTM:       dict  = {}   # admin_uid → {step, phone, phone_code_hash, tmp_client}
PENDING_TAG:       dict  = {}   # admin_uid → True  (waiting for tag text input)
FOLDER_ALPHA:      dict  = {}   # uid → folder_id  (for Alpha quick-resend)
BOT_START_TIME:    float = time.time()
_BUG_MODE:         bool  = False   # /titaniumbug — fake error for all users
_BUG_ERROR_CODE:   str   = "random" # "random"|"429"|"404"|"503"|"502"|"401"

# ── Global File Tag (set by admin/owner) ──────────────────────────────────────
FILE_TAG:         str  = ""     # e.g. "@MyChannel"
FILE_TAG_ENABLED: bool = False  # toggle

# ─────────────────────────────────────────────
#  Spinner / streaming animation
# ─────────────────────────────────────────────

_SPINNER = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])

def _spin() -> str:
    return next(_SPINNER)


def stream_reply(message: Message, lines: list, delay: float = 0.30) -> Message:
    """
    Send a new reply and reveal lines one-by-one (streaming / typewriter effect).
    Respects Telegram's flood-wait limits automatically.
    Returns the sent Message object.
    """
    msg     = message.reply_text("…")
    current = ""
    for i, line in enumerate(lines):
        current += line + ("\n" if i < len(lines) - 1 else "")
        try:
            msg.edit_text(current.strip(), parse_mode=enums.ParseMode.HTML)
            if i < len(lines) - 1:
                time.sleep(delay)
        except FloodWait as fw:
            time.sleep(fw.value + 0.5)
            try:
                msg.edit_text(current.strip(), parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass
        except Exception:
            pass
    return msg


# ─────────────────────────────────────────────
#  Telegram rate limiter — prevents FloodWait
# ─────────────────────────────────────────────

_tg_rate_lock  = threading.Lock()
_tg_rate_times: dict = {}   # chat_key → last_call_timestamp
_TG_MIN_GAP    = 1.15       # minimum seconds between API calls to same chat


def _chat_key(msg) -> str:
    """Return a stable string key for the chat this message belongs to."""
    return str(getattr(getattr(msg, "chat", None), "id", id(msg)))


def _tg_throttle(chat_key: str) -> None:
    """Proactively sleep so we never exceed ~1 msg/sec per chat."""
    with _tg_rate_lock:
        last = _tg_rate_times.get(chat_key, 0)
        gap  = time.time() - last
        if gap < _TG_MIN_GAP:
            time.sleep(_TG_MIN_GAP - gap)
        _tg_rate_times[chat_key] = time.time()


def tg_edit_safe(msg, text: str, markup=None,
                 parse_mode=enums.ParseMode.HTML,
                 block: bool = True) -> None:
    """
    Edit a Telegram message safely:
    • Proactive per-chat throttle (no FloodWait before it starts)
    • On FloodWait: notify user, wait the required time, then retry
    • block=False → skip silently (for high-frequency progress ticks)
    """
    if msg is None:
        return
    ck = _chat_key(msg)
    _tg_throttle(ck)
    kw: dict = {"parse_mode": parse_mode}
    if markup is not None:
        kw["reply_markup"] = markup
    try:
        msg.edit_text(text, **kw)
    except FloodWait as fw:
        wait = fw.value + 1
        print(f"[FloodWait] edit → {wait}s  chat={ck}")
        if wait >= 3:
            try:
                msg.edit_text(
                    f"⏳ <b>Telegram Rate Limit</b>\n\n"
                    f"Requests thodi zyada ho gayi hain.\n"
                    f"Bot <b>{wait}s</b> mein khud resume kar lega — kuch karne ki zaroorat nahi.",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass
        if block:
            time.sleep(wait)
            with _tg_rate_lock:
                _tg_rate_times[ck] = time.time()
            try:
                msg.edit_text(text, **kw)
            except Exception:
                pass
    except Exception:
        pass


def tg_reply_safe(message, text: str, markup=None,
                  parse_mode=enums.ParseMode.HTML):
    """
    Send a reply safely:
    • Proactive per-chat throttle
    • On FloodWait: wait and auto-retry (up to 3 attempts)
    Returns the sent Message or None.
    """
    if message is None:
        return None
    ck = _chat_key(message)
    _tg_throttle(ck)
    kw: dict = {"parse_mode": parse_mode}
    if markup is not None:
        kw["reply_markup"] = markup
    for attempt in range(3):
        try:
            return message.reply_text(text, **kw)
        except FloodWait as fw:
            wait = fw.value + 1
            print(f"[FloodWait] reply → {wait}s  chat={ck}  attempt={attempt + 1}")
            time.sleep(wait)
            with _tg_rate_lock:
                _tg_rate_times[ck] = time.time()
        except Exception as e:
            print(f"[tg_reply_safe] {e}")
            return None
    return None


def _send_blockquote(client, chat_id, plain_text, reply_to_message_id=None):
    """
    Send a message with blockquote+bold via Telegram Bot API HTTP (supports
    <blockquote> since Bot API 7.0). Falls back to plain bold if that fails.
    Returns (msg_id, chat_id) tuple or None.
    """
    import requests as _req

    html_text = f"<blockquote><b>{h(plain_text)}</b></blockquote>"
    payload = {
        "chat_id": chat_id,
        "text": html_text,
        "parse_mode": "HTML",
    }
    if reply_to_message_id:
        payload["reply_parameters"] = {"message_id": reply_to_message_id}

    try:
        resp = _req.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=12,
        )
        data = resp.json()
        if data.get("ok"):
            msg_id = data["result"]["message_id"]
            return (msg_id, chat_id)
        print(f"[BLOCKQUOTE] Bot API error: {data.get('description')}")
    except Exception as _e:
        print(f"[BLOCKQUOTE] request failed: {_e}")

    # Fallback: plain bold via Pyrogram
    try:
        sent = client.send_message(
            chat_id=chat_id,
            text=f"<b>{h(plain_text)}</b>",
            parse_mode=enums.ParseMode.HTML,
            reply_to_message_id=reply_to_message_id,
        )
        return (sent.id, sent.chat.id) if sent else None
    except Exception:
        return None


# ─────────────────────────────────────────────
#  Inline keyboard builders
# ─────────────────────────────────────────────

CANCEL_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("🚫  Cancel", callback_data="cancel_task"),
]])

RETRY_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("🔄  Retry",    callback_data="retry_task"),
    InlineKeyboardButton("⚙️  Settings", callback_data="settings_open"),
]])

FALLBACK_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("🔄  Retry",           callback_data="retry_task"),
    InlineKeyboardButton("🎭  Fallback Stream",  callback_data="fallback_task"),
], [
    InlineKeyboardButton("⚙️  Settings",         callback_data="settings_open"),
]])

DONE_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("⚙️  Settings", callback_data="settings_open"),
]])

_welcome_rows = [
    [InlineKeyboardButton("🌐  Connect Google Drive", callback_data="login_menu_open"),
     InlineKeyboardButton("⚙️  Settings",             callback_data="settings_open")],
    [InlineKeyboardButton("💎  VIP Plan (₹1500)",     callback_data="myplan_check"),
     InlineKeyboardButton("ℹ️  Help & Commands",      callback_data="help_info")],
    [InlineKeyboardButton("🤖  Buy This Bot / Clone", url="https://t.me/ftmdevz"),
     InlineKeyboardButton("👨‍💻  Contact Admin",       url=PLAN_CONTACT_URL)],
]
if HOW_TO_USE_URL:
    _welcome_rows.append([InlineKeyboardButton("📖  How to Use Guide", url=HOW_TO_USE_URL)])
WELCOME_KB = InlineKeyboardMarkup(_welcome_rows)


# ─────────────────────────────────────────────
#  Cookie / auth helpers
# ─────────────────────────────────────────────

def parse_cookie_str(cookie_str: str) -> dict:
    """
    Parse cookies from either:
    1. Semicolon-separated string: name1=val1; name2=val2
    2. JSON exported by Cookie Editor extension:
       {"url":"...","cookies":[{"name":"X","value":"Y"}, ...]}
       OR just the array: [{"name":"X","value":"Y"}, ...]
    Returns {name: value} dict including httpOnly cookies.
    """
    import json as _json
    cookies = {}
    text = cookie_str.strip()

    # Detect JSON format
    if text.startswith("{") or text.startswith("["):
        try:
            data = _json.loads(text)
            # Handle {"url":..., "cookies":[...]} format
            if isinstance(data, dict) and "cookies" in data:
                arr = data["cookies"]
            elif isinstance(data, list):
                arr = data
            else:
                arr = []
            for item in arr:
                if isinstance(item, dict):
                    name  = item.get("name", "").strip()
                    value = item.get("value", "").strip()
                    if name:
                        cookies[name] = value
            return cookies
        except Exception:
            pass  # Not valid JSON — fall through to string parser

    # Semicolon-separated string format
    for part in text.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def cookies_to_str(cookie_dict: dict) -> str:
    """Convert cookie dict back to semicolon-separated string for storage."""
    return "; ".join(f"{k}={v}" for k, v in cookie_dict.items())


def get_cookie_page_url(uid: int) -> str:
    base = PUBLIC_URL or f"http://localhost:{os.environ.get('PORT', '8080')}"
    return f"{base}/cookie?uid={uid}"


def get_autologin_url(uid: int) -> str:
    base = PUBLIC_URL or f"http://localhost:{os.environ.get('PORT', '8080')}"
    return f"{base}/autologin?uid={uid}"


def get_oauth_url(uid: int) -> str:
    base = PUBLIC_URL or f"http://localhost:{os.environ.get('PORT', '8080')}"
    return f"{base}/oauth/login?uid={uid}"


def get_browse_url(uid: int, folder_id: str) -> str:
    base = PUBLIC_URL or f"http://localhost:{os.environ.get('PORT', '8080')}"
    return f"{base}/browse?uid={uid}&folder={folder_id}"


def cookie_login_kb(uid: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🤖 Auto Login (Gmail / Password)", url=get_autologin_url(uid))],
        [InlineKeyboardButton("🔗 Cookie WebApp / Guide", url=get_cookie_page_url(uid))],
        [InlineKeyboardButton("🍪 Paste Cookies (.json)", callback_data="paste_cookies")],
        [
            InlineKeyboardButton("🔄 Retry",    callback_data="retry_task"),
            InlineKeyboardButton("⚙️ Settings", callback_data="settings_open"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def _build_account_status(uid: int) -> tuple:
    """
    Returns (text: str, keyboard: InlineKeyboardMarkup) for the Google account status.
    Used by /login command and Settings → My Account.
    """
    saved = db.get_google_cookies(uid)

    if not saved:
        text = (
            "👤 <b>My Google Account</b>\n\n"
            "❌ <b>Logged out</b> — koi account connected nahi hai.\n\n"
            "Private Drive files & folders download karne ke liye apna Google account connect karein.\n\n"
            "<b>Tareeqe:</b>\n"
            "🤖 <b>Auto Login</b> — Gmail + Password enter karein, bot khud live login karega\n"
            "🔗 <b>Cookie WebApp</b> — WebApp se direct cookies sync karein\n"
            "🍪 <b>Manual Cookies</b> — Extension se exported cookies paste karein"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Auto Login (Gmail / Password)", url=get_autologin_url(uid))],
            [InlineKeyboardButton("🔗 Cookie WebApp", url=get_cookie_page_url(uid))],
            [InlineKeyboardButton("🍪 Paste Cookies (.json)", callback_data="paste_cookies")],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="start_menu_back")],
        ])
        return text, kb

    # Cookies exist — fetch live account info
    info = get_drive_account_info(saved)
    if info["valid"]:
        used_gb   = info["storage_used"]  / (1024 ** 3)
        limit_gb  = info["storage_limit"] / (1024 ** 3)
        drive_gb  = info.get("drive_used",  0) / (1024 ** 3)
        gmail_gb  = info.get("gmail_used",  0) / (1024 ** 3)
        photos_gb = info.get("photos_used", 0) / (1024 ** 3)
        acct_type = info.get("account_type", "Gmail Account")
        total_dls = db.get_user_downloads(uid)

        if info["storage_limit"] > 0:
            pct    = info["storage_used"] / info["storage_limit"] * 100
            filled = int(16 * pct / 100)
            bar    = "█" * filled + "░" * (16 - filled)
            storage_bar = f"   [{bar}] {pct:.1f}%"
        else:
            pct = 0
            storage_bar = "   [unlimited]"

        breakdown = ""
        if any([drive_gb, gmail_gb, photos_gb]):
            breakdown = (
                "\n\n📊 <b>Storage Breakdown:</b>\n"
                f"   📁 Drive   :  {drive_gb:.2f} GB\n"
                f"   📧 Gmail   :  {gmail_gb:.2f} GB\n"
                f"   📸 Photos  :  {photos_gb:.2f} GB"
            )

        text = (
            "👤 <b>My Google Account</b>\n\n"
            "✅ <b>Logged In</b>\n\n"
            "<pre>"
            "╭━━━━━〔 ACCOUNT INFO 〕━━━━━╮\n"
            f"│  📛 Name    : {h(info['name'])}\n"
            f"│  📧 Email   : {h(info['email'])}\n"
            f"│  🌐 Type    : {h(acct_type)}\n"
            f"│  📥 Downloads: {total_dls}\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
            "</pre>\n\n"
            f"💾 <b>Storage:</b> {used_gb:.2f} GB / {limit_gb:.2f} GB\n"
            f"{storage_bar}"
            f"{breakdown}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh",  callback_data="my_account_refresh"),
             InlineKeyboardButton("🗑 Logout",   callback_data="gc_logout")],
            [InlineKeyboardButton("🔁 Re-login (Auto)", url=get_autologin_url(uid))],
            [InlineKeyboardButton("🍪 Re-login (Manual)", callback_data="paste_cookies")],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="start_menu_back")],
        ])
    else:
        text = (
            "👤 <b>My Google Account</b>\n\n"
            "⚠️ <b>Cookies expire ho gayi hain</b>\n\n"
            f"🔴 {h(info['error'] or 'Validation failed')}\n\n"
            "Nayi cookies export karein aur re-login karein."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Auto Login", url=get_autologin_url(uid))],
            [InlineKeyboardButton("🔗 Extract Guide",    url=get_cookie_page_url(uid))],
            [InlineKeyboardButton("🍪 Paste Cookies",    callback_data="paste_cookies")],
            [InlineKeyboardButton("🗑 Logout",           callback_data="gc_logout")],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="start_menu_back")],
        ])
    return text, kb


# ─────────────────────────────────────────────
#  Cookie validator + Google account info
# ─────────────────────────────────────────────

def compute_sapisidhash(sapisid: str, origin: str = "https://drive.google.com") -> str:
    """Compute Google SAPISIDHASH from SAPISID cookie for Drive API auth."""
    ts   = int(time.time())
    data = f"{ts} {sapisid} {origin}"
    sha1 = hashlib.sha1(data.encode("utf-8")).hexdigest()
    return f"{ts}_{sha1}"


def get_drive_account_info(cookie_str: str) -> dict:
    """
    Validate Drive cookies by fetching the Drive web UI HTML and parsing
    account info directly from the embedded JS data blobs.

    Tested and verified against real J2Team/CookieEditor JSON exports.
    Returns dict: {valid, name, email, photo, storage_used, storage_limit, error}
    """
    import re as _re
    result = {"valid": False, "name": None, "email": None,
              "photo": None, "storage_used": 0, "storage_limit": 0, "error": None}

    if not cookie_str:
        result["error"] = "Koi cookies saved nahi hain."
        return result

    cookies = parse_cookie_str(cookie_str)
    if not cookies:
        result["error"] = "Cookies parse nahi ho sakin. File/text sahi format mein dein."
        return result

    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0.0.0 Safari/537.36")

    # ── Primary: scrape drive.google.com/drive/u/0/ HTML ─────────────────
    try:
        resp = requests.get(
            "https://drive.google.com/drive/u/0/",
            cookies=cookies,
            headers={"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"},
            timeout=15,
            allow_redirects=True,
        )
        print(f"[COOKIE_VALIDATE] drive.google.com/drive/u/0/ → {resp.status_code}")

        # If redirected to accounts.google.com → cookies expired / not logged in
        if "accounts.google.com" in resp.url or resp.status_code != 200:
            result["error"] = (
                "Cookies expire ho gayi hain ya account logged out hai.\n"
                "drive.google.com pe login karke nayi cookies export karein."
            )
            return result

        html = resp.text
        dec_html = html.replace(r"\x22", '"').replace(r"\x5b", "[").replace(r"\x5d", "]")

        # ── Extract email ──────────────────────────────────────────────────
        email = None
        for pat in [
            r'"([\w.+%-]+@(?:gmail|googlemail)\.com)"',
            r'"([\w.+%-]+@[\w.-]+\.[a-z]{2,})"',
        ]:
            for m in _re.finditer(pat, dec_html):
                candidate = m.group(1)
                if (not any(x in candidate for x in ("gstatic", "google.", "schema", "w3.org"))
                        and len(candidate) < 80):
                    email = candidate
                    break
            if email:
                break

        if not email:
            result["error"] = (
                "Email extract nahi ho saki. Cookies shayad expire ho gayi hain.\n"
                "Dobara export karein."
            )
            return result

        # ── Extract name ───────────────────────────────────────────────────
        name = None
        m_signed = _re.search(r'Signed in as ([^"]+)', dec_html)
        if m_signed:
            name = m_signed.group(1).strip()

        if not name:
            m = _re.search(
                r'"([A-Za-z\u0080-\uFFFF][^"]{0,60}?)"\],null,\[\[\d{9,}',
                dec_html
            )
            if m and m.group(1) not in ("true", "false", "null", "name"):
                name = m.group(1).strip()

        if not name:
            # Fallback: first quoted capitalized word near the email
            idx = dec_html.find(f'"{email}"')
            if idx > 0:
                snippet = dec_html[max(0, idx - 600):idx + 400]
                nm = _re.search(r'"([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)"', snippet)
                if nm:
                    name = nm.group(1)

        name = name or (email.split("@")[0] if email else "Unknown")

        # ── Extract storage ────────────────────────────────────────────────
        storage_limit = 0
        storage_used  = 0
        drive_used = gmail_used = photos_used = 0

        sm = _re.search(
            r'\[\[(\d{9,}),(\d+),(\d+),\d+,\[\[null,(\d+),(\d+)\],\[null,(\d+),(\d+)\],\[null,(\d+),(\d+)\]',
            dec_html
        )
        if sm:
            storage_limit = int(sm.group(1))
            storage_used  = int(sm.group(3))
            comp_map = {
                int(sm.group(5)): int(sm.group(4)),
                int(sm.group(7)): int(sm.group(6)),
                int(sm.group(9)): int(sm.group(8)),
            }
            drive_used  = comp_map.get(1, int(sm.group(2)))
            gmail_used  = comp_map.get(2, 0)
            photos_used = comp_map.get(4, max(0, storage_used - drive_used - gmail_used))
        else:
            sm2 = _re.search(r'\[\[(\d{10,}),(\d+),(\d+)', dec_html)
            if sm2:
                storage_limit = int(sm2.group(1))
                drive_used    = int(sm2.group(2))
                storage_used  = int(sm2.group(3))
                photos_used   = max(0, storage_used - drive_used)

        # Determine account type from limit or domain
        account_type = "Free Gmail (15 GB)"
        if storage_limit >= 4 * 1024**4:
            account_type = "Google One Pro (5 TB)"
        elif storage_limit >= 1800 * 1024**3:
            account_type = "Google One Premium (2 TB)"
        elif storage_limit >= 90 * 1024**3:
            account_type = "Google One Basic"
        elif email and not email.lower().endswith(("@gmail.com", "@googlemail.com")):
            account_type = "Workspace Account"

        result.update({
            "valid":         True,
            "name":          name,
            "email":         email,
            "photo":         None,
            "storage_used":  storage_used,
            "storage_limit": storage_limit,
            "drive_used":    drive_used,
            "gmail_used":    gmail_used,
            "photos_used":   photos_used,
            "account_type":  account_type,
        })
        print(f"[COOKIE_VALIDATE] OK — {email}, storage {storage_used}/{storage_limit}")
        return result

    except requests.exceptions.Timeout:
        result["error"] = "Google server se response nahi aaya (timeout). Dobara try karein."
        return result
    except Exception as e:
        print(f"[COOKIE_VALIDATE] exception: {e}")
        result["error"] = f"Validation mein error: {e}"
        return result


# ─────────────────────────────────────────────
#  PDF / Document helpers
# ─────────────────────────────────────────────

PDF_MIME_TYPES = {
    "application/pdf",
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.drawing",
}

PDF_TYPE_LABELS = {
    "application/pdf":                           "📄 PDF File",
    "application/vnd.google-apps.document":      "📝 Google Doc",
    "application/vnd.google-apps.presentation":  "📊 Google Slides",
    "application/vnd.google-apps.spreadsheet":   "📈 Google Sheets",
    "application/vnd.google-apps.drawing":       "🎨 Google Drawing",
}


def _cookies_dict_to_str(cookies: dict) -> str:
    """Convert cookie dict to semicolon-separated string for Titanium API."""
    if not cookies:
        return ""
    if isinstance(cookies, str):
        return cookies.strip()
    return "; ".join(f"{k}={v}" for k, v in cookies.items())




def _build_pdf_url(file_id: str, mime_type: str, orientation: str) -> str:
    """Return the best-quality export URL for a given Drive file and orientation."""
    landscape = (orientation == "landscape")

    if mime_type == "application/vnd.google-apps.document":
        url = f"https://docs.google.com/document/d/{file_id}/export?format=pdf"
        if landscape:
            url += "&landscape=true"
        return url

    if mime_type == "application/vnd.google-apps.presentation":
        url = f"https://docs.google.com/presentation/d/{file_id}/export/pdf"
        if landscape:
            url += "?landscape=true"
        return url

    if mime_type == "application/vnd.google-apps.spreadsheet":
        url = (
            f"https://docs.google.com/spreadsheets/d/{file_id}/export"
            f"?format=pdf&portrait={'false' if landscape else 'true'}"
            "&size=A4&fitw=true&gridlines=false"
        )
        return url

    if mime_type == "application/vnd.google-apps.drawing":
        return f"https://docs.google.com/drawings/d/{file_id}/export/pdf"

    # Use drive.google.com/uc which handles the redirect chain and sets intermediate
    # auth cookies before landing on drive.usercontent.google.com
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def pdf_orient_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📄 Portrait",   callback_data="pdf_port"),
            InlineKeyboardButton("🔄 Landscape",  callback_data="pdf_land"),
        ],
        [InlineKeyboardButton("🚫 Cancel", callback_data="pdf_cancel")],
    ])


# ─────────────────────────────────────────────
#  Drive URL helpers
# ─────────────────────────────────────────────

def extract_drive_id(input_str: str) -> str:
    # Standard Drive file link:  /file/d/ID
    m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', input_str)
    if m: return m.group(1)
    # Google Docs:   docs.google.com/document/d/ID
    m = re.search(r'docs\.google\.com/document/d/([a-zA-Z0-9_-]+)', input_str)
    if m: return m.group(1)
    # Google Sheets: docs.google.com/spreadsheets/d/ID
    m = re.search(r'docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)', input_str)
    if m: return m.group(1)
    # Google Slides: docs.google.com/presentation/d/ID
    m = re.search(r'docs\.google\.com/presentation/d/([a-zA-Z0-9_-]+)', input_str)
    if m: return m.group(1)
    # Google Forms:  docs.google.com/forms/d/ID
    m = re.search(r'docs\.google\.com/forms/d/([a-zA-Z0-9_-]+)', input_str)
    if m: return m.group(1)
    return input_str.strip()


def _guess_mime_from_docs_url(url: str) -> str:
    """Return the Google Workspace MIME type implied by a docs.google.com URL.
    Returns empty string when rtpof=true is present — that flag means the file
    is an uploaded Office document (.docx/.xlsx/etc.) just *viewed* in Docs,
    NOT a native Google Workspace file.  In that case the direct
    uc?export=download path works and returns the original Office file."""
    if "rtpof=true" in url:
        return ""   # Office file in Docs viewer — download as-is, no PDF export
    if "docs.google.com/document"     in url: return "application/vnd.google-apps.document"
    if "docs.google.com/spreadsheets" in url: return "application/vnd.google-apps.spreadsheet"
    if "docs.google.com/presentation" in url: return "application/vnd.google-apps.presentation"
    if "docs.google.com/forms"        in url: return "application/vnd.google-apps.form"
    return ""


def extract_folder_id(text: str):
    m = re.search(r'/drive/folders/([a-zA-Z0-9_-]+)', text)
    return m.group(1) if m else None


def list_folder_file_ids(folder_id: str, cookies: dict = None,
                         access_token: str = "", refresh_token: str = "") -> list:
    """
    Return [(file_id, path/filename)] from a Drive folder.
    Priority: OAuth access_token → cookies (SAPISIDHASH) → API key → HTML scrape → gdown.
    Raises RuntimeError if nothing found.
    """
    from drive_utils import list_folder_files_flat
    result = list_folder_files_flat(
        folder_id,
        cookies=cookies,
        access_token=access_token,
        refresh_token=refresh_token,
    )
    print(f"[DRIVE] list_folder_file_ids: {len(result)} file(s) in folder {folder_id}")
    return result


def _sapisidhash(papisid: str, origin: str = "https://drive.google.com") -> str:
    """
    Compute the SAPISIDHASH auth header value from the __Secure-1PAPISID cookie.
    This is the same method Google Drive web UI uses for authenticated API requests.
    """
    import hashlib as _hl
    ts = str(int(time.time()))
    digest = _hl.sha1(f"{ts} {papisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


def list_folder_files_with_cookies(folder_id: str, cookies: dict,
                                    access_token: str = "", refresh_token: str = "") -> list:
    """
    Recursive folder listing with cookies or OAuth token.
    Priority: OAuth access_token → SAPISIDHASH (cookies) → HTML scrape.
    Returns [(file_id, path/filename)] sorted naturally.
    """
    from drive_utils import list_folder_files_flat
    result = list_folder_files_flat(
        folder_id,
        cookies=cookies,
        access_token=access_token,
        refresh_token=refresh_token,
    )
    print(f"[DRIVE] list_folder_files_with_cookies: {len(result)} file(s) in {folder_id}")
    return result


# ─────────────────────────────────────────────
#  Filename / format helpers
# ─────────────────────────────────────────────

def clean_filename(name: str) -> str:
    name = name.replace("+", " ")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"[. ]+$", "", name)
    if not name:
        name = "video"
    return name


def _apply_file_tag(filename: str) -> str:
    """Insert the global file tag into a filename before its extension.

    Example: 'movie.mp4' + '@Chan' → 'movie @Chan.mp4'
    If tag is disabled or not set, returns filename unchanged.
    """
    if not FILE_TAG_ENABLED or not FILE_TAG:
        return filename
    tag = FILE_TAG.strip()
    if not tag:
        return filename
    stem, ext = os.path.splitext(filename)
    if not stem:
        return filename
    return f"{stem} {tag}{ext}"


def get_video_url(page_content: str) -> tuple:
    """
    Returns (video_url, title, error_reason).
    video_url is None when Drive returns status=fail.
    error_reason is a human-readable string explaining why (or None on success).
    """
    video, title, status, reason = None, None, None, None
    for part in page_content.split("&"):
        if part.startswith("title=") and not title:
            title = unquote(part.split("=", 1)[-1])
        elif "videoplayback" in part and not video:
            video = unquote(part).split("|")[-1]
        elif part.startswith("status="):
            status = part.split("=", 1)[-1]
        elif part.startswith("reason="):
            reason = unquote(part.split("=", 1)[-1]).replace("+", " ")
        if video and title:
            break
    return video, title, reason


def get_file_size(url: str, cookies: dict) -> int:
    sess = _make_session(4, cookies)
    try:
        resp = sess.head(url, allow_redirects=True, timeout=15)
        size = int(resp.headers.get("content-length", 0))
        if size:
            return size
        resp2 = sess.get(url, stream=True, timeout=15)
        return int(resp2.headers.get("content-length", 0))
    except Exception:
        return 0


def format_size(n: float) -> str:
    if n < 1024:            return f"{n:.0f} B"
    if n < 1024 ** 2:       return f"{n / 1024:.2f} KB"
    if n < 1024 ** 3:       return f"{n / 1024**2:.2f} MB"
    return f"{n / 1024**3:.2f} GB"


def format_speed(bps: float) -> str:
    if bps < 1024 ** 2:
        return f"{bps / 1024:.2f} KB/s" if bps >= 1024 else f"{bps:.0f} B/s"
    return f"{bps / 1024**2:.2f} MB/s"


def format_eta(sec: float) -> str:
    if sec <= 0 or not math.isfinite(sec): return "∞"
    sec = int(sec)
    if sec < 60:   return f"{sec}s"
    if sec < 3600: m, s = divmod(sec, 60);  return f"{m}m {s}s"
    h_, r = divmod(sec, 3600); m, s = divmod(r, 60); return f"{h_}h {m}m {s}s"


def format_elapsed(sec: float) -> str:
    sec = int(sec)
    if sec < 60:   return f"{sec}s"
    if sec < 3600: m, s = divmod(sec, 60);  return f"{m}m {s}s"
    h_, r = divmod(sec, 3600); m, s = divmod(r, 60); return f"{h_}h {m}m {s}s"


def get_system_stats() -> tuple:
    cpu, ram = 0.0, 0.0
    try:
        if os.path.exists("/proc/stat") and os.path.exists("/proc/meminfo"):
            with open("/proc/stat") as f:
                v   = list(map(float, f.readline().split()[1:]))
                idle, total = v[3] + (v[4] if len(v) > 4 else 0), sum(v)
            time.sleep(0.05)
            with open("/proc/stat") as f:
                v2  = list(map(float, f.readline().split()[1:]))
                idle2, total2 = v2[3] + (v2[4] if len(v2) > 4 else 0), sum(v2)
            td  = total2 - total
            cpu = 100.0 * (td - (idle2 - idle)) / td if td else 0.0
            mt = ma = 0
            with open("/proc/meminfo") as f:
                for ln in f:
                    if ln.startswith("MemTotal:"):    mt = int(ln.split()[1])
                    elif ln.startswith("MemAvailable:"): ma = int(ln.split()[1])
            if mt: ram = 100.0 * (mt - ma) / mt
    except Exception: pass
    return round(cpu, 1), round(ram, 1)


# ─────────────────────────────────────────────
#  Progress / upload cards  (HTML  +  <pre>)
# ─────────────────────────────────────────────

def draw_progress_card(title, downloaded, total, speed, elapsed, eta,
                       file_index=1, total_files=1, threads=16) -> str:
    bar_width = 20
    pct  = downloaded / total if total > 0 else 0
    bar  = "█" * int(bar_width * pct) + "░" * (bar_width - int(bar_width * pct))
    t    = (title[:28] + "…") if len(title) > 31 else title
    idx  = f"  [{file_index}/{total_files}]" if total_files > 1 else ""
    spin = _spin()
    remaining = format_size(max(0, total - downloaded))
    return (
        f"<pre>"
        f"╭━━━━━〔 {spin} 📥 DOWNLOADING{idx} 〕━━━━━╮\n"
        f"│  📄 {t}\n"
        f"│\n"
        f"│  [{bar}]  {pct*100:.1f}%\n"
        f"│  📦 {format_size(downloaded)} / {format_size(total)}\n"
        f"│  📉 Remaining: {remaining}\n"
        f"│\n"
        f"│  ⚡ Speed  : {format_speed(speed)}\n"
        f"│  ⏱ Elapsed: {format_elapsed(elapsed)}\n"
        f"│  ⏳ ETA    : {format_eta(eta)}\n"
        f"│  🧵 Threads: {threads}\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
        f"</pre>"
    )


def draw_upload_card(title, file_size, uploaded, speed, elapsed, eta,
                     cpu, ram, file_index=1, total_files=1) -> str:
    bar_width = 20
    pct  = uploaded / file_size if file_size > 0 else 0
    bar  = "█" * int(bar_width * pct) + "░" * (bar_width - int(bar_width * pct))
    t    = (title[:28] + "…") if len(title) > 31 else title
    idx  = f"  [{file_index}/{total_files}]" if total_files > 1 else ""
    spin = _spin()
    remaining = format_size(max(0, file_size - uploaded))
    return (
        f"<pre>"
        f"╭━━━━━〔 {spin} 📤 UPLOADING{idx} 〕━━━━━╮\n"
        f"│  📄 {t}\n"
        f"│\n"
        f"│  [{bar}]  {pct*100:.1f}%\n"
        f"│  📦 {format_size(uploaded)} / {format_size(file_size)}\n"
        f"│  📉 Remaining: {remaining}\n"
        f"│\n"
        f"│  ⚡ Speed  : {format_speed(speed)}\n"
        f"│  ⏱ Elapsed: {format_elapsed(elapsed)}\n"
        f"│  ⏳ ETA    : {format_eta(eta)}\n"
        f"│  💻 CPU: {cpu:.1f}%   RAM: {ram:.1f}%\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
        f"</pre>"
    )


def get_video_metadata(path: str) -> dict:
    meta = {"duration": 0, "width": 0, "height": 0}
    try:
        r = subprocess.run(
            [_FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=0", path],
            capture_output=True, text=True,
        )
        for ln in r.stdout.splitlines():
            if "=" in ln:
                k, v = ln.strip().split("=", 1)
                if k == "duration":  meta["duration"] = int(float(v or 0))
                elif k == "width":   meta["width"]    = int(v or 0)
                elif k == "height":  meta["height"]   = int(v or 0)
    except Exception: pass
    return meta


def _extract_audio_meta(path: str) -> dict:
    """Extract duration, title, performer from audio using ffprobe."""
    meta = {"duration": 0, "title": "", "performer": ""}
    try:
        r = subprocess.run(
            [_FFPROBE, "-v", "error",
             "-show_entries",
             "format=duration:format_tags=title,artist,album_artist",
             "-of", "default=noprint_wrappers=1:nokey=0", path],
            capture_output=True, text=True, timeout=15,
        )
        for ln in r.stdout.splitlines():
            if "=" not in ln:
                continue
            k, v = ln.strip().split("=", 1)
            v = v.strip()
            k = k.lower().replace("tag:", "")
            if k == "duration":
                try: meta["duration"] = int(float(v))
                except: pass
            elif k == "title" and not meta["title"]:
                meta["title"] = v
            elif k in ("artist", "album_artist") and not meta["performer"]:
                meta["performer"] = v
    except Exception:
        pass
    return meta


def extract_thumbnail(video_path: str, out: str, duration: int = 0) -> bool:
    try:
        if not duration:
            r = subprocess.run(
                [_FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True,
            )
            duration = int(float(r.stdout.strip() or "0"))
        seek = max(0, duration * 0.1)
        subprocess.run(
            [_FFMPEG, "-y", "-ss", str(seek), "-i", video_path,
             "-vframes", "1", "-q:v", "2", out],
            capture_output=True, check=True,
        )
        return os.path.exists(out)
    except Exception:
        return False


def thumb_local_path(uid: int) -> str:
    return os.path.join(THUMBS_DIR, f"{uid}.jpg")


# ─────────────────────────────────────────────
#  DB Group — forum topic via raw Pyrogram API
# ─────────────────────────────────────────────

def create_forum_topic_raw(client: Client, chat_id: int, title: str):
    """Create forum topic via Pyrogram raw API. Returns thread_id (int) or None."""
    try:
        client.get_chat(chat_id)              # populates Pyrogram's peer cache
        peer   = client.resolve_peer(chat_id)
        result = client.invoke(
            raw_api.functions.channels.CreateForumTopic(
                channel=peer,
                title=title,
                random_id=random.randint(1, 2 ** 63 - 1),
            )
        )
        # result.updates is a list — look for the service message whose id = topic_id
        for upd in result.updates:
            if hasattr(upd, "message") and hasattr(upd.message, "id"):
                tid = upd.message.id
                if tid and tid > 0:
                    print(f"[FORUM_TOPIC] ✅ Created '{title}' → topic_id={tid} in chat={chat_id}")
                    return tid
        # Some Pyrogram builds surface the id at result.pts / inside update.id
        print(f"[FORUM_TOPIC] ⚠️ No message id found in updates for '{title}': {result}")
        return None
    except Exception as e:
        print(f"[FORUM_TOPIC] ❌ CreateForumTopic failed for chat={chat_id} title='{title}': {type(e).__name__}: {e}")
        return None


def _plan_contact_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 Buy VIP Plan (₹1,500/mo)", url=PLAN_CONTACT_URL)],
        [InlineKeyboardButton("🤖 Get Your Own Bot (@ftmdevz)", url="https://t.me/ftmdevz")],
        [InlineKeyboardButton("🔄 Check My Plan", callback_data="myplan_check"),
         InlineKeyboardButton("◀️ Main Menu", callback_data="start_menu_back")],
    ])


_ROAST_LINES = [
    "⚠️ <b>VIP Plan Required!</b>\nGoogle Drive files & folders process karne ke liye active VIP plan hona zaroori hai.",
    "🔒 <b>Access Restricted!</b>\nBina plan ke direct download access available nahi hai. Abhi VIP plan activate karein!",
    "💎 <b>VIP Membership Needed!</b>\nHigh-speed Google Drive downloading ke liye VIP plan active hona chahiye.",
    "🚀 <b>Premium Feature!</b>\nGoogle Drive links ko ultra-fast speed se Telegram pe laane ke liye VIP plan join karein.",
    "⚡ <b>Fast-Track Your Downloads!</b>\nPrivate files, shared drives aur bulk folders download karne ke liye VIP plan lein.",
]

import random as _random

def _plan_required_msg(client, message, uid: int, display: str = None):
    roast = _random.choice(_ROAST_LINES)
    text = (
        f"{roast}\n\n"
        f"╭━━━━〔 💎 VIP MEMBERSHIP 〕━━━━╮\n"
        f"│  💰 Price    : {ULTRA_PLAN_PRICE}\n"
        f"│  ⏳ Duration : 30 Days (1 Month)\n"
        f"│  ⚡ Speed    : Unlimited High-Speed\n"
        f"│  📁 Folders  : Full Batch Support\n"
        f"│  🔐 Private  : 1-Click OAuth Access\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"🤖 <b>Apna Khud Ka Bot Banwana Hai?</b>\n"
        f"Source code, clone bot ya custom bot setup lene ke liye admin se contact karein:\n"
        f"👉 <b>Contact Admin:</b> @ftmdevz\n\n"
        f"🆔 <b>Aapka User ID:</b> <code>{uid}</code>\n"
        f"<i>(Payment ke baad yeh User ID admin @ftmdevz ko bhejein)</i>"
    )
    message.reply_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=_plan_contact_kb())
    # ── Log to channel ────────────────────────────────────────────────────
    _disp = display or (db.get_user_full(uid).get("user") or {}).get("name") or f"User_{uid}"
    mention = f'<a href="tg://user?id={uid}">{h(_disp)}</a>'
    log_to_channel(client,
        f"🚫 #PlanRequired #uid_{uid}\n\n"
        f"👤 User: {mention} (<code>{uid}</code>)\n"
        f"📛 Name: {h(_disp)}\n"
        f"💎 Plan: <b>None / Expired ({ULTRA_PLAN_PRICE})</b>\n"
        f"⏰ {_now_str()}"
    )


def check_ultra_plan(uid: int) -> bool:
    if not FORCE_PLAN_REQUIRED:
        return True
    if uid in ADMIN_IDS:
        return True
    return db.has_ultra_plan(uid)


def get_or_create_db_topic(client: Client, user_id: int, display_name: str):
    """Return valid thread_id or create a new forum topic. Returns int or None."""
    tid = db.get_db_group_topic(user_id)
    if tid and tid > 0:
        return tid
    if not DB_GROUP_ID:
        return None
    print(f"[DB_GROUP] Creating topic for {user_id} '{display_name}'")
    new_id = create_forum_topic_raw(client, DB_GROUP_ID, f"{display_name} | {user_id}")
    if new_id and new_id > 0:
        db.set_db_group_topic(user_id, new_id)
        print(f"[DB_GROUP] Topic created → {new_id}")
        return new_id
    print(f"[DB_GROUP] Topic creation failed for {user_id}; bot needs Manage Topics permission")
    return None

def fetch_current_ip_details():
    apis = [
        "https://ipwho.is/",
        "https://ipapi.co/json/",
        "https://api.ipify.org?format=json",
    ]

    last_error = None

    for url in apis:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                last_error = f"{url} returned HTTP {r.status_code}"
                continue

            data = r.json()

            # ipwho.is response
            if "ip" in data and ("country" in data or "connection" in data):
                connection = data.get("connection") or {}
                timezone = data.get("timezone") or {}

                return {
                    "ip": data.get("ip", "N/A"),
                    "type": data.get("type", "N/A"),
                    "country": data.get("country", "N/A"),
                    "region": data.get("region", "N/A"),
                    "city": data.get("city", "N/A"),
                    "isp": connection.get("isp", data.get("org", "N/A")),
                    "asn": connection.get("asn", "N/A"),
                    "timezone": timezone.get("id", "N/A") if isinstance(timezone, dict) else timezone,
                    "source": "ipwho.is",
                }

            # ipapi.co response
            if "ip" in data and ("country_name" in data or "org" in data):
                return {
                    "ip": data.get("ip", "N/A"),
                    "type": data.get("version", "N/A"),
                    "country": data.get("country_name", "N/A"),
                    "region": data.get("region", "N/A"),
                    "city": data.get("city", "N/A"),
                    "isp": data.get("org", "N/A"),
                    "asn": data.get("asn", "N/A"),
                    "timezone": data.get("timezone", "N/A"),
                    "source": "ipapi.co",
                }

            # ipify response
            if "ip" in data:
                return {
                    "ip": data.get("ip", "N/A"),
                    "type": "N/A",
                    "country": "N/A",
                    "region": "N/A",
                    "city": "N/A",
                    "isp": "N/A",
                    "asn": "N/A",
                    "timezone": "N/A",
                    "source": "api.ipify.org",
                }

        except Exception as e:
            last_error = str(e)

    raise RuntimeError(last_error or "Unable to fetch IP details")
        
def _get_display_name(user) -> str:
    first = (user.first_name or "").strip()
    last  = (user.last_name  or "").strip()
    return (first + (" " + last if last else "")).strip() or "User"


def _now_str() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


# ─────────────────────────────────────────────
#  Log channel helper
# ─────────────────────────────────────────────

_log_channel_lock = threading.Lock()
_log_channel_last = {"ts": 0.0}
_LOG_CH_MIN_GAP   = 1.2   # seconds between log-channel messages

def log_to_channel(client: Client, text: str):
    """Send a log entry to LOG_CHANNEL_ID (fire-and-forget, rate-limited)."""
    if not LOG_CHANNEL_ID:
        return
    def _send():
        with _log_channel_lock:
            gap = time.time() - _log_channel_last["ts"]
            if gap < _LOG_CH_MIN_GAP:
                time.sleep(_LOG_CH_MIN_GAP - gap)
            _log_channel_last["ts"] = time.time()
        for attempt in range(3):
            try:
                client.send_message(LOG_CHANNEL_ID, text, parse_mode=enums.ParseMode.HTML,
                                    disable_web_page_preview=True)
                return
            except FloodWait as fw:
                wait = fw.value + 1
                print(f"[LOG_CH] FloodWait → {wait}s")
                time.sleep(wait)
                with _log_channel_lock:
                    _log_channel_last["ts"] = time.time()
            except Exception as e:
                print(f"[LOG_CH] ❌ {e}")
                return
    threading.Thread(target=_send, daemon=True).start()


# ─────────────────────────────────────────────
#  Dump channel helper
# ─────────────────────────────────────────────

def build_dump_caption(uid: int, display: str, file_type: str,
                       file_size: int, source_url: str = None,
                       folder_url: str = None) -> str:
    mention  = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    cap = (
        f"👤 ᴜsᴇʀ: {mention} (<code>{uid}</code>)\n"
        f"📂 ᴛʏᴘᴇ: {file_type}\n"
        f"📦 sɪᴢᴇ: {format_size(file_size)}"
    )
    if source_url:
        cap += f'\n📌 sᴏᴜʀᴄᴇ: <a href="{source_url}">🔗 Open Source</a>'
    if folder_url:
        cap += f'\n📁 ғᴏʟᴅᴇʀ: <a href="{folder_url}">🔗 Open Folder</a>'
    cap += f"\n⏰ {_now_str()}"
    return cap


def send_to_dump_channel(client: Client, uid: int, display: str,
                         sent_msg, file_type: str, file_size: int,
                         source_url: str = None, folder_url: str = None,
                         drive_file_id: str = None, fname: str = None):
    if not DUMP_CHANNEL_ID or sent_msg is None:
        return
    if db.is_dump_excluded(uid):
        print(f"[DUMP_CH] Skipped uid={uid} (dump excluded)")
        return
    def _send():
        try:
            orig_cap = (getattr(sent_msg, "caption", None) or
                        getattr(sent_msg, "text", None) or "")
            meta = build_dump_caption(uid, display, file_type, file_size, source_url, folder_url)
            full_cap = f"{orig_cap}\n\n{meta}" if orig_cap else meta
            dump_msg = client.copy_message(
                chat_id=DUMP_CHANNEL_ID,
                from_chat_id=sent_msg.chat.id,
                message_id=sent_msg.id,
                caption=full_cap,
                parse_mode=enums.ParseMode.HTML,
            )
            print(f"[DUMP_CH] ✅ uid={uid} dump_msg_id={dump_msg.id}")
            # Save to file_cache so FTM Alpha can reuse this dump message
            if drive_file_id and dump_msg:
                try:
                    db.set_file_cache(drive_file_id, dump_msg.id,
                                      fname or "", file_type, file_size)
                    print(f"[FILE_CACHE] Saved drive={drive_file_id} → dump_msg={dump_msg.id}")
                except Exception as ce:
                    print(f"[FILE_CACHE] Save error: {ce}")
        except Exception as e:
            print(f"[DUMP_CH] ❌ uid={uid}: {e}")
    threading.Thread(target=_send, daemon=True).start()


# ─────────────────────────────────────────────
#  Folder DB channel helper
# ─────────────────────────────────────────────

def send_folder_to_db_channel(client: Client, uid: int, display: str,
                               folder_id: str, sent_info: list):
    """
    After a folder download completes, create a forum topic in FOLDER_DB_CHANNEL_ID
    named after the root folder, then send every file organised by subfolder.
    Subfolder header messages are pinned so the structure is clear.

    sent_info: [(full_path_or_basename, sent_msg), ...]
    """
    if db.is_dump_excluded(uid):
        print(f"[FOLDER_DB] Skipped uid={uid} (dump excluded)")
        return
    if not FOLDER_DB_CHANNEL_ID or not sent_info:
        return

    def _run():
        try:
            from collections import OrderedDict

            # ── Determine root folder name from file paths ────────────────
            _GENERIC = {"root", "drive folder", "my drive", ""}
            root_name = None
            for fname, _ in sent_info:
                norm  = fname.replace("\\", "/")
                parts = norm.split("/")
                if len(parts) >= 2 and parts[0].lower() in _GENERIC:
                    root_name = parts[1]   # skip placeholder "Root"
                    break
                elif len(parts) >= 1 and parts[0].lower() not in _GENERIC:
                    root_name = parts[0]
                    break
            if not root_name:
                root_name = f"Folder_{folder_id[:12]}" if folder_id else "Downloads"

            # ── Create forum topic (fallback: General = thread_id 1) ─────
            topic_title = root_name[:128]
            topic_id    = create_forum_topic_raw(client, FOLDER_DB_CHANNEL_ID, topic_title)
            if not topic_id:
                print(f"[FOLDER_DB] ⚠️ Topic creation failed for '{topic_title}' — falling back to General topic (id=1)")
                topic_id = 1   # Telegram's built-in General topic

            # ── Send pinned root header ───────────────────────────────────
            mention    = f'<a href="tg://user?id={uid}">{h(display)}</a>'
            folder_url = f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else None
            # Send blockquote header for root folder name
            try:
                _send_blockquote(client, FOLDER_DB_CHANNEL_ID,
                                 f"📁 {root_name}",
                                 reply_to_message_id=topic_id)
            except Exception:
                pass
            hdr_lines  = [
                f"👤 <b>User:</b> {mention} (<code>{uid}</code>)",
                f"📦 <b>Total Files:</b> {len(sent_info)}",
            ]
            if folder_url:
                hdr_lines.append(f'🔗 <a href="{folder_url}">Open in Google Drive</a>')
            hdr_lines.append(f"⏰ {_now_str()}")
            try:
                root_msg = client.send_message(
                    chat_id=FOLDER_DB_CHANNEL_ID,
                    text="\n".join(hdr_lines),
                    parse_mode=enums.ParseMode.HTML,
                    reply_to_message_id=topic_id,
                    disable_web_page_preview=True,
                )
                client.pin_chat_message(
                    FOLDER_DB_CHANNEL_ID, root_msg.id, disable_notification=True
                )
            except Exception as e:
                print(f"[FOLDER_DB] Root header failed: {e}")

            # ── Group files by parent subfolder path ──────────────────────
            # Path layout: "RootName/SubA/SubB/file.ext"  →  parent = "SubA/SubB"
            # Flat files (no slash):                        parent = ""
            by_parent: OrderedDict = OrderedDict()
            for fname, sent_msg in sent_info:
                norm  = fname.replace("\\", "/")
                parts = norm.split("/")
                if len(parts) >= 3:
                    parent = "/".join(parts[1:-1])   # e.g. "SubA/SubB"
                elif len(parts) == 2:
                    parent = ""                       # direct child of root
                else:
                    parent = ""                       # no subfolder at all
                by_parent.setdefault(parent, []).append((parts[-1], sent_msg))

            # ── Send each group with optional pinned subfolder header ──────
            for parent_path, files in by_parent.items():
                if parent_path:
                    full_path = f"{root_name}/{parent_path}"
                    sub_name  = parent_path.split("/")[-1]
                    sub_hdr   = (
                        f"📂 <b>{h(sub_name)}</b>\n"
                        f"<code>📍 {h(full_path)}</code>\n"
                        f"<i>{len(files)} file(s)</i>"
                    )
                    try:
                        sub_msg = client.send_message(
                            chat_id=FOLDER_DB_CHANNEL_ID,
                            text=sub_hdr,
                            parse_mode=enums.ParseMode.HTML,
                            reply_to_message_id=topic_id,
                        )
                        client.pin_chat_message(
                            FOLDER_DB_CHANNEL_ID, sub_msg.id, disable_notification=True
                        )
                    except Exception as e:
                        print(f"[FOLDER_DB] Subfolder header '{parent_path}' failed: {e}")

                # Send each file under this group
                for bname, sent_msg in files:
                    try:
                        client.copy_message(
                            chat_id=FOLDER_DB_CHANNEL_ID,
                            from_chat_id=sent_msg.chat.id,
                            message_id=sent_msg.id,
                            reply_to_message_id=topic_id,
                        )
                    except Exception as e:
                        print(f"[FOLDER_DB] Copy failed '{bname}': {e}")

            print(
                f"[FOLDER_DB] ✅ uid={uid} folder='{root_name}' "
                f"files={len(sent_info)} topic={topic_id}"
            )

        except Exception as e:
            print(f"[FOLDER_DB] ❌ uid={uid}: {type(e).__name__}: {e}")

    threading.Thread(target=_run, daemon=True).start()


# ─────────────────────────────────────────────
#  Safe topic helpers (handles deleted topics)
# ─────────────────────────────────────────────

def _create_and_save_topic(client: Client, uid: int, display: str):
    """Create a new forum topic and persist it. Returns thread_id or None."""
    new_id = create_forum_topic_raw(client, DB_GROUP_ID, f"{display} | {uid}")
    if new_id and new_id > 0:
        db.set_db_group_topic(uid, new_id)
        print(f"[TOPIC] Created for uid={uid} → {new_id}")
        return new_id
    print(f"[TOPIC] Creation failed for uid={uid}")
    return None


def ensure_user_topic(client: Client, uid: int, display: str) -> int | None:
    """Return valid thread_id; create new topic if none exists."""
    if not DB_GROUP_ID:
        return None
    tid = db.get_db_group_topic(uid)
    if tid and tid > 0:
        return tid
    new_id = _create_and_save_topic(client, uid, display)
    if new_id and new_id > 0:
        return new_id
    print(f"[TOPIC] Unable to create topic for uid={uid}; bot needs Manage Topics permission")
    return None


def _safe_copy_to_topic(client: Client, uid: int, display: str,
                        from_chat_id: int, message_id: int,
                        caption: str = None, parse_mode=None) -> bool:
    """Copy message to user's DB group topic, re-creating topic if deleted."""
    if not DB_GROUP_ID:
        return False
    tid = ensure_user_topic(client, uid, display)
    for attempt in range(2):
        kw  = {"chat_id": DB_GROUP_ID, "from_chat_id": from_chat_id, "message_id": message_id}
        if tid and tid > 0:
            kw["reply_to_message_id"] = tid
        if caption is not None:
            kw["caption"] = caption
        if parse_mode is not None:
            kw["parse_mode"] = parse_mode
        try:
            client.copy_message(**kw)
            return True
        except Exception as e:
            err = str(e).lower()
            if attempt == 0 and ("topic" in err or "thread" in err or "not found" in err
                                 or "invalid" in err or "message_thread" in err):
                print(f"[TOPIC] Topic missing for uid={uid}, recreating… ({e})")
                db.set_db_group_topic(uid, 0)
                tid = _create_and_save_topic(client, uid, display)
                continue
            print(f"[DB_GROUP] ❌ uid={uid}: {type(e).__name__}: {e}")
            return False
    return False


def notify_process_start(client: Client, uid: int, display: str,
                         task_desc: str, s: dict):
    """Send 'process started' notification to user's DB group topic."""
    if not DB_GROUP_ID:
        return
    tid     = ensure_user_topic(client, uid, display)
    mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    ut_lbl  = "📄 Document" if s.get("upload_type") == "document" else "🎬 Video"
    tt_lbl  = {"auto": "🔄 Auto", "custom": "🖼 Custom", "none": "❌ None"}.get(s.get("thumb_type","auto"), "🔄 Auto")
    sp_lbl  = {"normal": "🐢 Normal (4T)", "fast": "🚀 Fast (8T)", "max": "⚡ Max (16T)"}.get(
        s.get("speed_preset","max"), "⚡ Max (16T)")
    text = (
        f"🚀 <b>Process Started</b>\n\n"
        f"👤 <b>User:</b>  {mention} (<code>{uid}</code>)\n"
        f"⏰ <b>Time:</b>  {_now_str()}\n"
        f"📋 <b>Task:</b>  {task_desc}\n\n"
        f"⚙️ <b>Settings</b>\n"
        f"  • Upload: {ut_lbl}\n"
        f"  • Thumb:  {tt_lbl}\n"
        f"  • Speed:  {sp_lbl}"
    )
    kw = {"chat_id": DB_GROUP_ID, "text": text, "parse_mode": enums.ParseMode.HTML,
          "disable_web_page_preview": True}
    if tid and tid > 0:
        kw["reply_to_message_id"] = tid
    def _send():
        try:
            client.send_message(**kw)
        except Exception as e:
            print(f"[TOPIC] notify_process_start uid={uid}: {e}")
    threading.Thread(target=_send, daemon=True).start()


def _copy_to_destinations(client: Client, message: Message, uid: int, sent_msg,
                           display: str = None, file_type: str = "File",
                           file_size: int = 0, source_url: str = None,
                           folder_url: str = None, drive_file_id: str = None,
                           fname: str = None):
    if sent_msg is None:
        return

    from_user = getattr(message, "from_user", None)
    # Always prefer DB-stored name to avoid getting bot's own name
    _db_name  = (db.get_user_full(uid).get("user") or {}).get("name", "")
    if display:
        disp = display
    elif _db_name:
        disp = _db_name
    elif from_user and not getattr(from_user, "is_bot", False):
        disp = _get_display_name(from_user)
    else:
        disp = f"User_{uid}"

    # ── Delta channel copy ────────────────────────────────────────────────
    ds = db.get_delta_settings(uid)
    if ds.get("delta_mode") and ds.get("delta_channel_id"):
        try:
            client.copy_message(
                chat_id=ds["delta_channel_id"],
                from_chat_id=sent_msg.chat.id,
                message_id=sent_msg.id,
            )
            print(f"[DELTA] ✅ uid={uid} → ch={ds['delta_channel_id']}")
        except Exception as de:
            print(f"[DELTA] ❌ uid={uid}: {de}")
            try:
                message.reply_text(
                    f"⚠️ Delta channel mein copy nahi ho saka:\n<code>{h(str(de))}</code>",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass

    # ── DB group topic copy (as-is, same as user receives) ────────────────
    if DB_GROUP_ID:
        db.save_user(uid, disp)
        ok = _safe_copy_to_topic(client, uid, disp, sent_msg.chat.id, sent_msg.id)
        print(f"[DB_GROUP] {'✅' if ok else '❌'} uid={uid}")

    # ── Dump channel copy with metadata caption ───────────────────────────
    send_to_dump_channel(client, uid, disp, sent_msg, file_type, file_size,
                         source_url, folder_url,
                         drive_file_id=drive_file_id, fname=fname)

    # ── Folder DB channel — General topic (single/non-folder files only) ──
    # Folder downloads skip this; they go through send_folder_to_db_channel instead
    if FOLDER_DB_CHANNEL_ID and not folder_url and not db.is_dump_excluded(uid):
        def _send_general():
            try:
                meta = build_dump_caption(uid, disp, file_type, file_size, source_url)
                orig = (getattr(sent_msg, "caption", None) or
                        getattr(sent_msg, "text", None) or "")
                full_cap = f"{orig}\n\n{meta}" if orig else meta
                client.copy_message(
                    chat_id=FOLDER_DB_CHANNEL_ID,
                    from_chat_id=sent_msg.chat.id,
                    message_id=sent_msg.id,
                    caption=full_cap,
                    parse_mode=enums.ParseMode.HTML,
                    reply_to_message_id=1,   # Telegram General topic ID
                )
                print(f"[FOLDER_DB] ✅ General topic uid={uid}")
            except Exception as e:
                print(f"[FOLDER_DB] ❌ General topic uid={uid}: {e}")
        threading.Thread(target=_send_general, daemon=True).start()

    # ── Activity log ──────────────────────────────────────────────────────
    mention  = f'<a href="tg://user?id={uid}">{h(disp)}</a>'
    src_part = f'<a href="{source_url}">link</a>' if source_url else "N/A"
    log_to_channel(client,
        f"📋 #Upload #uid_{uid} #{file_type.replace(' ','_')}\n\n"
        f"👤 User: {mention} (<code>{uid}</code>)\n"
        f"📄 File: <code>{h(file_type)}</code>\n"
        f"📦 Size: {format_size(file_size)}\n"
        f"📌 Source: {src_part}\n"
        f"⏰ {_now_str()}"
    )


# ─────────────────────────────────────────────
#  Settings UI
# ─────────────────────────────────────────────

def settings_keyboard(uid: int) -> InlineKeyboardMarkup:
    """Main settings menu — each row opens a dedicated submenu."""
    s    = db.get_settings(uid)
    ut   = "📄 Doc" if s["upload_type"] == "document" else "🎬 Video"
    tt   = {"auto": "🔄 Auto", "custom": "🖼 Custom", "none": "❌ None"}.get(s["thumb_type"], "🔄")
    ff   = "📂 All" if s.get("folder_filter", "all") == "all" else "🎬 Videos"
    sp   = {"normal": "🐢 4T", "fast": "🚀 8T", "max": "⚡ 16T"}.get(s.get("speed_preset", "max"), "⚡")
    tpl  = db.get_caption_template(uid)
    tpl_lbl = (tpl[:12] + "…") if len(tpl) > 12 else (tpl or "—")
    acct = "✅ Logged In" if db.get_google_cookies(uid) else "❌ Not Logged In"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"👤 My Account  ›  {acct}",        callback_data="settings_my_account")],
        [InlineKeyboardButton(f"🖼 Thumbnail    ›  {tt}",         callback_data="settings_sub_tt")],
        [InlineKeyboardButton(f"📂 Folder Filter ›  {ff}",        callback_data="settings_sub_ff")],
        [InlineKeyboardButton(f"⚡ Speed Preset  ›  {sp}",        callback_data="settings_sub_sp")],
        [InlineKeyboardButton(f"📝 Caption Template ›  {tpl_lbl}", callback_data="set_caption_tpl")],
        [InlineKeyboardButton("🔧  FTM Manager",                  callback_data="ftm_manager")],
    ])


def settings_sub_ut_keyboard(uid: int) -> InlineKeyboardMarkup:
    T  = lambda v: "✅" if v else "⬜"
    ut = db.get_settings(uid)["upload_type"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{T(ut=='document')} 📄 Document", callback_data="ut_document"),
         InlineKeyboardButton(f"{T(ut=='video')} 🎬 Video",       callback_data="ut_video")],
        [InlineKeyboardButton("◀️  Back to Settings", callback_data="settings_open")],
    ])


def settings_sub_tt_keyboard(uid: int) -> InlineKeyboardMarkup:
    T  = lambda v: "✅" if v else "⬜"
    tt = db.get_settings(uid)["thumb_type"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{T(tt=='auto')} 🔄 Auto",    callback_data="tt_auto"),
         InlineKeyboardButton(f"{T(tt=='custom')} 🖼 Custom", callback_data="tt_custom"),
         InlineKeyboardButton(f"{T(tt=='none')} ❌ None",    callback_data="tt_none")],
        [InlineKeyboardButton("🖼  Set Custom Thumbnail",    callback_data="set_thumb")],
        [InlineKeyboardButton("◀️  Back to Settings",        callback_data="settings_open")],
    ])


def settings_sub_ff_keyboard(uid: int) -> InlineKeyboardMarkup:
    T  = lambda v: "✅" if v else "⬜"
    ff = db.get_settings(uid).get("folder_filter", "all")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{T(ff=='all')} 📂 All Files",      callback_data="ff_all"),
         InlineKeyboardButton(f"{T(ff=='videos')} 🎬 Videos Only", callback_data="ff_videos")],
        [InlineKeyboardButton("◀️  Back to Settings", callback_data="settings_open")],
    ])


def settings_sub_sp_keyboard(uid: int) -> InlineKeyboardMarkup:
    T  = lambda v: "✅" if v else "⬜"
    sp = db.get_settings(uid).get("speed_preset", "max")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{T(sp=='normal')} 🐢 Normal 4T", callback_data="sp_normal"),
         InlineKeyboardButton(f"{T(sp=='fast')} 🚀 Fast 8T",     callback_data="sp_fast"),
         InlineKeyboardButton(f"{T(sp=='max')} ⚡ Max 16T",      callback_data="sp_max")],
        [InlineKeyboardButton("◀️  Back to Settings", callback_data="settings_open")],
    ])


def ftm_manager_keyboard(uid: int) -> InlineKeyboardMarkup:
    ds    = db.get_delta_settings(uid)
    dm    = ds["delta_mode"];  ch = ds["delta_channel_id"];  title = ds["delta_channel_title"]
    alpha = db.get_ftm_alpha(uid)

    d_icon = "🟢" if dm    else "🔴"
    a_icon = "🟢" if alpha  else "🔴"

    rows = [
        [InlineKeyboardButton("━━━━  FTM Alpha Mode  ━━━━",            callback_data="noop")],
        [InlineKeyboardButton(f"{a_icon}  Alpha Mode: {'ON' if alpha else 'OFF'}",  callback_data="alpha_toggle")],
        [InlineKeyboardButton("━━━━  FTM Delta Mode  ━━━━",            callback_data="noop")],
        [InlineKeyboardButton(f"{d_icon}  Delta Mode: {'ON' if dm else 'OFF'}",     callback_data="delta_toggle")],
    ]
    rows.append([InlineKeyboardButton("📡  Set Delta Channel",    callback_data="delta_set_ch")])
    if ch:
        rows.append([
            InlineKeyboardButton(f"📺  {title or ch}", callback_data="noop"),
            InlineKeyboardButton("🗑️ Remove",          callback_data="delta_remove_ch"),
        ])
    rows.append([InlineKeyboardButton("◀️  Back to Settings",          callback_data="ftm_back")])
    return InlineKeyboardMarkup(rows)


def _render_caption(template: str, filename: str = "", size: str = "",
                    file_type: str = "", mimetype: str = "", duration: str = "",
                    resolution: str = "", date: str = "", time_str: str = "") -> str:
    """Replace {variables} in a caption template with actual values.
    Lines containing an empty variable are skipped entirely."""
    now = datetime.datetime.utcnow()
    replacements = {
        "{filename}":   filename,
        "{size}":       size,
        "{type}":       file_type,
        "{mimetype}":   mimetype,
        "{duration}":   duration,
        "{resolution}": resolution,
        "{date}":       date or now.strftime("%Y-%m-%d"),
        "{time}":       time_str or now.strftime("%H:%M UTC"),
    }
    result_lines = []
    for line in template.split("\n"):
        skip = False
        for key, val in replacements.items():
            if key in line and not val:
                skip = True
                break
        if not skip:
            for key, val in replacements.items():
                line = line.replace(key, val)
            result_lines.append(line)
    result = "\n".join(result_lines)
    result = re.sub(r'\n{3,}', '\n\n', result).strip()
    return result


def _settings_html(uid: int) -> str:
    s   = db.get_settings(uid)
    ut  = "📄 Document" if s["upload_type"] == "document" else "🎬 Video"
    tt  = {"auto": "🔄 Auto-extract", "custom": "🖼 Custom", "none": "❌ None"}.get(s["thumb_type"], "🔄")
    ff  = "📂 All Files" if s.get("folder_filter", "all") == "all" else "🎬 Videos Only"
    sp  = {"normal": "🐢 Normal (4T)", "fast": "🚀 Fast (8T)", "max": "⚡ Max (16T)"}.get(
        s.get("speed_preset", "max"), "⚡ Max (16T)"
    )
    tpl = db.get_caption_template(uid)
    tpl_disp = (tpl[:30] + "…") if len(tpl) > 30 else (tpl or "—")
    return (
        "⚙️ <b>Settings</b>\n\n"
        f"<b>Upload Type:</b>     {ut}\n"
        f"<b>Thumbnail:</b>       {tt}\n"
        f"<b>Folder Filter:</b>   {ff}\n"
        f"<b>Speed Preset:</b>    {sp}\n"
        f"<b>Caption Template:</b> <code>{h(tpl_disp)}</code>"
    )


def _edit_settings(query: CallbackQuery, uid: int):
    try:
        query.edit_message_text(
            _settings_html(uid),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=settings_keyboard(uid),
        )
    except Exception:
        pass


def _edit_ftm(query: CallbackQuery, uid: int):
    try:
        query.edit_message_text(
            "🔧 <b>FTM Manager</b>\n\n"
            "⚡ <b>Alpha Mode:</b> Same file dobara request hone par "
            "seedha Dump Channel se copy karta hai — re-download ya re-upload nahi hota.\n\n"
            "🔄 <b>Delta Mode:</b> Har uploaded file ka copy "
            "aapke set kiye Delta Channel mein bhi jaata hai.",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=ftm_manager_keyboard(uid),
        )
    except Exception:
        pass


# ─────────────────────────────────────────────
#  Download logic
# ─────────────────────────────────────────────

def _make_session(num_threads: int = 16, cookies: dict = None) -> requests.Session:
    s = requests.Session()
    a = HTTPAdapter(
        pool_connections=max(num_threads, 4),
        pool_maxsize=max(num_threads * 2, 32),
        max_retries=Retry(total=3, backoff_factor=0.5,
                          status_forcelist=[500, 502, 503, 504]),
    )
    s.mount("https://", a);  s.mount("http://", a)
    # Persistent keep-alive and no Nagle (lower latency for large transfers)
    s.headers.update({
        "Connection":       "keep-alive",
        "Accept-Encoding":  "identity",   # disable gzip — already compressed media
    })
    if cookies:
        for name, value in cookies.items():
            for domain in (".google.com", ".usercontent.google.com"):
                s.cookies.set(name, str(value), domain=domain, path="/")
    return s


def _drive_auth_download(url: str, cookies: dict, filepath: str,
                          progress_cb=None, cancel_fn=None, meta_out: dict = None,
                          auth_headers: dict = None) -> int:
    """
    Download any Google Drive / Docs URL with authenticated cookies or OAuth headers.
    Cookies are sent as a raw Cookie: header to bypass Python cookiejar
    domain-matching restrictions (which break on drive.usercontent.google.com).
    Redirects are followed manually so cookies and auth are sent at every hop.
    If meta_out dict is provided, it is populated with:
      suggested_filename — real filename from Content-Disposition header
      content_type       — MIME type from response
    Returns file size in bytes.
    """
    import html as _html
    from urllib.parse import urlparse

    _AUTH_CHUNK  = 4 * 1024 * 1024   # 4 MB per chunk for fast streaming
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0.0.0 Safari/537.36")

    cookie_hdr = "; ".join(f"{k}={v}" for k, v in cookies.items()) if cookies else ""

    # Reuse a fast session with connection pooling
    _sess = _make_session(num_threads=4, cookies=cookies)
    base_hdrs = {"User-Agent": UA, "Accept-Encoding": "identity"}
    if auth_headers:
        base_hdrs.update(auth_headers)
    if cookie_hdr:
        base_hdrs["Cookie"] = cookie_hdr

    def _get(target_url, stream=False):
        """GET with Cookie header, follow redirects manually (cookie re-injection)."""
        for _ in range(12):
            r = _sess.get(target_url, headers=base_hdrs, stream=stream,
                          allow_redirects=False, timeout=(10, 60))
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location", "")
                if not loc:
                    break
                if loc.startswith("/"):
                    p = urlparse(target_url)
                    loc = f"{p.scheme}://{p.netloc}{loc}"
                target_url = loc
                if not stream:
                    r.close()
                continue
            return r, target_url
        return r, target_url

    # ── Compute SAPISIDHASH for restricted-file auth ───────────────────────
    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-1PAPISID") or ""
    if sapisid:
        base_hdrs["Authorization"] = "SAPISIDHASH " + compute_sapisidhash(sapisid)

    # Extract file_id from the URL (used for usercontent fallback)
    _fid_m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    _file_id_from_url = _fid_m.group(1) if _fid_m else None

    def _resolve_html_to_dl_url(html_body: str, current_url: str):
        """
        Parse HTML page returned by Drive and extract the actual download URL.
        Handles: large-file warning page, restricted-file page, confirmation forms.
        Returns resolved download URL or None if not found.
        """
        from urllib.parse import urlencode

        # 1) Direct usercontent download href (large-file warning link)
        m = re.search(r'href="(https://drive\.usercontent\.google\.com/download[^"]+)"', html_body)
        if m:
            return _html.unescape(m.group(1))

        # 2) Embedded JSON "downloadUrl" or "contentUrl" (restricted-file viewer page)
        for pat in [
            r'"downloadUrl"\s*:\s*"(https://[^"]+)"',
            r'"contentUrl"\s*:\s*"(https://[^"]+)"',
            r'data-url="(https://drive\.usercontent\.google\.com[^"]+)"',
        ]:
            m = re.search(pat, html_body)
            if m:
                return _html.unescape(m.group(1))

        # 3) Google virus-scan warning form — extract ALL hidden fields.
        #    Google requires 6 params: id, export, authuser, confirm, uuid, at.
        #    Sending only confirm causes an infinite loop back to the same page.
        form_action_m = re.search(
            r'<form[^>]+action="([^"]*(?:usercontent\.google\.com|drive\.google\.com)[^"]*)"',
            html_body, re.IGNORECASE)
        if form_action_m:
            action = _html.unescape(form_action_m.group(1))
            # Collect every hidden input in the form
            params = {}
            for inp in re.finditer(
                    r'<input[^>]+type=["\']hidden["\'][^>]*>', html_body, re.IGNORECASE):
                inp_str = inp.group(0)
                name_m  = re.search(r'name=["\']([^"\']+)["\']', inp_str)
                val_m   = re.search(r'value=["\']([^"\']*)["\']', inp_str)
                if name_m and val_m:
                    params[name_m.group(1)] = val_m.group(1)
            if params:
                sep = "&" if "?" in action else "?"
                return action + sep + urlencode(params)

        # 4) Fallback: just confirm token appended to current URL
        m = re.search(r'confirm=([0-9A-Za-z_\-]+)', html_body)
        confirm = m.group(1) if m else "t"
        sep = "&" if "?" in current_url else "?"
        return current_url + sep + "confirm=" + confirm

    # ── Step 1: resolve URL (check for login/confirmation pages) ──────────
    resp, url = _get(url, stream=False)
    ct = resp.headers.get("content-type", "")

    if "accounts.google.com" in url:
        raise Exception("Google login required — cookies missing or expired")

    if "text/html" in ct:
        body = resp.text
        resolved = _resolve_html_to_dl_url(body, url)
        resp.close()
        if resolved:
            url = resolved
        resp, url = _get(url, stream=False)
        ct = resp.headers.get("content-type", "")
        if "accounts.google.com" in url:
            raise Exception("Google login required — cookies missing or expired")

    # ── Step 1b: second HTML pass — try usercontent domain fallback ────────
    if "text/html" in ct and _file_id_from_url:
        resp.close()
        # Build direct usercontent download URL — works for restricted shared files
        _uc_url = (
            f"https://drive.usercontent.google.com/download"
            f"?id={_file_id_from_url}&export=download&authuser=0&confirm=t"
        )
        resp, url = _get(_uc_url, stream=False)
        ct = resp.headers.get("content-type", "")
        if "accounts.google.com" in url:
            raise Exception("Google login required — cookies missing or expired")

        # One more HTML parse on the usercontent page
        if "text/html" in ct:
            body2 = resp.text
            resolved2 = _resolve_html_to_dl_url(body2, url)
            resp.close()
            if resolved2 and resolved2 != url:
                url = resolved2
                resp, url = _get(url, stream=False)
                ct = resp.headers.get("content-type", "")

    if resp.status_code not in (200, 206):
        raise Exception(f"HTTP {resp.status_code}")
    if "text/html" in ct:
        # Peek at the HTML body to give a more specific error
        _err_body = resp.text
        resp.close()
        if "owner" in _err_body and "permission" in _err_body:
            raise Exception(
                "download_disabled_by_owner"
            )
        raise Exception("Got HTML page — auth failed or file not accessible with these cookies")
    resp.close()

    # ── Step 2: stream download (reuse same session — keeps TCP alive) ─────
    stream_resp = _sess.get(url, headers=base_hdrs, stream=True,
                            allow_redirects=True,
                            timeout=(_CONN_TIMEOUT, _READ_TIMEOUT))

    # Populate caller-supplied meta dict with filename / content-type
    if meta_out is not None:
        ct_resp = stream_resp.headers.get("content-type", "")
        cd      = stream_resp.headers.get("content-disposition", "")
        meta_out["content_type"]       = ct_resp
        meta_out["content_disposition"] = cd
        m_fn = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd, re.IGNORECASE)
        if m_fn:
            meta_out["suggested_filename"] = m_fn.group(1).strip().strip('"\'')

    total          = int(stream_resp.headers.get("content-length", 0))
    done           = 0
    t0             = time.time()
    win            = deque(maxlen=12)
    last_dl        = 0
    last_tick      = t0
    last_progress_t = t0

    with open(filepath, "wb") as f:
        for chunk in stream_resp.iter_content(_AUTH_CHUNK):
            if not chunk:
                # Empty chunk — check for stall
                if time.time() - last_progress_t > _STALL_TIMEOUT:
                    stream_resp.close()
                    raise Exception(f"Download stalled — no data for {_STALL_TIMEOUT}s")
                continue
            f.write(chunk)
            done           += len(chunk)
            last_progress_t = time.time()
            if cancel_fn and cancel_fn():
                stream_resp.close()
                raise Exception("Download cancelled by user")
            now = time.time()
            td  = now - last_tick
            if td >= 2 and progress_cb and total:
                win.append((done - last_dl) / max(td, 0.001))
                spd       = sum(win) / len(win)
                ela       = now - t0
                eta       = (total - done) / spd if spd > 0 else float("inf")
                progress_cb(done, total, spd, ela, eta)
                last_dl   = done
                last_tick = now

    if progress_cb:
        progress_cb(done, done, 0, time.time() - t0, 0)

    size = os.path.getsize(filepath)
    if size == 0:
        raise Exception("Downloaded file is empty (auth failed?)")
    print(f"[DL_AUTH] done: {size/1024/1024:.1f} MB in {time.time()-t0:.1f}s")
    return size


_STALL_TIMEOUT = 180  # seconds without progress → abort (90 was too aggressive for large files)
_CONN_TIMEOUT  = 15   # seconds to establish connection
_READ_TIMEOUT  = 120  # seconds max between two data chunks from server


# ─────────────────────────────────────────────────────────────────────────────
#  Playwright Chromium path (pre-installed via Nix)
# ─────────────────────────────────────────────────────────────────────────────
def _find_chromium() -> str | None:
    """
    Auto-detect Chromium/Chrome binary across platforms.
    Priority: hardcoded Nix path → env vars → PATH → Playwright cache → fixed paths.
    NOTE: Never glob /nix/store — it takes 5+ minutes. Use hardcoded path only.
    """
    # 0. Hardcoded Nix/Replit system Chromium (fastest, most reliable on Replit)
    _NIX_CHROMIUM = "/nix/store/qa9cnw4v5xkxyip6mb9kxqfq1z4x2dx1-chromium-138.0.7204.100/bin/chromium"
    if os.path.isfile(_NIX_CHROMIUM) and os.access(_NIX_CHROMIUM, os.X_OK):
        return _NIX_CHROMIUM

    # 1. Explicit env-var override (works on any platform)
    for env in ("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "CHROME_BIN",
                "CHROMIUM_PATH", "GOOGLE_CHROME_BIN", "CHROMIUM_BIN"):
        val = os.environ.get(env, "").strip()
        if val and os.path.isfile(val) and os.access(val, os.X_OK):
            return val

    # 2. Anything already on PATH
    for name in ("chromium", "chromium-browser",
                 "google-chrome", "google-chrome-stable", "google-chrome-beta"):
        found = shutil.which(name)
        if found:
            return found

    # 3. Playwright's own bundled Chromium (~/.cache/ms-playwright or workspace cache)
    _pw_bases = [
        os.path.expanduser("~/.cache/ms-playwright"),
        "/home/runner/workspace/.cache/ms-playwright",
        "/home/runner/.cache/ms-playwright",
    ]
    for base in _pw_bases:
        for pattern in (
            f"{base}/chromium*/chrome-linux64/chrome",
            f"{base}/chromium*/chrome-linux/chrome",
            f"{base}/chromium*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        ):
            matches = sorted(glob.glob(pattern), reverse=True)
            if matches:
                return matches[0]

    # 4. Fixed paths: Docker / Railway / Render / Heroku buildpack / Snap
    for path in (
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/local/bin/chromium",
        "/usr/local/bin/chromium-browser",
        "/app/.apt/usr/bin/google-chrome",
        "/app/.apt/usr/bin/chromium-browser",
        "/snap/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    return None

_PLAYWRIGHT_CHROMIUM = _find_chromium()
print(f"[PLAYWRIGHT] Chromium: {_PLAYWRIGHT_CHROMIUM or 'NOT FOUND'}")

def _drive_pdf_via_playwright(file_id: str, cookies: dict,
                               out_path: str, progress_cb=None, status_cb=None):
    """
    Use headless Chromium to open Drive's PDF viewer, scroll through ALL pages
    so every page image loads into the DOM as a blob: URL, then extract each
    page via canvas (exactly like the user's browser-console JS scripts).
    Also intercepts AKGpih network responses as a secondary source.
    Returns (byte_size, detected_title_or_None).
    """
    from playwright.sync_api import sync_playwright
    from PIL import Image
    import io as _io
    import base64 as _b64

    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0.0.0 Safari/537.36")

    # ── Thread-safe status relay ──────────────────────────────────────────────
    # sync_playwright() runs its own event loop inside the current thread.
    # Calling Pyrogram's edit_text() directly from that context creates an
    # unawaited coroutine ("coroutine was never awaited" warning).
    # Fix: queue messages and call status_cb from a separate relay thread that
    # lives OUTSIDE the Playwright context, where Pyrogram's sync wrapper works.
    _status_q        = _queue_mod.SimpleQueue()
    _RELAY_STOP      = object()          # sentinel to shut down relay thread

    def _relay_worker():
        while True:
            item = _status_q.get()
            if item is _RELAY_STOP:
                break
            try:
                status_cb(item)
            except Exception:
                pass

    _relay_thread = None
    if status_cb:
        _relay_thread = threading.Thread(target=_relay_worker, daemon=True)
        _relay_thread.start()

    def _safe_status(txt):
        """Queue a status message for the relay thread (no-op if no callback)."""
        if status_cb:
            _status_q.put(txt)

    # Network interception — captures AKGpih image responses as they load
    intercepted    = []
    seen_intercept = set()
    _lock          = threading.Lock()

    # JS: extract ALL blob: images via canvas — returns list of {src, data} objects.
    # Only returns images not already in `seen_srcs` (incremental).
    _CANVAS_JS = """(seen_srcs) => {
        const seen = new Set(seen_srcs);
        const results = [];
        const imgs = Array.from(document.querySelectorAll('img'));
        for (const img of imgs) {
            if (!img.src || !img.src.startsWith('blob:')) continue;
            const w = img.naturalWidth  || img.width;
            const h = img.naturalHeight || img.height;
            if (w < 100 || h < 100) continue;
            if (seen.has(img.src)) continue;
            try {
                const c = document.createElement('canvas');
                c.width = w; c.height = h;
                c.getContext('2d').drawImage(img, 0, 0, w, h);
                results.push({src: img.src,
                              data: c.toDataURL('image/jpeg', 1.0),
                              w: w, h: h});
            } catch(e) {}
        }
        return results;
    }"""

    try:
      with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path=_PLAYWRIGHT_CHROMIUM,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-gpu", "--disable-setuid-sandbox"],
        )
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
            device_scale_factor=2,
        )

        # Inject cookies to ALL relevant Google domains for proper auth
        _cookie_domains = [
            "https://drive.google.com",
            "https://docs.google.com",
            "https://accounts.google.com",
            "https://google.com",
            "https://lh3.google.com",
        ]
        for name, value in cookies.items():
            if not name or value is None:
                continue
            for domain_url in _cookie_domains:
                try:
                    ctx.add_cookies([{
                        "name": str(name), "value": str(value),
                        "url":  domain_url,
                    }])
                except Exception:
                    pass

        page = ctx.new_page()

        def _on_response(resp):
            url = resp.url
            # Capture Drive viewer page images (AKGpih tokens OR drive-viewer URLs)
            is_drive_viewer = (
                "AKGpih" in url
                or "drive-viewer" in url
                or ("lh3.google" in url and ("=s" in url or "=w" in url))
            )
            if not is_drive_viewer:
                return
            try:
                body = resp.body()
                ct   = resp.headers.get("content-type", "")
                if "image" not in ct or not body:
                    return
                key = url.split("=s")[0] if "=s" in url else url
                with _lock:
                    if key not in seen_intercept:
                        seen_intercept.add(key)
                        intercepted.append(body)
                        print(f"[PLAYWRIGHT] intercept pg={len(intercepted)}: "
                              f"{len(body)//1024} KB")
            except Exception as _ie:
                print(f"[PLAYWRIGHT] intercept err: {_ie}")

        page.on("response", _on_response)

        _safe_status("🌐 <b>Browser open hai — PDF viewer load ho raha hai…</b>")
        print(f"[PLAYWRIGHT] Loading preview for {file_id}…")
        # Use "domcontentloaded" — Drive is a SPA that never reaches "networkidle".
        # Catch timeout gracefully and continue; intercepted data is already live.
        try:
            page.goto(
                f"https://drive.google.com/file/d/{file_id}/preview",
                wait_until="domcontentloaded", timeout=30_000,
            )
        except Exception as _goto_err:
            print(f"[PLAYWRIGHT] goto warning ({_goto_err}) — continuing anyway")
        # Wait for Drive viewer to initialize and render first page.
        # Strategy: wait for first intercepted page OR blob: img (up to 15 s).
        _waited = 0
        while _waited < 15 and not intercepted:
            page.wait_for_timeout(1000)
            _waited += 1
            # Run canvas check each second so we catch canvas-rendered pages too
            try:
                _blob_check = page.evaluate(
                    "() => document.querySelectorAll('img[src^=\"blob:\"]').length"
                )
                if _blob_check:
                    break
            except Exception:
                pass
        print(f"[PLAYWRIGHT] Viewer init wait: {_waited}s | "
              f"intercept={len(intercepted)}")

        _title = None
        try:
            _title = page.title() or None
            if _title:
                _title = re.sub(r"\s*[-|–]\s*Google.*$", "", _title).strip() or None
        except Exception:
            pass
        print(f"[PLAYWRIGHT] Page loaded | title={_title!r} | "
              f"intercepted so far: {len(intercepted)}")

        # ── Scroll using mouse.wheel() + JS fallback ──────────────────────────
        # Drive embeds the viewer in an iframe — wheel events must land on it.
        # Also dispatch scroll via JS for iframe content window.
        _scroll_js = """() => {
            // Try scrolling the iframe content (Drive PDF viewer)
            const iframes = document.querySelectorAll('iframe');
            for (const f of iframes) {
                try {
                    if (f.contentWindow) {
                        f.contentWindow.scrollBy(0, 600);
                    }
                } catch(e) {}
            }
            // Also scroll the main window
            window.scrollBy(0, 600);
        }"""

        _seen_blob_srcs = []   # blob: URLs already captured via canvas
        canvas_items    = []   # list of raw JPEG bytes in order of capture
        _last_status_pg = [0]  # last page count at which we sent a status update

        def _run_canvas():
            """Extract new blob: images; queue status updates via relay thread."""
            try:
                items = page.evaluate(_CANVAS_JS, _seen_blob_srcs)
                for it in items:
                    src    = it.get("src", "")
                    raw_b64 = it.get("data", "")
                    if not raw_b64:
                        continue
                    try:
                        raw = _b64.b64decode(raw_b64.split(',', 1)[1])
                        canvas_items.append(raw)
                        _seen_blob_srcs.append(src)
                        pg  = len(canvas_items)
                        tot = len(canvas_items) + len(intercepted)
                        print(f"[PLAYWRIGHT] canvas pg={pg}: "
                              f"{len(raw)//1024} KB  {it['w']}×{it['h']}")
                        # Update every 5 pages (or on first page)
                        if pg == 1 or pg - _last_status_pg[0] >= 5:
                            _last_status_pg[0] = pg
                            _safe_status(
                                f"📄 <b>PDF scrape ho raha hai…</b>\n"
                                f"✅ <b>{pg}</b> pages ab tak capture ho gayi\n"
                                f"<i>(scroll jaari hai, thoda wait karein…)</i>"
                            )
                    except Exception:
                        pass
            except Exception as _ce:
                print(f"[PLAYWRIGHT] canvas err: {_ce}")

        # Move mouse to centre of page so wheel events land on the viewer
        page.mouse.move(640, 450)
        try:
            page.mouse.click(640, 450)   # focus the viewer / any iframe
        except Exception:
            pass

        _no_new_for = 0
        _prev_canvas = 0
        for _s in range(400):             # up to 400 wheel ticks
            # Primary: mouse wheel (works if viewer is not in a sandboxed iframe)
            page.mouse.wheel(0, 600)
            # Secondary: JS scroll inside iframes (handles sandboxed iframe case)
            try:
                page.evaluate(_scroll_js)
            except Exception:
                pass
            page.wait_for_timeout(700)    # 0.7 s — enough for IntersectionObserver

            # Extract canvas every 5 steps (or every step near end)
            if _s % 5 == 0 or _no_new_for > 5:
                _run_canvas()

            _cur = len(canvas_items) + len(intercepted)
            if _cur > _prev_canvas:
                _no_new_for = 0
                _prev_canvas = _cur
            else:
                _no_new_for += 1
                if _no_new_for >= 20:     # 20 × 0.7 s = 14 s with no new page
                    print(f"[PLAYWRIGHT] No new page after 14 s — stopping scroll")
                    break

            if _s % 10 == 0:
                print(f"[PLAYWRIGHT] wheel step {_s}: "
                      f"canvas={len(canvas_items)} intercept={len(intercepted)}")

        # Extra wait, then final canvas sweep
        page.wait_for_timeout(2000)
        _run_canvas()
        print(f"[PLAYWRIGHT] Final: canvas={len(canvas_items)} "
              f"intercept={len(intercepted)}")

        browser.close()

    finally:
        # Always shut down relay thread (even on exception)
        if _relay_thread is not None:
            _status_q.put(_RELAY_STOP)
            _relay_thread.join(timeout=8)

    # Use whichever source gave more pages
    if len(canvas_items) >= len(intercepted):
        print(f"[PLAYWRIGHT] Using canvas ({len(canvas_items)} pages) "
              f"vs intercept ({len(intercepted)})")
        raw_pages = canvas_items
    else:
        print(f"[PLAYWRIGHT] Using intercept ({len(intercepted)} pages) "
              f"vs canvas ({len(canvas_items)})")
        raw_pages = intercepted

    if not raw_pages:
        raise Exception("Playwright: no page images captured — "
                        "cookies may be invalid or file is restricted")

    total_pages = len(raw_pages)
    print(f"[PLAYWRIGHT] Stitching {total_pages} pages into PDF…")
    if status_cb:
        try:
            status_cb(
                f"🔗 <b>Saari pages capture ho gayi!</b>\n"
                f"✅ <b>{total_pages}</b> pages — ab ek PDF mein merge kar raha hai…"
            )
        except Exception:
            pass

    imgs = []
    for i, raw in enumerate(raw_pages):
        try:
            img = Image.open(_io.BytesIO(raw))
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            imgs.append(img)
        except Exception as _ie:
            print(f"[PLAYWRIGHT] decode err page {i+1}: {_ie}")

    if not imgs:
        raise Exception("Playwright: images captured but none decoded successfully")

    if len(imgs) == 1:
        imgs[0].save(out_path, "PDF", resolution=300)
    else:
        imgs[0].save(out_path, "PDF", resolution=300,
                     save_all=True, append_images=imgs[1:])

    size = os.path.getsize(out_path)
    print(f"[PLAYWRIGHT] PDF saved: {size//1024} KB, {len(imgs)} page(s)")
    return size, _title


# ─────────────────────────────────────────────────────────────────────────────
#  Viewer-based PDF fallback (for download-disabled Drive PDFs)
#  Works by extracting per-page image tokens from Drive's preview page and
#  stitching them into a PDF via Pillow — no browser needed.
# ─────────────────────────────────────────────────────────────────────────────
def _drive_pdf_via_viewer(file_id: str, cookies: dict, out_path: str,
                          progress_cb=None, status_cb=None):
    """
    Download a Drive PDF that has 'download disabled'.
    Tries Playwright (headless browser, intercepts all page images) first;
    falls back to HTML-token scraping if Playwright fails.

    Returns (byte_size, detected_title_or_None).
    Raises Exception on failure.
    """
    # ── Primary: Playwright headless browser ─────────────────────────────────
    if _PLAYWRIGHT_CHROMIUM and os.path.exists(_PLAYWRIGHT_CHROMIUM):
        try:
            print(f"[VIEWER_PDF] Trying Playwright for fid={file_id}")
            if status_cb:
                try: status_cb("🌐 <b>Browser kholke PDF viewer load ho raha hai…</b>")
                except Exception: pass
            return _drive_pdf_via_playwright(file_id, cookies, out_path,
                                             progress_cb, status_cb)
        except Exception as _pw_err:
            print(f"[VIEWER_PDF] Playwright failed ({_pw_err}), falling back to HTML scrape")
    else:
        print(f"[VIEWER_PDF] Playwright Chromium not found, using HTML scrape")

    # ── Fallback: Thumbnail API + AKGpih token scraping ──────────────────────
    from PIL import Image
    import io as _io

    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0.0.0 Safari/537.36")

    # Build raw Cookie header — sess.cookies.update() silently drops __Secure-*
    # and httpOnly cookies; a raw header string sends ALL of them correctly.
    _cookie_hdr = "; ".join(f"{k}={v}" for k, v in cookies.items()) if cookies else ""

    sess = requests.Session()
    hdrs = {
        "User-Agent":      UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        "Referer":         f"https://drive.google.com/file/d/{file_id}/view",
        "Cookie":          _cookie_hdr,
    }

    def _extract_tokens(html: str):
        raw = re.findall(r'AKGpih[A-Za-z0-9_\-]+', html)
        seen, out = set(), []
        for t in raw:
            if t not in seen:
                seen.add(t); out.append(t)
        return out

    def _extract_page_count(html: str):
        for pat in [
            r'"Page_Count"\s*:\s*(\d+)',
            r'"numPages"\s*:\s*(\d+)',
            r'"page_count"\s*:\s*(\d+)',
            r'"totalPages"\s*:\s*(\d+)',
            r'\\"Page_Count\\":\s*(\d+)',
            r'pageCount["\s:]+(\d+)',
            r'data-page-count=["\'](\d+)["\']',
            r',\"(\d{1,4})\",null,null',
            r'\["Pages"\s*,\s*(\d+)\]',
            r'\"pages\"\s*:\s*(\d+)',
        ]:
            m = re.search(pat, html)
            if m:
                v = int(m.group(1))
                if 1 <= v <= 9999:
                    return v
        return None

    def _extract_title(html: str):
        m = re.search(r'<title>([^<]+)</title>', html, re.I)
        if m:
            t = m.group(1).strip()
            t = re.sub(r'\s*[-–]\s*Google Drive\s*$', '', t, flags=re.I).strip()
            return t or None
        return None

    def _stitch_and_save(imgs: list):
        dpi = 300
        if len(imgs) == 1:
            imgs[0].save(out_path, "PDF", resolution=dpi)
        else:
            imgs[0].save(out_path, "PDF", resolution=dpi,
                         save_all=True, append_images=imgs[1:])
        size = os.path.getsize(out_path)
        print(f"[VIEWER_PDF] done: {size/1024/1024:.2f} MB, {len(imgs)} page(s) @ {dpi} DPI")
        return size

    # ── Step 1: Fetch preview to get page count + title ───────────────────────
    prev_url = f"https://drive.google.com/file/d/{file_id}/preview"
    r = sess.get(prev_url, headers=hdrs, timeout=25, allow_redirects=True)
    if r.status_code not in (200, 401):
        raise Exception(f"Preview page returned HTTP {r.status_code}")
    body           = r.text if r.status_code == 200 else ""
    page_count     = _extract_page_count(body) if body else None
    detected_title = _extract_title(body) if body else None
    print(f"[VIEWER_PDF] fid={file_id} | page_count={page_count} title={detected_title!r}")

    # ── Strategy A: Drive Thumbnail API ──────────────────────────────────────
    # NOTE: For download-disabled PDFs, Google returns the same cover image for
    # every page number. We detect duplicates via MD5 hash and abort early.
    import hashlib as _hashlib
    print("[VIEWER_PDF] Strategy A: Drive Thumbnail API (page-by-page)…")
    if status_cb:
        try: status_cb("📄 <b>PDF pages download ho rahi hain…</b>")
        except Exception: pass
    _thumb_images    = []
    _thumb_hashes    = []          # MD5 of each raw response body
    _max_pages       = page_count if page_count and page_count <= 500 else 500
    _t0              = time.time()
    _consecutive_fail = 0
    _dupe_count      = 0           # consecutive identical-content pages
    _last_status_t   = [0]
    _thumb_ok        = False       # True when ≥2 distinct page images found
    for pg in range(1, _max_pages + 1):
        _thumb_url = (
            f"https://drive.google.com/thumbnail"
            f"?id={file_id}&authuser=0&sz=s4096&page={pg}"
        )
        try:
            r_t = sess.get(_thumb_url, headers=hdrs, timeout=40, allow_redirects=True)
            ct  = r_t.headers.get("content-type", "")
            if r_t.status_code == 200 and "image" in ct:
                _h = _hashlib.md5(r_t.content).hexdigest()

                # ── Duplicate detection ──────────────────────────────────────
                # Google recycles the cover thumbnail for every page when
                # the file is download-restricted.  If page 2 onwards all hash
                # to the same value as page 1, abort thumbnail strategy.
                if pg == 1:
                    _first_hash = _h
                else:
                    if _h == _first_hash:
                        _dupe_count += 1
                        if _dupe_count >= 2:
                            print(
                                f"[VIEWER_PDF] thumb pg={pg}: duplicate cover "
                                f"(3 identical in a row) — thumbnail strategy aborted"
                            )
                            _thumb_images.clear()   # discard duplicates
                            break
                    else:
                        _dupe_count = 0
                        _thumb_ok = True

                img = Image.open(_io.BytesIO(r_t.content))
                if img.mode in ("RGBA", "P", "LA"):
                    img = img.convert("RGB")
                _thumb_images.append(img)
                _thumb_hashes.append(_h)
                _consecutive_fail = 0
                _now = time.time()
                if status_cb and (_now - _last_status_t[0] >= 3 or pg == 1):
                    _last_status_t[0] = _now
                    _total_lbl = f"/{page_count}" if page_count else ""
                    try:
                        status_cb(
                            f"📄 <b>PDF extract ho raha hai…</b>\n"
                            f"Page <b>{pg}{_total_lbl}</b> download ho gayi"
                        )
                    except Exception: pass
                if progress_cb:
                    elapsed = time.time() - _t0
                    progress_cb(pg * len(r_t.content), _max_pages * len(r_t.content),
                                len(r_t.content) / max(elapsed / pg, 0.1), elapsed, 0)
                print(f"[VIEWER_PDF] thumb pg={pg}: {img.size[0]}x{img.size[1]} "
                      f"({len(r_t.content)//1024} KB) hash={_h[:8]}")
            else:
                _consecutive_fail += 1
                print(f"[VIEWER_PDF] thumb pg={pg}: HTTP {r_t.status_code} ct={ct[:40]}")
                if _consecutive_fail >= 2:
                    print(f"[VIEWER_PDF] 2 consecutive fails — thumbnail strategy done")
                    break
        except Exception as _te:
            _consecutive_fail += 1
            print(f"[VIEWER_PDF] thumb pg={pg} error: {_te}")
            if _consecutive_fail >= 2:
                break

    # Only use thumbnail results if we got distinct per-page images
    _thumb_valid = _thumb_images and (_thumb_ok or page_count)
    if _thumb_valid and (not page_count or len(_thumb_images) >= page_count):
        print(f"[VIEWER_PDF] Thumbnail API success: {len(_thumb_images)} pages")
        if status_cb:
            try:
                status_cb(
                    f"🔗 <b>{len(_thumb_images)} pages merge ho rahi hain…</b>"
                )
            except Exception: pass
        return _stitch_and_save(_thumb_images), detected_title

    if _thumb_valid:
        print(f"[VIEWER_PDF] Thumbnail got {len(_thumb_images)}/{page_count} — "
              f"trying AKGpih tokens to fill gaps…")
    else:
        print(f"[VIEWER_PDF] Thumbnail API returned duplicates or no pages — "
              f"skipping to token/Playwright strategy")

    # ── Strategy B: AKGpih token scraping ─────────────────────────────────────
    # Extracts per-page tokens from Drive preview HTML, then fetches images.
    print("[VIEWER_PDF] Strategy B: AKGpih token scraping…")
    page_tokens = _extract_tokens(body)
    seen_tokens = set(page_tokens)
    print(f"[VIEWER_PDF] Initial tokens from preview: {len(page_tokens)}")

    _page_url_templates = [
        "https://drive.google.com/file/d/{fid}/preview?cp={pg}",
        "https://drive.google.com/file/d/{fid}/preview?page={pg}",
        "https://drive.google.com/file/d/{fid}/preview?p={pg}",
        "https://drive.google.com/file/d/{fid}/preview?pg={pg}",
    ]
    _stop_after = (page_count or 50) + 2
    for pg in range(2, min(_stop_after, 502)):
        got_new = False
        for tmpl in _page_url_templates:
            try:
                rp = sess.get(tmpl.format(fid=file_id, pg=pg),
                              headers=hdrs, timeout=20)
                if rp.status_code != 200:
                    continue
                new_toks = _extract_tokens(rp.text)
                param    = tmpl.split("?")[1].split("=")[0]
                for t in new_toks:
                    if t not in seen_tokens:
                        seen_tokens.add(t); page_tokens.append(t)
                        got_new = True
                        print(f"[VIEWER_PDF] nav pg={pg} {param}: {t[:40]}")
                if got_new:
                    break
            except Exception as _ne:
                print(f"[VIEWER_PDF] nav pg={pg} error: {_ne}")
        if not got_new:
            print(f"[VIEWER_PDF] No new token at pg={pg} — stopping nav")
            break

    print(f"[VIEWER_PDF] Token total: {len(page_tokens)} (need {page_count})")

    token_images = []
    _t0 = time.time()
    for i, tok in enumerate(page_tokens):
        img_url = f"https://drive.google.com/u/0/drive-viewer/{tok}=s4096-rw-v1"
        try:
            r_img = sess.get(img_url, headers=hdrs, timeout=40)
            if r_img.status_code != 200 or "image" not in r_img.headers.get("content-type", ""):
                print(f"[VIEWER_PDF] token pg={i+1} HTTP {r_img.status_code}, skip")
                continue
            img = Image.open(_io.BytesIO(r_img.content))
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            token_images.append(img)
            if progress_cb:
                elapsed = time.time() - _t0
                done    = (i + 1) * len(r_img.content)
                total_e = done * len(page_tokens) // (i + 1)
                progress_cb(done, total_e,
                            len(r_img.content) / max(elapsed / (i + 1), 0.1),
                            elapsed, 0)
            print(f"[VIEWER_PDF] token pg={i+1}/{len(page_tokens)}: "
                  f"{img.size[0]}x{img.size[1]} px ({len(r_img.content)//1024} KB)")
        except Exception as pe:
            print(f"[VIEWER_PDF] token pg={i+1} error: {pe}")

    # Use whichever strategy gave more pages
    best = token_images if len(token_images) >= len(_thumb_images) else _thumb_images
    if not best:
        raise Exception(
            "Koi bhi page download nahi hua — cookies expire ho gayi hain "
            "ya file accessible nahi hai."
        )

    print(f"[VIEWER_PDF] Using best result: {len(best)} pages "
          f"(token={len(token_images)}, thumb={len(_thumb_images)})")
    return _stitch_and_save(best), detected_title


def download_part(url, cookies, lock, start, end, part_file, prog, num, session):
    hdrs = {"Range": f"bytes={start}-{end}", "Connection": "keep-alive"}
    done = 0
    if os.path.exists(part_file):
        done = os.path.getsize(part_file)
        if done:
            hdrs["Range"] = f"bytes={start+done}-{end}"
            with lock: prog["downloaded"] += done
    if done >= (end - start + 1):
        return
    resp = session.get(url, stream=True, headers=hdrs,
                       timeout=(_CONN_TIMEOUT, _READ_TIMEOUT))
    if resp.status_code not in (200, 206):
        raise Exception(f"Part {num} status {resp.status_code}")
    mode = "ab" if done else "wb"
    last_progress = time.time()
    with open(part_file, mode) as f:
        for chunk in resp.iter_content(chunk_size=PROGRESS_CHUNK):
            if chunk:
                f.write(chunk);  done += len(chunk)
                with lock: prog["downloaded"] += len(chunk)
                last_progress = time.time()
                if done >= (end - start + 1): break
            elif time.time() - last_progress > _STALL_TIMEOUT:
                raise Exception(f"Part {num} stalled — no data for {_STALL_TIMEOUT}s")


def _part_wrapper(url, cookies, lock, start, end, part_file, prog, num, session):
    try:
        download_part(url, cookies, lock, start, end, part_file, prog, num, session)
    except Exception as e:
        thread_errors.append(e)


def merge_parts(parts, out):
    missing = [p for p in parts if not os.path.exists(p)]
    if missing:
        raise Exception(f"Merge fail — {len(missing)} part(s) missing: {missing[:3]}")
    try:
        with open(out, "wb") as o:
            for p in parts:
                with open(p, "rb") as f:
                    shutil.copyfileobj(f, o, length=CHUNK_SIZE)
    except Exception:
        try: os.remove(out)
        except Exception: pass
        raise
    finally:
        for p in parts:
            try: os.remove(p)
            except Exception: pass


def download_file(url, cookies, filepath, progress_cb=None,
                  num_threads: int = 16, cancel_fn=None):
    """Multi-threaded Drive download. cancel_fn() → True stops the download."""
    local_errors = []   # per-call list — avoids race condition with global thread_errors
    session    = _make_session(num_threads, cookies)
    total_size = get_file_size(url, cookies)
    if total_size == 0:
        return _download_single(url, cookies, filepath, progress_cb, total_size, session,
                                cancel_fn=cancel_fn)

    part_size = math.ceil(total_size / num_threads)
    parts, threads, lock, prog = [], [], threading.Lock(), {"downloaded": 0}

    def _local_part_wrapper(url, cookies, lock, start, end, pf, prog, i, session):
        try:
            download_part(url, cookies, lock, start, end, pf, prog, i, session)
        except Exception as e:
            local_errors.append(e)

    for i in range(num_threads):
        s_byte = i * part_size
        e_byte = min(s_byte + part_size - 1, total_size - 1)
        pf     = f"{filepath}.part{i}"
        parts.append(pf)
        t = threading.Thread(
            target=_local_part_wrapper,
            args=(url, cookies, lock, s_byte, e_byte, pf, prog, i, session),
            daemon=True,
        )
        threads.append(t);  t.start()

    t0 = time.time();  win = deque(maxlen=8);  last_dl, last_tick = 0, t0
    last_progress_t = t0   # time when bytes last increased

    while any(t.is_alive() for t in threads):
        # Poll every 0.25 s so /cancel fires near-instantly
        for _ in range(8):
            time.sleep(0.25)
            if cancel_fn and cancel_fn():
                raise Exception("Download cancelled by user")
        now = time.time()
        cur = prog["downloaded"]
        td  = now - last_tick
        if td: win.append((cur - last_dl) / max(td, 0.001))
        avg = sum(win) / len(win) if win else 0
        ela = now - t0;  eta = (total_size - cur) / avg if avg else float("inf")
        if cur > last_dl:
            last_progress_t = now    # bytes advanced — reset stall timer
        elif now - last_progress_t > _STALL_TIMEOUT:
            raise Exception(f"Download stalled — no progress for {_STALL_TIMEOUT}s")
        last_dl, last_tick = cur, now
        if progress_cb: progress_cb(cur, total_size, avg, ela, eta)
        if local_errors: raise Exception(f"Download failed: {local_errors[0]}")

    for t in threads: t.join(timeout=10)   # don't block forever
    if local_errors: raise Exception(f"Download failed: {local_errors[0]}")
    got = sum(os.path.getsize(p) for p in parts if os.path.exists(p))
    if got < total_size: raise Exception(f"Incomplete: {got}/{total_size} bytes")
    if progress_cb: progress_cb(total_size, total_size, 0, time.time() - t0, 0)
    merge_parts(parts, filepath)
    return total_size


def _download_single(url, cookies, filepath, progress_cb, total_size=0, session=None,
                     cancel_fn=None):
    if not session:
        session = _make_session(cookies=cookies)
    elif cookies:
        session.cookies.update(cookies)
    hdrs, mode, done = {}, "wb", 0
    if os.path.exists(filepath):
        done = os.path.getsize(filepath);  hdrs["Range"] = f"bytes={done}-";  mode = "ab"
    resp = session.get(url, stream=True, headers=hdrs,
                       timeout=(_CONN_TIMEOUT, _READ_TIMEOUT))
    if resp.status_code not in (200, 206):
        raise Exception(f"Status {resp.status_code}")
    if not total_size:
        total_size = int(resp.headers.get("content-length", 0)) + done
    t0 = time.time();  win = deque(maxlen=8);  last_dl, last_tick = done, t0
    last_progress_t = t0
    with open(filepath, mode) as f:
        for chunk in resp.iter_content(chunk_size=PROGRESS_CHUNK):
            if cancel_fn and cancel_fn():
                resp.close()
                raise Exception("Download cancelled by user")
            if chunk:
                f.write(chunk);  done += len(chunk)
                last_progress_t = time.time()
                now = time.time();  td = now - last_tick
                if td >= 2 and progress_cb:
                    win.append((done - last_dl) / max(td, 0.001))
                    avg = sum(win) / len(win)
                    ela = now - t0;  eta = (total_size - done) / avg if avg else float("inf")
                    progress_cb(done, total_size, avg, ela, eta)
                    last_dl, last_tick = done, now
            elif time.time() - last_progress_t > _STALL_TIMEOUT:
                raise Exception(f"Download stalled — no data for {_STALL_TIMEOUT}s")
    if progress_cb: progress_cb(total_size, total_size, 0, time.time() - t0, 0)
    return total_size


# ─────────────────────────────────────────────
#  Upload core
# ─────────────────────────────────────────────

def _do_upload(client, message, uid, filepath, valid_title,
               file_size, meta, thumb_path, upload_type, edit_fn,
               file_index=1, total_files=1):
    st = {"last": 0, "t0": time.time(), "prev_bytes": 0, "prev_t": time.time(),
          "win": deque(maxlen=12)}

    def on_progress(cur, total_b):
        now = time.time()
        td  = now - st["last"]
        if td < 2: return
        # Speed = bytes uploaded since last tick / seconds since last tick
        delta = cur - st["prev_bytes"]
        dt    = now  - st["prev_t"]
        if delta > 0 and dt > 0:
            st["win"].append(delta / dt)
        st["last"]        = now
        st["prev_bytes"]  = cur
        st["prev_t"]      = now
        spd  = sum(st["win"]) / len(st["win"]) if st["win"] else 0
        ela  = now - st["t0"]
        eta  = (total_b - cur) / spd if spd > 0 else float("inf")
        cpu, ram = get_system_stats()
        edit_fn(draw_upload_card(
            valid_title, total_b, cur, spd, ela, eta, cpu, ram,
            file_index, total_files,
        ), CANCEL_KB)

    cpu0, ram0 = get_system_stats()
    edit_fn(draw_upload_card(valid_title, file_size, 0, 0, 0, float("inf"),
                             cpu0, ram0, file_index, total_files), CANCEL_KB)

    # ── Apply global file tag (admin-controlled) ──────────────────────────
    _orig_bn = os.path.basename(filepath)
    _tagged_bn = _apply_file_tag(_orig_bn)
    if _tagged_bn != _orig_bn:
        _new_fp = os.path.join(os.path.dirname(filepath), _tagged_bn)
        try:
            os.rename(filepath, _new_fp)
            filepath = _new_fp
            valid_title = os.path.splitext(_tagged_bn)[0]
        except Exception as _tag_err:
            print(f"[TAG] Rename failed: {_tag_err}")

    tpl  = db.get_caption_template(uid)
    _ext = os.path.splitext(filepath)[1].lower()
    is_video  = _ext in VIDEO_EXTENSIONS
    is_image  = _ext in IMAGE_EXTENSIONS
    is_audio  = _ext in AUDIO_EXTENSIONS

    # ── Auto-enrich metadata when caller didn't supply it ─────────────────
    # (Happens for files downloaded via the doc path — meta={} by default)
    if is_video and not (meta.get("duration") or meta.get("width")):
        try:
            meta = get_video_metadata(filepath)
            print(f"[UPLOAD] Video meta auto-extracted: {meta}")
        except Exception:
            pass

    if is_video and not thumb_path:
        _auto_thumb = os.path.join(THUMBS_DIR, f"_vthumb_{os.path.basename(filepath)}.jpg")
        try:
            if extract_thumbnail(filepath, _auto_thumb, meta.get("duration", 0)):
                thumb_path = _auto_thumb
                print(f"[UPLOAD] Auto video thumbnail extracted")
        except Exception:
            pass

    if is_audio and not meta.get("duration"):
        try:
            _am = _extract_audio_meta(filepath)
            meta = {**meta, **_am}
            print(f"[UPLOAD] Audio meta auto-extracted: dur={meta.get('duration')}s "
                  f"title={meta.get('title')!r} by={meta.get('performer')!r}")
        except Exception:
            pass

    # ── Caption (built AFTER metadata enrichment) ─────────────────────────
    dur_str  = ""
    res_str  = ""
    if meta.get("duration"):
        m_, s_ = divmod(meta["duration"], 60)
        dur_str = f"{m_}m {s_:02d}s"
    if meta.get("width") and meta.get("height"):
        res_str = f"{meta['width']}×{meta['height']}"

    if is_video:  _ftype_str = "Video"
    elif is_audio: _ftype_str = "Audio"
    elif is_image: _ftype_str = "Image"
    else:          _ftype_str = "Document"

    if tpl:
        caption = _render_caption(
            tpl,
            filename=valid_title,
            size=format_size(file_size),
            file_type=_ftype_str,
            mimetype=meta.get("mimetype", ""),
            duration=dur_str,
            resolution=res_str,
        )
    else:
        # Per-type emoji + metadata in caption
        if is_video:
            caption = f"🎬 <b>{h(valid_title)}</b>\n📦 <b>Size:</b> {format_size(file_size)}"
            if dur_str: caption += f"\n⏱ <b>Duration:</b> {dur_str}"
            if res_str: caption += f"\n📐 <b>Resolution:</b> {res_str}"
        elif is_audio:
            caption = f"🎵 <b>{h(valid_title)}</b>\n📦 <b>Size:</b> {format_size(file_size)}"
            if dur_str: caption += f"\n⏱ <b>Duration:</b> {dur_str}"
            if meta.get("performer"): caption += f"\n🎤 <b>Artist:</b> {h(meta['performer'])}"
        elif is_image:
            caption = f"🖼 <b>{h(valid_title)}</b>\n📦 <b>Size:</b> {format_size(file_size)}"
        else:
            caption = f"📄 <b>{h(valid_title)}</b>\n📦 <b>Size:</b> {format_size(file_size)}"

    if is_video:
        return client.send_video(
            message.chat.id, filepath, caption=caption,
            parse_mode=enums.ParseMode.HTML,
            thumb=thumb_path, duration=meta.get("duration", 0),
            width=meta.get("width", 0), height=meta.get("height", 0),
            supports_streaming=True, progress=on_progress,
        )
    if is_image:
        # Telegram rejects send_photo for files > 10 MB — fall back to document
        if file_size > 10 * 1024 * 1024:
            print(f"[UPLOAD] Image > 10 MB ({file_size//1024//1024} MB) — sending as document")
            return client.send_document(
                message.chat.id, filepath, caption=caption,
                parse_mode=enums.ParseMode.HTML,
                thumb=thumb_path, progress=on_progress,
            )
        # Re-encode image as proper JPEG/PNG using Pillow before send_photo.
        # This fixes IMAGE_PROCESS_FAILED when Drive returns WebP/CMYK/corrupt data.
        _reencoded_path = None
        try:
            from PIL import Image as _PILImage
            _img = _PILImage.open(filepath)
            # Convert CMYK / palette / other modes → RGB (required for JPEG)
            if _img.mode not in ("RGB", "RGBA", "L"):
                _img = _img.convert("RGB")
            _reencoded_path = filepath + "_re.jpg"
            if _img.mode == "RGBA":
                _reencoded_path = filepath + "_re.png"
                _img.save(_reencoded_path, "PNG", optimize=True)
            else:
                if _img.mode != "RGB":
                    _img = _img.convert("RGB")
                _img.save(_reencoded_path, "JPEG", quality=92, optimize=True)
            _img.close()
            print(f"[UPLOAD] Image re-encoded → {os.path.basename(_reencoded_path)}")
        except Exception as _re_err:
            print(f"[UPLOAD] Image re-encode skipped ({_re_err})")
            _reencoded_path = None

        _photo_src = _reencoded_path or filepath
        try:
            result = client.send_photo(
                message.chat.id, _photo_src, caption=caption,
                parse_mode=enums.ParseMode.HTML,
                progress=on_progress,
            )
            return result
        except Exception as _photo_err:
            print(f"[UPLOAD] send_photo failed ({_photo_err}) — falling back to document")
            return client.send_document(
                message.chat.id, filepath, caption=caption,
                parse_mode=enums.ParseMode.HTML,
                thumb=thumb_path, progress=on_progress,
            )
        finally:
            if _reencoded_path and os.path.exists(_reencoded_path):
                try: os.remove(_reencoded_path)
                except Exception: pass
    if is_audio:
        return client.send_audio(
            message.chat.id, filepath, caption=caption,
            parse_mode=enums.ParseMode.HTML,
            duration=meta.get("duration", 0),
            performer=meta.get("performer", ""),
            title=meta.get("title", "") or os.path.splitext(valid_title)[0],
            thumb=thumb_path, progress=on_progress,
        )
    return client.send_document(
        message.chat.id, filepath, caption=caption,
        parse_mode=enums.ParseMode.HTML,
        thumb=thumb_path, progress=on_progress,
    )


def _do_ftm_upload(filepath, valid_title, file_size, meta, thumb_path,
                   upload_type, edit_fn, file_index=1, total_files=1, log_fn=None,
                   cancel_fn=None):
    """Upload a large file (2–4 GB) via FTM session directly to DUMP_CHANNEL.

    Uses asyncio.run() + async with Client() inside a dedicated thread.
    Each call gets a fully isolated event loop — zero cross-loop issues.
    """
    import asyncio as _asyncio

    if not DUMP_CHANNEL_ID:
        raise RuntimeError("DUMP_CHANNEL_ID set nahi hai.")

    session_str = db.get_ftm_session()
    if not session_str:
        raise RuntimeError("FTM session nahi hai. Admin /ftmsession se set kare.")

    # ── Apply global file tag (admin-controlled) ──────────────────────────
    _orig_bn = os.path.basename(filepath)
    _tagged_bn = _apply_file_tag(_orig_bn)
    if _tagged_bn != _orig_bn:
        _new_fp = os.path.join(os.path.dirname(filepath), _tagged_bn)
        try:
            os.rename(filepath, _new_fp)
            filepath = _new_fp
            valid_title = os.path.splitext(_tagged_bn)[0]
        except Exception as _tag_err:
            print(f"[TAG] FTM rename failed: {_tag_err}")

    sz_str = format_size(file_size)
    print(f"[FTM_UPLOAD] START  '{valid_title}'  size={sz_str}  index={file_index}/{total_files}")

    # Stop persistent client so same session isn't used twice simultaneously
    stop_ftm_client()

    # ── Shared progress state (written by Pyrogram callback, read by UI thread) ──
    st = {
        "cur": 0, "total": file_size, "t0": time.time(),
        "prev_bytes": 0, "prev_t": time.time(),
        "win": deque(maxlen=12),
        "milestones": {10: False, 25: False, 50: False, 75: False, 90: False},
        "done": False,
    }

    def on_progress(cur, total_b):
        delta = cur - st["prev_bytes"]
        dt    = time.time() - st["prev_t"]
        if delta > 0 and dt > 0:
            st["win"].append(delta / dt)
        st["cur"]        = cur
        st["total"]      = total_b or file_size
        st["prev_bytes"] = cur
        st["prev_t"]     = time.time()
        spd     = sum(st["win"]) / len(st["win"]) if st["win"] else 0
        ela     = time.time() - st["t0"]
        pct_int = int(cur / total_b * 100) if total_b else 0
        for m in [10, 25, 50, 75, 90]:
            if not st["milestones"][m] and pct_int >= m:
                st["milestones"][m] = True
                ela_str = f"{int(ela)//60}m {int(ela)%60:02d}s"
                spd_str = format_speed(spd)
                print(f"[FTM_UPLOAD] {m:3d}%  {format_size(cur)}/{format_size(total_b)}"
                      f"  spd={spd_str}  ela={ela_str}  '{valid_title}'")
                if log_fn:
                    log_fn(
                        f"📊 #FTM_Progress {m}%\n\n"
                        f"📄 File: <code>{h(valid_title)}</code>\n"
                        f"📦 {format_size(cur)} / {format_size(total_b)}\n"
                        f"⚡ Speed: {spd_str}\n"
                        f"⏱ Elapsed: {ela_str}\n"
                        f"⏰ {_now_str()}"
                    )

    # ── UI progress thread — edits Telegram status message every 3 s ──
    def _progress_loop():
        last_edit = 0
        while not st["done"]:
            time.sleep(1)
            now = time.time()
            if now - last_edit < 3:
                continue
            last_edit = now
            cur     = st["cur"]
            total_b = st["total"]
            spd     = sum(st["win"]) / len(st["win"]) if st["win"] else 0
            ela     = now - st["t0"]
            eta     = (total_b - cur) / spd if spd > 0 else float("inf")
            cpu, ram = get_system_stats()
            try:
                edit_fn(draw_upload_card(valid_title, total_b, cur, spd, ela, eta,
                                         cpu, ram, file_index, total_files))
            except Exception:
                pass

    _prog_thread = threading.Thread(target=_progress_loop, daemon=True)
    _prog_thread.start()

    # ── Caption ──
    caption = f"🎬 <b>{h(valid_title)}</b>\n📦 <b>Size:</b> {sz_str}"
    if meta.get("duration"):
        m_, s_ = divmod(meta["duration"], 60)
        caption += f"\n⏱ <b>Duration:</b> {m_}m {s_:02d}s"
    if meta.get("width") and meta.get("height"):
        caption += f"\n📐 <b>Resolution:</b> {meta['width']}×{meta['height']}"

    _ext      = os.path.splitext(filepath)[1].lower()
    is_video  = _ext in VIDEO_EXTENSIONS
    is_audio  = _ext in AUDIO_EXTENSIONS
    is_image  = _ext in IMAGE_EXTENSIONS

    # ── Auto-enrich metadata (same as _do_upload) ─────────────────────────
    if is_video and not (meta.get("duration") or meta.get("width")):
        try:
            meta = get_video_metadata(filepath)
        except Exception:
            pass
    if is_video and not thumb_path:
        _auto_thumb = os.path.join(THUMBS_DIR, f"_vthumb_{os.path.basename(filepath)}.jpg")
        try:
            if extract_thumbnail(filepath, _auto_thumb, meta.get("duration", 0)):
                thumb_path = _auto_thumb
        except Exception:
            pass
    if is_audio and not meta.get("duration"):
        try:
            _am = _extract_audio_meta(filepath)
            meta = {**meta, **_am}
        except Exception:
            pass

    # Rebuild caption with enriched meta
    caption = f"🎬 <b>{h(valid_title)}</b>\n📦 <b>Size:</b> {sz_str}"
    if meta.get("duration"):
        m_, s_ = divmod(meta["duration"], 60)
        caption += f"\n⏱ <b>Duration:</b> {m_}m {s_:02d}s"
    if meta.get("width") and meta.get("height"):
        caption += f"\n📐 <b>Resolution:</b> {meta['width']}×{meta['height']}"

    kind = "video" if is_video else "audio" if is_audio else "image" if is_image else "document"
    print(f"[FTM_UPLOAD] send_{kind}() → DUMP_CHANNEL {DUMP_CHANNEL_ID}")

    # ── The actual upload coroutine ──
    # async with Client + asyncio.run() = fully self-contained event loop,
    # no interaction with the bot's main loop whatsoever.
    async def _upload_coro():
        async with Client(
            "ftm_upload_session",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=session_str,
            in_memory=True,
            no_updates=True,
        ) as fc:
            if is_video:
                return await fc.send_video(
                    DUMP_CHANNEL_ID, filepath,
                    caption=caption, parse_mode=enums.ParseMode.HTML,
                    thumb=thumb_path, duration=meta.get("duration", 0),
                    width=meta.get("width", 0), height=meta.get("height", 0),
                    supports_streaming=True, progress=on_progress,
                )
            if is_audio:
                return await fc.send_audio(
                    DUMP_CHANNEL_ID, filepath,
                    caption=caption, parse_mode=enums.ParseMode.HTML,
                    duration=meta.get("duration", 0),
                    performer=meta.get("performer", ""),
                    title=meta.get("title", "") or os.path.splitext(valid_title)[0],
                    thumb=thumb_path, progress=on_progress,
                )
            if is_image:
                # Large images (>10MB) → send as document
                if file_size > 10 * 1024 * 1024:
                    return await fc.send_document(
                        DUMP_CHANNEL_ID, filepath,
                        caption=caption, parse_mode=enums.ParseMode.HTML,
                        thumb=thumb_path, progress=on_progress,
                    )
                return await fc.send_photo(
                    DUMP_CHANNEL_ID, filepath,
                    caption=caption, parse_mode=enums.ParseMode.HTML,
                    progress=on_progress,
                )
            return await fc.send_document(
                DUMP_CHANNEL_ID, filepath,
                caption=caption, parse_mode=enums.ParseMode.HTML,
                thumb=thumb_path, progress=on_progress,
            )

    # ── Run upload coroutine in the BOT's own event loop ──────────────────────
    # asyncio.run() creates a fresh loop which causes cross-loop Future errors
    # inside Pyrogram's save_file() — sessions attach futures to one loop but
    # they get awaited in another, silently stalling at 0 bytes forever.
    # Fix: schedule the coroutine in bot.loop (same loop Pyrogram already uses)
    # via run_coroutine_threadsafe(), then poll from this sync handler thread.
    import concurrent.futures as _cf

    coro_future = _asyncio.run_coroutine_threadsafe(_upload_coro(), bot.loop)

    # ── Monitor: heartbeat, stall detection, cancel ──
    STALL_TIMEOUT    = 120
    last_prog_bytes  = -1
    last_prog_t      = time.time()
    last_heartbeat_t = time.time()
    deadline         = time.time() + 7200

    try:
        while True:
            # Wait up to 2 s for the coroutine to finish; TimeoutError = still running
            try:
                _result_msg = coro_future.result(timeout=2)
                break  # upload completed successfully
            except _cf.TimeoutError:
                pass   # not done yet — fall through to monitoring checks
            except _cf.CancelledError:
                raise RuntimeError("FTM upload cancelled")
            except Exception:
                raise  # propagate upload errors (Pyrogram exceptions, etc.)

            cur_bytes = st["cur"]
            now       = time.time()
            ela       = now - st["t0"]

            if now - last_heartbeat_t >= 60:
                last_heartbeat_t = now
                spd = sum(st["win"]) / len(st["win"]) if st["win"] else 0
                pct = int(cur_bytes / file_size * 100) if file_size else 0
                print(f"[FTM_UPLOAD] ⏳ heartbeat {pct}%  "
                      f"{format_size(cur_bytes)}/{sz_str}  spd={format_speed(spd)}  "
                      f"ela={int(ela)//60}m{int(ela)%60:02d}s  '{valid_title}'")

            if cur_bytes != last_prog_bytes:
                last_prog_bytes = cur_bytes
                last_prog_t     = now
            elif cur_bytes == 0 and now - st["t0"] < 60:
                pass  # grace period while connecting
            elif now - last_prog_t > STALL_TIMEOUT:
                stall_msg = (f"FTM upload stalled {STALL_TIMEOUT}s — "
                             f"{format_size(cur_bytes)}/{sz_str}")
                print(f"[FTM_UPLOAD] ⚠️ STALL — {stall_msg}")
                coro_future.cancel()
                raise RuntimeError(stall_msg)

            if cancel_fn and cancel_fn():
                print(f"[FTM_UPLOAD] 🚫 Cancelled — '{valid_title}'")
                coro_future.cancel()
                raise RuntimeError("FTM upload cancelled by user")

            if now > deadline:
                coro_future.cancel()
                raise RuntimeError("FTM upload timed out after 2 hours")

        ela_total = time.time() - st["t0"]
        ela_str   = f"{int(ela_total)//60}m {int(ela_total)%60:02d}s"
        print(f"[FTM_UPLOAD] ✅ DONE  '{valid_title}'  elapsed={ela_str}  "
              f"msg_id={getattr(_result_msg, 'id', '?')}")
        return _result_msg

    finally:
        st["done"] = True
        _prog_thread.join(timeout=5)


# ── Large-file splitter ───────────────────────────────────────────────────────
SPLIT_PART_SIZE     = 3_900 * 1024 * 1024   # 3.9 GB per part — safe under Telegram's 4 GB limit (FTM)
SPLIT_BOT_PART_SIZE = 1_900 * 1024 * 1024   # 1.9 GB per part — safe under bot's 2 GB limit (no FTM)

def split_large_file(filepath: str, part_size: int = SPLIT_PART_SIZE) -> list:
    """
    Split a file that is too large for Telegram (> 4 GB) into ≤3.9 GB parts.

    - Video / audio: FFmpeg ``-c copy -f segment`` — no re-encode, splits at keyframes.
    - Everything else: raw binary chunk split.

    Returns an ordered list of part file paths.  Caller owns cleanup.
    """
    ext       = os.path.splitext(filepath)[1].lower()
    base_ne   = os.path.splitext(filepath)[0]
    is_av     = ext in (VIDEO_EXTENSIONS | AUDIO_EXTENSIONS)

    if is_av and _FFMPEG:
        pattern = base_ne + "_part%03d" + ext
        cmd = [
            _FFMPEG, "-y", "-i", filepath,
            "-c", "copy",
            "-f", "segment",
            "-segment_size", str(part_size),
            "-reset_timestamps", "1",
            "-avoid_negative_ts", "1",
            pattern,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
            if r.returncode == 0:
                parts = sorted(glob.glob(base_ne + "_part*" + ext))
                if parts:
                    print(f"[SPLIT] FFmpeg produced {len(parts)} parts for '{os.path.basename(filepath)}'")
                    return parts
            print(f"[SPLIT] FFmpeg non-zero ({r.returncode}) — falling back to binary split\n{r.stderr[-300:]}")
        except Exception as _se:
            print(f"[SPLIT] FFmpeg error: {_se} — falling back to binary split")

    # Binary split fallback (works for any file type)
    parts     = []
    part_idx  = 0
    file_size = os.path.getsize(filepath)
    print(f"[SPLIT] Binary split '{os.path.basename(filepath)}' "
          f"({format_size(file_size)}) into {part_size//1024//1024} MB parts")
    with open(filepath, "rb") as fin:
        while True:
            chunk = fin.read(part_size)
            if not chunk:
                break
            part_path = f"{base_ne}_part{part_idx:03d}{ext}"
            with open(part_path, "wb") as fout:
                fout.write(chunk)
            parts.append(part_path)
            part_idx += 1
    print(f"[SPLIT] Binary split done: {len(parts)} parts")
    return parts


def upload_local_file(client, message, uid, filepath,
                      status_msg=None, file_index=1, total=1, max_retries=2):
    """Upload locally stored file to Telegram with auto-retry + cancel support."""
    s  = db.get_settings(uid)
    ut = s["upload_type"];  tt = s["thumb_type"]

    if status_msg is None:
        status_msg = message.reply_text(f"⏳ [{file_index}/{total}] Preparing…")

    prefix = f"[{file_index}/{total}] " if total > 1 else ""

    def _edit(txt, markup=CANCEL_KB):
        tg_edit_safe(status_msg, txt, markup=markup)

    last_err = None
    for attempt in range(max_retries + 1):
        if attempt:
            _edit(f"<b>{prefix}🔄 Retry {attempt}/{max_retries}…</b>")
            time.sleep(3)
        thumb_path = None
        try:
            if uid in CANCEL_TASKS:
                CANCEL_TASKS.discard(uid)
                _edit(f"<b>{prefix}🚫 Cancelled.</b>", None)
                return None
            if not os.path.exists(filepath):
                _edit(f"<b>{prefix}❌ File not found:</b> <code>{h(os.path.basename(filepath))}</code>", None)
                return None

            file_size   = os.path.getsize(filepath)
            valid_title = clean_filename(os.path.splitext(os.path.basename(filepath))[0])
            _edit(f"<b>{prefix}🔍 Metadata extracting…</b>")
            meta = get_video_metadata(filepath)

            if tt == "custom":
                lp = thumb_local_path(uid);  thumb_path = lp if os.path.exists(lp) else None
            elif tt == "auto" and meta.get("duration", 0) > 0:
                ap = filepath + "_thumb.jpg"
                thumb_path = ap if extract_thumbnail(filepath, ap, meta["duration"]) else None

            if file_size > FTM_SIZE_MAX and _ftm_session_available():
                # ── SPLIT path: file > 4 GB — split into parts, upload each via FTM ─────────
                _edit(f"<b>{prefix}✂️ File {format_size(file_size)} — Splitting into parts (max 3.9 GB each)…</b>")
                log_to_channel(client,
                    f"✂️ #Split_Start #uid_{uid}\n\n"
                    f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
                    f"📄 File: <code>{h(valid_title)}</code>\n"
                    f"📦 Size: {format_size(file_size)}\n"
                    f"⏰ {_now_str()}"
                )
                parts = split_large_file(filepath)
                if not parts:
                    raise RuntimeError("File split karna fail ho gaya — koi part nahi bana.")
                total_parts = len(parts)
                _edit(f"<b>{prefix}✂️ {total_parts} parts ban gaye. Uploading…</b>")
                last_user_msg = None
                for pi, part_path in enumerate(parts, 1):
                    if uid in CANCEL_TASKS:
                        CANCEL_TASKS.discard(uid)
                        _edit(f"<b>{prefix}🚫 Cancelled.</b>", None)
                        return None
                    part_size_bytes = os.path.getsize(part_path)
                    part_title      = f"{valid_title} [Part {pi}/{total_parts}]"
                    part_meta       = get_video_metadata(part_path) if meta.get("duration") else meta
                    try:
                        ftm_part = _do_ftm_upload(
                            part_path, part_title, part_size_bytes,
                            part_meta, thumb_path, ut, _edit,
                            pi, total_parts,
                            cancel_fn=lambda: uid in CANCEL_TASKS,
                        )
                    finally:
                        try: os.remove(part_path)
                        except Exception: pass
                    if ftm_part:
                        try:
                            user_msg = client.copy_message(
                                message.chat.id,
                                ftm_part.chat.id, ftm_part.id,
                                caption=getattr(ftm_part, "caption", None),
                                parse_mode=enums.ParseMode.HTML,
                            )
                            last_user_msg = user_msg
                        except Exception as _ce:
                            print(f"[SPLIT_COPY] Part {pi} user copy fail: {_ce}")
                _edit(
                    f"✅ <b>{prefix}All {total_parts} parts sent via FTM Split!</b>\n"
                    f"📦 Total: {format_size(file_size)}",
                    DONE_KB,
                )
                log_to_channel(client,
                    f"✅ #Split_Done #uid_{uid}\n\n"
                    f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
                    f"📄 File: <code>{h(valid_title)}</code>\n"
                    f"📦 Size: {format_size(file_size)}  |  Parts: {total_parts}\n"
                    f"⏰ {_now_str()}"
                )
                if last_user_msg:
                    _copy_to_destinations(client, message, uid, last_user_msg,
                                          file_type="Video" if meta.get("duration") else "Document",
                                          file_size=file_size, source_url=source_url,
                                          folder_url=folder_url,
                                          drive_file_id=file_id, fname=valid_title)
                    db.save_download_history(uid, valid_title, file_size,
                                             "Video" if meta.get("duration") else "Document",
                                             source_url, folder_url)
                return last_user_msg

            elif FTM_SIZE_THRESHOLD < file_size <= FTM_SIZE_MAX and _ftm_session_available():
                # ── FTM path: dump channel → bot copies to user → destinations ──────────────
                _edit(f"<b>{prefix}📤 Uploading to Dump Channel (FTM 2GB+)...</b>")
                log_to_channel(client,
                    f"📤 #FTM_Start #uid_{uid}\n\n"
                    f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
                    f"📄 File: <code>{h(valid_title)}</code>\n"
                    f"📦 Size: {format_size(file_size)}\n"
                    f"⏰ {_now_str()}"
                )
                try:
                    ftm_sent = _do_ftm_upload(filepath, valid_title, file_size, meta, thumb_path, ut, _edit, file_index, total,
                                              cancel_fn=lambda: uid in CANCEL_TASKS)
                except RuntimeError as e:
                    err_s = str(e).lower()
                    if "cancelled by user" in err_s:
                        CANCEL_TASKS.discard(uid)
                        _edit(f"<b>{prefix}🚫 Cancelled.</b>", None)
                        return None
                    if "stall" in err_s or "timed out" in err_s:
                        print(f"[FTM_UPLOAD] ♻️ Will use fresh client on retry (stall/timeout)")
                    raise
                except Exception as e:
                    print(f"[FTM_UPLOAD] uid={uid} fail: {e}")
                    log_to_channel(client,
                        f"❌ #FTM_Fail #uid_{uid}\n\n"
                        f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
                        f"📄 File: <code>{h(valid_title)}</code>\n"
                        f"📦 Size: {format_size(file_size)}\n"
                        f"💥 Error: <code>{h(str(e))}</code>\n"
                        f"⏰ {_now_str()}"
                    )
                    raise

                if ftm_sent:
                    _edit(f"<b>{prefix}📤 Dumped! Now sending to you...</b>")
                    try:
                        # Bot client copies from dump channel to user (fast, no re-upload)
                        user_msg = client.copy_message(
                            message.chat.id,
                            ftm_sent.chat.id,
                            ftm_sent.id,
                            caption=getattr(ftm_sent, "caption", None),
                            parse_mode=enums.ParseMode.HTML,
                        )
                        _edit(f"✅ <b>{prefix}Successfully sent via FTM (2GB+)!</b>", DONE_KB)
                        _copy_to_destinations(client, message, uid, user_msg,
                                              file_type="Video" if meta.get("duration") else "Document",
                                              file_size=file_size, source_url=source_url,
                                              folder_url=folder_url,
                                              drive_file_id=file_id, fname=valid_title)
                        db.save_download_history(uid, valid_title, file_size,
                                                 "Video" if meta.get("duration") else "Document",
                                                 source_url, folder_url)
                        log_to_channel(client,
                            f"✅ #FTM_Success #uid_{uid} #LargeFile\n\n"
                            f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
                            f"📄 File: <code>{h(valid_title)}</code>\n"
                            f"📦 Size: {format_size(file_size)}\n"
                            f"📌 Dump Msg: <code>{ftm_sent.id}</code>\n"
                            f"📬 User Msg: <code>{user_msg.id}</code>\n"
                            f"⏰ {_now_str()}"
                        )
                    except Exception as e:
                        print(f"[FTM_COPY] uid={uid} user copy fail: {e}")
                        _edit(f"⚠️ <b>{prefix}Dump pe upload ho gaya (msg {ftm_sent.id}), user copy fail: {h(str(e))}</b>", DONE_KB)
                        log_to_channel(client,
                            f"⚠️ #FTM_Partial #uid_{uid}\n\n"
                            f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
                            f"📄 File: <code>{h(valid_title)}</code>\n"
                            f"📦 Size: {format_size(file_size)}\n"
                            f"📌 Dump Msg: <code>{ftm_sent.id}</code>\n"
                            f"💥 Copy Error: <code>{h(str(e))}</code>\n"
                            f"⏰ {_now_str()}"
                        )
                return ftm_sent

            # ── No-FTM split path: 2GB+ but no FTM session — split into 1.9GB parts ──
            elif file_size > FTM_SIZE_THRESHOLD and not _ftm_session_available():
                n_parts = math.ceil(file_size / SPLIT_BOT_PART_SIZE)
                _edit(
                    f"<b>{prefix}✂️ File {format_size(file_size)} — FTM session nahi hai.\n"
                    f"Bot upload ke liye {n_parts} part(s) mein split ho raha hai (max 1.9 GB each)…</b>"
                )
                log_to_channel(client,
                    f"✂️ #NoFTM_Split #uid_{uid}\n\n"
                    f"📄 File: <code>{h(valid_title)}</code>\n"
                    f"📦 Size: {format_size(file_size)}  |  Parts: ~{n_parts}\n"
                    f"⏰ {_now_str()}"
                )
                parts = split_large_file(filepath, part_size=SPLIT_BOT_PART_SIZE)
                if not parts:
                    raise RuntimeError("File split karna fail ho gaya — koi part nahi bana.")
                total_parts = len(parts)
                _edit(f"<b>{prefix}✂️ {total_parts} part(s) ban gaye. Uploading via bot…</b>")
                last_sent = None
                for pi, part_path in enumerate(parts, 1):
                    if uid in CANCEL_TASKS:
                        CANCEL_TASKS.discard(uid)
                        _edit(f"<b>{prefix}🚫 Cancelled.</b>", None)
                        return None
                    part_sz    = os.path.getsize(part_path)
                    part_title = f"{valid_title} [Part {pi}/{total_parts}]"
                    part_meta  = get_video_metadata(part_path) if meta.get("duration") else meta
                    try:
                        psent = _do_upload(
                            client, message, uid, part_path, part_title,
                            part_sz, part_meta, thumb_path, ut, _edit,
                            pi, total_parts,
                        )
                    finally:
                        try: os.remove(part_path)
                        except Exception: pass
                    if psent:
                        last_sent = psent
                _edit(
                    f"✅ <b>{prefix}All {total_parts} parts sent! (Bot split — no FTM)</b>\n"
                    f"📦 Total: {format_size(file_size)}",
                    DONE_KB,
                )
                if last_sent:
                    _copy_to_destinations(client, message, uid, last_sent,
                                          file_type="Video" if meta.get("duration") else "Document",
                                          file_size=file_size, source_url=source_url,
                                          folder_url=folder_url,
                                          drive_file_id=file_id, fname=valid_title)
                    db.save_download_history(uid, valid_title, file_size,
                                             "Video" if meta.get("duration") else "Document",
                                             source_url, folder_url)
                return last_sent

            # ── Normal path (< 2GB): bot uploads directly ────────────────────
            else:
                sent = _do_upload(client, message, uid, filepath, valid_title,
                                  file_size, meta, thumb_path, ut, _edit,
                                  file_index, total)
                _edit(f"✅ <b>{prefix}Successfully sent!</b>", DONE_KB)
                _copy_to_destinations(client, message, uid, sent,
                                      drive_file_id=file_id, fname=valid_title)
                return sent

        except Exception as e:
            last_err = e
            print(f"[UPLOAD] attempt={attempt+1} file={os.path.basename(filepath)}: {e}")
        finally:
            if thumb_path and thumb_path.endswith("_thumb.jpg") and os.path.exists(thumb_path):
                try: os.remove(thumb_path)
                except Exception: pass

    RETRY_DATA[uid] = {"type": "local_file", "filepath": filepath}
    _edit(
        f"<b>{prefix}❌ Failed after {max_retries+1} attempts:</b>\n"
        f"<code>{h(str(last_err))}</code>",
        RETRY_KB,
    )
    return None


def process_single_file(client, message, uid, file_id, hint_name="",
                        status_msg=None, file_index=1, total=1, max_retries=2,
                        folder_url: str = None, mime_hint: str = ""):
    """Download from Google Drive + upload to Telegram with cancel & retry support."""
    s   = db.get_settings(uid)
    ut  = s["upload_type"];  tt = s["thumb_type"]
    nt  = db.SPEED_THREADS.get(s.get("speed_preset", "max"), 16)
    source_url = f"https://drive.google.com/file/d/{file_id}"

    from_user = getattr(message, "from_user", None)
    display   = _get_display_name(from_user) if from_user else f"User_{uid}"

    if status_msg is None:
        status_msg = message.reply_text(f"⏳ [{file_index}/{total}] Processing…")

    prefix = f"[{file_index}/{total}] " if total > 1 else ""

    def _edit(txt, markup=CANCEL_KB, block=True):
        tg_edit_safe(status_msg, txt, markup=markup, block=block)

    # ── Cache hit: instant re-delivery from dump channel ─────────────────────
    if DUMP_CHANNEL_ID and db.get_ftm_alpha(uid):
        cached = db.get_file_cache(file_id)
        if cached and cached.get("dump_msg_id"):
            dump_msg_id  = cached["dump_msg_id"]
            cached_fname = cached.get("fname") or hint_name or "file"
            cached_ftype = cached.get("file_type", "File")
            cached_fsize = cached.get("file_size", 0)
            try:
                _edit(
                    f"⚡ <b>{prefix}Cache Hit!</b>\n"
                    f"🔄 Dump Channel se copy ho raha hai…",
                    CANCEL_KB,
                )
                # Apply user's caption template if set
                _tpl = db.get_caption_template(uid)
                _cap = None
                if _tpl:
                    _cap = (_tpl
                            .replace("{filename}", cached_fname)
                            .replace("{name}", display or f"User_{uid}")
                            .replace("{size}", str(cached_fsize)))
                sent = client.copy_message(
                    chat_id=message.chat.id,
                    from_chat_id=DUMP_CHANNEL_ID,
                    message_id=dump_msg_id,
                    caption=_cap,
                    parse_mode=enums.ParseMode.HTML if _cap else None,
                )
                _edit(f"✅ <b>{prefix}Sent from Cache!</b>", DONE_KB)
                _copy_to_destinations(client, message, uid, sent,
                                      display=display, file_type=cached_ftype,
                                      file_size=cached_fsize, source_url=source_url,
                                      folder_url=folder_url)
                db.save_download_history(uid, cached_fname, cached_fsize, cached_ftype,
                                         source_url, folder_url)
                print(f"[FILE_CACHE] Hit uid={uid} file_id={file_id} dump_msg={dump_msg_id}")
                return sent
            except Exception as ace:
                print(f"[FILE_CACHE] Miss fallback uid={uid}: {ace}")
                _edit(f"⚠️ <b>{prefix}Cache copy fail, normal download shuru…</b>")

    filepath = thumb_path = last_err = None

    for attempt in range(max_retries + 1):
        if attempt:
            _edit(f"<b>{prefix}🔄 Retry {attempt}/{max_retries}…</b>")
            time.sleep(3)
        filepath = thumb_path = None

        try:
            if uid in CANCEL_TASKS:
                CANCEL_TASKS.discard(uid)
                _edit(f"<b>{prefix}🚫 Cancelled.</b>", None)
                return None

            _edit(f"<b>{prefix}🔍 File info fetch ho rahi hai…</b>")

            # ── Load user's saved Google cookies + OAuth tokens ────────────
            saved_cookie_str = db.get_google_cookies(uid)
            saved_cookies    = parse_cookie_str(saved_cookie_str) if saved_cookie_str else {}
            cookie_str_for_api = _cookies_dict_to_str(saved_cookies)

            # ── Drive API file resolver: best-effort metadata + download URL ──
            _resolved   = {}
            try:
                from drive_utils import resolve_file_info as _resolve_fi
                _resolved = _resolve_fi(
                    file_id,
                    cookies=saved_cookies,
                )
            except Exception as _res_err:
                print(f"[RESOLVER] Non-fatal error for {file_id}: {_res_err}")

            # Use resolved metadata to improve hint_name / mime_hint
            if _resolved.get("name") and not hint_name:
                hint_name = _resolved["name"]
            elif _resolved.get("name") and hint_name in ("", "file"):
                hint_name = _resolved["name"]
            if _resolved.get("mime_type") and not mime_hint:
                mime_hint = _resolved["mime_type"]
            # Keep resolved download URL + auth headers for direct download
            _r_dl_url   = _resolved.get("download_url",  "")
            _r_auth_hdrs = _resolved.get("auth_headers", {})
            _r_method   = _resolved.get("method",       "")
            _r_ws       = _resolved.get("is_workspace",  False)

            print(f"[RESOLVE] {file_id} → name={hint_name!r} "
                  f"mime={mime_hint!r} method={_r_method!r}")

            # ── Direct stream capture ──────────────────────────────────────
            # Primary: get_video_info API → works even when download is disabled
            # Fallback: Drive API v3 alt=media → for non-video/document files
            _fallback_audio_url = None
            _titan_ok = False   # always False — direct path used throughout
            cdn_url = title = file_type = mime_type = None
            cookies = {}

            _edit(f"<b>{prefix}🔄 Stream URL fetch ho rahi hai…</b>")
            _stream_ok = False

            if not saved_cookies:
                _edit(
                    f"<b>{prefix}❌ Google Account Linked Nahi Hai</b>\n\n"
                    "Is file ko download karne ke liye pehle Google account se login karein.\n\n"
                    "👉 /gcookies ya /login use karein.",
                    DONE_KB,
                )
                return None

            # ── Skip video detection for known non-video MIME types ────────────
            # PDFs, images, audio, zip, workspace docs → go straight to doc path
            _NON_VIDEO_MIMES = {
                "application/pdf",
                "image/jpeg", "image/png", "image/gif", "image/webp",
                "image/bmp", "image/tiff", "image/svg+xml",
                "audio/mpeg", "audio/mp4", "audio/ogg", "audio/flac",
                "audio/wav", "audio/x-wav", "audio/aac", "audio/webm",
                "application/zip", "application/x-rar-compressed",
                "application/x-tar", "application/gzip",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-powerpoint",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "text/plain", "text/csv", "text/html",
            }
            _ext_hint = os.path.splitext(hint_name)[1].lower() if hint_name else ""
            _NON_VIDEO_EXTS = {
                ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
                ".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a",
                ".zip", ".rar", ".tar", ".gz", ".7z",
                ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                ".txt", ".csv", ".html", ".epub",
            }
            _is_known_non_video = (
                mime_hint in _NON_VIDEO_MIMES or
                (mime_hint and mime_hint.startswith("image/")) or
                (mime_hint and mime_hint.startswith("audio/")) or
                (mime_hint and mime_hint.startswith("application/vnd.google-apps.")) or
                _ext_hint in _NON_VIDEO_EXTS
            )
            if _is_known_non_video:
                print(f"[DIRECT] Skipping video detection for known non-video: "
                      f"mime={mime_hint!r} ext={_ext_hint!r}")
            else:
                try:
                    from fallback.stream_capture import _get_streams_via_api
                    _vid_url, _aud_url, _vid_title = _get_streams_via_api(
                        file_id, cookie_str_for_api
                    )
                    cdn_url             = _vid_url
                    _fallback_audio_url = _aud_url
                    title               = _vid_title or hint_name or "video"
                    file_type           = "video"
                    _stream_ok          = True
                    _aud_status = "Separate" if _aud_url else "Muxed (Inbuilt)"
                    print(f"[DIRECT] get_video_info OK — video=True audio={_aud_status} title={title!r}")
                except Exception as _sv_err:
                    print(f"[DIRECT] get_video_info failed ({_sv_err}), trying uc?export…")

            # Fallback for non-video files (documents, images, etc.)
            if not _stream_ok:
                _ext = os.path.splitext(hint_name)[1].lower() if hint_name else ""
                title     = hint_name or "file"
                mime_type = mime_hint or ""
                if not mime_type and _ext == ".pdf":
                    mime_type = "application/pdf"
                file_type = "file"
                cdn_url   = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
                cookies   = saved_cookies
                print(f"[DIRECT] usercontent download fallback for {file_id}")

            # ── PDF / Google Workspace document check ────────────────────────
            if not mime_type and mime_hint:
                mime_type = mime_hint
            if not mime_type:
                ext = os.path.splitext(hint_name)[1].lower() if hint_name else ""
                if ext == ".pdf":
                    mime_type = "application/pdf"

            if mime_type in PDF_MIME_TYPES:
                file_info = {"name": title, "mimeType": mime_type}
                file_name = title
                type_lbl  = PDF_TYPE_LABELS.get(mime_type, "📄 Document")

                # ── Actual PDF file: try Titanium CDN first, fallback to Google ──
                # No orientation prompt — orientation is baked into the PDF itself.
                if mime_type == "application/pdf":
                    raw_title   = os.path.splitext(file_name)[0] if file_name else \
                                  os.path.splitext(hint_name or "document")[0]
                    valid_title = clean_filename(raw_title) + ".pdf"
                    filepath    = os.path.join(DOWNLOADS_DIR, valid_title)
                    _edit(f"<b>{prefix}⬇️ PDF download ho raha hai…</b>")
                    last_edit = {"t": 0}
                    def on_progress_pdf(dl, total_b, spd, ela, eta):
                        now = time.time()
                        if now - last_edit["t"] < 2: return
                        last_edit["t"] = now
                        _edit(draw_progress_card(valid_title, dl, total_b, spd, ela, eta,
                                                 file_index, total, nt), CANCEL_KB, block=False)
                    def _cancelled_pdf():
                        return uid in CANCEL_TASKS
                    # 1st attempt: direct uc?export=download (no auth, fast for public files)
                    _pdf_cdn_ok = False
                    try:
                        download_file(cdn_url, {}, filepath, on_progress_pdf, nt, _cancelled_pdf)
                        # Validate: binary files (PDF, etc.) never start with '<'
                        with open(filepath, "rb") as _pf: _hdr = _pf.read(1)
                        if _hdr == b"<":
                            print(f"[PDF] CDN returned HTML (virus scan page) — trying auth download")
                            try: os.remove(filepath)
                            except: pass
                        else:
                            _pdf_cdn_ok = True
                            print(f"[PDF] CDN download succeeded for {file_id}")
                    except Exception as _cdn_err:
                        print(f"[PDF] CDN failed ({_cdn_err}), falling back to Google Drive")
                        try: os.remove(filepath)
                        except: pass
                    # 2nd attempt: Google Drive URL + user cookies (handles virus-scan page redirect)
                    if not _pdf_cdn_ok:
                        pdf_url = _build_pdf_url(file_id, mime_type, "portrait")
                        try:
                            _drive_auth_download(pdf_url, saved_cookies, filepath,
                                                 on_progress_pdf, _cancelled_pdf)
                        except Exception as _pdf_dl_err:
                            _pdf_err_s = str(_pdf_dl_err)
                            if "download_disabled_by_owner" in _pdf_err_s:
                                _edit(
                                    f"<b>{prefix}🔄 Download disabled by owner</b> — "
                                    "browser se page-by-page extract kar raha hai…\n"
                                    "<i>(kuch minutes lag sakte hain)</i>"
                                )
                                _, _vt_p = _drive_pdf_via_viewer(
                                    file_id, saved_cookies, filepath,
                                    on_progress_pdf, status_cb=_edit)
                                if _vt_p:
                                    _np_title = clean_filename(_vt_p) + ".pdf"
                                    _np_path  = os.path.join(DOWNLOADS_DIR, _np_title)
                                    try: os.rename(filepath, _np_path)
                                    except: _np_path = filepath; _np_title = valid_title
                                    filepath    = _np_path
                                    valid_title = _np_title
                            else:
                                raise
                    if uid in CANCEL_TASKS:
                        CANCEL_TASKS.discard(uid)
                        try: os.remove(filepath)
                        except: pass
                        _edit(f"<b>{prefix}🚫 Cancelled.</b>", None); return None
                    file_size = os.path.getsize(filepath)
                    tt_s = s.get("thumb_type", "auto")
                    thumb_path = thumb_local_path(uid) if tt_s == "custom" and os.path.exists(thumb_local_path(uid)) else None
                    sent = _do_upload(client, message, uid, filepath, valid_title,
                                      file_size, {}, thumb_path, "document", _edit, file_index, total)
                    _edit(f"✅ <b>{prefix}PDF sent!</b>", DONE_KB)
                    _copy_to_destinations(client, message, uid, sent, display=display,
                                          file_type="PDF", file_size=file_size,
                                          source_url=source_url, folder_url=folder_url,
                                          drive_file_id=file_id, fname=valid_title)
                    db.save_download_history(uid, valid_title, file_size, "PDF", source_url, folder_url)
                    return sent

                # ── Google Workspace files (Docs/Slides/Sheets/Drawings):
                # In a folder/bulk download (total>1 or folder_url set) → auto portrait.
                # For single-file downloads → prompt user for orientation choice.
                if folder_url or total > 1:
                    raw_title   = os.path.splitext(file_name)[0] if file_name else "document"
                    valid_title = clean_filename(raw_title) + ".pdf"
                    filepath    = os.path.join(DOWNLOADS_DIR, valid_title)
                    pdf_url     = _build_pdf_url(file_id, mime_type, "portrait")
                    _edit(f"<b>{prefix}⬇️ {type_lbl} download ho raha hai…</b>")
                    last_edit = {"t": 0}
                    def on_progress_doc(dl, total_b, spd, ela, eta):
                        now = time.time()
                        if now - last_edit["t"] < 2: return
                        last_edit["t"] = now
                        _edit(draw_progress_card(valid_title, dl, total_b, spd, ela, eta,
                                                 file_index, total, nt), CANCEL_KB, block=False)
                    def _cancelled_doc():
                        return uid in CANCEL_TASKS
                    try:
                        _drive_auth_download(pdf_url, saved_cookies, filepath, on_progress_doc, _cancelled_doc)
                    except Exception as _pdf_dl_err:
                        if "download_disabled_by_owner" in str(_pdf_dl_err):
                            _edit(f"<b>{prefix}🔄 Download disabled — browser se page-by-page extract kar raha hai…</b>")
                            _, _vt = _drive_pdf_via_viewer(file_id, saved_cookies, filepath,
                                                           on_progress_doc, status_cb=_edit)
                            if _vt:
                                _new_title = clean_filename(_vt) + ".pdf"
                                _new_path  = os.path.join(DOWNLOADS_DIR, _new_title)
                                try: os.rename(filepath, _new_path)
                                except: _new_path = filepath; _new_title = valid_title
                                filepath    = _new_path
                                valid_title = _new_title
                        else:
                            raise
                    if uid in CANCEL_TASKS:
                        CANCEL_TASKS.discard(uid); _edit(f"<b>{prefix}🚫 Cancelled.</b>", None); return None
                    file_size = os.path.getsize(filepath)
                    tt_s = s.get("thumb_type", "auto")
                    thumb_path = thumb_local_path(uid) if tt_s == "custom" and os.path.exists(thumb_local_path(uid)) else None
                    sent = _do_upload(client, message, uid, filepath, valid_title,
                                      file_size, {}, thumb_path, "document", _edit, file_index, total)
                    _edit(f"✅ <b>{prefix}Document sent!</b>", DONE_KB)
                    _copy_to_destinations(client, message, uid, sent, display=display,
                                          file_type="PDF", file_size=file_size,
                                          source_url=source_url, folder_url=folder_url,
                                          drive_file_id=file_id, fname=valid_title)
                    db.save_download_history(uid, valid_title, file_size, "PDF", source_url, folder_url)
                    return sent
                PENDING_PDF_ORIENT[uid] = {
                    "file_id": file_id, "hint_name": file_name,
                    "mime_type": mime_type, "cookies": {},
                    "status_msg": status_msg, "origin_msg": message,
                    "folder_url": folder_url,
                }
                _edit(
                    f"<b>{prefix}{type_lbl} mila!</b>\n\n"
                    f"📄 <b>File:</b> <code>{h(file_name)}</code>\n\n"
                    "PDF export ka orientation chunein:",
                    pdf_orient_kb(),
                )
                return None

            # ── Non-video / non-audio: download as document ──────────────────
            if file_type not in ("video", "audio"):
                tmp_path = os.path.join(DOWNLOADS_DIR, f"_tmp_{file_id}")
                _edit(f"<b>{prefix}⬇️ File download ho raha hai…</b>")
                try:
                    last_edit = {"t": 0}
                    def on_progress_raw(dl, total_b, spd, ela, eta):
                        now = time.time()
                        if now - last_edit["t"] < 2: return
                        last_edit["t"] = now
                        _edit(draw_progress_card(
                            title or file_id[:12], dl, total_b, spd, ela, eta,
                            file_index, total, nt), CANCEL_KB, block=False)
                    def _cancelled_raw():
                        return uid in CANCEL_TASKS

                    # Detect if this is an image file
                    _img_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
                                 ".tiff", ".tif", ".heic", ".heif"}
                    _dl_ext   = os.path.splitext(hint_name or "")[1].lower()
                    _is_img_dl = (
                        (mime_hint and mime_hint.startswith("image/")) or
                        _dl_ext in _img_exts
                    )

                    # 1st attempt: Drive API v3 alt=media — SKIP for images.
                    # API v3 sometimes returns a WebP thumbnail instead of the
                    # original file, causing IMAGE_PROCESS_FAILED on Telegram.
                    # For images, go straight to uc?export=download (preserves
                    # the original bytes).
                    _doc_ok = False
                    if _r_dl_url and _r_auth_hdrs and not _is_img_dl:
                        try:
                            from drive_utils import download_file_direct as _dfd
                            _dfd(file_id, tmp_path, _r_auth_hdrs,
                                 download_url=_r_dl_url,
                                 progress_cb=on_progress_raw,
                                 cancel_fn=_cancelled_raw)
                            _doc_ok = True
                            print(f"[DOC] API v3 direct download OK ({_r_method}) for {file_id}")
                        except Exception as _api_dl_err:
                            print(f"[DOC] API v3 direct failed ({_api_dl_err}), trying fallbacks")
                            try: os.remove(tmp_path)
                            except: pass
                    elif _is_img_dl:
                        print(f"[DOC] Image detected — skipping API v3, using uc?export=download directly")

                    # 2nd attempt: uc?export=download&id=FILE_ID with cookies
                    # For images this is always the first (and preferred) attempt.
                    _doc_meta = {}
                    if not _doc_ok:
                        try:
                            _uc_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                            _drive_auth_download(_uc_url, saved_cookies, tmp_path,
                                                 on_progress_raw, _cancelled_raw,
                                                 meta_out=_doc_meta)
                            # Validate: binary files never start with '<'; HTML/JSON pages do
                            with open(tmp_path, "rb") as _tf: _magic = _tf.read(1)
                            if _magic == b"<":
                                print(f"[DOC] auth download returned HTML — cookies may be expired")
                                try: os.remove(tmp_path)
                                except: pass
                                _doc_meta = {}
                            else:
                                _doc_ok = True
                                print(f"[DOC] uc?export download OK for {file_id}")
                        except Exception as _uc_err:
                            print(f"[DOC] uc?export download failed ({_uc_err}), trying usercontent direct")
                            try: os.remove(tmp_path)
                            except: pass
                            _doc_meta = {}

                    # 3rd attempt: drive.usercontent.google.com direct (with cookies)
                    if not _doc_ok:
                        _uc2_url = (
                            f"https://drive.usercontent.google.com/download"
                            f"?id={file_id}&export=download&authuser=0&confirm=t"
                        )
                        _uc2_err_str = ""
                        try:
                            _drive_auth_download(_uc2_url, saved_cookies, tmp_path,
                                                 on_progress_raw, _cancelled_raw,
                                                 meta_out=_doc_meta)
                            _doc_ok = True
                        except Exception as _uc2_err:
                            _uc2_err_str = str(_uc2_err)
                            print(f"[DOC] usercontent download failed ({_uc2_err_str})")
                            try: os.remove(tmp_path)
                            except: pass

                        # ── PDF viewer fallback for download-disabled PDFs ─────────
                        # If ALL direct methods failed AND file looks like a PDF,
                        # use page-by-page thumbnail extraction (works even when
                        # the owner has disabled downloads).
                        if not _doc_ok:
                            _fb_ext_chk = os.path.splitext(hint_name or title or "")[1].lower()
                            _fb_is_pdf  = (
                                _fb_ext_chk == ".pdf"
                                or (mime_type or "").lower() == "application/pdf"
                                or "download_disabled_by_owner" in _uc2_err_str
                                or "download_disabled_by_owner" in str(_uc_err if "_uc_err" in dir() else "")
                            )
                            if _fb_is_pdf and saved_cookies:
                                _edit(
                                    f"<b>{prefix}🔄 Direct download blocked</b> — "
                                    "page-by-page PDF extract kar raha hai…\n"
                                    "<i>(kuch minutes lag sakte hain)</i>"
                                )
                                _vw_fname = (hint_name or title or f"document_{file_id}")
                                _vw_base  = os.path.splitext(_vw_fname)[0]
                                _vw_path  = os.path.join(DOWNLOADS_DIR,
                                                          clean_filename(_vw_base) + ".pdf")
                                _, _vw_title = _drive_pdf_via_viewer(
                                    file_id, saved_cookies, _vw_path,
                                    on_progress_raw, status_cb=_edit
                                )
                                if _vw_title:
                                    _np_path2 = os.path.join(
                                        DOWNLOADS_DIR,
                                        clean_filename(_vw_title) + ".pdf"
                                    )
                                    try: os.rename(_vw_path, _np_path2)
                                    except: _np_path2 = _vw_path
                                else:
                                    _np_path2 = _vw_path
                                file_size = os.path.getsize(_np_path2)
                                tt_s = s.get("thumb_type", "auto")
                                thumb_path = thumb_local_path(uid) if tt_s == "custom" and os.path.exists(thumb_local_path(uid)) else None
                                sent = _do_upload(client, message, uid, _np_path2,
                                                  os.path.basename(_np_path2),
                                                  file_size, {}, thumb_path, "document",
                                                  _edit, file_index, total)
                                _edit(f"✅ <b>{prefix}PDF sent!</b>", DONE_KB)
                                _copy_to_destinations(client, message, uid, sent,
                                                      display=display,
                                                      file_type="PDF",
                                                      file_size=file_size,
                                                      source_url=source_url,
                                                      folder_url=folder_url,
                                                      drive_file_id=file_id,
                                                      fname=os.path.basename(_np_path2))
                                db.save_download_history(uid,
                                                         os.path.basename(_np_path2),
                                                         file_size, "PDF",
                                                         source_url, folder_url)
                                return sent
                            else:
                                raise Exception(_uc2_err_str or "All download methods failed")

                    if uid in CANCEL_TASKS:
                        CANCEL_TASKS.discard(uid)
                        try: os.remove(tmp_path)
                        except: pass
                        _edit(f"<b>{prefix}🚫 Cancelled.</b>", None); return None

                    # ── Determine filename: priority order ─────────────────────
                    # 1) Content-Disposition header from download response
                    # 2) hint_name from resolve_file_info or URL
                    # 3) title set during stream detection
                    # 4) Magic-bytes fallback
                    _cd_name = _doc_meta.get("suggested_filename", "")
                    _ct_mime = _doc_meta.get("content_type", "")

                    if _cd_name:
                        fb_base = os.path.splitext(_cd_name)[0]
                        fb_ext  = os.path.splitext(_cd_name)[1]
                        if not fb_ext and _cd_name:
                            fb_ext = ""
                        print(f"[DOC] filename from Content-Disposition: {_cd_name!r}")
                    elif hint_name:
                        fb_base = os.path.splitext(hint_name)[0]
                        fb_ext  = os.path.splitext(hint_name)[1]
                    elif title and title not in ("file", ""):
                        fb_base = os.path.splitext(title)[0]
                        fb_ext  = os.path.splitext(title)[1]
                    else:
                        fb_base = "file"
                        fb_ext  = ""

                    # ── Magic bytes fallback when extension still unknown ───────
                    if not fb_ext:
                        _MAGIC_EXTS = {
                            b"\xff\xd8\xff":         ".jpg",
                            b"\x89PNG":              ".png",
                            b"GIF8":                 ".gif",
                            b"RIFF":                 ".webp",
                            b"\x00\x00\x00\x18ftyp": ".mp4",
                            b"\x00\x00\x00\x20ftyp": ".mp4",
                            b"ID3":                  ".mp3",
                            b"\xff\xfb":             ".mp3",
                            b"fLaC":                 ".flac",
                            b"OggS":                 ".ogg",
                            b"PK\x03\x04":           ".zip",
                            b"Rar!":                 ".rar",
                            b"\x1f\x8b":             ".gz",
                            b"%PDF":                 ".pdf",
                            b"\x7fELF":              ".bin",
                        }
                        try:
                            with open(tmp_path, "rb") as _mf:
                                _mb = _mf.read(16)
                            for sig, ext in _MAGIC_EXTS.items():
                                if _mb[:len(sig)] == sig:
                                    fb_ext = ext
                                    print(f"[DOC] magic-bytes ext detected: {ext}")
                                    break
                        except Exception:
                            pass

                    # ── MIME-type fallback when still no extension ─────────────
                    if not fb_ext and _ct_mime:
                        _MIME_EXTS = {
                            "image/jpeg": ".jpg", "image/png": ".png",
                            "image/gif": ".gif", "image/webp": ".webp",
                            "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
                            "audio/ogg": ".ogg", "audio/flac": ".flac",
                            "audio/wav": ".wav", "audio/x-wav": ".wav",
                            "video/mp4": ".mp4", "video/webm": ".webm",
                            "application/pdf": ".pdf",
                            "application/zip": ".zip",
                            "application/x-rar-compressed": ".rar",
                            "application/octet-stream": "",
                        }
                        fb_ext = _MIME_EXTS.get(_ct_mime.split(";")[0].strip(), "")
                        if fb_ext:
                            print(f"[DOC] MIME-type ext detected: {fb_ext} from {_ct_mime}")

                    valid_title = clean_filename(fb_base) + fb_ext
                    if not valid_title or valid_title == fb_ext:
                        valid_title = f"file_{file_id[:8]}" + fb_ext
                    filepath = os.path.join(DOWNLOADS_DIR, valid_title)
                    os.replace(tmp_path, filepath)

                    file_size = os.path.getsize(filepath)
                    tt_s = s.get("thumb_type", "auto")
                    thumb_path = thumb_local_path(uid) if tt_s == "custom" and os.path.exists(thumb_local_path(uid)) else None
                    sent = _do_upload(client, message, uid, filepath, valid_title,
                                      file_size, {}, thumb_path, "document", _edit, file_index, total)
                    _edit(f"✅ <b>{prefix}File sent!</b>", DONE_KB)
                    _copy_to_destinations(client, message, uid, sent, display=display,
                                          file_type="Document", file_size=file_size,
                                          source_url=source_url, folder_url=folder_url,
                                          drive_file_id=file_id, fname=valid_title)
                    db.save_download_history(uid, valid_title, file_size, "Document", source_url, folder_url)
                    return sent
                except Exception as dl_err:
                    print(f"[DOC_UPLOAD] fid={file_id} error: {dl_err}")
                    try: os.remove(tmp_path)
                    except: pass
                    RETRY_DATA[uid] = {"type": "single", "file_id": file_id, "hint": hint_name}
                    _edit(
                        f"<b>{prefix}❌ Download failed: <code>{h(str(dl_err))}</code></b>\n\n"
                        "Retry karein ya baad mein try karein.",
                        RETRY_KB,
                    )
                    return None

            # ── Video / Audio: download via CDN ──────────────────────────────
            video_url = cdn_url

            # Apply rename if user set one
            raw_title   = title or hint_name or "video"
            if uid in PENDING_RENAME:
                raw_title = PENDING_RENAME.pop(uid)
            valid_title = clean_filename(raw_title)
            filepath    = os.path.join(DOWNLOADS_DIR, valid_title)
            last_edit   = {"t": 0}

            def on_progress(dl, total_b, spd, ela, eta):
                now = time.time()
                if now - last_edit["t"] < 2: return
                last_edit["t"] = now
                _edit(draw_progress_card(valid_title, dl, total_b, spd, ela, eta,
                                        file_index, total, nt), CANCEL_KB, block=False)

            def _cancelled():
                evt = CANCEL_EVENTS.get(uid)
                return uid in CANCEL_TASKS or (evt is not None and evt.is_set())

            # ── Fallback stream path (videoplayback URLs) ─────────────────────
            # These URLs require Cookie + Referer headers — not a cookie jar.
            # Use parallel_downloader which handles this correctly.
            if not _titan_ok:
                from fallback.parallel_downloader import (
                    download_stream          as _pdl_stream,
                    download_video_audio_parallel as _pdl_va,
                    strip_drive_range_from_url    as _strip_range,
                )
                _stream_hdrs = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/124.0.0.0 Safari/537.36",
                    "Cookie":   cookie_str_for_api,
                    "Referer":  f"https://drive.google.com/file/d/{file_id}/view",
                    "Origin":   "https://drive.google.com",
                    "X-Goog-AuthUser": "0",
                }
                _sap = (cookies.get("SAPISID") or cookies.get("__Secure-1PAPISID") or "") if isinstance(cookies, dict) else ""
                if _sap:
                    _stream_hdrs["Authorization"] = "SAPISIDHASH " + compute_sapisidhash(_sap, "https://drive.google.com")

                # Size check via Range request
                _pre_size = 0
                try:
                    _sz_r = requests.get(
                        _strip_range(video_url),
                        headers={**_stream_hdrs, "Range": "bytes=0-0"},
                        timeout=12, stream=True,
                    )
                    _cr = _sz_r.headers.get("Content-Range", "")
                    if "/" in _cr:
                        _pre_size = int(_cr.split("/")[-1])
                    _sz_r.close()
                except Exception as _sz_err:
                    print(f"[RESOLVE_FALLBACK] size check error: {_sz_err}")

                if _fallback_audio_url:
                    # Download video + audio in parallel, then merge
                    _audio_tmp = filepath + "_audio.m4a"
                    _edit(f"<b>{prefix}⬇️ Video + Audio parallel download ho rahe hain…</b>")

                    _t_start_va = time.time()
                    def _va_prog(v_done, v_total, a_done, a_total):
                        now = time.time()
                        comb_done  = v_done + a_done
                        comb_total = (v_total or 0) + (a_total or 0)
                        elapsed    = max(0.1, now - _t_start_va)
                        speed      = comb_done / elapsed
                        eta        = (comb_total - comb_done) / speed if (speed > 0 and comb_total > comb_done) else 0
                        if now - last_edit["t"] < 2: return
                        last_edit["t"] = now
                        _edit(draw_progress_card(
                            valid_title, comb_done, comb_total, speed, elapsed, eta,
                            file_index, total, nt), CANCEL_KB, block=False)

                    try:
                        _pdl_va(video_url, _fallback_audio_url, _stream_hdrs,
                                filepath, _audio_tmp, _va_prog, _cancelled)
                    except Exception as _va_err:
                        for _p in (_audio_tmp, filepath):
                            try: os.remove(_p)
                            except: pass
                        raise RuntimeError(f"Stream download fail: {_va_err}") from _va_err

                    if uid in CANCEL_TASKS:
                        CANCEL_TASKS.discard(uid)
                        for _p in (_audio_tmp, filepath):
                            try: os.remove(_p)
                            except: pass
                        _edit(f"<b>{prefix}🚫 Download cancelled.</b>", None)
                        return None

                    # Merge video + audio
                    if os.path.exists(_audio_tmp) and os.path.getsize(_audio_tmp) > 0:
                        _merged_tmp = filepath + "_merged.mp4"
                        _edit(f"<b>{prefix}🔀 Video + Audio merge ho raha hai…</b>")
                        import subprocess as _sp
                        _merge_ok = False
                        # Attempt 1: stream copy (fast, no re-encode)
                        _mr = _sp.run(
                            [_FFMPEG, "-y",
                             "-i", filepath, "-i", _audio_tmp,
                             "-c", "copy",
                             "-shortest", _merged_tmp],
                            capture_output=True, timeout=7200,
                        )
                        if _mr.returncode == 0 and os.path.exists(_merged_tmp) and os.path.getsize(_merged_tmp) > 0:
                            _merge_ok = True
                        else:
                            # Attempt 2: re-encode audio to AAC
                            try: os.remove(_merged_tmp)
                            except: pass
                            _mr = _sp.run(
                                [_FFMPEG, "-y",
                                 "-i", filepath, "-i", _audio_tmp,
                                 "-c:v", "copy", "-c:a", "aac",
                                 "-b:a", "192k", "-threads", "0",
                                 "-shortest", _merged_tmp],
                                capture_output=True, timeout=7200,
                            )
                            if _mr.returncode == 0 and os.path.exists(_merged_tmp) and os.path.getsize(_merged_tmp) > 0:
                                _merge_ok = True
                            else:
                                print(f"[RESOLVE_FALLBACK] ffmpeg merge failed: "
                                      f"{_mr.stderr.decode()[-300:]}")
                        if _merge_ok:
                            os.replace(_merged_tmp, filepath)
                            print(f"[RESOLVE_FALLBACK] Audio merge OK for {file_id}")
                        else:
                            try: os.remove(_merged_tmp)
                            except: pass
                        try: os.remove(_audio_tmp)
                        except: pass
                    else:
                        try: os.remove(_audio_tmp)
                        except: pass
                        print(f"[RESOLVE_FALLBACK] Audio empty/missing — keeping video-only")
                else:
                    # Video only (muxed stream)
                    _t_start_s = time.time()
                    def _stream_prog(done, total_b, label=""):
                        now = time.time()
                        elapsed = max(0.1, now - _t_start_s)
                        speed   = done / elapsed
                        eta     = (total_b - done) / speed if (speed > 0 and total_b > done) else 0
                        if now - last_edit["t"] < 2: return
                        last_edit["t"] = now
                        _edit(draw_progress_card(
                            valid_title, done, total_b, speed, elapsed, eta,
                            file_index, total, nt), CANCEL_KB, block=False)

                    try:
                        _pdl_stream(video_url, _stream_hdrs, filepath,
                                    "video", _stream_prog, _cancelled)
                    except Exception as _sdl_err:
                        try: os.remove(filepath)
                        except: pass
                        raise RuntimeError(f"Stream download fail: {_sdl_err}") from _sdl_err

                if uid in CANCEL_TASKS:
                    CANCEL_TASKS.discard(uid)
                    _edit(f"<b>{prefix}🚫 Download cancelled.</b>", None)
                    return None

            # ── Titanium CDN path (no auth needed) ───────────────────────────
            else:
                # ── Pre-download size guard ───────────────────────────────────
                _pre_size = get_file_size(video_url, cookies)

                download_file(video_url, cookies, filepath, on_progress, nt, _cancelled)

                if uid in CANCEL_TASKS:
                    CANCEL_TASKS.discard(uid)
                    _edit(f"<b>{prefix}🚫 Download cancelled.</b>", None)
                    return None

                # ── Merge separate audio stream (Titanium stream_fallback mode) ─
                if _fallback_audio_url:
                    _audio_tmp = filepath + "_audio.m4a"
                    try:
                        _edit(f"<b>{prefix}⬇️ Audio track download ho raha hai…</b>")
                        download_file(_fallback_audio_url, {}, _audio_tmp, None, nt, _cancelled)
                        _merged_tmp = filepath + "_merged.mp4"
                        _edit(f"<b>{prefix}🔀 Video + Audio merge ho raha hai…</b>")
                        import subprocess as _sp2
                        _merge_ok2 = False
                        # Attempt 1: stream copy (fast, no re-encode)
                        _mr2 = _sp2.run(
                            [_FFMPEG, "-y",
                             "-i", filepath, "-i", _audio_tmp,
                             "-c", "copy",
                             "-shortest", _merged_tmp],
                            capture_output=True, timeout=7200,
                        )
                        if _mr2.returncode == 0 and os.path.exists(_merged_tmp) and os.path.getsize(_merged_tmp) > 0:
                            _merge_ok2 = True
                        else:
                            # Attempt 2: re-encode audio to AAC
                            try: os.remove(_merged_tmp)
                            except: pass
                            _mr2 = _sp2.run(
                                [_FFMPEG, "-y",
                                 "-i", filepath, "-i", _audio_tmp,
                                 "-c:v", "copy", "-c:a", "aac",
                                 "-b:a", "192k", "-threads", "0",
                                 "-shortest", _merged_tmp],
                                capture_output=True, timeout=7200,
                            )
                            if _mr2.returncode == 0 and os.path.exists(_merged_tmp) and os.path.getsize(_merged_tmp) > 0:
                                _merge_ok2 = True
                            else:
                                print(f"[RESOLVE_FALLBACK] ffmpeg merge failed: "
                                      f"{_mr2.stderr.decode()[-300:]}")
                        if _merge_ok2:
                            os.replace(_merged_tmp, filepath)
                            print(f"[RESOLVE_FALLBACK] Audio merge OK for {file_id}")
                        else:
                            try: os.remove(_merged_tmp)
                            except: pass
                    except Exception as _merge_err:
                        print(f"[RESOLVE_FALLBACK] Audio merge error: {_merge_err}")
                    finally:
                        try: os.remove(_audio_tmp)
                        except: pass

            file_size = os.path.getsize(filepath)
            _edit(f"<b>{prefix}🔍 Extracting metadata…</b>")
            meta      = get_video_metadata(filepath)

            if tt == "custom":
                lp = thumb_local_path(uid);  thumb_path = lp if os.path.exists(lp) else None
            elif tt == "auto":
                ap = filepath + "_thumb.jpg"
                thumb_path = ap if extract_thumbnail(filepath, ap, meta["duration"]) else None

            _ftm_mention = f"<a href='tg://user?id={uid}'>{h(display)}</a>"

            if file_size > FTM_SIZE_MAX and _ftm_session_available():
                # ── SPLIT path: file > 4 GB — split into parts, upload each via FTM ─────────
                _edit(f"<b>{prefix}✂️ File {format_size(file_size)} — Splitting into parts (max 3.9 GB each)…</b>")
                log_to_channel(client,
                    f"✂️ #Split_Start #uid_{uid}\n\n"
                    f"👤 User: {_ftm_mention} (<code>{uid}</code>)\n"
                    f"📄 File: <code>{h(valid_title)}</code>\n"
                    f"📦 Size: {format_size(file_size)}\n"
                    f"⏰ {_now_str()}"
                )
                parts = split_large_file(filepath)
                if not parts:
                    raise RuntimeError("File split karna fail ho gaya — koi part nahi bana.")
                total_parts = len(parts)
                _edit(f"<b>{prefix}✂️ {total_parts} parts ban gaye. Uploading via FTM…</b>")
                last_user_msg = None
                def _split_log_fn(txt):
                    log_to_channel(client, f"👤 {_ftm_mention}\n" + txt)
                for pi, part_path in enumerate(parts, 1):
                    if uid in CANCEL_TASKS:
                        CANCEL_TASKS.discard(uid)
                        _edit(f"<b>{prefix}🚫 Cancelled.</b>", None)
                        return None
                    part_size_bytes = os.path.getsize(part_path)
                    part_title      = f"{valid_title} [Part {pi}/{total_parts}]"
                    part_meta       = get_video_metadata(part_path) if meta.get("duration") else meta
                    part_thumb      = None
                    if meta.get("duration"):
                        _pt = part_path + "_thumb.jpg"
                        if extract_thumbnail(part_path, _pt, part_meta.get("duration", 0)):
                            part_thumb = _pt
                    try:
                        ftm_part = _do_ftm_upload(
                            part_path, part_title, part_size_bytes,
                            part_meta, part_thumb or thumb_path, ut, _edit,
                            pi, total_parts,
                            log_fn=_split_log_fn,
                            cancel_fn=lambda: uid in CANCEL_TASKS,
                        )
                    finally:
                        try: os.remove(part_path)
                        except Exception: pass
                        if part_thumb:
                            try: os.remove(part_thumb)
                            except Exception: pass
                    if ftm_part:
                        try:
                            user_msg = client.copy_message(
                                message.chat.id,
                                ftm_part.chat.id, ftm_part.id,
                                caption=getattr(ftm_part, "caption", None),
                                parse_mode=enums.ParseMode.HTML,
                            )
                            last_user_msg = user_msg
                        except Exception as _ce:
                            print(f"[SPLIT_COPY] Part {pi} user copy fail: {_ce}")
                _edit(
                    f"✅ <b>{prefix}All {total_parts} parts sent via FTM Split!</b>\n"
                    f"📦 Total: {format_size(file_size)}",
                    DONE_KB,
                )
                log_to_channel(client,
                    f"✅ #Split_Done #uid_{uid}\n\n"
                    f"👤 User: {_ftm_mention} (<code>{uid}</code>)\n"
                    f"📄 File: <code>{h(valid_title)}</code>\n"
                    f"📦 Size: {format_size(file_size)}  |  Parts: {total_parts}\n"
                    f"⏰ {_now_str()}"
                )
                file_type = "Video" if meta.get("duration") else "Document"
                if last_user_msg:
                    _copy_to_destinations(client, message, uid, last_user_msg,
                                          display=display, file_type=file_type,
                                          file_size=file_size, source_url=source_url,
                                          folder_url=folder_url)
                    db.save_download_history(uid, valid_title, file_size, file_type,
                                             source_url, folder_url)
                return last_user_msg

            elif FTM_SIZE_THRESHOLD < file_size <= FTM_SIZE_MAX and _ftm_session_available():
                # ── FTM path: dump channel → bot copies to user → destinations ──────────────
                _edit(f"<b>{prefix}📤 Uploading to Dump Channel (FTM 2GB+)...</b>")
                log_to_channel(client,
                    f"📤 #FTM_Start #uid_{uid}\n\n"
                    f"👤 User: {_ftm_mention} (<code>{uid}</code>)\n"
                    f"📄 File: <code>{h(valid_title)}</code>\n"
                    f"📦 Size: {format_size(file_size)}\n"
                    f"⏰ {_now_str()}"
                )
                def _ftm_log_fn(txt):
                    log_to_channel(client, f"👤 {_ftm_mention}\n" + txt)
                try:
                    ftm_sent = _do_ftm_upload(filepath, valid_title, file_size, meta, thumb_path, ut, _edit, file_index, total, log_fn=_ftm_log_fn,
                                              cancel_fn=lambda: uid in CANCEL_TASKS)
                except RuntimeError as e:
                    err_s = str(e).lower()
                    if "cancelled by user" in err_s:
                        CANCEL_TASKS.discard(uid)
                        _edit(f"<b>{prefix}🚫 Cancelled.</b>", None)
                        return None
                    if "stall" in err_s or "timed out" in err_s:
                        print(f"[FTM_UPLOAD] ♻️ Will use fresh client on retry (stall/timeout)")
                    raise
                except Exception as e:
                    print(f"[FTM_UPLOAD] uid={uid} fail: {e}")
                    log_to_channel(client,
                        f"❌ #FTM_Fail #uid_{uid}\n\n"
                        f"👤 User: {_ftm_mention} (<code>{uid}</code>)\n"
                        f"📄 File: <code>{h(valid_title)}</code>\n"
                        f"📦 Size: {format_size(file_size)}\n"
                        f"💥 Error: <code>{h(str(e))}</code>\n"
                        f"⏰ {_now_str()}"
                    )
                    raise

                if ftm_sent:
                    _edit(f"<b>{prefix}📤 Dumped! Now sending to you...</b>")
                    try:
                        # BOT client copies from dump channel to user (fast, no re-upload)
                        user_msg = client.copy_message(
                            message.chat.id,
                            ftm_sent.chat.id,
                            ftm_sent.id,
                            caption=getattr(ftm_sent, "caption", None),
                            parse_mode=enums.ParseMode.HTML,
                        )
                        _edit(f"✅ <b>{prefix}Successfully sent via FTM (2GB+)!</b>", DONE_KB)
                        _copy_to_destinations(client, message, uid, user_msg,
                                              display=display, file_type="Video" if meta.get("duration") else "Document",
                                              file_size=file_size, source_url=source_url,
                                              folder_url=folder_url)
                        db.save_download_history(uid, valid_title, file_size,
                                                 "Video" if meta.get("duration") else "Document",
                                                 source_url, folder_url)
                        log_to_channel(client,
                            f"✅ #FTM_Success #uid_{uid} #Download\n\n"
                            f"👤 User: {_ftm_mention} (<code>{uid}</code>)\n"
                            f"📄 File: <code>{h(valid_title)}</code>\n"
                            f"📦 Size: {format_size(file_size)}\n"
                            f"📌 Dump Msg: <code>{ftm_sent.id}</code>\n"
                            f"📬 User Msg: <code>{user_msg.id}</code>\n"
                            f"⏰ {_now_str()}"
                        )
                    except Exception as e:
                        print(f"[FTM_COPY] uid={uid} user copy fail: {e}")
                        _edit(f"⚠️ <b>{prefix}Dump pe upload ho gaya, user copy fail.</b> Admin check karein.", DONE_KB)
                        log_to_channel(client,
                            f"⚠️ #FTM_Partial #uid_{uid}\n\n"
                            f"👤 User: {_ftm_mention} (<code>{uid}</code>)\n"
                            f"📄 File: <code>{h(valid_title)}</code>\n"
                            f"📦 Size: {format_size(file_size)}\n"
                            f"📌 Dump Msg: <code>{ftm_sent.id}</code>\n"
                            f"💥 Copy Error: <code>{h(str(e))}</code>\n"
                            f"⏰ {_now_str()}"
                        )
                return ftm_sent

            elif file_size > FTM_SIZE_THRESHOLD and not _ftm_session_available():
                # ── No-FTM split path: 2GB+ but no FTM session — split into 1.9GB parts ──
                n_parts = math.ceil(file_size / SPLIT_BOT_PART_SIZE)
                _edit(
                    f"<b>{prefix}✂️ File {format_size(file_size)} badi hai (2GB+). "
                    f"Bot upload ke liye {n_parts} part(s) mein split ho raha hai (max 1.9 GB each)…</b>"
                )
                log_to_channel(client,
                    f"✂️ #BotSplit_Start #uid_{uid}\n\n"
                    f"👤 User: {_ftm_mention} (<code>{uid}</code>)\n"
                    f"📄 File: <code>{h(valid_title)}</code>\n"
                    f"📦 Size: {format_size(file_size)}\n"
                    f"⏰ {_now_str()}"
                )
                parts = split_large_file(filepath, part_size=SPLIT_BOT_PART_SIZE)
                if not parts:
                    raise RuntimeError("File split karna fail ho gaya — koi part nahi bana.")
                total_parts   = len(parts)
                last_user_msg = None
                file_type     = "Video" if meta.get("duration") else "Document"
                for pi, part_path in enumerate(parts, 1):
                    if uid in CANCEL_TASKS:
                        CANCEL_TASKS.discard(uid)
                        _edit(f"<b>{prefix}🚫 Cancelled.</b>", None)
                        return None
                    part_size_bytes = os.path.getsize(part_path)
                    part_title      = f"{valid_title} [Part {pi}/{total_parts}]"
                    part_meta       = get_video_metadata(part_path) if meta.get("duration") else meta
                    part_thumb      = None
                    if meta.get("duration"):
                        _pt = part_path + "_thumb.jpg"
                        if extract_thumbnail(part_path, _pt, part_meta.get("duration", 0)):
                            part_thumb = _pt
                    try:
                        _edit(f"<b>{prefix}📤 Part {pi}/{total_parts} upload ho raha hai ({format_size(part_size_bytes)})…</b>")
                        part_sent = _do_upload(
                            client, message, uid, part_path, part_title,
                            part_size_bytes, part_meta, part_thumb or thumb_path, ut, _edit,
                            pi, total_parts,
                        )
                        last_user_msg = part_sent
                    finally:
                        try: os.remove(part_path)
                        except Exception: pass
                        if part_thumb:
                            try: os.remove(part_thumb)
                            except Exception: pass
                _edit(
                    f"✅ <b>{prefix}All {total_parts} parts sent! (Bot split — no FTM)</b>\n"
                    f"📦 Total: {format_size(file_size)}",
                    DONE_KB,
                )
                log_to_channel(client,
                    f"✅ #BotSplit_Done #uid_{uid}\n\n"
                    f"👤 User: {_ftm_mention} (<code>{uid}</code>)\n"
                    f"📄 File: <code>{h(valid_title)}</code>\n"
                    f"📦 Size: {format_size(file_size)}  |  Parts: {total_parts}\n"
                    f"⏰ {_now_str()}"
                )
                if last_user_msg:
                    _copy_to_destinations(client, message, uid, last_user_msg,
                                          display=display, file_type=file_type,
                                          file_size=file_size, source_url=source_url,
                                          folder_url=folder_url)
                    db.save_download_history(uid, valid_title, file_size, file_type,
                                             source_url, folder_url)
                return last_user_msg

            sent      = _do_upload(client, message, uid, filepath, valid_title,
                                   file_size, meta, thumb_path, ut, _edit,
                                   file_index, total)
            _edit(f"✅ <b>{prefix}Successfully sent!</b>", DONE_KB)

            file_type = "Video" if (ut == "video" and meta.get("duration", 0) > 0) else "Document"
            _copy_to_destinations(client, message, uid, sent,
                                  display=display, file_type=file_type,
                                  file_size=file_size, source_url=source_url,
                                  folder_url=folder_url,
                                  drive_file_id=file_id, fname=valid_title)
            db.save_download_history(uid, valid_title, file_size, file_type,
                                     source_url, folder_url)
            log_to_channel(client,
                f"✅ #Success #uid_{uid} #Download\n\n"
                f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
                f"📄 File: <code>{h(valid_title)}</code>\n"
                f"📦 Size: {format_size(file_size)}\n"
                f"📌 Source: <a href='{source_url}'>link</a>\n"
                f"⏰ {_now_str()}"
            )
            return sent

        except Exception as e:
            last_err = e
            print(f"[PROCESS] attempt={attempt+1} fid={file_id}: {e}")
        finally:
            for p in [filepath,
                      thumb_path if thumb_path and thumb_path.endswith("_thumb.jpg") else None]:
                if p and os.path.exists(p):
                    try: os.remove(p)
                    except Exception: pass

    RETRY_DATA[uid] = {"type": "single", "file_id": file_id, "hint": hint_name}
    _err_str = str(last_err)
    try:
        log_to_channel(client,
            f"❌ #Failed #uid_{uid} #Download\n\n"
            f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
            f"🆔 File ID: <code>{file_id}</code>\n"
            f"💢 Error: <code>{h(_err_str)}</code>\n"
            f"⏰ {_now_str()}"
        )
    except Exception as _log_err:
        print(f"[LOG_CHANNEL] warn: {_log_err}")
    if "download_disabled_by_owner" in _err_str:
        _edit(
            f"<b>{prefix}🚫 Download Disabled</b>\n\n"
            "File owner ne is file ka <b>download disable kar rakha hai</b>.\n\n"
            "📋 <b>Possible solutions:</b>\n"
            "• File owner se download permission maangein\n"
            "• Owner ko file settings mein <i>'Prevent viewers from downloading'</i> off karne ko bolein\n\n"
            "<i>Note: Cookies sahi hain, yeh Google Drive ka restriction hai.</i>",
            RETRY_KB,
        )
        return None

    # ── Auto-fallback: if CDN failed and user has Google cookies ──────────────
    _is_stream_fail = any(x in _err_str for x in [
        "status 404", "status 403", "Part ", "Download failed",
        "Incomplete", "stalled", "stream error",
        "File size equals to 0", "size equals to 0", "equals to 0 B",
        "0 bytes", "empty file", "Titanium API error",
    ])
    _saved_cookie_str = db.get_google_cookies(uid)
    print(f"[FALLBACK_DEBUG] err={repr(_err_str[:120])} is_fail={_is_stream_fail} has_cookies={bool(_saved_cookie_str)}")
    if _is_stream_fail and _saved_cookie_str:
        # Run fallback directly — no button press needed
        _edit(
            f"<b>{prefix}⚡ Auto Fallback</b>\n\n"
            f"CDN fail hua (<code>{h(_err_str[:120])}</code>)\n\n"
            "Drive API se directly download ho raha hai…\n"
            "<i>(yeh automatic hai, kuch karne ki zaroorat nahi)</i>"
        )
        _fb_source_url = f"https://drive.google.com/file/d/{file_id}"
        def _fb_post_send(sent_msg, valid_title, file_size, meta):
            file_type = "Video" if meta.get("duration", 0) > 0 else "Document"
            _copy_to_destinations(
                client, message, uid, sent_msg,
                display=display, file_type=file_type,
                file_size=file_size, source_url=_fb_source_url,
                folder_url=folder_url, drive_file_id=file_id,
                fname=valid_title,
            )
            db.save_download_history(uid, valid_title, file_size,
                                     file_type, _fb_source_url, folder_url)
            try:
                log_to_channel(client,
                    f"✅ #Success #uid_{uid} #Fallback\n\n"
                    f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
                    f"📄 File: <code>{h(valid_title)}</code>\n"
                    f"📦 Size: {format_size(file_size)}\n"
                    f"📌 Source: <a href='{_fb_source_url}'>link</a>\n"
                    f"⏰ {_now_str()}"
                )
            except Exception:
                pass

        return _ftm_fallback_run(
            client=client,
            message=message,
            uid=uid,
            file_id=file_id,
            cookies=parse_cookie_str(_saved_cookie_str),
            original_filename=hint_name,
            status_msg=status_msg,
            file_index=file_index,
            total=total,
            cancel_fn=lambda: uid in CANCEL_TASKS,
            thumb_type=tt,
            custom_thumb_path=thumb_local_path(uid),
            post_send_fn=_fb_post_send,
        )

    # No cookies or unrecognised error — show manual retry button
    _edit(
        f"<b>{prefix}❌ Error:</b>\n<code>{h(_err_str)}</code>\n\n"
        "Dobara try karne ke liye <b>Retry</b> dabayein.\n"
        "<i>Tip: /login se Google cookies save karein for auto-fallback.</i>",
        RETRY_KB,
    )
    return None


# ─────────────────────────────────────────────
#  Folder processing
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
#  Folder file selection UI helpers
# ─────────────────────────────────────────────

FILES_PER_PAGE = 5


def _fs_short(fname: str, maxlen: int = 38) -> str:
    """Truncate filename for inline button label."""
    # show only the bare filename, not the full sub-folder path
    base = os.path.basename(fname) or fname
    return base if len(base) <= maxlen else base[:maxlen - 1] + "…"


def folder_selection_keyboard(uid: int) -> InlineKeyboardMarkup:
    data = FOLDER_SELECTIONS.get(uid)
    if not data:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Cancel", callback_data="fs_cancel")]])

    files       = data["files"]
    selected    = data["selected"]
    page        = data.get("page", 0)
    total       = len(files)
    total_pages = math.ceil(total / FILES_PER_PAGE)
    start       = page * FILES_PER_PAGE
    end         = min(start + FILES_PER_PAGE, total)
    rows        = []

    # ── File toggle buttons (1 per row) ──────────────────────────────────
    for j in range(start, end):
        _, fname = files[j]
        tick = "✅" if j in selected else "☐"
        rows.append([InlineKeyboardButton(
            f"{tick} {_fs_short(fname)}",
            callback_data=f"fs_t_{j}",
        )])

    # ── Select / clear this page ──────────────────────────────────────────
    rows.append([
        InlineKeyboardButton("☑️ This Page", callback_data="fs_pg_sel"),
        InlineKeyboardButton("✖️ Clear Page", callback_data="fs_pg_clr"),
        InlineKeyboardButton("☑️ All Pages",  callback_data="fs_all"),
    ])

    # ── Pagination row ────────────────────────────────────────────────────
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"fs_pg_{page - 1}"))
    nav.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"fs_pg_{page + 1}"))
    rows.append(nav)

    # ── Download buttons ──────────────────────────────────────────────────
    n_sel = len(selected)
    n_pg  = end - start
    rows.append([
        InlineKeyboardButton(f"⬇️ This Page ({n_pg})", callback_data="fs_dl_pg"),
        InlineKeyboardButton(f"⬇️ Selected ({n_sel})", callback_data="fs_dl"),
    ])
    rows.append([
        InlineKeyboardButton(f"⬇️ All ({total})", callback_data="fs_dl_all"),
        InlineKeyboardButton("🚫 Cancel",         callback_data="fs_cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def folder_selection_text(uid: int) -> str:
    data        = FOLDER_SELECTIONS.get(uid)
    files       = data["files"]
    selected    = data["selected"]
    page        = data.get("page", 0)
    total       = len(files)
    total_pages = math.ceil(total / FILES_PER_PAGE)
    s_num       = page * FILES_PER_PAGE + 1
    e_num       = min((page + 1) * FILES_PER_PAGE, total)
    return (
        f"📂 <b>{total} file(s) mili!</b>\n"
        f"📄 <b>Page {page + 1}/{total_pages}</b>  ({s_num}–{e_num} of {total})\n\n"
        f"✅ <b>Selected:</b> {len(selected)}/{total}\n\n"
        f"<i>Files toggle karein → Download button dabayein.</i>"
    )


_SPIN_FRAMES_PUBLIC = [
    "📂 <b>Folder scan ho raha hai…</b>\n\n<code>⠋</code>  Drive se files detect ho rahi hain…",
    "📂 <b>Folder scan ho raha hai…</b>\n\n<code>⠙</code>  File list ban rahi hai…",
    "📂 <b>Folder scan ho raha hai…</b>\n\n<code>⠹</code>  Folder contents load ho rahe hain…",
    "📂 <b>Folder scan ho raha hai…</b>\n\n<code>⠸</code>  Drive se connect ho raha hai…",
    "📂 <b>Folder scan ho raha hai…</b>\n\n<code>⠼</code>  Metadata parse ho raha hai…",
    "📂 <b>Folder scan ho raha hai…</b>\n\n<code>⠴</code>  Files dhundh raha hai…",
    "📂 <b>Folder scan ho raha hai…</b>\n\n<code>⠦</code>  Contents aa rahe hain…",
    "📂 <b>Folder scan ho raha hai…</b>\n\n<code>⠧</code>  Thoda wait karein…",
]

_SPIN_FRAMES_PRIVATE = [
    "🔒 <b>Private folder — cookies se access ho raha hai…</b>\n\n<code>⠋</code>  Files fetch ho rahi hain…",
    "🔒 <b>Private folder — cookies se access ho raha hai…</b>\n\n<code>⠙</code>  Subfolders scan ho rahe hain…",
    "🔒 <b>Private folder — cookies se access ho raha hai…</b>\n\n<code>⠹</code>  File tree ban raha hai…",
    "🔒 <b>Private folder — cookies se access ho raha hai…</b>\n\n<code>⠸</code>  Files detect ho rahi hain…",
    "🔒 <b>Private folder — cookies se access ho raha hai…</b>\n\n<code>⠼</code>  Metadata parse ho raha hai…",
    "🔒 <b>Private folder — cookies se access ho raha hai…</b>\n\n<code>⠴</code>  Nested folders check ho rahe hain…",
    "🔒 <b>Private folder — cookies se access ho raha hai…</b>\n\n<code>⠦</code>  Almost done…",
    "🔒 <b>Private folder — cookies se access ho raha hai…</b>\n\n<code>⠧</code>  Thoda wait karein…",
]


def _folder_spinner(status_msg, stop_event: threading.Event, frames: list = None):
    """Cycle through loading frames while folder is being scanned."""
    _frames = frames or _SPIN_FRAMES_PUBLIC
    i = 0
    while not stop_event.is_set():
        try:
            status_msg.edit_text(_frames[i % len(_frames)], parse_mode=enums.ParseMode.HTML)
        except FloodWait as fw:
            stop_event.wait(fw.value + 1)
        except Exception:
            pass
        i += 1
        stop_event.wait(1.9)


def process_folder(client, message, uid, folder_id, status_msg):
    """List files → show inline selection UI → user picks → download."""
    s = db.get_settings(uid)

    def _edit(txt, markup=None):
        tg_edit_safe(status_msg, txt, markup=markup)

    # ── Quick resend from folder cache (all users) ───────────────────────────
    if DUMP_CHANNEL_ID and db.get_ftm_alpha(uid) and folder_id:
        cached_folder = db.get_folder_cache(folder_id)
        if cached_folder and cached_folder.get("files"):
            cf = cached_folder["files"]
            # Check if all files have dump_msg_ids in file_cache
            resendable = []
            for entry in cf:
                fid = entry.get("drive_file_id")
                fc  = db.get_file_cache(fid) if fid else None
                if fc and fc.get("dump_msg_id"):
                    resendable.append((fid, entry.get("fname", fid), fc))
            if resendable:
                import datetime as _dt
                cached_ts = cached_folder.get("ts", 0)
                cached_date = _dt.datetime.utcfromtimestamp(cached_ts).strftime("%d %b %Y, %H:%M UTC") if cached_ts else "—"
                FOLDER_ALPHA[uid] = folder_id
                _edit(
                    f"⚡ <b>Alpha Cache Hit!</b>\n\n"
                    f"📂 Is folder ka <b>{len(resendable)}</b> file(s) pehle se Dump Channel mein hain.\n"
                    f"⏰ Last processed: <i>{cached_date}</i>\n\n"
                    f"<b>Quick Resend</b> karein ya normal process karein?",
                    InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            f"⚡ Quick Resend ({len(resendable)} files)",
                            callback_data="alpha_folder_resend"
                        )],
                        [InlineKeyboardButton(
                            "🔄 Normal Process (Fresh Download)",
                            callback_data="alpha_folder_fresh"
                        )],
                        [InlineKeyboardButton("🚫 Cancel", callback_data="cancel_task")],
                    ]),
                )
                return

    # ── Phase 1: public API spinner ──────────────────────────────────────────
    _spin_stop = threading.Event()
    _spin_thread = threading.Thread(
        target=_folder_spinner,
        args=(status_msg, _spin_stop),
        kwargs={"frames": _SPIN_FRAMES_PUBLIC},
        daemon=True,
    )
    _spin_thread.start()

    file_list = None
    _public_err = None

    try:
        file_list = list_folder_file_ids(folder_id)
    except PermissionError:
        pass
    except Exception as fe:
        _public_err = str(fe)
        file_list = None

    # ── Phase 2: private folder handling ─────────────────────────────────────
    if file_list is None:
        saved_cookie_str = db.get_google_cookies(uid)

        if not saved_cookie_str:
            # No cookies — stop spinner and ask user to login
            _spin_stop.set()
            _edit(
                "🔒 <b>Private folder hai!</b>\n\n"
                "Yeh folder publicly shared nahi hai.\n"
                "Apne Google cookies add karein taaki bot access kar sake.",
                cookie_login_kb(uid),
            )
            RETRY_DATA[uid] = {"type": "folder", "folder_id": folder_id}
            return

        # Cookies exist — switch to private spinner and pre-fetch the tree
        _spin_stop.set()
        _spin_thread.join(timeout=2)

        _spin_stop2 = threading.Event()
        _spin_thread2 = threading.Thread(
            target=_folder_spinner,
            args=(status_msg, _spin_stop2),
            kwargs={"frames": _SPIN_FRAMES_PRIVATE},
            daemon=True,
        )
        _spin_thread2.start()

        # Pre-fetch folder tree so webapp opens instantly (use DB cache if available)
        try:
            from drive_utils import build_folder_tree
            cookies = parse_cookie_str(saved_cookie_str)
            _alpha_on = db.get_ftm_alpha(uid)
            prefetched_tree = db.get_drive_folder_tree(folder_id) if _alpha_on else None
            if prefetched_tree:
                print(f"[BROWSE] Tree cache hit (private) uid={uid}, folder={folder_id}, "
                      f"name={prefetched_tree.get('name')}, "
                      f"{prefetched_tree.get('total_files', 0)} file(s)")
            else:
                if not _alpha_on:
                    print(f"[BROWSE] Alpha OFF — skipping cache, fetching fresh (private) uid={uid}")
                prefetched_tree = build_folder_tree(
                    folder_id, cookies=cookies
                )
                real_name = prefetched_tree.get("name") or "Drive Folder"
                if real_name in ("Root", ""):
                    real_name = "Drive Folder"
                prefetched_tree["name"] = real_name
                db.set_drive_folder_tree(folder_id, prefetched_tree)
                print(f"[BROWSE] Fetched & cached tree uid={uid}, name={real_name}, "
                      f"{prefetched_tree.get('total_files', 0)} file(s)")
            cookie_server.set_folder_tree_cache(uid, folder_id, prefetched_tree)
        except Exception as te:
            print(f"[BROWSE] Pre-fetch failed for uid={uid}: {te}")

        _spin_stop2.set()
        _spin_thread2.join(timeout=2)

        # Register webapp download callback so /api/download can trigger the bot
        def _on_webapp_dl(fl, _client=client, _msg=message, _uid=uid, _fid=folder_id):
            threading.Thread(
                target=execute_folder_download,
                args=(_client, _msg, _uid, fl, None),
                kwargs={"folder_id": _fid},
                daemon=True,
            ).start()
        cookie_server.register_download_callback(uid, _on_webapp_dl)

        browse_url = get_browse_url(uid, folder_id)
        _edit(
            "🔒 <b>Private Folder Ready!</b>\n\n"
            "Drive Browser mein files select karein aur Telegram pe bhejein.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Open Drive Browser", web_app=WebAppInfo(url=browse_url))],
                [InlineKeyboardButton("🚫 Cancel", callback_data="cancel_task")],
            ]),
        )
        RETRY_DATA[uid] = {"type": "folder", "folder_id": folder_id}
        return

    # Public folder loaded — stop spinner
    _spin_stop.set()
    _spin_thread.join(timeout=2)

    if not file_list:
        _edit("❌ <b>Folder mein koi file nahi mili.</b>\n• Folder publicly shared ho\n• Folder empty na ho")
        return

    if s.get("folder_filter", "all") == "videos":
        file_list = [(fid, fn) for fid, fn in file_list
                     if os.path.splitext(fn)[1].lower() in VIDEO_EXTENSIONS]
        if not file_list:
            _edit("❌ <b>No video files found.</b>\nSettings → Folder Filter: All Files karein.")
            return

    # Pre-fetch full folder tree (hierarchy) for the webapp
    _spin_stop_pub = threading.Event()
    _spin_thread_pub = threading.Thread(
        target=_folder_spinner,
        args=(status_msg, _spin_stop_pub),
        kwargs={"frames": _SPIN_FRAMES_PUBLIC},
        daemon=True,
    )
    _spin_thread_pub.start()

    try:
        from drive_utils import build_folder_tree
        _alpha_on_pub = db.get_ftm_alpha(uid)
        prefetched_tree = db.get_drive_folder_tree(folder_id) if _alpha_on_pub else None
        if prefetched_tree:
            print(f"[BROWSE] Tree cache hit (public) folder={folder_id}, "
                  f"name={prefetched_tree.get('name')}, "
                  f"{prefetched_tree.get('total_files', 0)} file(s)")
        else:
            if not _alpha_on_pub:
                print(f"[BROWSE] Alpha OFF — skipping cache, fetching fresh (public) uid={uid}")
            prefetched_tree = build_folder_tree(folder_id, {})
            real_name = prefetched_tree.get("name") or "Drive Folder"
            if real_name in ("Root", ""):
                real_name = "Drive Folder"
            prefetched_tree["name"] = real_name
            if not prefetched_tree.get("total_files"):
                raise ValueError("empty tree")
            db.set_drive_folder_tree(folder_id, prefetched_tree)
            print(f"[BROWSE] Fetched & cached tree (public) name={real_name}, "
                  f"{prefetched_tree.get('total_files', 0)} file(s)")
    except Exception:
        # Fallback: flat tree built from the API file list
        real_name = "Drive Folder"
        prefetched_tree = {
            "id":          folder_id,
            "name":        real_name,
            "subfolders":  [],
            "files":       [{"id": fid, "name": fname} for fid, fname in file_list],
            "total_files": len(file_list),
        }

    cookie_server.set_folder_tree_cache(uid, folder_id, prefetched_tree)

    _spin_stop_pub.set()
    _spin_thread_pub.join(timeout=2)

    # Register webapp download callback
    def _on_public_dl(fl, _client=client, _msg=message, _uid=uid, _fid=folder_id):
        threading.Thread(
            target=execute_folder_download,
            args=(_client, _msg, _uid, fl, None),
            kwargs={"folder_id": _fid},
            daemon=True,
        ).start()
    cookie_server.register_download_callback(uid, _on_public_dl)

    browse_url = get_browse_url(uid, folder_id)
    total = prefetched_tree.get("total_files", len(file_list))
    _edit(
        f"📂 <b>Folder Ready!</b>\n\n"
        f"<b>{total}</b> files mil gayi.\n"
        "Drive Browser mein files select karein aur Telegram pe bhejein.",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Open Drive Browser", web_app=WebAppInfo(url=browse_url))],
            [InlineKeyboardButton("🚫 Cancel", callback_data="cancel_task")],
        ]),
    )
    RETRY_DATA[uid] = {"type": "folder", "folder_id": folder_id}


def _do_pdf_download(client, uid: int, orientation: str):
    """Download PDF/document and upload to user. Called after orientation chosen."""
    data       = PENDING_PDF_ORIENT.pop(uid, None)
    if not data:
        return
    file_id    = data["file_id"]
    hint_name  = data["hint_name"]
    mime_type  = data["mime_type"]
    status_msg = data["status_msg"]
    origin_msg = data["origin_msg"]
    folder_url = data.get("folder_url")

    # Always re-fetch the freshest cookies from DB — user may have re-uploaded
    # cookies after the orientation prompt appeared, so stale dict can be wrong
    saved_cookie_str = db.get_google_cookies(uid)
    if saved_cookie_str:
        cookies = parse_cookie_str(saved_cookie_str)
    else:
        cookies = data.get("cookies", {})   # fall back to stored dict
    print(f"[PDF_DL] uid={uid} file={file_id} mime={mime_type} cookies={len(cookies)}")

    from_user  = getattr(origin_msg, "from_user", None)
    display    = _get_display_name(from_user) if from_user else f"User_{uid}"
    s          = db.get_settings(uid)
    nt         = db.SPEED_THREADS.get(s.get("speed_preset", "max"), 16)

    def _edit(txt, markup=CANCEL_KB):
        tg_edit_safe(status_msg, txt, markup=markup)

    raw_title = os.path.splitext(hint_name)[0] if hint_name else "document"
    if uid in PENDING_RENAME:
        raw_title = PENDING_RENAME.pop(uid)
    valid_title = clean_filename(raw_title) + ".pdf"
    filepath    = os.path.join(DOWNLOADS_DIR, valid_title)

    pdf_url    = _build_pdf_url(file_id, mime_type, orientation)
    orient_lbl = "🔄 Landscape" if orientation == "landscape" else "📄 Portrait"
    _edit(f"<b>⬇️ PDF download ho raha hai…</b>\n{orient_lbl}")

    ACTIVE_TASKS.add(uid);  TASK_START_TIMES[uid] = time.time()
    _cancel_evt = threading.Event(); CANCEL_EVENTS[uid] = _cancel_evt
    try:
        last_edit = {"t": 0}

        def on_progress(dl, total_b, spd, ela, eta):
            now = time.time()
            if now - last_edit["t"] < 2:
                return
            last_edit["t"] = now
            _edit(draw_progress_card(valid_title, dl, total_b, spd, ela, eta, 1, 1, nt), CANCEL_KB)

        def _cancelled():
            return uid in CANCEL_TASKS

        # Use the proven authenticated requests download for ALL document types.
        # _build_pdf_url gives the correct export URL for native Google Workspace files
        # (Docs → /export?format=pdf, Sheets → spreadsheets/export, etc.)
        # _drive_auth_download sends cookies with .google.com domain so they reach
        # docs.google.com, drive.google.com, googleusercontent.com etc.
        try:
            _drive_auth_download(pdf_url, cookies, filepath, on_progress, _cancelled)
        except Exception as _pdf_dl_err:
            if "download_disabled_by_owner" in str(_pdf_dl_err):
                _edit(
                    "🔄 <b>Download disabled by owner</b> — browser kholke page-by-page extract kar raha hai…\n"
                    "<i>(kuch minutes lag sakte hain)</i>"
                )
                _, _vt3 = _drive_pdf_via_viewer(file_id, cookies, filepath,
                                                on_progress, status_cb=_edit)
                if _vt3:
                    _r3_title = clean_filename(_vt3) + ".pdf"
                    _r3_path  = os.path.join(DOWNLOADS_DIR, _r3_title)
                    try: os.rename(filepath, _r3_path)
                    except: _r3_path = filepath; _r3_title = valid_title
                    filepath    = _r3_path
                    valid_title = _r3_title
            else:
                raise

        if uid in CANCEL_TASKS:
            CANCEL_TASKS.discard(uid)
            _edit("<b>🚫 Download cancelled.</b>", None)
            return

        file_size = os.path.getsize(filepath)
        _edit("<b>📤 Upload ho raha hai…</b>")

        thumb_path = None
        tt = s.get("thumb_type", "auto")
        if tt == "custom":
            lp = thumb_local_path(uid)
            thumb_path = lp if os.path.exists(lp) else None

        sent = _do_upload(
            client, origin_msg, uid, filepath, valid_title,
            file_size, {}, thumb_path, "document", _edit, 1, 1,
        )
        _edit("✅ <b>PDF successfully sent!</b>", DONE_KB)

        source_url = f"https://drive.google.com/file/d/{file_id}"
        _copy_to_destinations(
            client, origin_msg, uid, sent,
            display=display, file_type="PDF",
            file_size=file_size, source_url=source_url, folder_url=folder_url,
            drive_file_id=file_id, fname=valid_title,
        )
        db.save_download_history(uid, valid_title, file_size, "PDF", source_url, folder_url)
        log_to_channel(client,
            f"✅ #PDF #uid_{uid}\n\n"
            f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
            f"📄 File: <code>{h(valid_title)}</code>\n"
            f"📦 Size: {format_size(file_size)}\n"
            f"🔄 Orient: {orient_lbl}\n"
            f"⏰ {_now_str()}"
        )
    except Exception as e:
        err_str = str(e).lower()
        has_cookies = bool(db.get_google_cookies(uid))
        if any(x in err_str for x in ("403", "401", "forbidden", "permission", "access denied", "status 4")):
            RETRY_DATA[uid] = {"type": "pdf", "file_id": file_id, "hint": hint_name, "mime": mime_type}
            if has_cookies:
                _edit(
                    f"❌ <b>PDF download failed — cookies expire ho gayi hain ya file private hai.</b>\n\n"
                    "Nayi cookies export karein aur re-login karein.",
                    cookie_login_kb(uid),
                )
            else:
                _edit(
                    f"❌ <b>PDF download failed — file private hai.</b>\n\n"
                    "Apne Google cookies share karein taaki main private Drive files download kar sakoon.",
                    cookie_login_kb(uid),
                )
        else:
            _edit(
                f"❌ <b>PDF download failed:</b>\n<code>{h(str(e))}</code>",
                RETRY_KB,
            )
        print(f"[PDF] ❌ uid={uid}: {e}")
    finally:
        ACTIVE_TASKS.discard(uid);  TASK_START_TIMES.pop(uid, None)
        CANCEL_EVENTS.pop(uid, None)
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass


def _build_folder_index_text(tree: dict) -> str:
    """
    Build a folder structure preview message to send before downloads.
    Format:
      📁 "Main Folder Name"          ← bold + quotes always
      📂 Subfolder Name              ← bold, no quotes (if subfolders exist)
         ┗ 📂 Sub-subfolder          ← indented bold (if nested)
    """
    if not tree:
        return ""
    main_name  = tree.get("name", "Folder")
    subfolders = tree.get("subfolders", [])

    lines = [f'📁 <b>"{h(main_name)}"</b>']

    if subfolders:
        lines.append("")
        for sf in subfolders:
            lines.append(f'📂 <b>{h(sf.get("name", ""))}</b>')
            sub_subs = sf.get("subfolders", [])
            for ssf in sub_subs:
                lines.append(f'   ┗ 📂 <b>{h(ssf.get("name", ""))}</b>')

    return "\n".join(lines)


def execute_folder_download(client, message, uid, file_list, status_msg,
                            folder_id: str = None):
    """Download + upload using the same single-file logic for every file."""
    # Normalise: accept both dicts {id,name,path} (from web browse) and tuples/lists (from bot)
    # For dicts: reconstruct full "FolderPath/filename" so subfolder grouping works.
    def _norm(item):
        if isinstance(item, dict):
            fid         = item.get("id") or item.get("file_id", "")
            name        = item.get("name", "")
            folder_path = item.get("path", "")   # e.g. "Dark Psychology/Module 1"
            mime        = item.get("mimeType", "") or item.get("mime_type", "")
            if folder_path and name and not folder_path.endswith("/" + name):
                return (fid, folder_path + "/" + name, mime)
            return (fid, name or folder_path or "unknown", mime)
        # Support both (fid, path) and (fid, path, mime) tuples
        if len(item) >= 3:
            return (item[0], item[1], item[2])
        return (item[0], item[1], "")
    file_list = [_norm(x) for x in file_list]
    # Natural sort by full path so subfolders always come in correct numbered order
    # e.g. "1. Module/" before "2. Module/" before "10. Module/"
    def _nat_sort_key(s: str):
        import re as _re_nat
        return [int(c) if c.isdigit() else c.lower()
                for c in _re_nat.split(r"(\d+)", s)]
    file_list.sort(key=lambda x: _nat_sort_key(x[1]))
    total      = len(file_list)
    success = fail = 0
    sent_info  = []    # list of (fname, sent_msg) for successful files
    fail_info  = []    # list of fname for failed files
    ACTIVE_TASKS.add(uid);  TASK_START_TIMES[uid] = time.time()
    _cancel_evt = threading.Event(); CANCEL_EVENTS[uid] = _cancel_evt
    folder_url = f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else None

    from_user = getattr(message, "from_user", None)
    # Prioritise name stored in DB — avoids getting bot's own name when
    # message is a bot-sent message (e.g. status/callback message)
    _stored_name = (db.get_user_full(uid).get("user") or {}).get("name", "")
    if _stored_name:
        display = _stored_name
    elif from_user and not getattr(from_user, "is_bot", False):
        display = _get_display_name(from_user)
    else:
        display = f"User_{uid}"

    s = db.get_settings(uid)
    log_to_channel(client,
        f"🚀 #FolderStart #uid_{uid}\n\n"
        f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
        f"📂 Files: {total}\n"
        + (f"📁 Folder: <a href='{folder_url}'>link</a>\n" if folder_url else "")
        + f"⏰ {_now_str()}"
    )

    # ── Build ordered groups from file paths ──────────────────────────────────
    # file_list items are (file_id, "RootFolder/SubFolder/filename.ext")
    # path parts: [0]=main folder, [1]=subfolder (if any), [-1]=filename
    # Groups = [(subfolder_header_or_None, [(fid, fname), ...]), ...]
    _main_folder_name = None
    _ordered_groups   = None

    try:
        from collections import OrderedDict as _OD
        _sf_map   = _OD()    # subfolder_key → list of (fid, fname)
        _root_key = "__root__"

        _GENERIC_ROOTS = {"root", "drive folder", "my drive", ""}

        def _nat_key(s: str):
            """Natural sort key: splits on digit runs so '10' > '2'."""
            import re as _re2
            return [int(c) if c.isdigit() else c.lower()
                    for c in _re2.split(r"(\d+)", s)]

        for fid, fname, fmime in file_list:
            parts = fname.replace("\\", "/").split("/")
            # parts[-1] = filename (always)
            # Detect if parts[0] is a generic placeholder (e.g. "Root" from old API)
            _p0_generic = len(parts) > 0 and parts[0].lower() in _GENERIC_ROOTS

            # Main folder name: first non-generic part
            if not _main_folder_name:
                if _p0_generic and len(parts) >= 4:
                    # "Root / MainFolder / SubFolder / file" — MainFolder is parts[1]
                    _main_folder_name = parts[1]
                elif _p0_generic and len(parts) >= 3:
                    # "Root / SubFolder / file" — no real main folder in path
                    pass   # leave None; DB fallback will fill it
                elif not _p0_generic and len(parts) >= 1:
                    _main_folder_name = parts[0]

            # Subfolder key: always the TOP-LEVEL subfolder (parts[1] for generic root)
            # e.g. "Root/1. FolderName/SubA/file" → key = "1. FolderName" (not "SubA")
            if _p0_generic:
                # parts[1] is always the top-level subfolder regardless of depth
                sf_key = parts[1] if len(parts) >= 3 else _root_key
            else:
                # "MainFolder / SubFolder(optional) / ... / file"
                sf_key = parts[1] if len(parts) >= 3 else _root_key

            if sf_key not in _sf_map:
                _sf_map[sf_key] = []
            _sf_map[sf_key].append((fid, fname, fmime))

        # Build ordered groups: root files first, then subfolders sorted naturally
        _groups = []
        if _root_key in _sf_map:
            _groups.append((None, _sf_map[_root_key]))
        _sorted_sf_keys = sorted(
            (k for k in _sf_map if k != _root_key),
            key=_nat_key,
        )
        for sf_key in _sorted_sf_keys:
            # Sort files within each subfolder naturally too
            _sf_map[sf_key].sort(key=lambda x: _nat_key(x[1]))
            _groups.append((sf_key, _sf_map[sf_key]))
        # Also sort root-level files naturally
        if _groups and _groups[0][0] is None:
            _groups[0][1].sort(key=lambda x: _nat_key(x[1]))

        _ordered_groups = _groups if _groups else None
        print(f"[FOLDER_GROUP] uid={uid} main='{_main_folder_name}' "
              f"groups={[(g[0], len(g[1])) for g in (_groups or [])]}")

    except Exception as _te:
        print(f"[FOLDER_TREE] path grouping failed: {_te}")
        import traceback; traceback.print_exc()

    # ── Fallback: get folder name from DB tree if path gave nothing usable ────
    if not _main_folder_name and folder_id:
        try:
            _cached = db.get_drive_folder_tree(folder_id)
            if _cached:
                _n = _cached.get("name", "")
                if _n and _n.lower() not in ("root", "drive folder", ""):
                    _main_folder_name = _n
        except Exception:
            pass

    # ── Send main folder name as blockquote + bold via raw MTProto ───────────
    if _main_folder_name:
        _folder_plain = f"📁 {_main_folder_name}"
        # User chat
        try:
            _send_blockquote(client, message.chat.id, _folder_plain, reply_to_message_id=message.id)
        except Exception as _fne:
            print(f"[FOLDER_GROUP] folder name send failed: {_fne}")
        # Delta channel if enabled
        try:
            _ds = db.get_delta_settings(uid)
            if _ds.get("delta_mode") and _ds.get("delta_channel_id"):
                _send_blockquote(client, _ds["delta_channel_id"], _folder_plain)
        except Exception as _dfe:
            print(f"[DELTA] folder header failed: {_dfe}")

    # ── ONE persistent progress message for the whole folder ─────────────────
    # Creating + deleting a message per file (300 files = 600+ API calls) triggers
    # Telegram flood-wait and makes the bot unresponsive. Reuse a single message.
    _folder_prog_msg = status_msg
    _folder_prog_pinned = False
    if _folder_prog_msg is None:
        try:
            _folder_prog_msg = message.reply_text(
                f"📂 <b>{total} file(s) download shuru…</b>\n"
                f"<i>Cancel karne ke liye Cancel button dabayein.</i>",
                reply_markup=CANCEL_KB,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            _folder_prog_msg = None
    else:
        try:
            _folder_prog_msg.edit_text(
                f"📂 <b>{total} file(s) download shuru…</b>\n"
                f"<i>Cancel karne ke liye Cancel button dabayein.</i>",
                reply_markup=CANCEL_KB,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass
    # Pin the progress message so user can always see status
    if _folder_prog_msg:
        try:
            client.pin_chat_message(
                _folder_prog_msg.chat.id,
                _folder_prog_msg.id,
                disable_notification=True,
                both_sides=True,
            )
            _folder_prog_pinned = True
        except Exception as _pe:
            print(f"[FOLDER_PIN] pin failed: {_pe}")

    start_time = time.time()
    try:
        def _folder_cancelled():
            evt = CANCEL_EVENTS.get(uid)
            return uid in CANCEL_TASKS or (evt is not None and evt.is_set())

        def _process_file(fid, fname, file_index, fmime=""):
            return process_single_file(
                client, message, uid,
                file_id=fid,
                hint_name=os.path.basename(fname),
                status_msg=_folder_prog_msg,
                file_index=file_index,
                total=total,
                max_retries=2,
                folder_url=folder_url,
                mime_hint=fmime,
            )

        global_i = 0

        if _ordered_groups:
            # ── Grouped: send subfolder header before each group's files ──────
            for sf_header, grp_files in _ordered_groups:
                if _folder_cancelled():
                    CANCEL_TASKS.discard(uid)
                    break

                # Send subfolder name as blockquote+bold (same style as main folder)
                if sf_header:
                    print(f"[FOLDER_GROUP] Sending subfolder header: '{sf_header}' ({len(grp_files)} files)")
                    try:
                        _sfh_res = _send_blockquote(
                            client, message.chat.id,
                            f"📂 {sf_header}",
                            reply_to_message_id=message.id,
                        )
                        print(f"[FOLDER_GROUP] Subfolder header sent: {bool(_sfh_res)}")
                    except Exception as _sfhe:
                        print(f"[FOLDER_GROUP] Subfolder header failed: {_sfhe}")
                    # Also send subfolder header to delta channel
                    try:
                        _ds2 = db.get_delta_settings(uid)
                        if _ds2.get("delta_mode") and _ds2.get("delta_channel_id"):
                            _send_blockquote(client, _ds2["delta_channel_id"], f"📂 {sf_header}")
                    except Exception:
                        pass

                # Track the FULL intermediate path (supports unlimited nesting depth)
                _cur_subsf_path = []   # list of folder name parts between sf_header and filename

                for _item in grp_files:
                    fid, fname, fmime = _item[0], _item[1], (_item[2] if len(_item) > 2 else "")
                    global_i += 1
                    if _folder_cancelled():
                        CANCEL_TASKS.discard(uid)
                        break

                    # ── Detect ALL intermediate subfolder levels and send headers ──
                    # Path formats:
                    #   Non-generic: "MainFolder/Sub1/SubA/SubSubA/file.ext"
                    #                [0]=main, [1]=sf_header_level, [2:-1]=intermediates
                    #   Generic root: "Root/Sub1/SubA/SubSubA/file.ext"
                    #                [0]=root, [1]=sf_header_level, [2:-1]=intermediates
                    # In both cases intermediates = parts[2:-1] (same formula)
                    _fparts = fname.replace("\\", "/").split("/")
                    # parts[2:-1] gives everything between the top-level subfolder and the filename
                    _subsf_parts = _fparts[2:-1] if len(_fparts) >= 4 else []

                    if _subsf_parts != _cur_subsf_path:
                        # Find common prefix length (parts that haven't changed)
                        _common = 0
                        for _pa, _pb in zip(_subsf_parts, _cur_subsf_path):
                            if _pa == _pb:
                                _common += 1
                            else:
                                break
                        _cur_subsf_path = list(_subsf_parts)
                        # Send headers only for new/changed levels
                        for _lvl in range(_common, len(_subsf_parts)):
                            _part   = _subsf_parts[_lvl]
                            _indent = "  " * (_lvl + 1)
                            _sfh_txt = f'{_indent}┗ 📂 <b>{h(_part)}</b>'
                            try:
                                tg_reply_safe(message, _sfh_txt)
                            except Exception:
                                pass
                            # Also to delta channel
                            try:
                                _ds3 = db.get_delta_settings(uid)
                                if _ds3.get("delta_mode") and _ds3.get("delta_channel_id"):
                                    client.send_message(
                                        chat_id=_ds3["delta_channel_id"],
                                        text=_sfh_txt,
                                        parse_mode=enums.ParseMode.HTML,
                                    )
                            except Exception:
                                pass

                    sent = _process_file(fid, fname, global_i, fmime)

                    if _folder_cancelled():
                        CANCEL_TASKS.discard(uid)
                        break

                    if sent:
                        success += 1
                        sent_info.append((fname, sent))
                    else:
                        fail += 1
                        fail_info.append(os.path.basename(fname))

                    if global_i < total and not _folder_cancelled():
                        time.sleep(0.5)
        else:
            # ── Flat (no tree): original sequential processing ─────────────────
            for i, item in enumerate(file_list, 1):
                fid   = item[0]
                fname = item[1]
                fmime = item[2] if len(item) > 2 else ""
                if _folder_cancelled():
                    CANCEL_TASKS.discard(uid)
                    break

                sent = _process_file(fid, fname, i, fmime)

                if _folder_cancelled():
                    CANCEL_TASKS.discard(uid)
                    break

                if sent:
                    success += 1
                    sent_info.append((fname, sent))
                else:
                    fail += 1
                    fail_info.append(os.path.basename(fname))

                if i < total and not _folder_cancelled():
                    time.sleep(0.5)

    finally:
        ACTIVE_TASKS.discard(uid);  TASK_START_TIMES.pop(uid, None)
        CANCEL_EVENTS.pop(uid, None)
        FOLDER_SELECTIONS.pop(uid, None)
        # Unpin progress message now that download is done
        if _folder_prog_pinned and _folder_prog_msg:
            try:
                client.unpin_chat_message(
                    _folder_prog_msg.chat.id,
                    _folder_prog_msg.id,
                )
            except Exception:
                pass

    elapsed  = time.time() - start_time
    elapsed_str = f"{int(elapsed//60)}m {int(elapsed%60)}s" if elapsed >= 60 else f"{int(elapsed)}s"

    log_to_channel(client,
        f"{'✅' if fail==0 else '⚠️'} #FolderDone #uid_{uid}\n\n"
        f"👤 User: <a href='tg://user?id={uid}'>{h(display)}</a>\n"
        f"📂 Total: {total}  ✅ {success}  ❌ {fail}\n"
        f"⏰ {_now_str()}"
    )

    # ── Streaming summary animation ───────────────────────────────────────
    summary_msg = tg_reply_safe(
        message,
        "📊 <b>Process complete…</b>\n<code>⠋</code>  Report collect ho raha hai…",
    )
    time.sleep(0.7)
    tg_edit_safe(summary_msg,
        f"📊 <b>Process complete…</b>\n<code>⠹</code>  Stats compile ho rahi hain…\n\n"
        f"✅ <b>{success}</b> / {total} files sent"
    )
    time.sleep(0.7)

    # Build detailed summary
    emoji = "✅" if fail == 0 else ("⚠️" if success else "❌")
    lines = [
        f"{emoji} <b>Folder Process Complete!</b>",
        "",
        f"📂 <b>Total Files:</b>  {total}",
        f"✅ <b>Sent:</b>         {success}",
    ]
    if fail:
        lines.append(f"❌ <b>Failed:</b>       {fail}")
    lines.append(f"⏱ <b>Time Taken:</b>   {elapsed_str}")

    if sent_info:
        lines.append("")
        lines.append("📄 <b>Sent Files:</b>")
        for fname, _ in sent_info[:10]:
            lines.append(f"  ✅ <code>{h(os.path.basename(fname))}</code>")
        if len(sent_info) > 10:
            lines.append(f"  … and {len(sent_info) - 10} more")

    if fail_info:
        lines.append("")
        lines.append("❌ <b>Failed Files:</b>")
        for fname in fail_info[:5]:
            lines.append(f"  ❌ <code>{h(fname)}</code>")
        if len(fail_info) > 5:
            lines.append(f"  … and {len(fail_info) - 5} more")

    tg_edit_safe(summary_msg, "\n".join(lines))
    try:
        summary_msg.edit_reply_markup(DONE_KB)
    except FloodWait as fw:
        time.sleep(fw.value + 1)
        try:
            summary_msg.edit_reply_markup(DONE_KB)
        except Exception:
            pass
    except Exception:
        pass

    # ── Save folder cache for Alpha quick-resend ──────────────────────────
    if sent_info and folder_id:
        try:
            # Build a fid→fname map from file_list so we can save drive file IDs
            _fid_map = {os.path.basename(item[1]): item[0] for item in file_list}
            cache_files = []
            for fn, _ in sent_info:
                bname = os.path.basename(fn)
                fid = _fid_map.get(bname)
                if fid:
                    fc = db.get_file_cache(fid)
                    cache_files.append({
                        "drive_file_id": fid,
                        "fname":         bname,
                        "dump_msg_id":   fc.get("dump_msg_id") if fc else None,
                        "file_type":     fc.get("file_type", "File") if fc else "File",
                        "file_size":     fc.get("file_size", 0) if fc else 0,
                    })
            if cache_files:
                db.set_folder_cache(folder_id, cache_files, folder_url)
                print(f"[FOLDER_CACHE] Saved folder_id={folder_id} with {len(cache_files)} files")
        except Exception as fce:
            print(f"[FOLDER_CACHE] Save error: {fce}")

    # ── Send to folder DB channel (organized by subfolder) ────────────────
    if sent_info and folder_id:
        send_folder_to_db_channel(client, uid, display, folder_id, sent_info)


# ─────────────────────────────────────────────
#  Startup helpers
# ─────────────────────────────────────────────

def restore_thumbnails():
    entries = db.get_all_custom_thumbs()
    if not entries: return
    print(f"[THUMB] Restoring {len(entries)} thumbnail(s)…")
    for e in entries:
        uid = e["user_id"];  fid = e["custom_thumb_file_id"]
        lp  = thumb_local_path(uid)
        if os.path.exists(lp): continue
        try:
            bot.download_media(fid, file_name=lp)
            print(f"[THUMB] Restored uid={uid}")
        except Exception as err:
            print(f"[THUMB] Failed uid={uid}: {err}")


def ensure_db_topics():
    if not DB_GROUP_ID:
        print("[DB_GROUP] DB_GROUP_ID not set — skipping"); return
    users = db.get_all_users()
    if not users:
        print("[DB_GROUP] No users in DB yet — skipping"); return
    print(f"[DB_GROUP] Syncing topics for {len(users)} user(s)…")
    created = 0
    for u in users:
        uid  = u["user_id"];  name = u.get("name") or f"User_{uid}"
        if (db.get_db_group_topic(uid) or 0) > 0: continue
        new_id = create_forum_topic_raw(bot, DB_GROUP_ID, f"{name} | {uid}")
        if new_id and new_id > 0:
            db.set_db_group_topic(uid, new_id)
            print(f"[DB_GROUP] Created topic for {name} ({uid}) → {new_id}")
            created += 1
        else:
            print(f"[DB_GROUP] Topic creation failed for {uid} (need Manage Topics perm)")
    print(f"[DB_GROUP] Sync done — {created} new topic(s) created")


# ─────────────────────────────────────────────
#  Force Subscribe check
# ─────────────────────────────────────────────

def _force_sub_invite_link(client: Client, ch) -> tuple:
    """
    Return (title, invite_link) for a force-sub channel.
    If bot is admin it creates a fresh invite link; otherwise falls back to
    the existing invite_link or a public t.me link.
    """
    try:
        chat  = client.get_chat(ch)
        title = chat.title or str(ch)
    except Exception:
        return str(ch), None

    # Try creating invite link (works only if bot is admin)
    try:
        lnk = client.create_chat_invite_link(ch).invite_link
        print(f"[FORCE_SUB] Created invite link for {ch}: {lnk}")
        return title, lnk
    except Exception:
        pass

    # Fall back to existing invite link or public username link
    if chat.invite_link:
        return title, chat.invite_link
    if chat.username:
        return title, f"https://t.me/{chat.username}"

    print(f"[FORCE_SUB] Could not get any link for {ch} — bot may not be admin")
    return title, None


def check_force_sub(client: Client, message: Message) -> bool:
    """Return True if user passes all FORCE_SUB_CHANNELS checks (or none configured)."""
    if not FORCE_SUB_CHANNELS:
        return True
    uid        = message.from_user.id
    not_joined = []
    for ch in FORCE_SUB_CHANNELS:
        try:
            mem = client.get_chat_member(ch, uid)
            if mem.status in (enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.LEFT):
                not_joined.append(ch)
        except Exception:
            not_joined.append(ch)

    if not not_joined:
        return True

    print(f"[FORCE_SUB] uid={uid} | not joined: {not_joined}")
    rows = []
    for ch in not_joined:
        title, lnk = _force_sub_invite_link(client, ch)
        if lnk:
            rows.append([InlineKeyboardButton(f"📢 Join: {title}", url=lnk)])
        else:
            rows.append([InlineKeyboardButton(f"📢 Join: {title}", callback_data="noop")])

    rows.append([InlineKeyboardButton("✅ Maine Join Kar Liya", callback_data="check_sub")])
    warn_msg = stream_reply(
        message,
        [
            "⚠️ <b>Force Subscribe</b>",
            "",
            "Is bot ko use karne ke liye pehle",
            "neeche diye channels join karein:",
        ],
        delay=0.15,
    )
    # Send keyboard message and track both message IDs for later deletion
    msg_ids = []
    if warn_msg:
        msg_ids.append(warn_msg.id)
    try:
        sent = message.reply_text(
            "👇 <b>Yeh channels join karein:</b>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows),
        )
        msg_ids.append(sent.id)
    except Exception:
        pass
    FORCE_SUB_MSGS[uid] = msg_ids
    return False


# ─────────────────────────────────────────────
#  Bot handlers
# ─────────────────────────────────────────────

def get_welcome_text(display: str) -> str:
    return (
        "╭━━━━━〔 ⚡ GOOGLE DRIVE BOT ⚡ 〕━━━━━╮\n"
        "│  <i>Advanced • High-Speed • Cloud Downloader</i>  │\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"👋 <b>Namaste {h(display)}!</b>\n\n"
        "Google Drive ka koi bhi link bhejein, bot multi-threaded engine se fast download karke aapko bhej dega.\n\n"
        "🚀 <b>Core Capabilities:</b>\n"
        "• 📁 <b>Folders & Batch:</b> Poora folder ek click mein download karein\n"
        "• 🌐 <b>1-Click OAuth:</b> Private files & Shared Drives direct access\n"
        "• ⚡ <b>Turbo Speed:</b> Multi-threaded direct streaming\n"
        "• 🎨 <b>Personalize:</b> Custom rename, custom thumbnail, video/doc mode\n"
        "• 📦 <b>Large Files:</b> 4GB tak Telegram support\n\n"
        "💎 <b>VIP Membership:</b>\n"
        f"• Price: <b>{ULTRA_PLAN_PRICE}</b> (Unlimited Access)\n"
        "• Plan lene ke liye Admin: <b>@ftmdevz</b>\n\n"
        "🤖 <b>Bot Setup / Clone Bot Chahiye?</b>\n"
        "Apna khud ka branded Google Drive bot banwane ke liye contact karein:\n"
        "👉 <b>Admin:</b> @ftmdevz"
    )


@bot.on_message(filters.command(["start", "help"]))
def send_welcome(client: Client, message: Message):
    uid     = message.from_user.id
    display = _get_display_name(message.from_user)

    # ── Force Subscribe check ─────────────────────────────────────────────
    if not check_force_sub(client, message):
        print(f"[FORCE_SUB] uid={uid} | failed force-sub check on /start — ignored")
        return

    is_new  = db.save_user(uid, display)

    # Ensure topic exists (create if missing)
    tid = ensure_user_topic(client, uid, display)

    if is_new and DB_GROUP_ID:
        # Send & pin a welcome message in user's topic
        mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
        welcome_txt = (
            f"👋 <b>New User Joined!</b>\n\n"
            f"👤 <b>Name:</b> {mention}\n"
            f"🆔 <b>UID:</b> <code>{uid}</code>\n"
            f"⏰ <b>Joined:</b> {_now_str()}\n\n"
            f"#NewUser #uid_{uid}"
        )
        kw = {"chat_id": DB_GROUP_ID, "text": welcome_txt,
              "parse_mode": enums.ParseMode.HTML}
        if tid and tid > 0:
            kw["reply_to_message_id"] = tid
        def _pin_welcome():
            try:
                m = client.send_message(**kw)
                client.pin_chat_message(DB_GROUP_ID, m.id, disable_notification=True)
            except Exception as e:
                print(f"[TOPIC] Pin welcome failed uid={uid}: {e}")
        threading.Thread(target=_pin_welcome, daemon=True).start()

        log_to_channel(client,
            f"🆕 #NewUser #uid_{uid}\n\n"
            f"👤 User: {mention}\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"⏰ {_now_str()}"
        )

    if not is_new:
        mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
        log_to_channel(client,
            f"👋 #Start #uid_{uid}\n\n"
            f"👤 User: {mention} (<code>{uid}</code>)\n"
            f"🔄 Action: <b>Used /start</b>\n"
            f"⏰ {_now_str()}"
        )

    message.reply_text(
        get_welcome_text(display),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=WELCOME_KB,
    )

@bot.on_message(filters.command("myip"))
def myip_command(client: Client, message: Message):
    status = message.reply_text("🔍 <b>Checking server IP details...</b>", parse_mode=enums.ParseMode.HTML)

    try:
        info = fetch_current_ip_details()

        hostname = socket.gethostname()
        try:
            local_ip = socket.gethostbyname(hostname)
        except Exception:
            local_ip = "N/A"

        text = (
            "🌐 <b>Server IP Details</b>\n\n"
            f"📡 <b>Public IP:</b> <code>{h(str(info.get('ip', 'N/A')))}</code>\n"
            f"🔖 <b>IP Type:</b> <code>{h(str(info.get('type', 'N/A')))}</code>\n\n"
            f"🏙️ <b>City:</b> <code>{h(str(info.get('city', 'N/A')))}</code>\n"
            f"📍 <b>Region:</b> <code>{h(str(info.get('region', 'N/A')))}</code>\n"
            f"🌎 <b>Country:</b> <code>{h(str(info.get('country', 'N/A')))}</code>\n"
            f"⏰ <b>Timezone:</b> <code>{h(str(info.get('timezone', 'N/A')))}</code>\n\n"
            f"🏢 <b>ISP/Org:</b> <code>{h(str(info.get('isp', 'N/A')))}</code>\n"
            f"🔢 <b>ASN:</b> <code>{h(str(info.get('asn', 'N/A')))}</code>\n\n"
            f"🖥️ <b>Hostname:</b> <code>{h(hostname)}</code>\n"
            f"🔌 <b>Local IP:</b> <code>{h(local_ip)}</code>\n"
            f"🐍 <b>Python:</b> <code>{platform.python_version()}</code>\n"
            f"💻 <b>System:</b> <code>{h(platform.system())} {h(platform.release())}</code>\n\n"
            f"📦 <b>Source:</b> <code>{h(str(info.get('source', 'N/A')))}</code>"
        )

        status.edit_text(text, parse_mode=enums.ParseMode.HTML)

    except Exception as e:
        status.edit_text(
            "❌ <b>Failed to fetch IP details</b>\n\n"
            f"Error: <code>{h(str(e))}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
@bot.on_message(filters.command(["settings"]))
def cmd_settings(client: Client, message: Message):
    uid     = message.from_user.id
    display = _get_display_name(message.from_user)
    mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    log_to_channel(client,
        f"⚙️ #Settings #uid_{uid}\n\n"
        f"👤 User: {mention} (<code>{uid}</code>)\n"
        f"🔄 Action: <b>Opened Settings</b>\n"
        f"⏰ {_now_str()}"
    )
    message.reply_text(
        _settings_html(uid),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=settings_keyboard(uid),
    )


@bot.on_message(filters.command(["stats"]))
def cmd_stats(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        stream_reply(message, ["❌ Sirf admins ke liye."])
        return
    user_count = db.get_user_count()
    active_cnt = len(ACTIVE_TASKS)
    stream_reply(message, [
        "📊 <b>Bot Stats</b>",
        "",
        f"👥 <b>Total Users:</b>   {user_count}",
        f"⚡ <b>Active Tasks:</b>  {active_cnt}",
    ], delay=0.12)


@bot.on_message(filters.command(["cancel"]))
def cmd_cancel(client: Client, message: Message):
    uid     = message.from_user.id
    display = _get_display_name(message.from_user)
    mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    if uid in ACTIVE_TASKS:
        CANCEL_TASKS.add(uid)
        # Signal the cancel event immediately for instant stop
        evt = CANCEL_EVENTS.get(uid)
        if evt:
            evt.set()
        log_to_channel(client,
            f"🚫 #Cancel #uid_{uid}\n\n"
            f"👤 User: {mention} (<code>{uid}</code>)\n"
            f"🔄 Action: <b>Cancelled active task</b>\n"
            f"⏰ {_now_str()}"
        )
        message.reply_text(
            "🚫 <b>Cancelled!</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        stream_reply(message, ["ℹ️ Koi active download nahi chal raha."])


@bot.on_message(filters.command(["restart"]))
def cmd_restart(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        message.reply_text("❌ Sirf admins hi /restart use kar sakte hain.", parse_mode=enums.ParseMode.HTML)
        return
    display = _get_display_name(message.from_user)
    mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    log_to_channel(client,
        f"🔄 #Restart #uid_{uid}\n\n"
        f"👤 Admin: {mention} (<code>{uid}</code>)\n"
        f"⏰ {_now_str()}"
    )
    message.reply_text("🔄 <b>Bot restart ho raha hai…</b>", parse_mode=enums.ParseMode.HTML)
    time.sleep(1)
    import sys
    os.execv(sys.executable, [sys.executable] + sys.argv)


def _fmt_ts(ts) -> str:
    """Format a unix timestamp float → readable IST date-time string."""
    if not ts:
        return "—"
    try:
        dt = datetime.datetime.fromtimestamp(float(ts), tz=ZoneInfo("Asia/Kolkata"))
        return dt.strftime("%d %b %Y  %I:%M %p")
    except Exception:
        return str(ts)


@bot.on_message(filters.command(["history"]))
def cmd_history(client: Client, message: Message):
    uid  = message.from_user.id
    args = message.text.split(None, 1)
    n    = int(args[1].strip()) if len(args) > 1 and args[1].strip().isdigit() else 10
    n    = min(max(n, 1), 50)
    rows = db.get_download_history(uid, n)
    if not rows:
        stream_reply(message, ["📭 <b>Koi download history nahi mili.</b>"])
        return
    lines = [f"📋 <b>Last {len(rows)} Downloads</b>", ""]
    for i, r in enumerate(rows, 1):
        name  = h(r.get("filename") or "Unknown")
        ftype = r.get("file_type") or "—"
        sz    = format_size(r.get("size_bytes") or 0)
        ts    = _fmt_ts(r.get("ts"))
        src   = r.get("source_url", "")
        icon  = "🎬" if ftype == "Video" else "📄"
        line  = f"{i}. {icon} <b>{name}</b>\n    📦 {sz}  ·  {ftype}  ·  🕐 {ts}"
        if src:
            line += f"\n    🔗 <a href=\"{src}\">Source</a>"
        lines.append(line)
    stream_reply(message, lines, delay=0.10)


@bot.on_message(filters.command(["userinfo"]))
def cmd_userinfo(client: Client, message: Message):
    admin_uid = message.from_user.id
    if admin_uid not in ADMIN_IDS:
        stream_reply(message, ["❌ Sirf admins ke liye."])
        return
    args = message.text.split(None, 1)
    if len(args) < 2 or not args[1].strip().lstrip("-").isdigit():
        stream_reply(message, [
            "👤 <b>UserInfo Usage:</b>",
            "",
            "<code>/userinfo &lt;user_id&gt;</code>",
            "Example: <code>/userinfo 123456789</code>",
        ], delay=0.10)
        return

    target_uid = int(args[1].strip())
    data       = db.get_user_full(target_uid)
    user_doc   = data["user"]
    sett_doc   = data["settings"]

    if not user_doc:
        stream_reply(message, [f"❌ <b>User {target_uid} DB mein nahi mila.</b>"])
        return

    name          = h(user_doc.get("name") or "Unknown")
    first_seen    = _fmt_ts(user_doc.get("first_seen"))
    total_dl      = user_doc.get("total_downloads", 0)
    upload_type   = sett_doc.get("upload_type", "document")
    thumb_type    = sett_doc.get("thumb_type", "auto")
    speed_preset  = sett_doc.get("speed_preset", "max")
    folder_filter = sett_doc.get("folder_filter", "all")
    delta_mode    = sett_doc.get("delta_mode", False)
    delta_ch      = sett_doc.get("delta_channel_title") or "—"
    has_cookies   = bool(db.get_google_cookies(target_uid))
    has_caption   = bool(db.get_caption_template(target_uid))

    ut_lbl = "🎬 Video"   if upload_type == "video"  else "📄 Document"
    tt_lbl = {"auto": "🔄 Auto", "custom": "🖼 Custom", "none": "❌ None"}.get(thumb_type, thumb_type)
    sp_lbl = {"normal": "🐢 Normal", "fast": "⚡ Fast", "max": "🚀 Max"}.get(speed_preset, speed_preset)

    hist  = db.get_download_history(target_uid, 5)
    h_lines = []
    for i, r in enumerate(hist, 1):
        fn    = h(r.get("filename") or "Unknown")
        ftype = r.get("file_type") or "—"
        sz    = format_size(r.get("size_bytes") or 0)
        ts    = _fmt_ts(r.get("ts"))
        icon  = "🎬" if ftype == "Video" else "📄"
        h_lines.append(f"  {i}. {icon} <b>{fn}</b>  ({sz})  🕐 {ts}")

    lines = [
        f"👤 <b>User Info</b>",
        "",
        f"🆔 <b>UID :</b> <code>{target_uid}</code>",
        f"📛 <b>Name:</b> {name}",
        f"📅 <b>Joined:</b> {first_seen}",
        f"📥 <b>Total Downloads:</b> {total_dl}",
        "",
        "⚙️ <b>Settings</b>",
        f"  📁 Upload Type  : {ut_lbl}",
        f"  🖼 Thumbnail    : {tt_lbl}",
        f"  ⚡ Speed Preset : {sp_lbl}",
        f"  📂 Folder Filter: {folder_filter}",
        f"  🔀 Delta Mode   : {'✅ ON' if delta_mode else '❌ OFF'}  ({delta_ch})",
        f"  🍪 Google Auth  : {'✅ Logged in' if has_cookies else '❌ Not logged in'}",
        f"  📝 Caption Tpl  : {'✅ Custom set' if has_caption else '❌ Default'}",
        "",
        "📋 <b>Last 5 Downloads</b>",
    ] + (h_lines if h_lines else ["  <i>Koi history nahi</i>"])

    stream_reply(message, lines, delay=0.08)


# ── /users — paginated user list (admin only) ─────────────────────────────────

_UL_PER_PAGE = 8


def _build_users_page(page: int):
    """Return (lines_list, keyboard) for the given page."""
    total    = db.get_user_count()
    pages    = max(1, math.ceil(total / _UL_PER_PAGE))
    page     = max(1, min(page, pages))
    users    = db.get_users_page(page, _UL_PER_PAGE)
    offset   = (page - 1) * _UL_PER_PAGE

    lines = [
        f"👥 <b>Registered Users</b>  <i>(Page {page}/{pages})</i>",
        f"📊 <b>Total:</b> {total}  |  Showing {offset+1}–{offset+len(users)}",
        "─" * 30,
    ]
    for i, u in enumerate(users, offset + 1):
        uid_val = u.get("user_id", "?")
        name    = h(u.get("name") or "Unknown")
        joined  = _fmt_ts(u.get("first_seen"))
        dls     = u.get("total_downloads", 0)
        lines.append(
            f"{i}. 👤 <b>{name}</b>\n"
            f"    🆔 <code>{uid_val}</code>  ·  📥 {dls} downloads  ·  📅 {joined}"
        )

    # ── Navigation keyboard ──────────────────────────────────────────────────
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"ul_pg_{page-1}"))
    nav.append(InlineKeyboardButton(f"📄 {page}/{pages}", callback_data="noop"))
    if page < pages:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"ul_pg_{page+1}"))

    keyboard = InlineKeyboardMarkup([
        nav,
        [InlineKeyboardButton("🚫 Close", callback_data="ul_close")],
    ])
    return lines, keyboard


@bot.on_message(filters.command(["users"]))
def cmd_users(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        stream_reply(message, ["❌ Sirf admins ke liye."])
        return

    args = message.text.split(None, 1)
    page = int(args[1].strip()) if len(args) > 1 and args[1].strip().isdigit() else 1

    lines, keyboard = _build_users_page(page)
    sent = stream_reply(message, lines, delay=0.07)
    try:
        sent.edit_reply_markup(reply_markup=keyboard)
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^ul_pg_(\d+)$"))
def cb_users_page(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    if uid not in ADMIN_IDS:
        query.answer("❌ Sirf admins ke liye.", show_alert=True)
        return

    page             = int(query.matches[0].group(1))
    lines, keyboard  = _build_users_page(page)
    full_text        = "\n".join(lines)
    query.answer(f"Page {page} load ho raha…")
    try:
        query.edit_message_text(
            full_text,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^ul_close$"))
def cb_users_close(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    if uid not in ADMIN_IDS:
        query.answer()
        return
    query.answer("Closed.")
    try:
        query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


@bot.on_message(filters.command(["system"]))
def cmd_system(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        stream_reply(message, ["❌ Sirf admins ke liye."])
        return

    cpu_pct   = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count(logical=True)
    mem       = psutil.virtual_memory()
    disk      = psutil.disk_usage("/")
    net       = psutil.net_io_counters()
    boot_ts   = psutil.boot_time()
    uptime_s  = int(time.time() - boot_ts)
    up_h, rem = divmod(uptime_s, 3600)
    up_m, up_s = divmod(rem, 60)
    uptime_str = f"{up_h}h {up_m}m {up_s}s"
    boot_str   = _fmt_ts(boot_ts)

    bot_up_s   = int(time.time() - BOT_START_TIME)
    bup_h, brem = divmod(bot_up_s, 3600)
    bup_m, bup_s2 = divmod(brem, 60)
    bot_up_str = f"{bup_h}h {bup_m}m {bup_s2}s"

    os_name  = platform.system()
    os_ver   = platform.release()
    arch     = platform.machine()
    py_ver   = platform.python_version()
    hostname = platform.node()

    def _bar(pct, width=15):
        filled = int(width * pct / 100)
        return "█" * filled + "░" * (width - filled)

    lines = [
        "🖥 <b>System Information</b>",
        "",
        "🔧 <b>Host</b>",
        f"  🏷 Hostname : <code>{h(hostname)}</code>",
        f"  💿 OS       : <code>{os_name} {os_ver} ({arch})</code>",
        f"  🐍 Python   : <code>v{py_ver}</code>",
        f"  🤖 Bot Ver  : <code>{BOT_VERSION}</code>",
        "",
        "⚡ <b>CPU</b>",
        f"  🧮 Cores    : <b>{cpu_count}</b>",
        f"  📊 Usage    : <b>{cpu_pct:.1f}%</b>  [{_bar(cpu_pct)}]",
        "",
        "🧠 <b>Memory (RAM)</b>",
        f"  📊 Usage    : <b>{mem.percent:.1f}%</b>  [{_bar(mem.percent)}]",
        f"  ✅ Used     : <b>{format_size(mem.used)}</b>",
        f"  💤 Free     : <b>{format_size(mem.available)}</b>",
        f"  📦 Total    : <b>{format_size(mem.total)}</b>",
        "",
        "💾 <b>Disk</b>",
        f"  📊 Usage    : <b>{disk.percent:.1f}%</b>  [{_bar(disk.percent)}]",
        f"  ✅ Used     : <b>{format_size(disk.used)}</b>",
        f"  💤 Free     : <b>{format_size(disk.free)}</b>",
        f"  📦 Total    : <b>{format_size(disk.total)}</b>",
        "",
        "🌐 <b>Network</b>",
        f"  ⬆️ Sent     : <b>{format_size(net.bytes_sent)}</b>",
        f"  ⬇️ Recv     : <b>{format_size(net.bytes_recv)}</b>",
        "",
        "⏱ <b>Uptime</b>",
        f"  🖥 System   : <b>{uptime_str}</b>  (boot: {boot_str})",
        f"  🤖 Bot      : <b>{bot_up_str}</b>",
        "",
        "📊 <b>Bot Stats</b>",
        f"  👥 Users    : <b>{db.get_user_count()}</b>",
        f"  ⚡ Active   : <b>{len(ACTIVE_TASKS)}</b>",
    ]
    stream_reply(message, lines, delay=0.07)




# ── Admin management (owner-only for add/remove) ──────────────────────────────

@bot.on_message(filters.command(["addadmin"]))
def cmd_addadmin(client: Client, message: Message):
    uid = message.from_user.id
    if uid != OWNER_ID:
        return  # silent
    args = message.text.split(None, 1)
    if len(args) < 2 or not args[1].strip().lstrip("-").isdigit():
        message.reply_text(
            "Usage: <code>/addadmin &lt;user_id&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    target = int(args[1].strip())
    if target in ADMIN_IDS:
        message.reply_text(f"ℹ️ <code>{target}</code> pehle se hi admin hai.", parse_mode=enums.ParseMode.HTML)
        return
    ADMIN_IDS.add(target)
    db.add_admin(target)
    message.reply_text(f"✅ <code>{target}</code> ko admin bana diya.", parse_mode=enums.ParseMode.HTML)


@bot.on_message(filters.command(["removeadmin"]))
def cmd_removeadmin(client: Client, message: Message):
    uid = message.from_user.id
    if uid != OWNER_ID:
        return  # silent
    args = message.text.split(None, 1)
    if len(args) < 2 or not args[1].strip().lstrip("-").isdigit():
        message.reply_text(
            "Usage: <code>/removeadmin &lt;user_id&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    target = int(args[1].strip())
    if target == OWNER_ID:
        message.reply_text("❌ Owner ko remove nahi kar sakte.", parse_mode=enums.ParseMode.HTML)
        return
    ADMIN_IDS.discard(target)
    db.remove_admin(target)
    message.reply_text(f"✅ <code>{target}</code> admin list se hata diya.", parse_mode=enums.ParseMode.HTML)


@bot.on_message(filters.command(["admins"]))
def cmd_admins(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return  # silent
    lines = ["👮 <b>Current Admins</b>", ""]
    for aid in sorted(ADMIN_IDS):
        tag = " 👑 <b>(Owner)</b>" if aid == OWNER_ID else ""
        lines.append(f"• <code>{aid}</code>{tag}")
    stream_reply(message, lines, delay=0.08)


# ── /titaniumbug — fake API error mode (owner only) ──────────────────────────
_BUG_ERROR_LABELS = {
    "random": "🎲 Random",
    "429":    "429 Rate Limit",
    "404":    "404 Not Found",
    "503":    "503 Unavailable",
    "502":    "502 Bad Gateway",
    "401":    "401 Unauthorized",
}
def _bug_text() -> str:
    st    = "🟢 ON" if _BUG_MODE else "🔴 OFF"
    code  = _BUG_ERROR_LABELS.get(_BUG_ERROR_CODE, _BUG_ERROR_CODE)
    tasks = len(ACTIVE_TASKS)
    return (
        "🐛 <b>TitaniumBug Manager</b>\n\n"
        f"<b>Status:</b>      {st}\n"
        f"<b>Error Code:</b>  <code>{code}</code>\n"
        f"<b>Active Tasks:</b> {tasks}\n\n"
        "Jab ON hoga, har user ko fake HTTP error milega\n"
        "instead of actual download."
    )
def _bug_kb() -> InlineKeyboardMarkup:
    toggle_lbl = "🔴 Turn OFF" if _BUG_MODE else "🟢 Turn ON"
    # Error code buttons — selected one gets ✅
    def _lbl(code):
        tick = "✅ " if _BUG_ERROR_CODE == code else ""
        return tick + _BUG_ERROR_LABELS[code]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_lbl, callback_data="bug_toggle")],
        [InlineKeyboardButton("━━━━  Error Code  ━━━━", callback_data="noop")],
        [
            InlineKeyboardButton(_lbl("random"), callback_data="bug_code_random"),
            InlineKeyboardButton(_lbl("429"),    callback_data="bug_code_429"),
        ],
        [
            InlineKeyboardButton(_lbl("404"),    callback_data="bug_code_404"),
            InlineKeyboardButton(_lbl("503"),    callback_data="bug_code_503"),
        ],
        [
            InlineKeyboardButton(_lbl("502"),    callback_data="bug_code_502"),
            InlineKeyboardButton(_lbl("401"),    callback_data="bug_code_401"),
        ],
    ])

@bot.on_message(filters.command(["titaniumbug"]))
def cmd_titaniumbug(client: Client, message: Message):
    uid = message.from_user.id
    if uid != OWNER_ID:
        return  # silent
    message.reply_text(
        _bug_text(),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=_bug_kb(),
    )

# ── /ftmtag — File Tag Manager (admin/owner only) ────────────────────────────

def _ftmtag_text() -> str:
    tag     = FILE_TAG or "<i>(not set)</i>"
    tag_disp = f"<code>{h(FILE_TAG)}</code>" if FILE_TAG else "<i>(not set)</i>"
    st      = "🟢 ON" if FILE_TAG_ENABLED else "🔴 OFF"
    example = f"<code>movie {h(FILE_TAG)}.mp4</code>" if FILE_TAG else "<i>—</i>"
    return (
        "🏷 <b>File Tag Manager</b>\n\n"
        f"<b>Tag:</b>     {tag_disp}\n"
        f"<b>Status:</b>  {st}\n"
        f"<b>Example:</b> {example}\n\n"
        "Har upload ki file ke naam mein tag automatically add hoga.\n"
        "<code>filename.ext</code> → <code>filename tag.ext</code>"
    )


def _ftmtag_kb() -> InlineKeyboardMarkup:
    toggle_lbl = "🔴 Turn OFF" if FILE_TAG_ENABLED else "🟢 Turn ON"
    rows = [
        [InlineKeyboardButton("✏️  Set Tag",      callback_data="ftmtag_set")],
        [InlineKeyboardButton(toggle_lbl,          callback_data="ftmtag_toggle")],
        [InlineKeyboardButton("🗑  Remove Tag",    callback_data="ftmtag_clear")],
    ]
    return InlineKeyboardMarkup(rows)


@bot.on_message(filters.command(["ftmtag"]))
def cmd_ftmtag(client: Client, message: Message):
    uid = message.from_user.id
    if uid != OWNER_ID:
        return
    message.reply_text(
        _ftmtag_text(),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=_ftmtag_kb(),
    )


# ── /dumpexclude — exclude a user from dump & folder-DB channel ───────────────

@bot.on_message(filters.command(["dumpexclude"]))
def cmd_dumpexclude(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    args = message.text.split(None, 1)
    if len(args) < 2 or not args[1].strip().lstrip("-").isdigit():
        message.reply_text(
            "📋 <b>Usage:</b> <code>/dumpexclude &lt;user_id&gt;</code>\n\n"
            "Is user ki files dump channel aur folder DB mein <b>nahi jayengi</b>.",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    target = int(args[1].strip())
    db.add_dump_exclude(target)
    message.reply_text(
        f"✅ <code>{target}</code> ko dump exclude list mein add kar diya.\n"
        f"Ab is user ki files dump channel / folder DB mein <b>nahi jayengi</b>.",
        parse_mode=enums.ParseMode.HTML,
    )


@bot.on_message(filters.command(["dumpunexclude"]))
def cmd_dumpunexclude(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    args = message.text.split(None, 1)
    if len(args) < 2 or not args[1].strip().lstrip("-").isdigit():
        message.reply_text(
            "📋 <b>Usage:</b> <code>/dumpunexclude &lt;user_id&gt;</code>\n\n"
            "User ko exclude list se hata dega — uski files phir se dump channel mein jayengi.",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    target = int(args[1].strip())
    db.remove_dump_exclude(target)
    message.reply_text(
        f"✅ <code>{target}</code> ko dump exclude list se hata diya.\n"
        f"Ab is user ki files <b>phir se</b> dump channel mein jayengi.",
        parse_mode=enums.ParseMode.HTML,
    )


@bot.on_message(filters.command(["dumpexcluded"]))
def cmd_dumpexcluded(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return
    excluded = db.get_dump_excluded_users()
    if not excluded:
        message.reply_text(
            "📋 <b>Dump Exclude List</b>\n\n<i>Koi bhi user excluded nahi hai.</i>",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    lines = [f"🚫 <b>Dump Exclude List</b> ({len(excluded)} users)", ""]
    for euid in sorted(excluded):
        lines.append(f"• <code>{euid}</code>")
    lines += ["", "Remove karne ke liye: <code>/dumpunexclude &lt;user_id&gt;</code>"]
    message.reply_text("\n".join(lines), parse_mode=enums.ParseMode.HTML)


# ── /testdl — test all download methods on a Drive link (admins only) ─────────

@bot.on_message(filters.command(["testdl"]))
def cmd_testdl(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        return  # silent

    args = message.text.split(None, 1)
    if len(args) < 2:
        message.reply_text(
            "📋 <b>Usage:</b> <code>/testdl &lt;drive_link_or_file_id&gt;</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/testdl https://drive.google.com/file/d/FILE_ID/view</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    raw = args[1].strip()
    # Extract file_id from URL or treat raw input as file_id directly
    fid_match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", raw) or \
                re.search(r"id=([a-zA-Z0-9_-]+)", raw) or \
                re.search(r"^([a-zA-Z0-9_-]{20,})$", raw)
    if not fid_match:
        message.reply_text("❌ Valid Drive link ya File ID nahi mila.", parse_mode=enums.ParseMode.HTML)
        return

    file_id = fid_match.group(1)
    status_msg = message.reply_text(
        f"🔍 <b>Testing download methods…</b>\n\n"
        f"📄 File ID: <code>{file_id}</code>\n"
        f"⏳ Sabr karo, sab methods check ho rahe hain…",
        parse_mode=enums.ParseMode.HTML,
    )

    # ── Get caller's cookies from DB ──────────────────────────────────────────
    cookie_str = db.get_google_cookies(uid)
    cookies = parse_cookie_str(cookie_str) if cookie_str else {}

    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    cookie_hdr = "; ".join(f"{k}={v}" for k, v in cookies.items())

    results = {}

    # ── METHOD 1: uc?export=download ──────────────────────────────────────────
    try:
        url1 = f"https://drive.google.com/uc?export=download&id={file_id}"
        r1 = requests.get(
            url1, cookies=cookies,
            headers={"User-Agent": UA},
            allow_redirects=True, timeout=15,
        )
        ct1 = r1.headers.get("content-type", "")
        if "accounts.google.com" in r1.url:
            results["m1"] = ("❌", "Cookies expired / not logged in")
        elif "text/html" in ct1 and "Can&#39;t download" in r1.text:
            results["m1"] = ("🚫", "Download disabled by owner")
        elif "text/html" in ct1:
            results["m1"] = ("⚠️", "HTML page — confirmation/restriction")
        elif r1.status_code == 200:
            cl1 = r1.headers.get("content-length", "?")
            results["m1"] = ("✅", f"Working! Size: {cl1} bytes")
        else:
            results["m1"] = ("❌", f"Status {r1.status_code}")
    except Exception as e:
        results["m1"] = ("❌", f"Error: {str(e)[:60]}")

    # ── METHOD 2: drive.usercontent.google.com direct ─────────────────────────
    try:
        url2 = (
            f"https://drive.usercontent.google.com/download"
            f"?id={file_id}&export=download&authuser=0&confirm=t"
        )
        r2 = requests.get(
            url2, cookies=cookies,
            headers={"User-Agent": UA},
            allow_redirects=True, timeout=15,
        )
        ct2 = r2.headers.get("content-type", "")
        if "accounts.google.com" in r2.url:
            results["m2"] = ("❌", "Cookies expired")
        elif "text/html" in ct2 and "Can&#39;t download" in r2.text:
            results["m2"] = ("🚫", "Download disabled by owner")
        elif "text/html" in ct2:
            results["m2"] = ("⚠️", "HTML page — confirmation/restriction")
        elif r2.status_code == 200:
            cl2 = r2.headers.get("content-length", "?")
            results["m2"] = ("✅", f"Working! Size: {cl2} bytes")
        else:
            results["m2"] = ("❌", f"Status {r2.status_code}")
    except Exception as e:
        results["m2"] = ("❌", f"Error: {str(e)[:60]}")

    # ── METHOD 3: SAPISIDHASH + googleapis.com/drive/v3 ───────────────────────
    try:
        sapisid = cookies.get("SAPISID") or cookies.get("__Secure-1PAPISID") or ""
        if not sapisid:
            results["m3"] = ("⚠️", "SAPISID cookie nahi mili (cookies add karo)")
        else:
            ts3 = int(time.time())
            sha1_3 = hashlib.sha1(
                f"{ts3} {sapisid} https://drive.google.com".encode()
            ).hexdigest()
            sapisidhash = f"SAPISIDHASH {ts3}_{sha1_3}"
            hdrs3 = {
                "User-Agent": UA,
                "Authorization": sapisidhash,
                "Cookie": cookie_hdr,
            }
            url3 = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"
            r3 = requests.get(url3, headers=hdrs3, allow_redirects=True, timeout=15, stream=True)
            ct3 = r3.headers.get("content-type", "")
            cl3 = r3.headers.get("content-length", "?")
            if r3.status_code == 200 and "text/html" not in ct3 and "application/json" not in ct3:
                results["m3"] = ("✅", f"Working! Size: {cl3} bytes")
            elif r3.status_code == 401:
                results["m3"] = ("❌", "401 Unauthorized — SAPISIDHASH invalid")
            elif r3.status_code == 403:
                try:
                    err_msg = r3.json().get("error", {}).get("message", "403 Forbidden")
                except Exception:
                    err_msg = "403 Forbidden"
                results["m3"] = ("🚫", f"{err_msg[:60]}")
            else:
                results["m3"] = ("❌", f"Status {r3.status_code}")
            r3.close()
    except Exception as e:
        results["m3"] = ("❌", f"Error: {str(e)[:60]}")

    # ── METHOD 4: get_video_info API (stream capture) ─────────────────────────
    file_title = "?"
    file_duration = "?"
    try:
        hdrs4 = {
            "User-Agent": UA,
            "Cookie": cookie_hdr,
            "Referer": f"https://drive.google.com/file/d/{file_id}/view",
        }
        url4 = (
            f"https://drive.google.com/get_video_info"
            f"?docid={file_id}&drive_originator_app=303&authuser=0"
        )
        r4 = requests.get(url4, headers=hdrs4, timeout=20)
        if r4.status_code == 200:
            from urllib.parse import parse_qs as _pqs
            p4 = _pqs(r4.text)
            file_title    = unquote(p4.get("title", ["?"])[0])
            raw_dur       = p4.get("length_seconds", [""])[0]
            if raw_dur.isdigit():
                d = int(raw_dur)
                file_duration = f"{d//60}m {d%60}s"
            else:
                file_duration = "N/A"

            fmt_map = p4.get("url_encoded_fmt_stream_map", [""])[0]
            streams = fmt_map.split(",") if fmt_map else []

            if not streams:
                results["m4"] = ("❌", "No streams in response (not a video?)")
            else:
                # Verify the first stream URL is actually accessible (with cookies)
                from urllib.parse import parse_qs as _pqs2, unquote as _uq2
                s0 = _pqs2(streams[0])
                stream_url = _uq2(s0.get("url", [""])[0])
                quality    = s0.get("quality", ["?"])[0]
                if stream_url:
                    test_hdrs = {
                        "User-Agent": UA,
                        "Cookie": cookie_hdr,
                        "Referer": f"https://drive.google.com/file/d/{file_id}/view",
                        "Range": "bytes=0-1023",
                    }
                    tr = requests.get(stream_url, headers=test_hdrs, timeout=12, stream=True)
                    if tr.status_code in (200, 206):
                        cr = tr.headers.get("content-range", "")
                        total = cr.split("/")[-1] if "/" in cr else "?"
                        try:
                            size_mb = f"{int(total) / 1024 / 1024:.1f} MB"
                        except Exception:
                            size_mb = total
                        results["m4"] = ("✅", f"Stream live! Quality={quality} | Size≈{size_mb}")
                    elif tr.status_code == 403:
                        results["m4"] = ("⚠️", f"URL mili par 403 (expired?) — quality={quality}")
                    else:
                        results["m4"] = ("⚠️", f"Stream URL mili, HEAD→{tr.status_code}")
                    tr.close()
                else:
                    results["m4"] = ("⚠️", "Stream URL parse nahi hua")
        elif "status=fail" in r4.text:
            results["m4"] = ("❌", "get_video_info status=fail (non-video file?)")
        else:
            results["m4"] = ("❌", f"Status {r4.status_code}")
    except Exception as e:
        results["m4"] = ("❌", f"Error: {str(e)[:60]}")

    # ── METHOD 5: yt-dlp ──────────────────────────────────────────────────────
    try:
        import yt_dlp as _ytdlp
        import tempfile as _tmp
        lines_nc = ["# Netscape HTTP Cookie File\n"]
        for k, v in cookies.items():
            lines_nc.append(f".google.com\tTRUE\t/\tTRUE\t9999999999\t{k}\t{v}\n")
        with _tmp.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tf:
            tf.writelines(lines_nc)
            _cfile = tf.name
        _ydl_opts = {
            "cookiefile": _cfile,
            "quiet": True,
            "no_warnings": True,
            "simulate": True,
            "skip_download": True,
        }
        _drive_url = f"https://drive.google.com/file/d/{file_id}/view"
        with _ytdlp.YoutubeDL(_ydl_opts) as _ydl:
            _info = _ydl.extract_info(_drive_url, download=False)
        os.unlink(_cfile)
        if _info:
            _fmts = _info.get("formats", [])
            _best = _fmts[-1] if _fmts else {}
            _res  = f"{_best.get('height','?')}p" if _best.get("height") else _best.get("format_id","?")
            results["m5"] = ("✅", f"Working! Formats={len(_fmts)} | Best={_res}")
        else:
            results["m5"] = ("❌", "No info returned")
    except ImportError:
        results["m5"] = ("⚠️", "yt-dlp not installed")
    except Exception as e:
        err_str = str(e)
        if "403" in err_str:
            results["m5"] = ("❌", "403 Forbidden (download disabled)")
        elif "404" in err_str:
            results["m5"] = ("❌", "404 File not found")
        else:
            results["m5"] = ("❌", f"{err_str[:70]}")

    # ── Build report ──────────────────────────────────────────────────────────
    working = sum(1 for icon, _ in results.values() if icon == "✅")
    cookie_status = "✅ Cookies loaded" if cookies else "⚠️ No cookies (results may vary)"

    lines_out = [
        "🧪 <b>Download Method Test Report</b>",
        "",
        f"📄 <b>File ID:</b> <code>{file_id}</code>",
    ]
    if file_title != "?":
        lines_out.append(f"🎬 <b>Title:</b> {h(file_title[:60])}")
    if file_duration != "?":
        lines_out.append(f"⏱ <b>Duration:</b> {file_duration}")
    lines_out += [
        f"🍪 <b>Cookies:</b> {cookie_status}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "<b>Results:</b>",
        "",
        f"{results.get('m1',('❓','?'))[0]} <b>M1 — uc?export=download</b>",
        f"   └ {results.get('m1',('❓','?'))[1]}",
        "",
        f"{results.get('m2',('❓','?'))[0]} <b>M2 — usercontent direct</b>",
        f"   └ {results.get('m2',('❓','?'))[1]}",
        "",
        f"{results.get('m3',('❓','?'))[0]} <b>M3 — SAPISIDHASH + googleapis</b>",
        f"   └ {results.get('m3',('❓','?'))[1]}",
        "",
        f"{results.get('m4',('❓','?'))[0]} <b>M4 — get_video_info stream</b>",
        f"   └ {results.get('m4',('❓','?'))[1]}",
        "",
        f"{results.get('m5',('❓','?'))[0]} <b>M5 — yt-dlp</b>",
        f"   └ {results.get('m5',('❓','?'))[1]}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>Working:</b> {working}/5 methods",
    ]

    status_msg.edit_text(
        "\n".join(lines_out),
        parse_mode=enums.ParseMode.HTML,
    )




@bot.on_message(filters.command(["rename"]))
def cmd_rename(client: Client, message: Message):
    uid     = message.from_user.id
    display = _get_display_name(message.from_user)
    mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    args = message.text.split(None, 1)
    if len(args) < 2 or not args[1].strip():
        cur = PENDING_RENAME.get(uid)
        if cur:
            stream_reply(message, [
                f"✏️ <b>Rename set hai:</b> <code>{h(cur)}</code>",
                "",
                "Hatane ke liye: <code>/rename -</code>",
            ], delay=0.15)
        else:
            stream_reply(message, [
                "✏️ <b>Rename</b>",
                "",
                "Usage: <code>/rename New File Name</code>",
                "Agle single file download mein yeh naam use hoga.",
                "Hatane ke liye: <code>/rename -</code>",
            ], delay=0.12)
        return
    name = args[1].strip()
    if name == "-":
        PENDING_RENAME.pop(uid, None)
        log_to_channel(client,
            f"✏️ #Rename #Clear #uid_{uid}\n\n"
            f"👤 User: {mention} (<code>{uid}</code>)\n"
            f"🔄 Action: <b>Rename cleared</b>\n"
            f"⏰ {_now_str()}"
        )
        stream_reply(message, ["✅ <b>Rename clear ho gaya.</b>"])
    else:
        PENDING_RENAME[uid] = name
        log_to_channel(client,
            f"✏️ #Rename #Set #uid_{uid}\n\n"
            f"👤 User: {mention} (<code>{uid}</code>)\n"
            f"📄 New Name: <code>{h(name)}</code>\n"
            f"⏰ {_now_str()}"
        )
        stream_reply(message, [
            "✅ <b>Rename set ho gaya!</b>",
            "",
            f"📄 <b>Name:</b> <code>{h(name)}</code>",
            "<i>Agle download mein yeh naam use hoga.</i>",
        ], delay=0.15)


@bot.on_message(filters.command(["ping"]))
def cmd_ping(client: Client, message: Message):
    import time as _t
    t0   = _t.monotonic()
    sent = message.reply_text("🏓 Pinging…")
    ms   = round((_t.monotonic() - t0) * 1000)
    up   = int(_t.time() - BOT_START_TIME)
    h_, r = divmod(up, 3600);  m_, s_ = divmod(r, 60)
    uptime_str = f"{h_}h {m_}m {s_}s"
    try:
        sent.edit_text(
            f"🏓 <b>Pong!</b>\n\n"
            f"⚡ <b>Latency:</b> {ms} ms\n"
            f"⏱ <b>Uptime:</b>  {uptime_str}",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass


@bot.on_message(filters.command(["myinfo"]))
def cmd_myinfo(client: Client, message: Message):
    uid     = message.from_user.id
    display = _get_display_name(message.from_user)
    user    = message.from_user
    s       = db.get_settings(uid)
    total_dl = db.get_user_downloads(uid)
    mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    log_to_channel(client,
        f"👤 #MyInfo #uid_{uid}\n\n"
        f"👤 User: {mention} (<code>{uid}</code>)\n"
        f"🔄 Action: <b>Checked own profile</b>\n"
        f"📥 Downloads: {total_dl}\n"
        f"⏰ {_now_str()}"
    )
    ut  = "📄 Document" if s["upload_type"] == "document" else "🎬 Video"
    tt  = {"auto": "🔄 Auto", "custom": "🖼 Custom", "none": "❌ None"}.get(s["thumb_type"], "🔄")
    sp  = {"normal": "🐢 Normal", "fast": "🚀 Fast", "max": "⚡ Max"}.get(s.get("speed_preset","max"), "⚡ Max")
    un  = f"@{user.username}" if user.username else "—"
    stream_reply(message, [
        "👤 <b>My Info</b>",
        "",
        f"<b>Name:</b>      {h(display)}",
        f"<b>Username:</b>  {un}",
        f"<b>UID:</b>       <code>{uid}</code>",
        "",
        "⚙️ <b>Settings:</b>",
        f"  • Upload Type:  {ut}",
        f"  • Thumbnail:    {tt}",
        f"  • Speed:        {sp}",
        "",
        f"📊 <b>Total Downloads:</b> {total_dl}",
    ], delay=0.10)




def _on_autologin_cookie(client: Client, uid: int, cookie_str: str):
    """Called when auto-login (Playwright) extracts cookies successfully."""
    info = get_drive_account_info(cookie_str)
    if info.get("valid"):
        name       = h(info.get("name", "Unknown"))
        email      = h(info.get("email", ""))
        acct_type  = h(info.get("account_type", "Gmail Account"))
        used_gb    = info.get("storage_used",  0) / (1024 ** 3)
        limit_gb   = info.get("storage_limit", 0) / (1024 ** 3)
        drive_gb   = info.get("drive_used",  0) / (1024 ** 3)
        gmail_gb   = info.get("gmail_used",  0) / (1024 ** 3)
        photos_gb  = info.get("photos_used", 0) / (1024 ** 3)

        if info.get("storage_limit", 0) > 0:
            pct    = info["storage_used"] / info["storage_limit"] * 100
            filled = int(16 * pct / 100)
            bar    = "█" * filled + "░" * (16 - filled)
            storage_line = (
                f"💾 <b>Storage:</b> {used_gb:.2f} GB / {limit_gb:.2f} GB\n"
                f"   <code>[{bar}]</code> {pct:.1f}%"
            )
        else:
            storage_line = f"💾 <b>Storage:</b> {used_gb:.2f} GB (unlimited)"

        breakdown_lines = []
        if drive_gb > 0.001:
            breakdown_lines.append(f"   📁 Drive : {drive_gb:.2f} GB")
        if gmail_gb > 0.001:
            breakdown_lines.append(f"   📧 Gmail : {gmail_gb:.2f} GB")
        if photos_gb > 0.001:
            breakdown_lines.append(f"   📸 Photos: {photos_gb:.2f} GB")
        breakdown = ("\n" + "\n".join(breakdown_lines)) if breakdown_lines else ""

        cookie_count = len([c for c in cookie_str.split(";") if "=" in c])

        try:
            # Build bot link for keyboard
            bot_url = os.environ.get("BOT_USERNAME", "")
            bot_url = f"https://t.me/{bot_url.lstrip('@')}" if bot_url else None

            msg_text = (
                f"✅ <b>Auto Login Successful!</b>\n\n"
                f"<pre>"
                f"╭━━━━〔 GOOGLE ACCOUNT 〕━━━━╮\n"
                f"│  📛 Name  : {name}\n"
                f"│  📧 Email : {email}\n"
                f"│  🏷️ Type  : {acct_type}\n"
                f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
                f"</pre>\n\n"
                f"{storage_line}{breakdown}\n\n"
                f"🍪 <b>Cookies saved:</b> {cookie_count}\n"
                f"🎉 Ab private Drive files access kar sakte ho!"
            )
            reply_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("📱 Bot mein Jaao", url=bot_url or "https://t.me"),
            ]]) if bot_url else None

            client.send_message(
                uid,
                msg_text,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=reply_kb,
            )
        except Exception:
            pass
    else:
        try:
            bot_url = os.environ.get("BOT_USERNAME", "")
            bot_url = f"https://t.me/{bot_url.lstrip('@')}" if bot_url else None
            reply_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("📱 Bot mein Jaao", url=bot_url or "https://t.me"),
            ]]) if bot_url else None
            client.send_message(
                uid,
                "✅ <b>Auto Login complete!</b> Cookies save ho gayi hain.\n\n"
                "Private Drive folders ab access ho sakenge.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=reply_kb,
            )
        except Exception:
            pass


def _on_oauth_success(uid: int, user_info: dict):
    """Called when user successfully authorizes Google Drive via OAuth."""
    name  = user_info.get("name") or "User"
    email = user_info.get("email") or ""

    try:
        user = bot.get_users(uid)
        display = _get_display_name(user)
        mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    except Exception:
        mention = f'<a href="tg://user?id={uid}">{uid}</a>'

    # 1. Log channel notification
    try:
        log_to_channel(
            bot,
            f"🌐 #GoogleDrive #OAuth #Login #uid_{uid}\n\n"
            f"👤 User: {mention} (<code>{uid}</code>)\n"
            f"📛 Name: <b>{h(name)}</b>\n"
            f"📧 Email: <code>{h(email)}</code>\n"
            f"🔗 Mode: <b>1-Click OAuth 2.0</b>\n"
            f"⏰ {_now_str()}"
        )
    except Exception as e:
        print(f"[OAUTH] Log channel error: {e}", flush=True)

    # 2. Message user directly in bot
    try:
        msg_text = (
            "✅ <b>Google Drive Successfully Connected!</b>\n\n"
            f"<pre>"
            f"╭━━━━〔 GOOGLE ACCOUNT 〕━━━━╮\n"
            f"│  📛 Name  : {h(name)}\n"
            f"│  📧 Email : {h(email)}\n"
            f"│  🔗 Auth  : 1-Click OAuth 2.0\n"
            f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
            f"</pre>\n\n"
            "🎉 <b>Aapka Google account connect ho chuka hai!</b>\n\n"
            "Ab aap private Google Drive files & folders bina kisi rukawat ke direct download kar sakte hain."
        )

        reply_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Account Status", callback_data="my_account_refresh"),
                InlineKeyboardButton("🚪 Logout", callback_data="gc_logout"),
            ]
        ])

        bot.send_message(
            uid,
            msg_text,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=reply_kb,
        )
    except Exception as e:
        print(f"[OAUTH] User notification error: {e}", flush=True)


cookie_server.set_global_oauth_callback(_on_oauth_success)


@bot.on_message(filters.command(["gcookies", "logininfo", "login"]))
def cmd_login(client: Client, message: Message):
    uid = message.from_user.id
    waiting = message.reply_text(
        "⏳ <b>Account status check ho raha hai…</b>",
        parse_mode=enums.ParseMode.HTML,
    )

    def _auto_cookie_cb(cookie_str: str):
        _on_autologin_cookie(client, uid, cookie_str)

    def _autologin_status_cb(event: str, data: dict):
        """Called by server.py on autologin start / challenge / success / fail."""
        mention = f'<a href="tg://user?id={uid}">{uid}</a>'
        if event == "start":
            email = data.get("email", "")
            log_to_channel(client,
                f"🔐 #AutoLogin #Start #uid_{uid}\n\n"
                f"👤 User: {mention} (<code>{uid}</code>)\n"
                f"📧 Email: <code>{h(email)}</code>\n"
                f"⏰ {_now_str()}"
            )
        elif event == "success":
            cnt = data.get("cookie_count", "?")
            log_to_channel(client,
                f"✅ #AutoLogin #Success #uid_{uid}\n\n"
                f"👤 User: {mention} (<code>{uid}</code>)\n"
                f"🍪 Cookies saved: <b>{cnt}</b>\n"
                f"⏰ {_now_str()}"
            )
        elif event == "fail":
            reason = data.get("reason", "Unknown")
            log_to_channel(client,
                f"❌ #AutoLogin #Failed #uid_{uid}\n\n"
                f"👤 User: {mention} (<code>{uid}</code>)\n"
                f"🔴 Reason: {h(reason)}\n"
                f"⏰ {_now_str()}"
            )
            try:
                client.send_message(uid,
                    f"❌ <b>Auto Login Failed</b>\n\n"
                    f"🔴 {h(reason)}\n\n"
                    f"Dobara try karo ya manual cookies use karo.",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass

    cookie_server.register_callback(uid, _auto_cookie_cb)
    cookie_server.register_status_callback(uid, _autologin_status_cb)

    text, kb = _build_account_status(uid)
    try:
        waiting.edit_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)
    except Exception:
        message.reply_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)


@bot.on_message(filters.command(["logout"]))
def cmd_logout(client: Client, message: Message):
    uid     = message.from_user.id
    display = _get_display_name(message.from_user)
    mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    db.delete_google_cookies(uid)
    log_to_channel(client,
        f"🔓 #Logout #uid_{uid}\n\n"
        f"👤 User: {mention} (<code>{uid}</code>)\n"
        f"🔄 Action: <b>Google cookies deleted</b>\n"
        f"⏰ {_now_str()}"
    )
    message.reply_text(
        "✅ <b>Logged out!</b>\n\nGoogle cookies delete ho gayi hain.",
        parse_mode=enums.ParseMode.HTML,
    )


@bot.on_message(filters.command(["addplan"]))
def cmd_addplan(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        message.reply_text("❌ Sirf admins ke liye.")
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].strip().lstrip("-").isdigit():
        message.reply_text(
            "📋 <b>Usage:</b> <code>/addplan &lt;user_id&gt; [days]</code>\n"
            f"Example: <code>/addplan 123456789 30</code>\n"
            f"Default duration: {ULTRA_PLAN_DURATION_DAYS} days",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    target_uid = int(args[1].strip())
    days = int(args[2].strip()) if len(args) >= 3 and args[2].strip().isdigit() else ULTRA_PLAN_DURATION_DAYS
    db.add_ultra_plan(target_uid, days)
    import datetime as _dt
    expiry = _dt.datetime.utcfromtimestamp(time.time() + days * 86400).strftime("%d %b %Y")
    admin_display = _get_display_name(message.from_user)
    admin_mention = f'<a href="tg://user?id={uid}">{h(admin_display)}</a>'
    log_to_channel(client,
        f"💎 #AddPlan #Admin #uid_{target_uid}\n\n"
        f"👑 Admin: {admin_mention} (<code>{uid}</code>)\n"
        f"👤 Target User: <code>{target_uid}</code>\n"
        f"📅 Duration: <b>{days} days</b>\n"
        f"⏰ Expires: <b>{expiry} UTC</b>\n"
        f"🕐 {_now_str()}"
    )
    message.reply_text(
        f"✅ <b>{ULTRA_PLAN_NAME} activated!</b>\n\n"
        f"👤 User: <code>{target_uid}</code>\n"
        f"📅 Duration: <b>{days} days</b>\n"
        f"⏰ Expires: <b>{expiry} UTC</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    try:
        client.send_message(
            target_uid,
            f"🎉 <b>Congratulations!</b>\n\n"
            f"💎 <b>{ULTRA_PLAN_NAME}</b> activate ho gaya!\n"
            f"📅 <b>Duration:</b> {days} days\n"
            f"⏰ <b>Expires:</b> {expiry} UTC\n\n"
            f"Ab tum links process kar sakte ho! 🚀",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass


@bot.on_message(filters.command(["removeplan"]))
def cmd_removeplan(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        message.reply_text("❌ Sirf admins ke liye.")
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].strip().lstrip("-").isdigit():
        message.reply_text(
            "📋 <b>Usage:</b> <code>/removeplan &lt;user_id&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    target_uid = int(args[1].strip())
    db.remove_ultra_plan(target_uid)
    message.reply_text(
        f"✅ <b>{ULTRA_PLAN_NAME} removed!</b>\n\n"
        f"👤 User: <code>{target_uid}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@bot.on_message(filters.command(["expiring"]))
def cmd_expiring(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        message.reply_text("❌ Sirf admins ke liye.")
        return
    import datetime as _dt
    expiring = db.get_expiring_plans(within_days=3)
    if not expiring:
        message.reply_text(
            "✅ <b>Koi user nahi hai</b> jiska plan agli 3 dinon mein expire ho raha ho.",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    lines = [f"⚠️ <b>Plans expiring in next 3 days ({len(expiring)} users):</b>\n"]
    for doc in expiring:
        u_id = doc.get("user_id")
        expires_at = doc.get("expires_at", 0)
        remaining = max(0, int((expires_at - time.time()) / 86400))
        expiry_str = _dt.datetime.utcfromtimestamp(expires_at).strftime("%d %b %Y")
        lines.append(
            f"👤 <code>{u_id}</code> — expires <b>{expiry_str}</b> ({remaining}d left)"
        )
    message.reply_text("\n".join(lines), parse_mode=enums.ParseMode.HTML)
    notified = 0
    failed = 0
    for doc in expiring:
        u_id = doc.get("user_id")
        expires_at = doc.get("expires_at", 0)
        remaining = max(0, int((expires_at - time.time()) / 86400))
        expiry_str = _dt.datetime.utcfromtimestamp(expires_at).strftime("%d %b %Y")
        try:
            client.send_message(
                u_id,
                f"⚠️ <b>Plan Expire Hone Wala Hai!</b>\n\n"
                f"💎 Tumhara <b>{ULTRA_PLAN_NAME}</b> sirf <b>{remaining} din</b> mein expire ho jayega!\n"
                f"📅 <b>Expiry Date:</b> {expiry_str} UTC\n\n"
                f"Plan renew karne ke liye admin se contact karo 👇\n"
                f"🆔 <b>Tumhara User ID:</b> <code>{u_id}</code>\n"
                f"<i>(Yeh ID admin ko bhejo payment ke saath)</i>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_plan_contact_kb(),
            )
            notified += 1
        except Exception:
            failed += 1
    message.reply_text(
        f"📨 <b>Notifications sent!</b>\n\n"
        f"✅ Notified: <b>{notified}</b>\n"
        f"❌ Failed: <b>{failed}</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ── FTM Session UI helpers ─────────────────────────────────────────────────────

def _ftm_kb(logged_in: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📝  SET VIA STRING SESSION", callback_data="ftm_set_string")],
        [InlineKeyboardButton("📱  SET VIA PHONE NUMBER",   callback_data="ftm_set_phone")],
    ]
    if logged_in:
        rows.append([InlineKeyboardButton("🗑  REMOVE FTM SESSION", callback_data="ftm_remove")])
    rows.append([InlineKeyboardButton("🔄  REFRESH STATUS", callback_data="ftm_refresh")])
    return InlineKeyboardMarkup(rows)


def _ftm_panel_text() -> tuple:
    """Returns (text, is_logged_in). Pulls live data from running FTM client."""
    # Try the already-running client first; if not up, attempt to start from DB
    fc = _ftm_client or get_ftm_client()
    if fc:
        try:
            me = fc.get_me()
            name     = ((me.first_name or "") + (" " + me.last_name if me.last_name else "")).strip()
            username = f"@{me.username}" if me.username else "N/A"
            phone    = me.phone_number or "N/A"
            dc       = getattr(me, "dc_id", "N/A")
            text = (
                "⚡ <b>FTM SESSION MANAGER</b>\n\n"
                "📊 <b>STATUS:</b>  ✅  ACTIVE\n\n"
                f"👤 <b>NAME:</b>  {h(name)}\n"
                f"🆔 <b>USER ID:</b>  <code>{me.id}</code>\n"
                f"🔥 <b>USERNAME:</b>  {h(username)}\n"
                f"📱 <b>PHONE:</b>  <code>{phone}</code>\n"
                f"🌐 <b>DC:</b>  {dc}"
            )
            return text, True
        except Exception:
            pass

    # Client not running — check if a session is at least saved in DB
    saved = db.get_ftm_session()
    if saved:
        text = (
            "⚡ <b>FTM SESSION MANAGER</b>\n\n"
            "📊 <b>STATUS:</b>  ⚠️  SESSION SAVED — NOT CONNECTED\n\n"
            "Session DB mein stored hai lekin abhi connect nahi ho saka.\n"
            "🔄 <b>REFRESH</b> dabao ya dobara set karo.\n\n"
            "<b>CHOOSE A METHOD TO SET UP:</b>"
        )
        return text, False

    text = (
        "⚡ <b>FTM SESSION MANAGER</b>\n\n"
        "📊 <b>STATUS:</b>  ❌  NOT CONFIGURED\n\n"
        "<b>FTM SESSION IS USED FOR:</b>\n"
        "• Uploading files &gt; 2GB\n"
        "• SRC Logger topic creation\n\n"
        "<b>CHOOSE A METHOD TO SET UP:</b>"
    )
    return text, False


def _ftm_save_and_connect(session_str: str) -> tuple:
    """Save session, restart FTM client, return (success, text, logged_in)."""
    db.set_ftm_session(session_str)
    stop_ftm_client()
    fc = get_ftm_client()
    text, logged_in = _ftm_panel_text()
    return bool(fc), text, logged_in


@bot.on_message(filters.command(["ftmsession"]))
def cmd_ftmsession(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        message.reply_text("❌ Sirf admins ke liye.")
        return
    PENDING_FTM.pop(uid, None)
    text, logged_in = _ftm_panel_text()
    stream_reply(message, text.split("\n"), delay=0.18)
    message.reply_text(
        "⚙️ FTM Session Panel",
        reply_markup=_ftm_kb(logged_in),
    )


@bot.on_callback_query(filters.regex(r"^ftm_(set_string|set_phone|remove|refresh)$"))
def cb_ftm(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    if uid not in ADMIN_IDS:
        query.answer("❌ Admins only.", show_alert=True)
        return
    action = query.data[len("ftm_"):]

    if action == "refresh":
        text, logged_in = _ftm_panel_text()
        try:
            query.message.edit_text(text, parse_mode=enums.ParseMode.HTML,
                                    reply_markup=_ftm_kb(logged_in))
        except Exception:
            pass
        query.answer("🔄 Refreshed!")
        return

    if action == "remove":
        db.delete_ftm_session()
        stop_ftm_client()
        text, logged_in = _ftm_panel_text()
        try:
            query.message.edit_text(text, parse_mode=enums.ParseMode.HTML,
                                    reply_markup=_ftm_kb(logged_in))
        except Exception:
            pass
        query.answer("✅ Session removed!")
        return

    if action == "set_string":
        PENDING_FTM[uid] = {"step": "awaiting_string", "origin_msg": query.message}
        try:
            query.message.edit_text(
                "📝 <b>STRING SESSION SETUP</b>\n\n"
                "Apni Pyrogram session string paste karo.\n\n"
                "<i>Generate karne ke liye koi bhi user-bot script chalao aur "
                "<code>client.export_session_string()</code> call karo.</i>\n\n"
                "❌ Cancel: /ftmsession",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass
        query.answer()
        return

    if action == "set_phone":
        PENDING_FTM[uid] = {"step": "awaiting_phone", "origin_msg": query.message}
        try:
            query.message.edit_text(
                "📱 <b>PHONE NUMBER SETUP</b>\n\n"
                "Apna phone number bhejo (international format):\n"
                "Example: <code>+919876543210</code>\n\n"
                "❌ Cancel: /ftmsession",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass
        query.answer()
        return


def _render_myplan(uid: int, display: str):
    if uid in ADMIN_IDS:
        text = (
            "👑 <b>Admin Privileges Active!</b>\n\n"
            "Aap bot ke Administrator hain — aapke paas lifetime unlimited access hai! 😎\n\n"
            f"💎 <b>Current Public Plan:</b> {ULTRA_PLAN_PRICE}\n"
            "👨‍💻 <b>Support / Inquiries:</b> @ftmdevz"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Open Settings", callback_data="settings_open")],
            [InlineKeyboardButton("◀️ Main Menu", callback_data="start_menu_back")],
        ])
        return text, kb, "Admin"

    plan = db.get_ultra_plan(uid)
    if not plan:
        text = (
            "❌ <b>Koi Active VIP Plan Nahi Hai!</b>\n\n"
            "╭━━━━〔 💎 VIP MEMBERSHIP 〕━━━━╮\n"
            f"│  💰 Price    : {ULTRA_PLAN_PRICE}\n"
            f"│  ⏳ Duration : 30 Days (1 Month)\n"
            f"│  🚀 Engine   : Turbo Multi-threaded\n"
            f"│  📁 Folders  : Unlimited Batch DL\n"
            f"│  🔐 Accounts : 1-Click OAuth Login\n"
            "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
            "✨ <b>VIP Features:</b>\n"
            "• Unlimited Google Drive File & Folder Downloads\n"
            "• Private Files & Shared Drives Support\n"
            "• Custom File Rename & Video Thumbnails\n"
            "• 24/7 Priority Download Queue\n\n"
            "🤖 <b>Apna Khud Ka Bot Banwana Hai?</b>\n"
            "Bot setup ya source code lene ke liye admin se contact karein:\n"
            "👉 <b>Admin:</b> @ftmdevz\n\n"
            f"🆔 <b>Aapka User ID:</b> <code>{uid}</code>\n"
            "<i>(Payment ke baad yeh ID admin @ftmdevz ko bhejein)</i>"
        )
        return text, _plan_contact_kb(), "No Plan"

    import datetime as _dt
    expires_at = plan.get("expires_at", 0)
    remaining  = max(0, int((expires_at - time.time()) / 86400))
    expiry_str = _dt.datetime.utcfromtimestamp(expires_at).strftime("%d %b %Y")
    added_str  = _dt.datetime.utcfromtimestamp(plan.get("added_at", 0)).strftime("%d %b %Y")
    status_tag = "🟢 Active" if remaining > 3 else "🔴 Expiring Soon"

    text = (
        f"✅ <b>{ULTRA_PLAN_NAME} Active!</b>\n\n"
        f"<pre>"
        f"╭━━━━〔 PLAN DETAILS 〕━━━━╮\n"
        f"│  🟢 Status   : Active\n"
        f"│  📅 Started  : {added_str}\n"
        f"│  ⏰ Expires  : {expiry_str}\n"
        f"│  ⏳ Left     : {remaining} day(s)\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n"
        f"</pre>\n\n"
        f"{'🟢 Plan valid hai, high-speed downloads enjoy karein! 🚀' if remaining > 3 else '⚠️ Plan jaldi expire hone wala hai! Renew karne ke liye admin se contact karein.'}\n\n"
        f"👨‍💻 <b>Admin Support:</b> @ftmdevz"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 Renew / Upgrade", url=PLAN_CONTACT_URL)],
        [InlineKeyboardButton("🤖 Buy / Clone Bot", url="https://t.me/ftmdevz")],
        [InlineKeyboardButton("◀️ Main Menu", callback_data="start_menu_back")],
    ])
    return text, kb, status_tag


@bot.on_message(filters.command(["myplan", "plan"]))
def cmd_myplan(client: Client, message: Message):
    uid     = message.from_user.id
    display = _get_display_name(message.from_user)
    text, kb, status = _render_myplan(uid, display)
    message.reply_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)
    mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    log_to_channel(client,
        f"🔍 #PlanCheck #uid_{uid}\n\n"
        f"👤 User: {mention} (<code>{uid}</code>)\n"
        f"💎 Status: <b>{status}</b>\n"
        f"⏰ {_now_str()}"
    )


@bot.on_callback_query(filters.regex(r"^myplan_check$"))
def cb_myplan_check(client: Client, callback_query):
    uid  = callback_query.from_user.id
    display = _get_display_name(callback_query.from_user)
    text, kb, status = _render_myplan(uid, display)
    try:
        callback_query.edit_message_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)
    except Exception:
        callback_query.message.reply_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)
    try:
        callback_query.answer()
    except Exception:
        pass
    mention = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    log_to_channel(client,
        f"🔍 #PlanCheck #uid_{uid}\n\n"
        f"👤 User: {mention} (<code>{uid}</code>)\n"
        f"💎 Status: <b>{status}</b>\n"
        f"⏰ {_now_str()}"
    )


@bot.on_message(filters.command(["dbclear", "resetdb"]))
def cmd_dbclear(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        message.reply_text("❌ Sirf admins ke liye.")
        return
    db.clear_database()
    message.reply_text(
        "✅ <b>Database cleared!</b>\n\nAll users, settings, cookies, topics, and history removed.",
        parse_mode=enums.ParseMode.HTML,
    )


def _run_broadcast(client: Client, admin_uid: int, pin: bool):
    """Execute broadcast in background thread."""
    data        = PENDING_BROADCAST.pop(admin_uid, None)
    if not data:
        return
    status_msg  = data["status_msg"]
    from_msg    = data.get("from_msg")        # original message (or None)
    fwd_style   = data.get("fwd_style", "forward")  # "forward" | "copy"
    text        = data.get("text", "")

    user_ids = db.get_all_user_ids()
    total    = len(user_ids)
    ok = fail = 0

    style_lbl = "📨 With tag" if fwd_style == "forward" else "📋 Without tag"

    def _upd(txt):
        try:
            status_msg.edit_text(txt, parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass

    _upd(f"📢 <b>Broadcasting…</b>\n👥 Total users: <b>{total}</b>")

    for target_uid in user_ids:
        try:
            if from_msg:
                if fwd_style == "copy":
                    sent = client.copy_message(
                        chat_id=target_uid,
                        from_chat_id=from_msg.chat.id,
                        message_id=from_msg.id,
                    )
                else:
                    sent = from_msg.forward(target_uid)
            else:
                sent = client.send_message(
                    target_uid, text,
                    parse_mode=enums.ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            if pin and sent:
                try:
                    client.pin_chat_message(target_uid, sent.id, disable_notification=True)
                except Exception:
                    pass
            ok += 1
            time.sleep(0.05)
        except Exception:
            fail += 1

    _upd(
        f"📢 <b>Broadcast Complete!</b>\n\n"
        f"✅ <b>Sent   :</b> {ok}\n"
        f"❌ <b>Failed :</b> {fail}\n"
        f"📨 <b>Style  :</b> {style_lbl}\n"
        f"📌 <b>Pinned :</b> {'Yes' if pin else 'No'}"
    )


def _bc_pin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📌 Pin karo",     callback_data="bc_pin_yes"),
            InlineKeyboardButton("❌ Pin mat karo", callback_data="bc_pin_no"),
        ],
        [InlineKeyboardButton("🚫 Cancel", callback_data="bc_cancel")],
    ])


@bot.on_message(filters.command(["broadcast"]))
def cmd_broadcast(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        message.reply_text("❌ Sirf admins ke liye.")
        return

    from_msg = message.reply_to_message
    args     = message.text.split(None, 1)
    text     = args[1].strip() if len(args) > 1 else ""

    if not from_msg and not text:
        message.reply_text(
            "📢 <b>Broadcast Usage:</b>\n\n"
            "1️⃣ Kisi message ko reply karo + <code>/broadcast</code>\n"
            "2️⃣ Ya seedha: <code>/broadcast &lt;text&gt;</code>\n\n"
            "<b>🎨 HTML Formatting (text broadcast mein use karein):</b>\n"
            "  <code>&lt;b&gt;text&lt;/b&gt;</code>       — <b>Bold</b>\n"
            "  <code>&lt;i&gt;text&lt;/i&gt;</code>       — <i>Italic</i>\n"
            "  <code>&lt;u&gt;text&lt;/u&gt;</code>       — <u>Underline</u>\n"
            "  <code>&lt;s&gt;text&lt;/s&gt;</code>       — <s>Strikethrough</s>\n"
            "  <code>&lt;code&gt;text&lt;/code&gt;</code> — <code>Monospace</code>\n"
            "  <code>&lt;b&gt;&lt;i&gt;text&lt;/i&gt;&lt;/b&gt;</code> — <b><i>Bold Italic</i></b>\n\n"
            "<b>💡 Example:</b>\n"
            "<code>/broadcast &lt;b&gt;⚠️ Maintenance Notice&lt;/b&gt;\n"
            "Bot &lt;i&gt;1 ghante ke liye band&lt;/i&gt; rahega.</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    user_count = db.get_user_count()
    preview    = (text[:80] + "…") if text and len(text) > 80 else (text or "📨 Forwarded message")

    # If reply-based → first ask forward style, then pin
    if from_msg:
        status_msg = message.reply_text(
            f"📢 <b>Broadcast Preview</b>\n\n"
            f"👥 <b>Users:</b> {user_count}\n"
            f"📝 <b>Message:</b> <code>{h(preview)}</code>\n\n"
            f"📨 <b>Kaise bhejein?</b>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📨 Forward tag ke saath", callback_data="bc_fwd_yes"),
                    InlineKeyboardButton("📋 Bina forward tag ke",  callback_data="bc_fwd_no"),
                ],
                [InlineKeyboardButton("🚫 Cancel", callback_data="bc_cancel")],
            ]),
        )
    else:
        # Text broadcast → skip forward style step, go straight to pin
        status_msg = message.reply_text(
            f"📢 <b>Broadcast Preview</b>\n\n"
            f"👥 <b>Users:</b> {user_count}\n"
            f"📝 <b>Message:</b> <code>{h(preview)}</code>\n\n"
            f"📌 <b>Pin karna hai?</b>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_bc_pin_keyboard(),
        )

    PENDING_BROADCAST[uid] = {
        "text":       text,
        "from_msg":   from_msg,
        "status_msg": status_msg,
        "fwd_style":  "forward",   # default; updated by bc_fwd_* callbacks
    }


@bot.on_callback_query(filters.regex(r"^bc_(fwd_yes|fwd_no|pin_yes|pin_no|cancel)$"))
def cb_broadcast_action(client: Client, query: CallbackQuery):
    uid    = query.from_user.id
    action = query.data

    if uid not in ADMIN_IDS:
        query.answer("❌ Sirf admins ke liye.", show_alert=True)
        return

    if action == "bc_cancel":
        PENDING_BROADCAST.pop(uid, None)
        try:
            query.edit_message_text("🚫 <b>Broadcast cancel ho gaya.</b>",
                                    parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass
        query.answer("Cancelled.")
        return

    if uid not in PENDING_BROADCAST:
        query.answer("⚠️ Koi pending broadcast nahi.", show_alert=True)
        return

    data = PENDING_BROADCAST[uid]

    # ── Step 1: forward style chosen → show pin question ─────────────────
    if action in ("bc_fwd_yes", "bc_fwd_no"):
        data["fwd_style"] = "forward" if action == "bc_fwd_yes" else "copy"
        lbl = "📨 Forward tag ke saath" if action == "bc_fwd_yes" else "📋 Bina forward tag ke"
        query.answer(f"Style set: {lbl}")
        try:
            preview = data.get("text", "")[:80] or "📨 Forwarded message"
            query.edit_message_text(
                f"📢 <b>Broadcast Preview</b>\n\n"
                f"📨 <b>Style  :</b> {lbl}\n\n"
                f"📌 <b>Pin karna hai?</b>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_bc_pin_keyboard(),
            )
        except Exception:
            pass
        return

    # ── Step 2: pin choice → run broadcast ───────────────────────────────
    pin = (action == "bc_pin_yes")
    query.answer("📢 Broadcasting shuru ho gaya…")
    try:
        query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    threading.Thread(
        target=_run_broadcast,
        args=(client, uid, pin),
        daemon=True,
        name=f"broadcast-{uid}",
    ).start()


# ── Settings callbacks ────────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^settings_sub_ut$"))
def cb_sub_ut(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    ut  = db.get_settings(uid)["upload_type"]
    lbl = "📄 Document" if ut == "document" else "🎬 Video"
    try:
        query.edit_message_text(
            f"📁 <b>Upload Type</b>\n\nCurrent: <b>{lbl}</b>\n\nEk option chunein:",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=settings_sub_ut_keyboard(uid),
        )
    except Exception: pass
    query.answer()


@bot.on_callback_query(filters.regex(r"^settings_sub_tt$"))
def cb_sub_tt(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    tt  = db.get_settings(uid)["thumb_type"]
    lbl = {"auto": "🔄 Auto", "custom": "🖼 Custom", "none": "❌ None"}.get(tt, "🔄 Auto")
    try:
        query.edit_message_text(
            f"🖼 <b>Thumbnail</b>\n\nCurrent: <b>{lbl}</b>\n\nEk option chunein:",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=settings_sub_tt_keyboard(uid),
        )
    except Exception: pass
    query.answer()


@bot.on_callback_query(filters.regex(r"^settings_sub_ff$"))
def cb_sub_ff(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    ff  = db.get_settings(uid).get("folder_filter", "all")
    lbl = "📂 All Files" if ff == "all" else "🎬 Videos Only"
    try:
        query.edit_message_text(
            f"📂 <b>Folder Filter</b>\n\nCurrent: <b>{lbl}</b>\n\nEk option chunein:",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=settings_sub_ff_keyboard(uid),
        )
    except Exception: pass
    query.answer()


@bot.on_callback_query(filters.regex(r"^settings_sub_sp$"))
def cb_sub_sp(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    sp  = db.get_settings(uid).get("speed_preset", "max")
    lbl = {"normal": "🐢 Normal (4T)", "fast": "🚀 Fast (8T)", "max": "⚡ Max (16T)"}.get(sp, "⚡")
    try:
        query.edit_message_text(
            f"⚡ <b>Download Speed</b>\n\nCurrent: <b>{lbl}</b>\n\nEk option chunein:",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=settings_sub_sp_keyboard(uid),
        )
    except Exception: pass
    query.answer()


@bot.on_callback_query(filters.regex(r"^ut_(document|video)$"))
def cb_upload_type(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    ut  = query.data.split("_", 1)[1]
    db.set_upload_type(uid, ut)
    try:
        query.edit_message_reply_markup(settings_sub_ut_keyboard(uid))
    except Exception: pass
    query.answer(f"Upload type → {ut.capitalize()} ✅")


@bot.on_callback_query(filters.regex(r"^tt_(auto|custom|none)$"))
def cb_thumb_type(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    tt  = query.data.split("_", 1)[1]
    db.set_thumb_type(uid, tt)
    try:
        query.edit_message_reply_markup(settings_sub_tt_keyboard(uid))
    except Exception: pass
    query.answer(f"Thumbnail → {tt.capitalize()} ✅")


@bot.on_callback_query(filters.regex(r"^ff_(all|videos)$"))
def cb_folder_filter(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    ff  = query.data.split("_", 1)[1]
    db.set_folder_filter(uid, ff)
    try:
        query.edit_message_reply_markup(settings_sub_ff_keyboard(uid))
    except Exception: pass
    query.answer(f"Folder Filter → {'All Files' if ff=='all' else 'Videos Only'} ✅")


@bot.on_callback_query(filters.regex(r"^sp_(normal|fast|max)$"))
def cb_speed_preset(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    sp  = query.data.split("_", 1)[1]
    db.set_speed_preset(uid, sp)
    try:
        query.edit_message_reply_markup(settings_sub_sp_keyboard(uid))
    except Exception: pass
    t = db.SPEED_THREADS.get(sp, 16)
    query.answer(f"Speed → {sp.capitalize()} ({t} threads) ✅")


@bot.on_callback_query(filters.regex(r"^set_thumb$"))
def cb_set_thumb(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    PENDING_THUMB[uid] = True
    query.answer("Send your thumbnail photo now")
    query.message.reply_text(
        "🖼 <b>Custom Thumbnail Setup</b>\n\n"
        "Abhi ek image/photo send karein — woh aapka default thumbnail ban jaayega.",
        parse_mode=enums.ParseMode.HTML,
    )


@bot.on_callback_query(filters.regex(r"^noop$"))
def cb_noop(client: Client, query: CallbackQuery):
    query.answer()


@bot.on_callback_query(filters.regex(r"^check_sub$"))
def cb_check_sub(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    not_joined = []
    for ch in FORCE_SUB_CHANNELS:
        try:
            mem = client.get_chat_member(ch, uid)
            if mem.status in (enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.LEFT):
                not_joined.append(ch)
        except Exception:
            not_joined.append(ch)
    print(f"[CHECK_SUB] uid={uid} | not_joined={not_joined}")
    if not not_joined:
        query.answer("✅ Verified! Ab link bhejein.", show_alert=True)
        # Delete all stored force-sub warning messages
        chat_id = query.message.chat.id
        msg_ids = FORCE_SUB_MSGS.pop(uid, [])
        for mid in msg_ids:
            try:
                client.delete_messages(chat_id, mid)
            except Exception:
                pass
        # Also delete the keyboard message itself if not already in list
        try:
            if query.message.id not in msg_ids:
                client.delete_messages(chat_id, query.message.id)
        except Exception:
            pass
    else:
        # Refresh invite links for channels still not joined
        rows = []
        for ch in not_joined:
            title, lnk = _force_sub_invite_link(client, ch)
            if lnk:
                rows.append([InlineKeyboardButton(f"📢 Join: {title}", url=lnk)])
            else:
                rows.append([InlineKeyboardButton(f"📢 Join: {title}", callback_data="noop")])
        rows.append([InlineKeyboardButton("✅ Maine Join Kar Liya", callback_data="check_sub")])
        query.answer("❌ Abhi bhi join nahi kiya!", show_alert=True)
        try:
            query.edit_message_reply_markup(InlineKeyboardMarkup(rows))
        except Exception:
            pass


def _caption_window_kb(has_template: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("✏️  Edit / Set New",   callback_data="cap_edit")],
    ]
    if has_template:
        rows.append([InlineKeyboardButton("🗑  Delete Template", callback_data="cap_delete")])
    rows.append([InlineKeyboardButton("◀️  Back to Settings", callback_data="settings_open")])
    return InlineKeyboardMarkup(rows)


@bot.on_callback_query(filters.regex(r"^set_caption_tpl$"))
def cb_set_caption_tpl(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    cur = db.get_caption_template(uid)
    cur_disp = f"<code>{h(cur)}</code>" if cur else "<i>(none — default caption used)</i>"
    query.answer()
    try:
        query.edit_message_text(
            f"📝 <b>Caption Template</b>\n\n"
            f"<b>Current template:</b>\n{cur_disp}",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_caption_window_kb(bool(cur)),
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^cap_edit$"))
def cb_cap_edit(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    PENDING_CAPTION_TPL[uid] = True
    query.answer("Abhi template bhejein…")
    try:
        query.edit_message_text(
            "📝 <b>Caption Template — Edit</b>\n\n"
            "Abhi naya template bhejein.\n"
            "Template hatane ke liye sirf <code>-</code> bhejein.\n\n"
            "<b>📌 Available Variables:</b>\n"
            "  <code>{filename}</code>   — file ka naam\n"
            "  <code>{size}</code>       — file size\n"
            "  <code>{type}</code>       — Video / Document\n"
            "  <code>{mimetype}</code>   — MIME type\n"
            "  <code>{duration}</code>   — video duration\n"
            "  <code>{resolution}</code> — video resolution\n"
            "  <code>{date}</code>       — date (YYYY-MM-DD)\n"
            "  <code>{time}</code>       — time (HH:MM UTC)\n\n"
            "<b>🎨 HTML Formatting Tags:</b>\n"
            "  <code>&lt;b&gt;text&lt;/b&gt;</code>         — <b>Bold</b>\n"
            "  <code>&lt;i&gt;text&lt;/i&gt;</code>         — <i>Italic</i>\n"
            "  <code>&lt;u&gt;text&lt;/u&gt;</code>         — <u>Underline</u>\n"
            "  <code>&lt;s&gt;text&lt;/s&gt;</code>         — <s>Strikethrough</s>\n"
            "  <code>&lt;code&gt;text&lt;/code&gt;</code>   — <code>Monospace</code>\n"
            "  <code>&lt;b&gt;&lt;i&gt;text&lt;/i&gt;&lt;/b&gt;</code>   — <b><i>Bold Italic</i></b>\n\n"
            "<b>💡 Example:</b>\n"
            "<code>&lt;b&gt;📁 {filename}&lt;/b&gt;\n"
            "📦 {size}  |  🎬 {type}\n"
            "&lt;i&gt;⏱ {duration}  📐 {resolution}&lt;/i&gt;\n"
            "📅 {date}  🕐 {time}</code>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️  Back", callback_data="set_caption_tpl")],
            ]),
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^cap_delete$"))
def cb_cap_delete(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    db.set_caption_template(uid, "")
    query.answer("Caption template deleted ✅")
    try:
        query.edit_message_text(
            "📝 <b>Caption Template</b>\n\n"
            "<b>Current template:</b>\n<i>(none — default caption used)</i>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_caption_window_kb(False),
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^settings_open$"))
def cb_settings_open(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    try:
        query.edit_message_text(
            _settings_html(uid),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=settings_keyboard(uid),
        )
    except Exception:
        query.message.reply_text(
            _settings_html(uid),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=settings_keyboard(uid),
        )
    query.answer()


@bot.on_callback_query(filters.regex(r"^settings_my_account$"))
def cb_settings_my_account(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    query.answer("⏳ Loading…")
    try:
        query.edit_message_text(
            "⏳ <b>Account status check ho raha hai…</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass
    text, kb = _build_account_status(uid)
    kb_rows = kb.inline_keyboard + [
        [InlineKeyboardButton("◀️  Back to Settings", callback_data="settings_open")],
    ]
    final_kb = InlineKeyboardMarkup(kb_rows)
    try:
        query.edit_message_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=final_kb)
    except Exception:
        query.message.reply_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=final_kb)


@bot.on_callback_query(filters.regex(r"^my_account_refresh$"))
def cb_my_account_refresh(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    query.answer("🔄 Refreshing…")
    try:
        query.edit_message_text(
            "⏳ <b>Account status refresh ho raha hai…</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass
    text, kb = _build_account_status(uid)
    # Check if this was opened from settings (add Back button) or from /login (no back)
    kb_rows = kb.inline_keyboard
    try:
        query.edit_message_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)
    except Exception:
        query.message.reply_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^help_info$"))
def cb_help_info(client: Client, query: CallbackQuery):
    query.answer()
    help_text = (
        "📖 <b>Bot Help & Command Guide</b>\n\n"
        "╭━━━━〔 📥 DOWNLOADS 〕━━━━╮\n"
        "• Bas koi bhi Google Drive link bhejein\n"
        "• Single File / Folder / Multi-links support\n"
        "• <b>/cancel</b> — Current task stop karein\n"
        "• <b>/history</b> — Last 10 downloads dekhein\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "╭━━━━〔 ⚙️ CUSTOMIZATION 〕━━━━╮\n"
        "• <b>/settings</b> — Upload type (Video/Doc), speed & thumbnails\n"
        "• <b>/rename &lt;name&gt;</b> — Agli file ka custom naam set karein\n"
        "• Photo send karke custom thumbnail save karein\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "╭━━━━〔 🌐 GOOGLE ACCOUNT 〕━━━━╮\n"
        "• <b>/login</b> ya <b>/gcookies</b> — 1-Click OAuth connect karein\n"
        "• <b>/logout</b> — Drive access remove karein\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "╭━━━━〔 💎 VIP & SUPPORT 〕━━━━╮\n"
        f"• <b>/plan</b> — VIP plan status ({ULTRA_PLAN_PRICE})\n"
        "• <b>/ping</b> — Bot server latency & uptime\n"
        "• <b>/myinfo</b> — Aapki profile stats & ID\n"
        "• <b>Admin Support / Bot Buy:</b> @ftmdevz\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
    )
    try:
        query.edit_message_text(
            help_text,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Settings", callback_data="settings_open"),
                 InlineKeyboardButton("💎 VIP Plan", callback_data="myplan_check")],
                [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="start_menu_back")],
            ]),
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^(close_help|start_menu_back)$"))
def cb_start_menu_back(client: Client, query: CallbackQuery):
    display = _get_display_name(query.from_user)
    text = get_welcome_text(display)
    try:
        query.edit_message_text(
            text,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=WELCOME_KB,
        )
    except Exception:
        try:
            query.edit_message_reply_markup(reply_markup=WELCOME_KB)
        except Exception:
            pass
    query.answer()


@bot.on_callback_query(filters.regex(r"^login_menu_open$"))
def cb_login_menu_open(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    query.answer()
    text, kb = _build_account_status(uid)
    try:
        query.edit_message_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)
    except Exception:
        query.message.reply_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)


# ── Cancel / Retry callbacks ──────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^cancel_task$"))
def cb_cancel_task(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    CANCEL_TASKS.add(uid)
    # Signal the cancel event immediately for instant stop
    evt = CANCEL_EVENTS.get(uid)
    if evt:
        evt.set()
    query.answer("🚫 Cancelled!", show_alert=False)
    try:
        query.edit_message_text(
            "🚫 <b>Cancelled!</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^paste_cookies$"))
def cb_paste_cookies(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    PENDING_COOKIES[uid] = True
    query.answer()
    query.message.reply_text(
        "🍪 <b>Cookies Dein</b>\n\n"
        "Do tarike se de sakte ho:\n\n"
        "📁 <b>Option 1 — .json File (Recommended)</b>\n"
        "J2Team Cookies extension se export karo — woh seedha <b>.json file</b> "
        "download karega. Woh file yahan bhejo. Telegram kabhi split nahi karega!\n\n"
        "📋 <b>Option 2 — Text Paste</b>\n"
        "JSON ya plain text paste karo:\n"
        "<code>name1=value1; name2=value2; ...</code>\n\n"
        "❓ <i>Step-by-step guide ke liye:</i>\n"
        f"<a href='{get_cookie_page_url(uid)}'>🔗 Cookies Extract Page</a>\n\n"
        "Cancel: /cancel",
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )


@bot.on_callback_query(filters.regex(r"^gc_logout$"))
def cb_gc_logout(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    db.delete_google_cookies(uid)
    db.delete_oauth_tokens(uid)
    query.answer("✅ Account logout ho gaya!", show_alert=True)
    try:
        query.edit_message_text(
            "✅ <b>Logged out!</b>\n\nGoogle Drive account disconnected.",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^gc_validate$"))
def cb_gc_validate(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    query.answer("🔍 Validating…")
    try:
        query.edit_message_text(
            "⏳ <b>Cookies validate ho rahi hain…</b>\n\nGoogle Drive API se account info fetch ho raha hai…",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    saved = db.get_google_cookies(uid)
    info  = get_drive_account_info(saved)

    if info["valid"]:
        used_gb  = info["storage_used"]  / (1024 ** 3)
        limit_gb = info["storage_limit"] / (1024 ** 3)
        if info["storage_limit"] > 0:
            pct      = info["storage_used"] / info["storage_limit"] * 100
            bar_w    = 16
            filled   = int(bar_w * pct / 100)
            bar      = "█" * filled + "░" * (bar_w - filled)
            storage_line = (
                f"\n💾 <b>Storage:</b> {used_gb:.2f} GB / {limit_gb:.2f} GB\n"
                f"   [{bar}] {pct:.1f}%"
            )
        else:
            storage_line = f"\n💾 <b>Storage:</b> {used_gb:.2f} GB used (unlimited)"

        text = (
            f"✅ <b>Cookies Valid Hain!</b>\n\n"
            f"<pre>"
            f"╭━━━━━〔 👤 ACCOUNT INFO 〕━━━━━╮\n"
            f"│  📛 Name  : {h(info['name'])}\n"
            f"│  📧 Email : {h(info['email'])}\n"
            f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
            f"</pre>"
            f"{storage_line}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Logout", callback_data="gc_logout")],
        ])
    else:
        text = (
            f"❌ <b>Cookies Invalid / Expire Ho Gayi!</b>\n\n"
            f"🔴 <b>Error:</b> {h(info['error'] or 'Unknown error')}\n\n"
            f"Nayi Drive cookies extract karein:"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Cookies Extract Link", url=get_cookie_page_url(uid))],
            [InlineKeyboardButton("🍪 Paste Cookies Manually", callback_data="paste_cookies")],
        ])

    try:
        query.edit_message_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)
    except Exception:
        query.message.reply_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)


# ── PDF orientation callbacks ─────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^pdf_port$"))
def cb_pdf_portrait(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    if uid not in PENDING_PDF_ORIENT:
        query.answer("⚠️ Session expired. Link dobara bhejein.", show_alert=True)
        return
    if uid in ACTIVE_TASKS:
        query.answer("⚠️ Ek download already chal raha hai!", show_alert=True)
        return
    query.answer("📄 Portrait — download shuru ho raha hai…")
    try:
        query.edit_message_reply_markup(None)
    except Exception:
        pass
    threading.Thread(target=_do_pdf_download, args=(client, uid, "portrait"), daemon=True).start()


@bot.on_callback_query(filters.regex(r"^pdf_land$"))
def cb_pdf_landscape(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    if uid not in PENDING_PDF_ORIENT:
        query.answer("⚠️ Session expired. Link dobara bhejein.", show_alert=True)
        return
    if uid in ACTIVE_TASKS:
        query.answer("⚠️ Ek download already chal raha hai!", show_alert=True)
        return
    query.answer("🔄 Landscape — download shuru ho raha hai…")
    try:
        query.edit_message_reply_markup(None)
    except Exception:
        pass
    threading.Thread(target=_do_pdf_download, args=(client, uid, "landscape"), daemon=True).start()


@bot.on_callback_query(filters.regex(r"^pdf_cancel$"))
def cb_pdf_cancel(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    PENDING_PDF_ORIENT.pop(uid, None)
    query.answer("🚫 Cancelled")
    try:
        query.edit_message_text("🚫 <b>PDF download cancelled.</b>", parse_mode=enums.ParseMode.HTML)
    except Exception:
        pass


# ── Folder file selection callbacks ──────────────────────────────────────────

def _fs_refresh(query: CallbackQuery, uid: int):
    """Helper: re-render the selection message."""
    try:
        query.edit_message_text(
            folder_selection_text(uid),
            reply_markup=folder_selection_keyboard(uid),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass


def _fs_kick_download(client, query: CallbackQuery, uid: int, file_list: list):
    """Helper: close the menu and start download thread."""
    if not check_ultra_plan(uid):
        query.answer("❌ Ultra Plan nahi hai! Pehle plan lo.", show_alert=True)
        _plan_required_msg(client, query.message, uid)
        return
    if uid in ACTIVE_TASKS:
        query.answer("⚠️ Ek download already chal raha hai. Pehle usse complete hone do ya Cancel karo.", show_alert=True)
        return
    sel_data  = FOLDER_SELECTIONS.get(uid, {})
    origin    = sel_data.get("origin_msg", query.message)
    folder_id = sel_data.get("folder_id")
    try:
        query.edit_message_text(
            f"⬇️ <b>{len(file_list)} file(s) download shuru ho rahi hain…</b>\n"
            f"<i>Cancel karne ke liye Cancel button ka use karein.</i>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass
    threading.Thread(
        target=execute_folder_download,
        args=(client, origin, uid, file_list, query.message),
        kwargs={"folder_id": folder_id},
        daemon=True,
    ).start()


# ── Toggle a single file ──────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^fs_t_(\d+)$"))
def cb_fs_toggle(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    idx  = int(query.data.split("_")[2])
    data = FOLDER_SELECTIONS.get(uid)
    if not data:
        query.answer("⚠️ Session expired. Folder link dobara bhejein.", show_alert=True)
        return
    sel = data["selected"]
    if idx in sel:
        sel.discard(idx)
        query.answer("☐ Deselected")
    else:
        sel.add(idx)
        query.answer("✅ Selected")
    _fs_refresh(query, uid)


# ── Page navigation ───────────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^fs_pg_(\d+)$"))
def cb_fs_page(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    data = FOLDER_SELECTIONS.get(uid)
    if not data:
        query.answer("⚠️ Session expired.", show_alert=True)
        return
    page        = int(query.data.split("_")[2])
    total_pages = math.ceil(len(data["files"]) / FILES_PER_PAGE)
    if not (0 <= page < total_pages):
        query.answer("Invalid page.", show_alert=True)
        return
    data["page"] = page
    query.answer(f"Page {page + 1}")
    _fs_refresh(query, uid)


# ── Select / clear current page ───────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^fs_pg_sel$"))
def cb_fs_pg_sel(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    data = FOLDER_SELECTIONS.get(uid)
    if not data:
        query.answer("⚠️ Session expired.", show_alert=True)
        return
    page  = data.get("page", 0)
    start = page * FILES_PER_PAGE
    end   = min(start + FILES_PER_PAGE, len(data["files"]))
    data["selected"].update(range(start, end))
    query.answer(f"☑️ Page {page + 1} selected")
    _fs_refresh(query, uid)


@bot.on_callback_query(filters.regex(r"^fs_pg_clr$"))
def cb_fs_pg_clr(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    data = FOLDER_SELECTIONS.get(uid)
    if not data:
        query.answer("⚠️ Session expired.", show_alert=True)
        return
    page  = data.get("page", 0)
    start = page * FILES_PER_PAGE
    end   = min(start + FILES_PER_PAGE, len(data["files"]))
    data["selected"].difference_update(range(start, end))
    query.answer(f"✖️ Page {page + 1} cleared")
    _fs_refresh(query, uid)


# ── Select / clear all pages ──────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^fs_all$"))
def cb_fs_all(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    data = FOLDER_SELECTIONS.get(uid)
    if not data:
        query.answer("⚠️ Session expired.", show_alert=True)
        return
    data["selected"] = set(range(len(data["files"])))
    query.answer(f"☑️ All {len(data['files'])} selected")
    _fs_refresh(query, uid)


@bot.on_callback_query(filters.regex(r"^fs_none$"))
def cb_fs_none(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    data = FOLDER_SELECTIONS.get(uid)
    if not data:
        query.answer("⚠️ Session expired.", show_alert=True)
        return
    data["selected"] = set()
    query.answer("✖️ All cleared")
    _fs_refresh(query, uid)


# ── Cancel ────────────────────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^fs_cancel$"))
def cb_fs_cancel(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    FOLDER_SELECTIONS.pop(uid, None)
    query.answer("🚫 Cancelled")
    try:
        query.edit_message_text(
            "🚫 <b>Folder selection cancelled.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass


# ── Browse in Telegram (flat list) for private folders ───────────────────────

@bot.on_callback_query(filters.regex(r"^fb_tg_(.+)$"))
def cb_fb_tg(client: Client, query: CallbackQuery):
    uid       = query.from_user.id
    folder_id = query.matches[0].group(1)
    query.answer("📋 File list fetch ho rahi hai…")

    def _do():
        def _edit(txt, markup=None):
            try:
                if markup is not None:
                    query.edit_message_text(txt, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
                else:
                    query.edit_message_text(txt, parse_mode=enums.ParseMode.HTML)
            except FloodWait as fw:
                wait = fw.value + 1
                print(f"[FloodWait] cb_edit → {wait}s")
                time.sleep(wait)
                try:
                    if markup is not None:
                        query.edit_message_text(txt, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
                    else:
                        query.edit_message_text(txt, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass
            except Exception:
                pass

        _edit("📂 <b>Private folder — file list ban rahi hai…</b>")
        saved = db.get_google_cookies(uid)
        if not saved:
            _edit("❌ Cookies nahi hain. Pehle /login karein.", cookie_login_kb(uid))
            return
        cookies = parse_cookie_str(saved)
        try:
            file_list = list_folder_files_with_cookies(folder_id, cookies)
        except Exception as e:
            _edit(
                f"❌ <b>Folder listing fail:</b>\n<code>{h(str(e))}</code>\n\nCookies expire ho sakti hain.",
                cookie_login_kb(uid),
            )
            return

        s = db.get_settings(uid)
        if s.get("folder_filter", "all") == "videos":
            file_list = [(fid, fn) for fid, fn in file_list
                         if os.path.splitext(fn)[1].lower() in VIDEO_EXTENSIONS]
            if not file_list:
                _edit("❌ <b>No video files found.</b>")
                return

        FOLDER_SELECTIONS[uid] = {
            "folder_id":  folder_id,
            "files":      file_list,
            "selected":   set(),
            "page":       0,
            "origin_msg": query.message,
        }
        _edit(folder_selection_text(uid), folder_selection_keyboard(uid))

    threading.Thread(target=_do, daemon=True).start()


# ── Download: selected files only ────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^fs_dl$"))
def cb_fs_dl(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    data = FOLDER_SELECTIONS.get(uid)
    if not data:
        query.answer("⚠️ Session expired.", show_alert=True)
        return
    sel = data["selected"]
    if not sel:
        query.answer("⚠️ Koi file select nahi ki!", show_alert=True)
        return
    file_list = [data["files"][i] for i in sorted(sel)]
    query.answer(f"⬇️ {len(file_list)} file(s) download shuru…")
    _fs_kick_download(client, query, uid, file_list)


# ── Download: current page only ───────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^fs_dl_pg$"))
def cb_fs_dl_pg(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    data = FOLDER_SELECTIONS.get(uid)
    if not data:
        query.answer("⚠️ Session expired.", show_alert=True)
        return
    page  = data.get("page", 0)
    start = page * FILES_PER_PAGE
    end   = min(start + FILES_PER_PAGE, len(data["files"]))
    file_list = data["files"][start:end]
    query.answer(f"⬇️ Page {page + 1} — {len(file_list)} file(s) shuru…")
    _fs_kick_download(client, query, uid, file_list)


# ── Download: all files ───────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^fs_dl_all$"))
def cb_fs_dl_all(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    data = FOLDER_SELECTIONS.get(uid)
    if not data:
        query.answer("⚠️ Session expired.", show_alert=True)
        return
    file_list = list(data["files"])
    query.answer(f"⬇️ All {len(file_list)} files shuru…")
    _fs_kick_download(client, query, uid, file_list)


@bot.on_callback_query(filters.regex(r"^retry_task$"))
def cb_retry_task(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    if not check_ultra_plan(uid):
        query.answer("❌ Ultra Plan nahi hai! Pehle plan lo.", show_alert=True)
        _plan_required_msg(client, query.message, uid)
        return
    data = RETRY_DATA.get(uid)
    if not data:
        query.answer("❌ No retry data available (expired)", show_alert=True)
        return
    query.answer("🔄 Retrying…")
    status_msg = query.message
    if data.get("type") == "single":
        process_single_file(
            client, query.message, uid,
            data["file_id"], data.get("hint", ""), status_msg,
        )
    elif data.get("type") == "folder":
        process_folder(client, query.message, uid, data["folder_id"], status_msg)


@bot.on_callback_query(filters.regex(r"^fallback_task$"))
def cb_fallback_task(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    if not check_ultra_plan(uid):
        query.answer("❌ Ultra Plan nahi hai! Pehle plan lo.", show_alert=True)
        _plan_required_msg(client, query.message, uid)
        return
    data = FALLBACK_DATA.get(uid)
    if not data:
        query.answer("❌ No fallback data (session expired)", show_alert=True)
        return
    saved_cookie_str = db.get_google_cookies(uid)
    if not saved_cookie_str:
        query.answer("❌ Google login nahi hai!", show_alert=True)
        query.message.edit_text(
            "❌ <b>Google account login nahi hai.</b>\n\n"
            "Fallback ke liye Google cookies chahiye.\n"
            "/login ya /gcookies se login karein.",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    query.answer("🎭 Fallback stream shuru ho raha hai…")
    cookies    = parse_cookie_str(saved_cookie_str)
    status_msg = query.message
    file_id    = data["file_id"]
    hint       = data.get("hint", "")

    _s          = db.get_settings(uid)
    _tt         = _s.get("thumb_type", "auto")
    _fb_src_url = f"https://drive.google.com/file/d/{file_id}"
    _fb_display = (db.get_user_full(uid).get("user") or {}).get("name", f"User_{uid}")

    def _btn_post_send(sent_msg, valid_title, file_size, meta):
        file_type = "Video" if meta.get("duration", 0) > 0 else "Document"
        _copy_to_destinations(
            client, query.message, uid, sent_msg,
            display=_fb_display, file_type=file_type,
            file_size=file_size, source_url=_fb_src_url,
            drive_file_id=file_id, fname=valid_title,
        )
        db.save_download_history(uid, valid_title, file_size,
                                 file_type, _fb_src_url, None)
        try:
            log_to_channel(client,
                f"✅ #Success #uid_{uid} #Fallback\n\n"
                f"👤 User: <a href='tg://user?id={uid}'>{h(_fb_display)}</a>\n"
                f"📄 File: <code>{h(valid_title)}</code>\n"
                f"📦 Size: {format_size(file_size)}\n"
                f"📌 Source: <a href='{_fb_src_url}'>link</a>\n"
                f"⏰ {_now_str()}"
            )
        except Exception:
            pass

    def _run():
        _ftm_fallback_run(
            client=client,
            message=query.message,
            uid=uid,
            file_id=file_id,
            cookies=cookies,
            original_filename=hint,
            status_msg=status_msg,
            cancel_fn=lambda: uid in CANCEL_TASKS,
            thumb_type=_tt,
            custom_thumb_path=thumb_local_path(uid),
            post_send_fn=_btn_post_send,
        )

    threading.Thread(target=_run, daemon=True).start()


# ── FTM Manager callbacks ─────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^ftmtag_open$"))
def cb_ftmtag_open(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    if uid != OWNER_ID:
        query.answer("❌ Sirf owner ke liye.", show_alert=True)
        return
    query.answer()
    try:
        query.edit_message_text(
            _ftmtag_text(),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_ftmtag_kb(),
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^ftmtag_set$"))
def cb_ftmtag_set(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    if uid != OWNER_ID:
        query.answer("❌ Sirf owner ke liye.", show_alert=True)
        return
    PENDING_TAG[uid] = query.message
    query.answer()
    query.message.reply_text(
        "✏️ <b>Tag Set Karein</b>\n\n"
        "Abhi apna tag bhejein.\n"
        "Example: <code>@MyChannel</code>\n\n"
        "Cancel karne ke liye <code>/ftmtag</code> bhejein.",
        parse_mode=enums.ParseMode.HTML,
    )


@bot.on_callback_query(filters.regex(r"^ftmtag_toggle$"))
def cb_ftmtag_toggle(client: Client, query: CallbackQuery):
    global FILE_TAG_ENABLED
    uid = query.from_user.id
    if uid != OWNER_ID:
        query.answer("❌ Sirf owner ke liye.", show_alert=True)
        return
    if not FILE_TAG:
        query.answer("⚠️ Pehle tag set karein!", show_alert=True)
        return
    FILE_TAG_ENABLED = not FILE_TAG_ENABLED
    db.set_file_tag_enabled(FILE_TAG_ENABLED)
    query.answer("🟢 Tag ON!" if FILE_TAG_ENABLED else "🔴 Tag OFF!")
    try:
        query.edit_message_text(
            _ftmtag_text(),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_ftmtag_kb(),
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^ftmtag_clear$"))
def cb_ftmtag_clear(client: Client, query: CallbackQuery):
    global FILE_TAG, FILE_TAG_ENABLED
    uid = query.from_user.id
    if uid != OWNER_ID:
        query.answer("❌ Sirf owner ke liye.", show_alert=True)
        return
    FILE_TAG         = ""
    FILE_TAG_ENABLED = False
    db.clear_file_tag()
    query.answer("🗑 Tag remove ho gaya!")
    try:
        query.edit_message_text(
            _ftmtag_text(),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=_ftmtag_kb(),
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^bug_toggle$"))
def cb_bug_toggle(client: Client, query: CallbackQuery):
    global _BUG_MODE
    uid = query.from_user.id
    if uid != OWNER_ID:
        query.answer("❌ Sirf owner ke liye.", show_alert=True)
        return
    _BUG_MODE = not _BUG_MODE
    if _BUG_MODE:
        # Cancel all running tasks immediately
        cancelled = set(ACTIVE_TASKS)
        CANCEL_TASKS.update(cancelled)
        for _cuid in cancelled:
            _evt = CANCEL_EVENTS.get(_cuid)
            if _evt:
                _evt.set()
        cnt = len(cancelled)
        query.answer(f"🟢 Bug mode ON! {cnt} task(s) cancelled." if cnt else "🟢 Bug mode ON!")
    else:
        query.answer("🔴 Bug mode OFF!")
    try:
        query.edit_message_text(_bug_text(), parse_mode=enums.ParseMode.HTML, reply_markup=_bug_kb())
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^bug_code_(.+)$"))
def cb_bug_code(client: Client, query: CallbackQuery):
    global _BUG_ERROR_CODE
    uid = query.from_user.id
    if uid != OWNER_ID:
        query.answer("❌ Sirf owner ke liye.", show_alert=True)
        return
    code = query.matches[0].group(1)
    if code not in _BUG_ERROR_LABELS:
        query.answer("❌ Invalid code.")
        return
    _BUG_ERROR_CODE = code
    label = _BUG_ERROR_LABELS[code]
    query.answer(f"✅ Error code: {label}")
    try:
        query.edit_message_text(_bug_text(), parse_mode=enums.ParseMode.HTML, reply_markup=_bug_kb())
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^ftm_manager$"))
def cb_ftm_manager(client: Client, query: CallbackQuery):
    _edit_ftm(query, query.from_user.id);  query.answer()


@bot.on_callback_query(filters.regex(r"^ftm_back$"))
def cb_ftm_back(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    try:
        query.edit_message_text(
            _settings_html(uid),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=settings_keyboard(uid),
        )
    except Exception:
        pass
    query.answer()


@bot.on_callback_query(filters.regex(r"^delta_set_ch$"))
def cb_delta_set_ch(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    PENDING_DELTA[uid] = True
    query.answer()
    query.message.reply_text(
        "📡 <b>Delta Channel Setup</b>\n\n"
        "Apne target channel ka koi bhi message <b>forward</b> karein yahan.\n\n"
        "Ya channel ka message link ya <code>@username</code> bhi bhej sakte hain.",
        parse_mode=enums.ParseMode.HTML,
    )


@bot.on_callback_query(filters.regex(r"^alpha_folder_resend$"))
def cb_alpha_folder_resend(client: Client, query: CallbackQuery):
    uid       = query.from_user.id
    folder_id = FOLDER_ALPHA.pop(uid, None)
    query.answer()
    if not folder_id:
        query.edit_message_text("❌ Cache data nahi mila. Folder link dobara bhejein.")
        return

    cached_folder = db.get_folder_cache(folder_id)
    if not cached_folder or not cached_folder.get("files"):
        query.edit_message_text("❌ Folder cache expire ho gaya. Dobara bhejein.")
        return

    resendable = []
    for entry in cached_folder["files"]:
        fid = entry.get("drive_file_id")
        fc  = db.get_file_cache(fid) if fid else None
        if fc and fc.get("dump_msg_id"):
            resendable.append((fid, entry.get("fname", fid), fc))

    if not resendable:
        query.edit_message_text("❌ Files dump channel mein nahi milein. Normal process karein.")
        return

    def _do_resend():
        total = len(resendable)
        ACTIVE_TASKS.add(uid); TASK_START_TIMES[uid] = time.time()
        _cancel_evt = threading.Event(); CANCEL_EVENTS[uid] = _cancel_evt
        success = fail = 0
        try:
            query.edit_message_text(
                f"⚡ <b>Alpha Quick Resend shuru…</b>\n"
                f"📂 {total} files Dump Channel se copy ho rahe hain.",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass

        for i, (fid, fname, fc) in enumerate(resendable, 1):
            if uid in CANCEL_TASKS:
                CANCEL_TASKS.discard(uid)
                break
            dump_msg_id = fc["dump_msg_id"]
            f_type  = fc.get("file_type", "File")
            f_size  = fc.get("file_size", 0)
            try:
                # Apply user's caption template if set
                _tpl = db.get_caption_template(uid)
                _cap = None
                if _tpl:
                    _cap = (_tpl
                            .replace("{filename}", fname)
                            .replace("{name}", f"User_{uid}")
                            .replace("{size}", str(f_size)))
                sent = client.copy_message(
                    chat_id=query.message.chat.id,
                    from_chat_id=DUMP_CHANNEL_ID,
                    message_id=dump_msg_id,
                    caption=_cap,
                    parse_mode=enums.ParseMode.HTML if _cap else None,
                )
                _folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
                _src_url    = f"https://drive.google.com/file/d/{fid}"
                _copy_to_destinations(client, query.message, uid, sent,
                                      file_type=f_type, file_size=f_size,
                                      source_url=_src_url, folder_url=_folder_url)
                db.save_download_history(uid, fname, f_size, f_type, _src_url, _folder_url)
                success += 1
            except Exception as re:
                print(f"[ALPHA_RESEND] fail fid={fid}: {re}")
                fail += 1

        ACTIVE_TASKS.discard(uid); TASK_START_TIMES.pop(uid, None)
        CANCEL_EVENTS.pop(uid, None)
        emoji = "✅" if not fail else "⚠️"
        try:
            query.message.reply_text(
                f"{emoji} <b>Alpha Quick Resend Complete!</b>\n\n"
                f"✅ Sent: {success}  "
                f"❌ Failed: {fail}",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=DONE_KB,
            )
        except Exception:
            pass

    threading.Thread(target=_do_resend, daemon=True).start()


@bot.on_callback_query(filters.regex(r"^alpha_folder_fresh$"))
def cb_alpha_folder_fresh(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    folder_id = FOLDER_ALPHA.pop(uid, None)
    query.answer()
    if not folder_id:
        query.edit_message_text("❌ Folder ID nahi mila. Dobara link bhejein.")
        return
    try:
        status_msg = query.edit_message_text(
            "⏳ <b>Normal process shuru…</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        status_msg = query.message
    threading.Thread(
        target=process_folder,
        args=(client, query.message, uid, folder_id, status_msg),
        daemon=True,
    ).start()


@bot.on_callback_query(filters.regex(r"^alpha_toggle$"))
def cb_alpha_toggle(client: Client, query: CallbackQuery):
    uid    = query.from_user.id
    current = db.get_ftm_alpha(uid)
    db.set_ftm_alpha(uid, not current)
    state  = "ON 🟢" if not current else "OFF 🔴"
    query.answer(f"FTM Alpha Mode {state}", show_alert=False)
    _edit_ftm(query, uid)


@bot.on_callback_query(filters.regex(r"^delta_remove_ch$"))
def cb_delta_remove_ch(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    db.clear_delta_channel(uid)
    query.answer("Delta Channel remove ho gaya ✅", show_alert=True)
    _edit_ftm(query, uid)


@bot.on_callback_query(filters.regex(r"^delta_toggle$"))
def cb_delta_toggle(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    ds  = db.get_delta_settings(uid)
    dm  = ds["delta_mode"];  ch = ds["delta_channel_id"]

    if dm:
        db.set_delta_mode(uid, False)
        query.answer("Delta Mode OFF ✅")
        _edit_ftm(query, uid)
        return

    if not ch:
        query.answer("Pehle Delta Channel set karein! 📡", show_alert=True)
        return

    try:
        member = client.get_chat_member(ch, "me")
        if member.status not in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
            query.answer("Bot is channel mein admin nahi hai! Full Admin permissions chahiye. ❌", show_alert=True)
            return
    except Exception as e:
        query.answer(f"Channel check failed:\n{e}", show_alert=True)
        return

    db.set_delta_mode(uid, True)
    query.answer("Delta Mode ON 🟢")
    _edit_ftm(query, uid)


# ── Message handlers ──────────────────────────────────────────────────────────

@bot.on_message(filters.command(["clearcache"]))
def cmd_clearcache(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        message.reply_text("❌ Sirf admins ke liye.")
        return
    args = message.text.split(None, 2)[1:]
    # Sub-command: tree / file / folder / all  +  optional id
    sub    = args[0].lower() if args else "tree"
    target = args[1].strip() if len(args) > 1 else None

    if sub in ("tree", "all"):
        n = db.clear_tree_cache(target)
        msg = f"🗑 <b>Tree Cache:</b> <code>{n}</code> entr{'y' if n==1 else 'ies'} delete ki"
    elif sub == "file":
        n = db.clear_file_cache(target)
        msg = f"🗑 <b>File Cache:</b> <code>{n}</code> entr{'y' if n==1 else 'ies'} delete ki"
    elif sub == "folder":
        n = db.clear_folder_cache(target)
        msg = f"🗑 <b>Folder Cache:</b> <code>{n}</code> entr{'y' if n==1 else 'ies'} delete ki"
    else:
        message.reply_text(
            "📖 <b>Usage:</b>\n"
            "<code>/clearcache</code>               — folder tree cache clear\n"
            "<code>/clearcache tree</code>           — folder tree cache clear\n"
            "<code>/clearcache tree &lt;folder_id&gt;</code> — specific folder\n"
            "<code>/clearcache file</code>           — file cache clear\n"
            "<code>/clearcache file &lt;file_id&gt;</code>   — specific file\n"
            "<code>/clearcache folder</code>         — folder list cache clear\n"
            "<code>/clearcache all</code>            — tree cache sab clear",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    if target:
        msg += f"\n🔑 <b>ID:</b> <code>{target}</code>"
    message.reply_text(msg + "\n\n✅ <b>Done!</b>", parse_mode=enums.ParseMode.HTML)


@bot.on_message(filters.command(["cache"]))
def cmd_cache(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        message.reply_text("❌ Sirf admins ke liye.")
        return

    stats = db.get_cache_stats()
    age   = stats["age_fn"]

    # ── Tree cache ──────────────────────────────────────────────────────────
    tree_lines = []
    for d in sorted(stats["tree"]["docs"], key=lambda x: x.get("ts", 0), reverse=True)[:8]:
        name = d.get("folder_name") or d.get("folder_id", "?")[:12]
        tree_lines.append(
            f"  📁 <code>{name[:20]}</code> "
            f"({d.get('total_files', '?')} files, {age(d.get('ts'))} ago)"
        )

    # ── File cache ──────────────────────────────────────────────────────────
    file_lines = []
    for d in sorted(stats["file"]["docs"], key=lambda x: x.get("ts", 0), reverse=True)[:8]:
        fname = d.get("fname") or d.get("drive_file_id", "?")[:12]
        sz    = format_size(d.get("file_size", 0)) if d.get("file_size") else "?"
        file_lines.append(f"  📄 <code>{h(str(fname))[:24]}</code> ({sz}, {age(d.get('ts'))} ago)")

    # ── Folder cache ────────────────────────────────────────────────────────
    folder_lines = []
    for d in sorted(stats["folder"]["docs"], key=lambda x: x.get("ts", 0), reverse=True)[:5]:
        nfiles = len(d.get("files") or [])
        folder_lines.append(
            f"  📂 <code>{d.get('folder_id','?')[:16]}</code> "
            f"({nfiles} files, {age(d.get('ts'))} ago)"
        )

    tree_section   = "\n".join(tree_lines)   or "  <i>(empty)</i>"
    file_section   = "\n".join(file_lines)   or "  <i>(empty)</i>"
    folder_section = "\n".join(folder_lines) or "  <i>(empty)</i>"

    total_file_size = format_size(stats["file"]["total_size"])

    text = (
        "📊 <b>Cache Statistics</b>\n\n"
        f"🌳 <b>Folder Tree Cache</b>  —  <code>{stats['tree']['count']}</code> folders\n"
        f"{tree_section}\n\n"
        f"💾 <b>File Cache</b>  —  <code>{stats['file']['count']}</code> files  "
        f"(<b>{total_file_size}</b> total)\n"
        f"{file_section}\n\n"
        f"📂 <b>Folder List Cache</b>  —  <code>{stats['folder']['count']}</code> folders\n"
        f"{folder_section}\n\n"
        f"🗑 Clear karne ke liye: <code>/clearcache</code>"
    )
    message.reply_text(text, parse_mode=enums.ParseMode.HTML)


# ── NEW FEATURE 1: /bookmark & /bookmarks ─────────────────────────────────────

import json as _json_bm

_BOOKMARKS_FILE = "bookmarks.json"

def _bm_load() -> dict:
    try:
        with open(_BOOKMARKS_FILE) as _f:
            return _json_bm.load(_f)
    except Exception:
        return {}

def _bm_save(data: dict):
    try:
        with open(_BOOKMARKS_FILE, "w") as _f:
            _json_bm.dump(data, _f, indent=2)
    except Exception as e:
        print(f"[BOOKMARK] save error: {e}")


@bot.on_message(filters.command(["bookmark"]))
def cmd_bookmark(client: Client, message: Message):
    uid  = str(message.from_user.id)
    args = message.text.split(None, 1)
    url  = args[1].strip() if len(args) > 1 else ""

    if not url and message.reply_to_message:
        import re as _re_bm
        txt = message.reply_to_message.text or message.reply_to_message.caption or ""
        found = _re_bm.findall(r'https?://[^\s]+', txt)
        url = found[0] if found else ""

    if not url:
        message.reply_text(
            "📌 <b>Bookmark kaise karein:</b>\n\n"
            "• <code>/bookmark &lt;drive_link&gt;</code> — koi bhi Drive link save karein\n"
            "• Ya Drive link wale message ko reply karein <code>/bookmark</code> ke saath\n\n"
            "📋 Saved bookmarks dekhne ke liye: <code>/bookmarks</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    if "drive.google.com" not in url and "docs.google.com" not in url:
        message.reply_text("❌ Sirf Google Drive / Docs links bookmark ho sakte hain.")
        return

    bm = _bm_load()
    bm.setdefault(uid, [])
    if url in bm[uid]:
        message.reply_text("⚠️ Ye link pehle se bookmarked hai.\n\n/bookmarks se list dekho.", parse_mode=enums.ParseMode.HTML)
        return
    if len(bm[uid]) >= 20:
        message.reply_text("⚠️ Max 20 bookmarks allowed. Pehle <code>/bookmarks</code> se koi delete karein.", parse_mode=enums.ParseMode.HTML)
        return

    bm[uid].append(url)
    _bm_save(bm)
    message.reply_text(
        f"✅ <b>Bookmark save hua!</b>\n\n"
        f"🔗 <code>{h(url[:60])}{'...' if len(url)>60 else ''}</code>\n\n"
        f"📌 Total bookmarks: <b>{len(bm[uid])}</b>\n"
        f"📋 Dekhne ke liye: /bookmarks",
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )


@bot.on_message(filters.command(["bookmarks"]))
def cmd_bookmarks(client: Client, message: Message):
    uid = str(message.from_user.id)
    bm  = _bm_load()
    lst = bm.get(uid, [])
    if not lst:
        message.reply_text(
            "📋 <b>Koi bookmark nahi hai.</b>\n\n"
            "Drive link save karne ke liye: <code>/bookmark &lt;link&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    lines = [f"📌 <b>Aapke Bookmarks ({len(lst)})</b>\n"]
    buttons = []
    for i, url in enumerate(lst, 1):
        short = url.split("/")[-1][:28] or url[:28]
        lines.append(f"{i}. <code>{h(short)}</code>")
        buttons.append([
            InlineKeyboardButton(f"▶️ {i}. {short[:22]}", url=url),
            InlineKeyboardButton(f"🗑 Del #{i}", callback_data=f"bm_del_{i-1}"),
        ])

    lines.append("\n📤 Link pe tap karein — directly download shuru ho jayega!")
    message.reply_text(
        "\n".join(lines),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )


@bot.on_callback_query(filters.regex(r"^bm_del_(\d+)$"))
def cb_bm_del(client: Client, query: CallbackQuery):
    uid = str(query.from_user.id)
    idx = int(query.matches[0].group(1))
    bm  = _bm_load()
    lst = bm.get(uid, [])
    if 0 <= idx < len(lst):
        removed = lst.pop(idx)
        bm[uid] = lst
        _bm_save(bm)
        query.answer(f"🗑 Bookmark #{idx+1} deleted!")
        try:
            if lst:
                lines = [f"📌 <b>Aapke Bookmarks ({len(lst)})</b>\n"]
                buttons = []
                for i, url in enumerate(lst, 1):
                    short = url.split("/")[-1][:28] or url[:28]
                    lines.append(f"{i}. <code>{h(short)}</code>")
                    buttons.append([
                        InlineKeyboardButton(f"▶️ {i}. {short[:22]}", url=url),
                        InlineKeyboardButton(f"🗑 Del #{i}", callback_data=f"bm_del_{i-1}"),
                    ])
                lines.append("\n📤 Link pe tap karein — directly download shuru ho jayega!")
                query.edit_message_text(
                    "\n".join(lines),
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    disable_web_page_preview=True,
                )
            else:
                query.edit_message_text("📋 <b>Koi bookmark nahi bacha.</b>\n/bookmark se nayi save karein.", parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass
    else:
        query.answer("⚠️ Bookmark nahi mila.")


# ── NEW FEATURE 2: /caption command shortcut ───────────────────────────────────

@bot.on_message(filters.command(["caption"]))
def cmd_caption_shortcut(client: Client, message: Message):
    uid  = message.from_user.id
    args = message.text.split(None, 1)
    cur  = db.get_caption_template(uid) or ""

    if len(args) == 1:
        if cur:
            message.reply_text(
                f"📝 <b>Current Caption Template:</b>\n\n"
                f"<code>{h(cur)}</code>\n\n"
                f"<b>Available placeholders:</b>\n"
                f"  <code>{{name}}</code> — file ka naam\n"
                f"  <code>{{size}}</code> — file ka size\n"
                f"  <code>{{index}}</code> — folder mein number\n\n"
                f"Change karne ke liye: <code>/caption Mera Video: {{name}}</code>\n"
                f"Clear karne ke liye:  <code>/caption clear</code>",
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            message.reply_text(
                "📝 <b>Caption Template Set Karein</b>\n\n"
                "Usage: <code>/caption Mera Video: {name}</code>\n\n"
                "<b>Placeholders:</b>\n"
                "  <code>{name}</code> — file ka naam\n"
                "  <code>{size}</code> — file ka size\n"
                "  <code>{index}</code> — folder mein number\n\n"
                "Clear karne ke liye: <code>/caption clear</code>",
                parse_mode=enums.ParseMode.HTML,
            )
        return

    new_tpl = args[1].strip()
    if new_tpl.lower() == "clear":
        db.set_caption_template(uid, "")
        message.reply_text("✅ <b>Caption template clear ho gaya.</b>", parse_mode=enums.ParseMode.HTML)
    else:
        db.set_caption_template(uid, new_tpl)
        message.reply_text(
            f"✅ <b>Caption Template Set!</b>\n\n<code>{h(new_tpl)}</code>",
            parse_mode=enums.ParseMode.HTML,
        )


# ── NEW FEATURE 3: /queue ──────────────────────────────────────────────────────

@bot.on_message(filters.command(["queue"]))
def cmd_queue(client: Client, message: Message):
    uid        = message.from_user.id
    is_admin   = uid in ADMIN_IDS
    active_cnt = len(ACTIVE_TASKS)

    if is_admin:
        lines = [
            "📋 <b>Download Queue (Admin View)</b>\n",
            f"⚡ <b>Active Tasks:</b>  {active_cnt}",
            f"👥 <b>Total Users:</b>   {db.get_user_count()}",
        ]
        if ACTIVE_TASKS:
            lines.append("\n<b>Active UIDs:</b>")
            for auid in list(ACTIVE_TASKS)[:10]:
                you = " <i>(you)</i>" if auid == uid else ""
                lines.append(f"  • <code>{auid}</code>{you}")
        if CANCEL_TASKS:
            lines.append(f"\n🚫 <b>Cancelling:</b> {len(CANCEL_TASKS)} task(s)")
    else:
        if uid in ACTIVE_TASKS:
            lines = [
                "⚡ <b>Aapka Task Active Hai</b>\n",
                "🔄 Download chal rahi hai — please wait.",
                "",
                "Cancel karne ke liye: /cancel",
            ]
        elif uid in CANCEL_TASKS:
            lines = ["🚫 <b>Task cancel ho raha hai...</b>"]
        else:
            pending_txt = ""
            for k, v in PENDING_COOKIES.items():
                if k == uid:
                    pending_txt = "⏳ Cookies ka wait hai"
                    break
            lines = [
                "📭 <b>Koi active task nahi hai.</b>\n",
                pending_txt or "Google Drive link bhejein — download shuru ho jayega!",
            ]

    message.reply_text("\n".join(lines), parse_mode=enums.ParseMode.HTML)


# ── NEW FEATURE 4: /mystats ────────────────────────────────────────────────────

@bot.on_message(filters.command(["mystats"]))
def cmd_mystats(client: Client, message: Message):
    uid     = message.from_user.id
    display = _get_display_name(message.from_user)

    waiting = message.reply_text("⏳ <b>Stats load ho rahe hain...</b>", parse_mode=enums.ParseMode.HTML)

    total_dls = db.get_user_downloads(uid)
    history   = db.get_download_history(uid, 50)

    total_bytes = sum(r.get("size_bytes") or 0 for r in history)
    video_cnt   = sum(1 for r in history if r.get("file_type") == "Video")
    doc_cnt     = sum(1 for r in history if r.get("file_type") not in ("Video",) and r.get("file_type"))
    last_dl     = history[0] if history else None
    last_ts     = _fmt_ts(last_dl.get("ts")) if last_dl else "—"
    last_name   = h(last_dl.get("filename", "")[:30]) if last_dl else "—"

    has_cookie  = bool(db.get_google_cookies(uid))
    has_plan    = db.has_ultra_plan(uid)
    has_caption = bool(db.get_caption_template(uid))
    settings    = db.get_settings(uid)

    bm  = _bm_load()
    bm_cnt = len(bm.get(str(uid), []))

    plan_tag  = f"💎 {ULTRA_PLAN_NAME}" if has_plan else "🆓 Free"
    login_tag = "✅ Logged In" if has_cookie else "❌ Not Logged In"
    ut        = settings.get("upload_type", "video").title()

    try:
        waiting.edit_text(
            f"📊 <b>My Stats</b>\n\n"
            f"<pre>"
            f"╭━━━━━〔 USER STATS 〕━━━━━╮\n"
            f"│  👤 Name     : {h(display[:18])}\n"
            f"│  🆔 UID      : {uid}\n"
            f"│  💎 Plan     : {plan_tag}\n"
            f"│  🔐 Google   : {login_tag}\n"
            f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
            f"</pre>\n\n"
            f"📥 <b>Downloads:</b>  {total_dls} total\n"
            f"   🎬 Videos   :  {video_cnt}\n"
            f"   📄 Docs     :  {doc_cnt}\n"
            f"   💾 Data     :  {format_size(total_bytes)}\n\n"
            f"🕐 <b>Last Download:</b>\n"
            f"   {last_name}  ({last_ts})\n\n"
            f"⚙️ <b>Config:</b>\n"
            f"   📤 Upload Type : {ut}\n"
            f"   📝 Caption     : {'Set ✅' if has_caption else 'Default'}\n"
            f"   📌 Bookmarks   : {bm_cnt}",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 History", callback_data="mystats_history"),
                 InlineKeyboardButton("⚙️ Settings", callback_data="settings_open")],
            ]),
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^mystats_history$"))
def cb_mystats_history(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    rows = db.get_download_history(uid, 5)
    query.answer()
    if not rows:
        query.message.reply_text("📭 Koi download history nahi mili.")
        return
    lines = ["📋 <b>Last 5 Downloads</b>\n"]
    for i, r in enumerate(rows, 1):
        icon = "🎬" if r.get("file_type") == "Video" else "📄"
        lines.append(f"{i}. {icon} <b>{h(r.get('filename','?')[:28])}</b>")
        lines.append(f"   {format_size(r.get('size_bytes',0))}  ·  {_fmt_ts(r.get('ts'))}")
    query.message.reply_text("\n".join(lines), parse_mode=enums.ParseMode.HTML)


# ── NEW FEATURE 5: /clearhistory ──────────────────────────────────────────────

@bot.on_message(filters.command(["clearhistory"]))
def cmd_clearhistory(client: Client, message: Message):
    uid = message.from_user.id
    message.reply_text(
        "🗑 <b>Download History Clear Karein?</b>\n\n"
        "Aapki saari download history delete ho jayegi.\n"
        "Ye action undo nahi ho sakta.",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Haan, Delete Karo", callback_data="clrhist_confirm"),
             InlineKeyboardButton("❌ Cancel",            callback_data="clrhist_cancel")],
        ]),
    )


@bot.on_callback_query(filters.regex(r"^clrhist_confirm$"))
def cb_clrhist_confirm(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    try:
        db._col("history").delete_many({"user_id": uid})
    except Exception as e:
        query.answer(f"Error: {e}", show_alert=True)
        return
    query.answer("✅ History cleared!")
    try:
        query.edit_message_text(
            "✅ <b>Download history clear ho gayi!</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex(r"^clrhist_cancel$"))
def cb_clrhist_cancel(client: Client, query: CallbackQuery):
    query.answer("Cancelled.")
    try:
        query.edit_message_text("❌ <b>Cancelled.</b>", parse_mode=enums.ParseMode.HTML)
    except Exception:
        pass


# ── Message handlers ──────────────────────────────────────────────────────────

@bot.on_message(filters.private & filters.forwarded & ~filters.document & ~filters.photo)
def handle_forwarded(client: Client, message: Message):
    uid = message.from_user.id
    if message.from_user and message.from_user.is_bot:
        return
    print(f"[FWD] uid={uid} | forward_from_chat={getattr(message.forward_from_chat, 'id', None)}")
    if uid not in PENDING_DELTA: return
    fc = message.forward_from_chat
    if not fc:
        message.reply_text(
            "❌ Yeh message kisi channel se forward nahi hai.\nChannel ka koi message forward karein.",
            parse_mode=enums.ParseMode.HTML,
        )
        return
    ch_id = fc.id;  ch_title = fc.title or str(ch_id)
    db.set_delta_channel(uid, ch_id, ch_title)
    del PENDING_DELTA[uid]
    message.reply_text(
        f"✅ <b>Delta Channel set ho gaya!</b>\n\n"
        f"📺 Channel: <b>{h(ch_title)}</b>\n"
        f"🆔 ID: <code>{ch_id}</code>\n\n"
        f"⚠️ Ab is channel mein bot ko <b>Full Admin</b> permissions ke saath add karein,\n"
        f"phir <code>/settings</code> → 🔧 FTM Manager → Delta Mode ON karein.",
        parse_mode=enums.ParseMode.HTML,
    )


@bot.on_message(filters.private & filters.document)
def handle_document(client: Client, message: Message):
    if message.from_user and message.from_user.is_bot:
        return
    uid  = message.from_user.id
    doc  = message.document
    name = (doc.file_name or "").lower()
    print(f"[DOC] uid={uid} | file={name} | pending_cookies={uid in PENDING_COOKIES}")

    # ── Cookie file upload (.json / .txt, while PENDING_COOKIES) ──────────
    COOKIE_EXTS = (".json", ".txt")
    if uid in PENDING_COOKIES and name.endswith(COOKIE_EXTS):
        del PENDING_COOKIES[uid]
        status_m = message.reply_text(
            "⏳ <b>Cookie file padhh raha hoon…</b>",
            parse_mode=enums.ParseMode.HTML,
        )
        ext      = ".json" if name.endswith(".json") else ".txt"
        tmp_path = os.path.join(DOWNLOADS_DIR, f"cookies_{uid}{ext}")
        try:
            client.download_media(message, file_name=tmp_path)
            with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read().strip()
        except Exception as e:
            status_m.edit_text(
                f"❌ <b>File padhh nahi saka:</b> <code>{h(str(e))}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
            return
        finally:
            try: os.remove(tmp_path)
            except Exception: pass

        is_json = text.startswith("{") or text.startswith("[")
        if len(text) < 10 or (not is_json and "=" not in text):
            status_m.edit_text(
                "❌ <b>File mein valid cookies nahi mili.</b>\n\n"
                "Sahi format:\n"
                "• J2Team Cookies ka .json export (recommended)\n"
                "• Ya plain text: <code>name=value; name2=value2</code>",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        count = len(parse_cookie_str(text))
        status_m.edit_text(
            f"🔍 <b>{count} cookies mili — validate ho raha hai…</b>",
            parse_mode=enums.ParseMode.HTML,
        )
        info = get_drive_account_info(text)
        if info["valid"]:
            db.save_google_cookies(uid, text)
            used_gb  = info["storage_used"]  / (1024 ** 3)
            limit_gb = info["storage_limit"] / (1024 ** 3)
            if info["storage_limit"] > 0:
                pct    = info["storage_used"] / info["storage_limit"] * 100
                bar_w  = 16
                filled = int(bar_w * pct / 100)
                bar    = "█" * filled + "░" * (bar_w - filled)
                storage_line = (
                    f"\n💾 <b>Storage:</b> {used_gb:.2f} GB / {limit_gb:.2f} GB\n"
                    f"   [{bar}] {pct:.1f}%"
                )
            else:
                storage_line = f"\n💾 <b>Storage:</b> {used_gb:.2f} GB (unlimited)"
            reply_text = (
                f"✅ <b>Login Successful!</b>\n\n"
                f"<pre>"
                f"╭━━━━━〔 👤 ACCOUNT INFO 〕━━━━━╮\n"
                f"│  📛 Name  : {h(info['name'])}\n"
                f"│  📧 Email : {h(info['email'])}\n"
                f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
                f"</pre>"
                f"{storage_line}\n\n"
                "Ab apna private Drive link bhejein — main download karunga. 🚀"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Logout", callback_data="gc_logout")],
            ])
        else:
            reply_text = (
                f"❌ <b>Cookies validate nahi hui — save nahi ki gayi.</b>\n\n"
                f"🔴 {h(info['error'] or 'Unknown error')}\n\n"
                "drive.google.com pe logged-in hokar nayi cookies export karein."
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Extract Karein", url=get_cookie_page_url(uid))],
                [InlineKeyboardButton("🍪 Phir Se Bhejein", callback_data="paste_cookies")],
            ])
        try:
            status_m.edit_text(reply_text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)
        except Exception:
            message.reply_text(reply_text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)
        return

    # ── Wrong file type while expecting cookies ────────────────────────────
    if uid in PENDING_COOKIES:
        message.reply_text(
            "❌ <b>Sirf .json ya .txt file accept hogi</b> cookies ke liye.\n\n"
            "J2Team Cookies extension se export karo — woh seedha <b>.json file</b> download karega.\n"
            "Woh file yahan bhejo.",
            parse_mode=enums.ParseMode.HTML,
        )
        return


@bot.on_message(filters.private & filters.photo)
def handle_photo(client: Client, message: Message):
    if message.from_user and message.from_user.is_bot:
        return
    uid = message.from_user.id
    print(f"[PHOTO] uid={uid} | pending_thumb={uid in PENDING_THUMB}")
    if uid not in PENDING_THUMB: return
    del PENDING_THUMB[uid]
    status = message.reply_text("⏳ Thumbnail save ho raha hai…")
    try:
        fid   = message.photo.file_id
        local = thumb_local_path(uid)
        client.download_media(fid, file_name=local)
        db.set_custom_thumb(uid, fid)
        status.edit_text("✅ <b>Custom thumbnail set ho gaya!</b>", parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        status.edit_text(
            f"❌ <b>Thumbnail save nahi hua:</b>\n<code>{h(str(e))}</code>",
            parse_mode=enums.ParseMode.HTML,
        )


@bot.on_message(filters.private & filters.text & ~filters.command(["start", "help", "settings",
                                                        "stats", "broadcast",
                                                        "cancel", "history", "rename",
                                                        "ping", "myinfo", "logout",
                                                        "gcookies", "logininfo", "login"]))
def handle_message(client: Client, message: Message):
    if message.from_user and message.from_user.is_bot:
        return
    raw_text = message.text or message.caption or ""
    text = raw_text.strip()
    uid  = message.from_user.id
    is_fwd = bool(message.forward_date)
    chat_type = getattr(message.chat, "type", "unknown")
    display  = _get_display_name(message.from_user)

    print(f"[MSG] uid={uid} | chat_type={chat_type} | fwd={is_fwd} | len={len(text)} | preview={text[:80]!r}")

    if text.startswith("/"): return

    # ── PENDING_FTM: admin is in FTM auth flow ─────────────────────────────
    if uid in ADMIN_IDS and uid in PENDING_FTM:
        step_data   = PENDING_FTM.get(uid, {})
        step        = step_data.get("step")
        origin_msg  = step_data.get("origin_msg")

        def _ftm_done(session_str):
            """Save session, update the panel, clean up."""
            ok, panel_text, logged_in = _ftm_save_and_connect(session_str)
            PENDING_FTM.pop(uid, None)
            if origin_msg:
                try:
                    origin_msg.edit_text(panel_text, parse_mode=enums.ParseMode.HTML,
                                         reply_markup=_ftm_kb(logged_in))
                except Exception:
                    pass
            return ok

        if step == "awaiting_string":
            session_str = text.strip()
            sm = message.reply_text("⏳ <b>Connecting…</b>", parse_mode=enums.ParseMode.HTML)
            ok = _ftm_done(session_str)
            sm.edit_text(
                "✅ <b>Session connected!</b>" if ok else
                "❌ <b>Session invalid — dobara try karo.</b>",
                parse_mode=enums.ParseMode.HTML,
            )
            return

        if step == "awaiting_phone":
            phone = text.strip()
            sm = message.reply_text("⏳ <b>OTP bhej raha hai…</b>", parse_mode=enums.ParseMode.HTML)
            try:
                tmp = Client("ftm_phone_tmp", api_id=API_ID, api_hash=API_HASH, in_memory=True)
                tmp.connect()
                sent_code = tmp.send_code(phone)
                PENDING_FTM[uid].update({
                    "step": "awaiting_otp",
                    "phone": phone,
                    "phone_code_hash": sent_code.phone_code_hash,
                    "tmp_client": tmp,
                })
                sm.edit_text(
                    f"📱 OTP bheja gaya <code>{phone}</code> par!\n\n"
                    f"OTP enter karo:",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception as e:
                PENDING_FTM.pop(uid, None)
                sm.edit_text(f"❌ OTP send fail: <code>{h(str(e))}</code>",
                             parse_mode=enums.ParseMode.HTML)
            return

        if step == "awaiting_otp":
            otp = text.strip().replace(" ", "")
            tmp = step_data.get("tmp_client")
            sm  = message.reply_text("⏳ <b>Verifying OTP…</b>", parse_mode=enums.ParseMode.HTML)
            try:
                tmp.sign_in(step_data["phone"], step_data["phone_code_hash"], otp)
                session_str = tmp.export_session_string()
                try: tmp.disconnect()
                except Exception: pass
                ok = _ftm_done(session_str)
                sm.edit_text(
                    "✅ <b>Phone login successful!</b>" if ok else
                    "❌ <b>Login OK lekin client start fail — session saved.</b>",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception as e:
                err = str(e)
                if "PHONE_CODE_INVALID" in err:
                    sm.edit_text("❌ OTP galat hai. Dobara bhejo:", parse_mode=enums.ParseMode.HTML)
                elif "SESSION_PASSWORD_NEEDED" in err:
                    PENDING_FTM[uid]["step"] = "awaiting_2fa"
                    sm.edit_text("🔐 <b>2FA Password required!</b>\n\nApna 2FA password bhejo:",
                                 parse_mode=enums.ParseMode.HTML)
                else:
                    PENDING_FTM.pop(uid, None)
                    try: tmp.disconnect()
                    except Exception: pass
                    sm.edit_text(f"❌ Error: <code>{h(err)}</code>", parse_mode=enums.ParseMode.HTML)
            return

        if step == "awaiting_2fa":
            password = text.strip()
            tmp = step_data.get("tmp_client")
            sm  = message.reply_text("⏳ <b>Verifying 2FA…</b>", parse_mode=enums.ParseMode.HTML)
            try:
                tmp.check_password(password)
                session_str = tmp.export_session_string()
                try: tmp.disconnect()
                except Exception: pass
                ok = _ftm_done(session_str)
                sm.edit_text(
                    "✅ <b>2FA verified! Session saved.</b>" if ok else
                    "❌ <b>2FA OK lekin client start fail — session saved.</b>",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception as e:
                PENDING_FTM.pop(uid, None)
                try: tmp.disconnect()
                except Exception: pass
                sm.edit_text(f"❌ 2FA error: <code>{h(str(e))}</code>",
                             parse_mode=enums.ParseMode.HTML)
            return

    # ── PENDING_COOKIES: user is pasting Google cookies ───────────────────
    if uid in PENDING_COOKIES:
        print(f"[COOKIES] uid={uid} | awaiting cookies | fwd={is_fwd} | text_len={len(text)}")
        del PENDING_COOKIES[uid]
        # Accept both JSON (from Cookie Editor/forwarded) and key=value string
        is_json = text.startswith("{") or text.startswith("[")
        if len(text) < 10 or (not is_json and "=" not in text):
            print(f"[COOKIES] uid={uid} | INVALID format — too short or missing = | is_json={is_json}")
            message.reply_text(
                "❌ <b>Invalid cookies format.</b>\n\n"
                "Do formats accepted hain:\n"
                "• <b>JSON</b> (Cookie Editor extension se): <code>{\"cookies\":[...]}</code>\n"
                "• <b>Plain text</b>: <code>name1=value1; name2=value2</code>",
                parse_mode=enums.ParseMode.HTML,
            )
            return
        count    = len(parse_cookie_str(text))
        print(f"[COOKIES] uid={uid} | parsed {count} cookies | is_json={is_json}")
        status_m = message.reply_text(
            f"🔍 <b>{count} cookies mili — validate ho raha hai…</b>",
            parse_mode=enums.ParseMode.HTML,
        )
        info = get_drive_account_info(text)
        print(f"[COOKIES] uid={uid} | valid={info['valid']} | email={info.get('email')} | err={info.get('error')}")
        if info["valid"]:
            db.save_google_cookies(uid, text)
            used_gb  = info["storage_used"]  / (1024 ** 3)
            limit_gb = info["storage_limit"] / (1024 ** 3)
            if info["storage_limit"] > 0:
                pct    = info["storage_used"] / info["storage_limit"] * 100
                bar_w  = 16
                filled = int(bar_w * pct / 100)
                bar    = "█" * filled + "░" * (bar_w - filled)
                storage_line = (
                    f"\n💾 <b>Storage:</b> {used_gb:.2f} GB / {limit_gb:.2f} GB\n"
                    f"   [{bar}] {pct:.1f}%"
                )
            else:
                storage_line = f"\n💾 <b>Storage:</b> {used_gb:.2f} GB (unlimited)"
            reply_text = (
                f"✅ <b>Login Successful!</b>\n\n"
                f"<pre>"
                f"╭━━━━━〔 👤 ACCOUNT INFO 〕━━━━━╮\n"
                f"│  📛 Name  : {h(info['name'])}\n"
                f"│  📧 Email : {h(info['email'])}\n"
                f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
                f"</pre>"
                f"{storage_line}\n\n"
                "Ab apna private Drive link bhejein — main download karunga. 🚀"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Logout", callback_data="gc_logout")],
            ])
        else:
            reply_text = (
                f"❌ <b>Cookies validate nahi hui — save nahi ki gayi.</b>\n\n"
                f"🔴 {h(info['error'] or 'Unknown error')}\n\n"
                "drive.google.com pe logged-in hokar nayi cookies export karein."
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Extract Karein", url=get_cookie_page_url(uid))],
                [InlineKeyboardButton("🍪 Phir Se Bhejein", callback_data="paste_cookies")],
            ])
        try:
            status_m.edit_text(reply_text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)
        except Exception:
            message.reply_text(reply_text, parse_mode=enums.ParseMode.HTML, reply_markup=kb)
        return

    # ── PENDING_CAPTION_TPL: caption template text ─────────────────────────
    if uid in PENDING_CAPTION_TPL:
        print(f"[CAPTION_TPL] uid={uid} | new_tpl preview={text[:60]!r}")
        del PENDING_CAPTION_TPL[uid]
        new_tpl = "" if text.strip() == "-" else text.strip()
        db.set_caption_template(uid, new_tpl)
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝  View Caption Settings", callback_data="set_caption_tpl")],
            [InlineKeyboardButton("⚙️  Settings",              callback_data="settings_open")],
        ])
        if new_tpl:
            preview = _render_caption(
                new_tpl,
                filename="Sample Video.mp4",
                size="250 MB",
                file_type="Video",
                mimetype="video/mp4",
                duration="1m 30s",
                resolution="1920×1080",
            )
            message.reply_text(
                f"✅ <b>Caption template saved!</b>\n\n"
                f"<b>Preview:</b>\n<code>{h(preview)}</code>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=back_kb,
            )
        else:
            message.reply_text(
                "✅ Caption template <i>removed</i> — default caption use hogi.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=back_kb,
            )
        return

    # ── PENDING_TAG: admin typed a new file tag ──────────────────────────
    if uid in ADMIN_IDS and uid in PENDING_TAG:
        origin_msg = PENDING_TAG.pop(uid)
        global FILE_TAG, FILE_TAG_ENABLED
        new_tag = text.strip()
        FILE_TAG         = new_tag
        FILE_TAG_ENABLED = True
        db.set_file_tag(new_tag)
        print(f"[TAG] uid={uid} | tag set → '{new_tag}'")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏷  Open Tag Manager", callback_data="ftmtag_open")],
        ])
        message.reply_text(
            f"✅ <b>Tag set ho gaya!</b>\n\n"
            f"🏷 Tag: <code>{h(new_tag)}</code>\n"
            f"📂 Example: <code>movie {h(new_tag)}.mp4</code>\n"
            f"🟢 Status: <b>ON</b>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=kb,
        )
        # Refresh the original tag manager message if still accessible
        try:
            origin_msg.edit_text(
                _ftmtag_text(),
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_ftmtag_kb(),
            )
        except Exception:
            pass
        return

    # ── PENDING_DELTA: channel link / @username ───────────────────────────
    if uid in PENDING_DELTA:
        print(f"[DELTA] uid={uid} | text preview={text[:60]!r}")
        ch_link = re.search(r't\.me/([a-zA-Z0-9_]+)(?:/\d+)?', text)
        ch_user = re.search(r'@([a-zA-Z0-9_]+)', text)
        ident   = "@" + (ch_link.group(1) if ch_link else (ch_user.group(1) if ch_user else ""))
        if not (ch_link or ch_user):
            print(f"[DELTA] uid={uid} | no channel found in text")
            message.reply_text(
                "❌ Channel nahi mila.\n"
                "Channel ka message <b>forward</b> karein, ya <code>@username</code> bhejein.",
                parse_mode=enums.ParseMode.HTML,
            )
            return
        try:
            print(f"[DELTA] uid={uid} | resolving ident={ident}")
            chat = client.get_chat(ident)
            db.set_delta_channel(uid, chat.id, chat.title or ident)
            del PENDING_DELTA[uid]
            print(f"[DELTA] uid={uid} | channel set → id={chat.id} title={chat.title}")
            message.reply_text(
                f"✅ <b>Delta Channel set ho gaya!</b>\n\n"
                f"📺 Channel: <b>{h(chat.title or ident)}</b>\n"
                f"🆔 ID: <code>{chat.id}</code>\n\n"
                f"⚠️ Ab bot ko <b>Full Admin</b> permissions ke saath add karein,\n"
                f"phir <code>/settings</code> → 🔧 FTM Manager → Delta Mode ON karein.",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            print(f"[DELTA] uid={uid} | resolve error: {e}")
            message.reply_text(f"❌ Channel resolve nahi hua: <code>{h(str(e))}</code>",
                               parse_mode=enums.ParseMode.HTML)
        return

    # ── Force Subscribe check ─────────────────────────────────────────────
    if not check_force_sub(client, message):
        print(f"[FORCE_SUB] uid={uid} | failed force-sub check — ignored")
        return

    # ── Ultra Plan check ──────────────────────────────────────────────────
    if not check_ultra_plan(uid):
        print(f"[PLAN] uid={uid} | no active plan — blocked")
        _plan_required_msg(client, message, uid, display)
        return

    # ── Active task guard (one download at a time) ────────────────────────
    if uid in ACTIVE_TASKS:
        print(f"[GUARD] uid={uid} | already has an active task — rejecting new request")
        message.reply_text(
            "⚠️ <b>Ek download already chal raha hai!</b>\n\n"
            "Pehle current download complete karo ya /cancel karo.",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    # ── Bug mode: fake HTTP error after short delay (owner-controlled) ───
    if _BUG_MODE:
        sm = message.reply_text("⏳ <b>Processing your request…</b>", parse_mode=enums.ParseMode.HTML)
        time.sleep(30)
        try:
            import random as _rnd
            import uuid  as _uuid
            _boss = "<a href='https://t.me/ftmdevz'>@ftmdevz</a>"
            _rid  = _uuid.uuid4().hex[:16]
            _tid  = _uuid.uuid4().hex[:12]
            _ALL_ERRORS = {
                "429": (
                    f"<pre>HTTP/1.1 429 Too Many Requests\nContent-Type: application/json\n\n"
                    f'{{\n  "error": 429,\n  "message": "API rate limit exceeded.",\n'
                    f'  "description": "Too many requests have been made to the API in a short time.",\n'
                    f'  "request_id": "{_rid}",\n  "trace_id": "{_tid}",\n  "contact": "@ftmdevz"\n}}</pre>\n\n'
                    f"Contact your boss {_boss} to increase your call limit."
                ),
                    "404": (
                        f"<pre>HTTP/1.1 404 Not Found\nContent-Type: application/json\n\n"
                        f'{{\n  "error": 404,\n  "message": "IP address blocked.",\n'
                        f'  "description": "Your IP has been blocked by the server administrator.",\n'
                        f'  "request_id": "{_rid}",\n  "trace_id": "{_tid}",\n  "contact": "@ftmdevz"\n}}</pre>\n\n'
                    f"Contact your boss {_boss} to get unblocked."
                ),
                    "503": (
                        f"<pre>HTTP/1.1 503 Service Unavailable\nContent-Type: application/json\n\n"
                        f'{{\n  "error": 503,\n  "message": "Service temporarily unavailable.",\n'
                        f'  "description": "The server is unable to handle your request right now.",\n'
                        f'  "request_id": "{_rid}",\n  "trace_id": "{_tid}",\n  "contact": "@ftmdevz"\n}}</pre>\n\n'
                    f"Report this to your boss {_boss}."
                ),
                    "502": (
                        f"<pre>HTTP/1.1 502 Bad Gateway\nContent-Type: application/json\n\n"
                        f'{{\n  "error": 502,\n  "message": "Bad gateway.",\n'
                        f'  "description": "Invalid response received from upstream server.",\n'
                        f'  "request_id": "{_rid}",\n  "trace_id": "{_tid}",\n  "contact": "@ftmdevz"\n}}</pre>\n\n'
                    f"Ask your boss {_boss} to fix the gateway."
                ),
                    "401": (
                        f"<pre>HTTP/1.1 401 Unauthorized\nContent-Type: application/json\n\n"
                        f'{{\n  "error": 401,\n  "message": "Unauthorized access.",\n'
                        f'  "description": "Your session has expired or access has been revoked.",\n'
                        f'  "request_id": "{_rid}",\n  "trace_id": "{_tid}",\n  "contact": "@ftmdevz"\n}}</pre>\n\n'
                    f"Contact your boss {_boss} to renew your access."
                ),
            }
            # Pick error based on admin's choice
            if _BUG_ERROR_CODE == "random":
                err_text = _rnd.choice(list(_ALL_ERRORS.values()))
            else:
                err_text = _ALL_ERRORS.get(_BUG_ERROR_CODE, _rnd.choice(list(_ALL_ERRORS.values())))

            sm.edit_text(err_text, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            pass
        print(f"[BUG_MODE] uid={uid} | code={_BUG_ERROR_CODE} | fake error shown")
        return

    # ── Extract all Drive/Docs links from the full message text ──────────
    _URL_PAT = (
        r'https?://drive\.google\.com/file/d/[a-zA-Z0-9_\-]+(?:/[^\s]*)?'
        r'|https?://docs\.google\.com/(?:document|spreadsheets|presentation|forms)/d/[a-zA-Z0-9_\-]+(?:/[^\s]*)?'
        r'|https?://drive\.google\.com/\S+'
        r'|https?://docs\.google\.com/\S+'
    )

    # ── Folder link ───────────────────────────────────────────────────────
    folder_id = extract_folder_id(text)
    if folder_id:
        print(f"[FOLDER] uid={uid} | folder_id={folder_id}")
        status = message.reply_text(
            "📂 <b>Folder scan ho raha hai…</b>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=CANCEL_KB,
        )
        process_folder(client, message, uid, folder_id, status)
        return

    # ── Extract unique Drive/Docs links from (possibly long) message ─────
    raw_urls  = re.findall(_URL_PAT, text)
    seen: set = set();  unique_urls: list = []
    for u in raw_urls:
        if u not in seen: seen.add(u);  unique_urls.append(u)

    print(f"[LINKS] uid={uid} | msg_len={len(text)} | found {len(unique_urls)} unique Drive link(s): {unique_urls}")

    # ── No Drive links found — silently ignore ───────────────────────────
    if not unique_urls:
        print(f"[LINKS] uid={uid} | no Drive links found — silently ignoring")
        return

    # ── Bulk (multiple links) ─────────────────────────────────────────────
    if len(unique_urls) > 1:
        total       = len(unique_urls)
        print(f"[BATCH] uid={uid} | starting batch of {total} links")
        summary_msg = message.reply_text(
            f"📋 <b>{total} links mili!</b> Processing shuru…",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=CANCEL_KB,
        )
        ACTIVE_TASKS.add(uid);  TASK_START_TIMES[uid] = time.time()
        _cancel_evt = threading.Event(); CANCEL_EVENTS[uid] = _cancel_evt
        ok = fail = 0
        try:
            for i, lnk in enumerate(unique_urls, 1):
                if uid in CANCEL_TASKS:
                    print(f"[BATCH] uid={uid} | cancelled at item {i}/{total}")
                    CANCEL_TASKS.discard(uid);  break
                print(f"[BATCH] uid={uid} | [{i}/{total}] processing: {lnk}")
                fs = message.reply_text(
                    f"⏳ <b>[{i}/{total}]</b> Processing…",
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=CANCEL_KB,
                )
                mime_hint = _guess_mime_from_docs_url(lnk)
                r = process_single_file(client, message, uid, extract_drive_id(lnk), "",
                                        fs, i, total, mime_hint=mime_hint)
                print(f"[BATCH] uid={uid} | [{i}/{total}] result={'ok' if r else 'fail'}")
                if r: ok += 1
                else: fail += 1
        finally:
            ACTIVE_TASKS.discard(uid);  TASK_START_TIMES.pop(uid, None)
            CANCEL_EVENTS.pop(uid, None)
            print(f"[BATCH] uid={uid} | done — ok={ok} fail={fail}")

        try:
            summary_msg.edit_text(
                f"📋 <b>Batch Complete!</b>\n\n"
                f"✅ <b>Success:</b> {ok}/{total}\n"
                + (f"❌ <b>Failed:</b>  {fail}\n" if fail else ""),
                parse_mode=enums.ParseMode.HTML,
                reply_markup=DONE_KB,
            )
        except Exception:
            pass
        return

    # ── Single link ───────────────────────────────────────────────────────
    single_url = unique_urls[0]
    drive_id   = extract_drive_id(single_url)
    display    = _get_display_name(message.from_user)
    mention    = f'<a href="tg://user?id={uid}">{h(display)}</a>'
    print(f"[SINGLE] uid={uid} | url={single_url} | drive_id={drive_id}")
    log_to_channel(client,
        f"🔗 #SingleLink #Received #uid_{uid}\n\n"
        f"👤 User: {mention} (<code>{uid}</code>)\n"
        f"🆔 Drive ID: <code>{drive_id}</code>\n"
        f"⏰ {_now_str()}"
    )

    ACTIVE_TASKS.add(uid);  TASK_START_TIMES[uid] = time.time()
    _cancel_evt = threading.Event(); CANCEL_EVENTS[uid] = _cancel_evt
    status = message.reply_text(
        "⏳ <b>Processing link…</b>",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=CANCEL_KB,
    )
    try:
        mime_hint = _guess_mime_from_docs_url(single_url)
        print(f"[SINGLE] uid={uid} | mime_hint={mime_hint} | starting download")
        process_single_file(client, message, uid, drive_id, "", status,
                            mime_hint=mime_hint)
        print(f"[SINGLE] uid={uid} | download complete")
    except Exception as exc:
        print(f"[SINGLE] uid={uid} | unhandled exception: {exc}")
        raise
    finally:
        ACTIVE_TASKS.discard(uid);  TASK_START_TIMES.pop(uid, None)
        CANCEL_EVENTS.pop(uid, None)


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

def _task_watchdog():
    """Background thread: auto-release ACTIVE_TASKS stuck for > 30 minutes."""
    MAX_TASK_SEC = 1800  # 30 minutes
    while True:
        try:
            time.sleep(60)
            now  = time.time()
            dead = [uid for uid, t0 in list(TASK_START_TIMES.items())
                    if now - t0 > MAX_TASK_SEC]
            for uid in dead:
                print(f"[WATCHDOG] ⚠️ uid={uid} stuck >{MAX_TASK_SEC}s — force-releasing")
                ACTIVE_TASKS.discard(uid)
                TASK_START_TIMES.pop(uid, None)
                CANCEL_TASKS.discard(uid)
                CANCEL_EVENTS.pop(uid, None)
        except Exception as e:
            print(f"[WATCHDOG] error: {e}")


def _anti_sleep_worker():
    """Background thread: ping PUBLIC_URL every 2 minutes to keep hosting alive 24/7."""
    time.sleep(15)
    target_url = (PUBLIC_URL or "").rstrip("/")
    if not target_url:
        print("[ANTI_SLEEP] No PUBLIC_URL set — self-ping inactive", flush=True)
        return
    print(f"[ANTI_SLEEP] Active — auto-pinging {target_url} every 2 minutes", flush=True)
    while True:
        try:
            requests.get(target_url, timeout=15)
        except Exception as e:
            print(f"[ANTI_SLEEP] Ping warning: {e}", flush=True)
        time.sleep(120)


def send_restart_notifications():
    """Broadcast restart message to all users + log to channel. Runs in background thread."""
    import asyncio

    async def _do():
        try:
            me           = await bot.get_me()
            bot_name     = me.first_name or "Bot"
            bot_username = me.username or ""
            deeplink     = f"https://t.me/{bot_username}" if bot_username else bot_name

            tz       = ZoneInfo("Asia/Kolkata")
            now      = datetime.datetime.now(tz)
            date_str = now.strftime("%d-%m-%Y")
            time_str = now.strftime("%I:%M:%S %p")

            # ── Log channel message ───────────────────────────────────────
            if LOG_CHANNEL_ID:
                log_txt = (
                    f"#ʙᴏᴛ_ʀᴇsᴛᴀʀᴛ 🔄\n\n"
                    f"🤖 ʙᴏᴛ: <a href=\"{deeplink}\">{h(bot_name)}</a>\n"
                    f"📅 ᴅᴀᴛᴇ: {date_str}\n"
                    f"⏰ ᴛɪᴍᴇ: {time_str}\n"
                    f"🌐 ᴛɪᴍᴇᴢᴏɴᴇ: Asia/Kolkata\n"
                    f"🛠️ ʙᴜɪʟᴅ sᴛᴀᴛᴜs: {BOT_VERSION}"
                )
                try:
                    await bot.send_message(LOG_CHANNEL_ID, log_txt,
                                           parse_mode=enums.ParseMode.HTML,
                                           disable_web_page_preview=True)
                except Exception as e:
                    print(f"[RESTART] Log channel error: {e}")

            # ── Broadcast to all users ────────────────────────────────────
            users  = db.get_all_users()
            sent   = failed = 0
            for u in users:
                uid = u.get("user_id")
                if not uid:
                    continue
                try:
                    await bot.send_message(uid, "<b><i>๏[-ิ_•ิ]๏ ʙᴏᴛ ʀᴇsᴛᴀʀᴛᴇᴅ !</i></b>",
                                           parse_mode=enums.ParseMode.HTML)
                    sent += 1
                    await asyncio.sleep(0.05)   # ~20 msg/s
                except Exception:
                    failed += 1
            print(f"[RESTART] Broadcast done — sent={sent} failed={failed}")

        except Exception as e:
            print(f"[RESTART] Notification error: {e}")

    # Schedule on the bot's already-running event loop (safe from any thread)
    try:
        future = asyncio.run_coroutine_threadsafe(_do(), bot.loop)
        future.result(timeout=300)   # wait up to 5 min for large user bases
    except Exception as e:
        print(f"[RESTART] Failed to schedule notification: {e}")


if __name__ == "__main__":
    print("🤖 Bot start ho raha hai…", flush=True)
    _flask_port = int(os.environ.get("PORT", 8080))

    # ── Free port if held by a stale process ──────────────────────────────────
    try:
        import psutil as _psutil
        _my_pid = os.getpid()
        for _proc in _psutil.process_iter(['pid', 'name']):
            try:
                if _proc.pid == _my_pid:
                    continue
                for _conn in _proc.net_connections(kind='inet'):
                    if getattr(_conn.laddr, 'port', None) == _flask_port:
                        print(f"[STARTUP] Freeing port {_flask_port} from PID {_proc.pid}", flush=True)
                        _proc.kill()
                        break
            except Exception:
                pass
        import time as _t; _t.sleep(0.5)
    except Exception as _e:
        print(f"[STARTUP] Cleanup warning: {_e}", flush=True)

    cookie_server.start_in_background(port=_flask_port)
    try:
        from cf_auto_tunnel import start_auto_tunnel_thread
        start_auto_tunnel_thread(port=_flask_port)
    except Exception as _tfe:
        print(f"[TUNNEL] Auto tunnel launch error: {_tfe}", flush=True)
    print(f"[CONFIG] Public URL: {PUBLIC_URL or '(none — cookie page unavailable)'}", flush=True)
    print("[BOT] Telegram se connect ho raha hai…", flush=True)
    bot.start()
    print("[BOT] ✅ Telegram connected!", flush=True)
    try:
        _me = bot.get_me()
        if _me and _me.username:
            os.environ["BOT_USERNAME"] = _me.username
    except Exception:
        pass
    # Load admins from DB and merge with env-var admins
    ADMIN_IDS.add(OWNER_ID)
    for _aid in db.get_admin_ids():
        ADMIN_IDS.add(_aid)
    print(f"[BOT] Admin IDs loaded: {sorted(ADMIN_IDS)}", flush=True)
    # Load global file tag settings from DB
    _tag_cfg = db.get_file_tag_settings()
    FILE_TAG         = _tag_cfg["tag"]
    FILE_TAG_ENABLED = _tag_cfg["enabled"]
    print(f"[BOT] File tag loaded: '{FILE_TAG}' enabled={FILE_TAG_ENABLED}", flush=True)
    emoji_utils.patch_all()
    restore_thumbnails()
    ensure_db_topics()
    threading.Thread(target=_task_watchdog, daemon=True, name="task-watchdog").start()
    threading.Thread(target=_anti_sleep_worker, daemon=True, name="anti-sleep").start()
    threading.Thread(target=send_restart_notifications, daemon=True, name="restart-notify").start()
    # Auto-start FTM client if session string is saved in DB
    import asyncio
    def _init_ftm():
        try:
            fc = get_ftm_client()
            if fc:
                try:
                    me = fc.get_me()
                    print(f"[FTM] Connected as {me.first_name} (id={me.id}, premium={getattr(me, 'is_premium', False)})", flush=True)
                except Exception as e:
                    print(f"[FTM] get_me() failed: {e}", flush=True)
            else:
                print("[FTM] No session saved — large file route inactive", flush=True)
        except Exception as e:
            print(f"[FTM] Init error: {e}", flush=True)
    threading.Thread(target=_init_ftm, daemon=True, name="ftm-init").start()
    print("✅ Bot chal raha hai! Telegram pe message karein.", flush=True)
    try:
        while True:
            try:
                pyrogram_idle()
            except (KeyboardInterrupt, SystemExit):
                break
            except Exception as e:
                pass
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        print("\n[BOT] Shutting down...", flush=True)
    finally:
        stop_ftm_client()
        try:
            bot.stop()
        except Exception:
            pass
