"""
stream_capture.py — Google Drive video stream URL capture.

Primary method: get_video_info API (requests-based, fast, ~1-2s).
  - Calls drive.google.com/get_video_info with user cookies.
  - Parses player_response.streamingData.adaptiveFormats for best video+audio.
  - Falls back to fmt_stream_map muxed URL if adaptive not available.

Fallback method: Playwright browser capture (if API fails).
  - Opens Drive preview, injects cookies, forces play, intercepts network.
  - Detects any URL with videoplayback, mime=video/*, mime=audio/*,
    Content-Type: video/*, audio/*, c.drive.google.com, googlevideo.com.

After capture, always apply strip_drive_range_from_url() before downloading.
"""
import os
import re
import time
import json
import glob as _glob
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qsl

import requests as _requests

# ── Chromium path for Playwright fallback ────────────────────────────────────
_chromium_candidates = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/nix/store/qa9cnw4v5xkxyip6mb9kxqfq1z4x2dx1-chromium-138.0.7204.100/bin/chromium",
    "/home/runner/workspace/.cache/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-linux64/chrome-headless-shell",
    "/home/runner/workspace/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome",
    "/nix/store/kcvsxrmgwp3ffz5jijyy7wn9fcsjl4hz-playwright-browsers-1.55.0-with-cjk/chromium-1187/chrome-linux/chrome",
]
_chromium_candidates += _glob.glob(os.path.expanduser(
    "~/.cache/ms-playwright/chromium_headless_shell*/chrome-headless-shell-linux64/chrome-headless-shell"))
_chromium_candidates += _glob.glob(os.path.expanduser(
    "~/.cache/ms-playwright/chromium*/chrome-linux64/chrome"))
_chromium_candidates += _glob.glob(os.path.expanduser(
    "~/.cache/ms-playwright/chromium*/chrome-linux/chrome"))
CHROMIUM = next((p for p in _chromium_candidates if os.path.exists(p)), None)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Video itag priority (higher quality first), then common Drive itags
VIDEO_ITAGS = [
    266, 264, 299, 137, 248, 298, 136, 247,
    135, 246, 245, 244, 134, 243, 133, 242,
    160, 278, 22, 18,
]
AUDIO_ITAGS = [251, 250, 249, 140, 141, 139]


@dataclass
class CapturedStreams:
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    headers: dict = field(default_factory=dict)
    method: str = "unknown"   # "api" or "playwright"
    title: Optional[str] = None


def _parse_itag(url: str) -> Optional[int]:
    m = re.search(r"[?&]itag=(\d+)", url)
    return int(m.group(1)) if m else None


def _mime_from_url(url: str) -> str:
    m = re.search(r"[?&]mime=([^&]+)", url)
    return m.group(1).replace("%2F", "/").lower() if m else ""


# ─────────────────────────────────────────────────────────────────────────────
# Method 1: Workspace Playback API (Modern Drive API, fast, supports view-only)
# ─────────────────────────────────────────────────────────────────────────────

def _get_streams_via_workspace_api(file_id: str, cookie_hdr: str) -> tuple:
    """
    Directly query Google Workspace video playback API with SAPISIDHASH.
    Works for all Google Drive videos, including view-only / download-disabled videos.
    Returns (video_url, audio_url, title).
    """
    import hashlib
    cookies = {}
    if isinstance(cookie_hdr, dict):
        cookies = dict(cookie_hdr)
        cookie_hdr = "; ".join(f"{k}={v}" for k, v in cookies.items())
    elif isinstance(cookie_hdr, str):
        c_str_clean = cookie_hdr.strip()
        if c_str_clean.startswith("{") or c_str_clean.startswith("["):
            try:
                parsed = json.loads(c_str_clean)
                arr = parsed.get("cookies", []) if isinstance(parsed, dict) else parsed
                for item in arr:
                    if isinstance(item, dict) and item.get("name"):
                        cookies[item["name"]] = item.get("value", "")
                cookie_hdr = "; ".join(f"{k}={v}" for k, v in cookies.items())
            except Exception:
                pass
        if not cookies:
            for part in cookie_hdr.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    cookies[k.strip()] = v.strip()

    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-1PAPISID") or ""
    origin = "https://drive.google.com"
    ts = int(time.time())
    sha1 = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    auth_hdr = f"SAPISIDHASH {ts}_{sha1}"

    url = (
        f"https://workspacevideo-pa.clients6.google.com/v1/drive/media/{file_id}/playback"
        "?auditContext=forDisplay&key=AIzaSyDVQw45DwoYh632gvsP5vPDqEKvb-Ywnb8"
    )
    hdrs = {
        "User-Agent": _UA,
        "Origin": origin,
        "Referer": f"https://drive.google.com/file/d/{file_id}/view",
        "Cookie": cookie_hdr,
        "Authorization": auth_hdr,
        "X-Goog-AuthUser": "0",
    }
    resp = _requests.get(url, headers=hdrs, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    sb = data.get("mediaStreamingData", {}).get("serializedHouseBrandPlayerResponse", "")
    if not sb:
        raise RuntimeError("No streaming data in workspace playback response")

    pr = json.loads(sb)
    streaming_data = pr.get("streamingData", {})
    formats = streaming_data.get("formats", [])
    adaptive = streaming_data.get("adaptiveFormats", [])

    video_url = None
    audio_url = None
    title = pr.get("videoDetails", {}).get("title")

    # Muxed formats (already have audio + video merged) - sort by height descending (e.g. 720p > 360p)
    muxed = [f for f in formats if f.get("url")]
    muxed.sort(key=lambda x: int(x.get("height", 0)), reverse=True)
    if muxed:
        video_url = muxed[0]["url"]

    # If adaptive is needed or if no muxed
    if not video_url:
        v_candidates = []
        a_candidates = []
        for fmt in adaptive:
            u = fmt.get("url", "")
            mime = fmt.get("mimeType", "")
            itag = fmt.get("itag", 0)
            if not u:
                continue
            if mime.startswith("video/"):
                rank = VIDEO_ITAGS.index(itag) if itag in VIDEO_ITAGS else 999
                v_candidates.append((rank, u))
            elif mime.startswith("audio/"):
                rank = AUDIO_ITAGS.index(itag) if itag in AUDIO_ITAGS else 999
                a_candidates.append((rank, u))

        v_candidates.sort(key=lambda x: x[0])
        a_candidates.sort(key=lambda x: x[0])
        if v_candidates:
            video_url = v_candidates[0][1]
        if a_candidates:
            audio_url = a_candidates[0][1]

    if not video_url:
        raise RuntimeError("No stream URL found in workspace streamingData")

    return video_url, audio_url, title


# ─────────────────────────────────────────────────────────────────────────────
# Legacy get_video_info API fallback
# ─────────────────────────────────────────────────────────────────────────────

def _get_streams_via_api(file_id: str, cookie_hdr: str) -> tuple:
    """
    Returns (video_url, audio_url, title) or raises on failure.
    Tries modern workspacevideo-pa API first, then falls back to legacy get_video_info.
    """
    try:
        return _get_streams_via_workspace_api(file_id, cookie_hdr)
    except Exception as w_err:
        pass

    hdrs = {"User-Agent": _UA, "Cookie": cookie_hdr,
            "Referer": "https://drive.google.com/"}

    resp = _requests.get(
        "https://drive.google.com/get_video_info",
        params={"docid": file_id, "sle": "true"},
        headers=hdrs, timeout=20,
    )
    resp.raise_for_status()
    raw = resp.text

    data = dict(parse_qsl(raw))
    status = data.get("status", "")
    if status == "fail":
        reason = data.get("reason", "unknown")
        raise RuntimeError(f"get_video_info fail: {reason}")

    # ── Try adaptiveFormats from player_response ──────────────────────────
    pr_raw = data.get("player_response", "")
    video_url = None
    audio_url = None

    if pr_raw:
        try:
            pr = json.loads(pr_raw)
            adaptive = pr.get("streamingData", {}).get("adaptiveFormats", [])
            formats  = pr.get("streamingData", {}).get("formats", [])

            # Collect all candidates
            v_candidates = []
            a_candidates = []
            muxed_candidates = []

            for fmt in adaptive + formats:
                url  = fmt.get("url", "")
                mime = fmt.get("mimeType", "")
                itag = fmt.get("itag", 0)
                if not url:
                    continue
                if mime.startswith("video/"):
                    rank = VIDEO_ITAGS.index(itag) if itag in VIDEO_ITAGS else 999
                    v_candidates.append((rank, url))
                elif mime.startswith("audio/"):
                    rank = AUDIO_ITAGS.index(itag) if itag in AUDIO_ITAGS else 999
                    a_candidates.append((rank, url))
                else:
                    muxed_candidates.append(url)

            v_candidates.sort(key=lambda x: x[0])
            a_candidates.sort(key=lambda x: x[0])

            video_url = v_candidates[0][1]  if v_candidates  else None
            audio_url = a_candidates[0][1]  if a_candidates  else None

            # If no separate video found, use muxed
            if not video_url and muxed_candidates:
                video_url = muxed_candidates[0]

        except Exception:
            pass

    # ── Fallback: fmt_stream_map ──────────────────────────────────────────
    if not video_url:
        for entry in data.get("fmt_stream_map", "").split(","):
            if "|" in entry:
                _, url = entry.split("|", 1)
                video_url = url.strip()
                break

    if not video_url:
        raise RuntimeError("No stream URL found in get_video_info response")

    # ── Extract title ─────────────────────────────────────────────────────
    # Priority 1: videoDetails.title inside player_response
    title = None
    if pr_raw:
        try:
            _pr = json.loads(pr_raw)
            title = _pr.get("videoDetails", {}).get("title") or None
        except Exception:
            pass

    # Priority 2: top-level 'title' field in the get_video_info response
    # (Drive puts the real filename here, e.g. "Day 3 - Meeting.mp4")
    if not title:
        title = data.get("title") or None

    return video_url, audio_url, title


# ─────────────────────────────────────────────────────────────────────────────
# Method 2: Playwright browser capture  (slower but broader)
# ─────────────────────────────────────────────────────────────────────────────

def _is_stream_url(url: str, content_type: str = "") -> bool:
    if "videoplayback" in url:      return True
    if "c.drive.google.com" in url: return True
    if "googlevideo.com" in url:    return True
    mime = _mime_from_url(url)
    if mime.startswith(("video/", "audio/")): return True
    ct = (content_type or "").lower()
    if ct.startswith(("video/", "audio/")):   return True
    return False


def _classify_url(url: str) -> str:
    itag = _parse_itag(url)
    if itag in VIDEO_ITAGS: return "video"
    if itag in AUDIO_ITAGS: return "audio"
    mime = _mime_from_url(url)
    if mime.startswith("audio/"): return "audio"
    if mime.startswith("video/"): return "video"
    return "muxed"


def _get_streams_via_playwright(
    file_id: str,
    cookie_hdr: str,
    status_cb=None,
    timeout_s: int = 120,
) -> tuple:
    """
    Opens Drive preview in Playwright, clicks play, intercepts stream URLs.
    Returns (video_url, audio_url) or raises on failure.
    """
    if not CHROMIUM:
        raise RuntimeError("Chromium not found — run: playwright install chromium")

    from playwright.sync_api import sync_playwright

    seen: dict = {}   # url → classification

    def _trigger_play(page):
        for frame in page.frames:
            try:
                frame.evaluate("""
                    Array.from(document.querySelectorAll('video')).forEach(v => {
                        try { v.muted = false; v.currentTime = 0; v.play(); } catch(e) {}
                    });
                """)
            except Exception:
                pass
            for sel in [".ytp-play-button", "button[aria-label*='Play']",
                        "button[aria-label*='play']", "[data-testid*='play']", "video"]:
                try:
                    frame.click(sel, timeout=800)
                except Exception:
                    pass

    def _cb(msg):
        if status_cb:
            try: status_cb(msg)
            except Exception: pass

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=CHROMIUM, headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--disable-blink-features=AutomationControlled",
                  "--autoplay-policy=no-user-gesture-required",
                  "--disable-web-security"],
        )
        ctx = browser.new_context(
            user_agent=_UA, viewport={"width": 1280, "height": 720},
            extra_http_headers={"Cookie": cookie_hdr, "Accept-Language": "en-US,en;q=0.9"},
        )

        page = ctx.new_page()

        def _on_request(req):
            if _is_stream_url(req.url):
                seen[req.url] = _classify_url(req.url)

        def _on_response(resp):
            try: ct = resp.headers.get("content-type", "")
            except Exception: ct = ""
            if _is_stream_url(resp.url, ct):
                seen[resp.url] = _classify_url(resp.url)

        page.on("request",  _on_request)
        page.on("response", _on_response)

        _cb("📂 Drive preview open ho raha hai…")
        try:
            page.goto(
                f"https://drive.google.com/file/d/{file_id}/preview",
                timeout=30_000, wait_until="domcontentloaded",
            )
        except Exception:
            pass

        # Wait for video player iframe
        for _ in range(20):
            time.sleep(1)
            if any("youtube" in f.url or "googleapis.com/embed" in f.url
                   or "usercontent.google.com" in f.url for f in page.frames):
                break

        _cb("▶️ Play trigger ho raha hai…")
        _trigger_play(page)

        _cb("📡 Stream URLs capture ho rahi hain…")
        deadline  = time.time() + timeout_s
        last_trig = time.time()

        while time.time() < deadline:
            time.sleep(1.5)
            if time.time() - last_trig > 10:
                _trigger_play(page)
                last_trig = time.time()

            videos = [u for u, c in seen.items() if c in ("video", "muxed")]
            audios  = [u for u, c in seen.items() if c == "audio"]
            if videos and audios:
                break
            if videos and (deadline - time.time() < 10):
                break

        try: browser.close()
        except Exception: pass

    v_cands = sorted(
        [(VIDEO_ITAGS.index(_parse_itag(u)) if _parse_itag(u) in VIDEO_ITAGS else 999, u)
         for u, c in seen.items() if c in ("video", "muxed")]
    )
    a_cands = sorted(
        [(AUDIO_ITAGS.index(_parse_itag(u)) if _parse_itag(u) in AUDIO_ITAGS else 999, u)
         for u, c in seen.items() if c == "audio"]
    )

    video_url = v_cands[0][1] if v_cands else None
    audio_url = a_cands[0][1] if a_cands else None

    if not video_url:
        raise RuntimeError(
            "Playwright: koi stream nahi mila. "
            "Google login expired ho sakta hai — /login ya /gcookies."
        )
    return video_url, audio_url


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def capture_drive_video_streams(
    file_id: str,
    cookies: dict,
    status_cb=None,
    timeout_s: int = 120,
) -> CapturedStreams:
    """
    Capture Google Drive video+audio stream URLs.
    Tries API method first (fast), falls back to Playwright if needed.

    Returns CapturedStreams with video_url (always set) and optional audio_url.
    Raises RuntimeError if no stream found.
    """
    def _cb(msg):
        if status_cb:
            try: status_cb(msg)
            except Exception: pass

    cookie_hdr = "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())
    result = CapturedStreams()
    result.headers = {
        "User-Agent": _UA,
        "Referer":    "https://drive.google.com/",
        "Cookie":     cookie_hdr,
    }

    # ── Method 1: get_video_info API ──────────────────────────────────────
    _cb("🔍 Drive stream API se URLs fetch ho rahi hain…")
    try:
        v_url, a_url, api_title = _get_streams_via_api(file_id, cookie_hdr)
        result.video_url = v_url
        result.audio_url = a_url
        result.method    = "api"
        result.title     = api_title
        _aud_label = "✅ (Separate)" if a_url else "✅ (Inbuilt MP4)"
        _cb(f"✅ API se streams mile! (video=✅ audio={_aud_label})")
        return result
    except Exception as api_err:
        _cb(f"⚠️ API fail hua ({api_err}), Playwright try ho raha hai…")

    # ── Method 2: Playwright fallback ─────────────────────────────────────
    _cb("🎭 Browser launch ho raha hai (fallback)…")
    try:
        v_url, a_url = _get_streams_via_playwright(
            file_id, cookie_hdr, status_cb=_cb, timeout_s=timeout_s
        )
        result.video_url = v_url
        result.audio_url = a_url
        result.method    = "playwright"
        return result
    except Exception as pw_err:
        raise RuntimeError(
            f"Dono methods fail ho gaye.\n"
            f"API: {api_err}\n"
            f"Playwright: {pw_err}"
        )
