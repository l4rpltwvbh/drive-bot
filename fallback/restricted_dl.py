"""
restricted_dl.py — Two extra methods for downloading private/restricted Google Drive files
WITHOUT any external paid API.

Method 1: googleapis.com?alt=media  (direct authenticated download)
  - Uses SAPISIDHASH computed from SAPISID cookie (same as Drive web UI)
  - Works for files shared with the logged-in account (restricted shared + private)
  - Returns a streaming response iterator — caller writes to disk

Method 2: yt-dlp  (most powerful, for videos)
  - yt-dlp natively supports Google Drive
  - Extracts adaptive video+audio stream URLs even for download-disabled files
  - Passes cookies as a Netscape-format temp file
  - Returns (video_url, audio_url, title, headers) tuple — caller downloads

Both methods raise RuntimeError on failure with a descriptive message.
"""

import os
import re
import time
import json
import hashlib
import tempfile
import threading
import requests

# ── Cookie helpers ─────────────────────────────────────────────────────────────

def _cookies_to_header(cookies) -> str:
    if not cookies:
        return ""
    if isinstance(cookies, str):
        return cookies.strip()
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _cookies_to_dict(cookies) -> dict:
    if not cookies:
        return {}
    if isinstance(cookies, dict):
        return cookies
    out = {}
    for part in cookies.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# ── SAPISIDHASH ────────────────────────────────────────────────────────────────

def _compute_sapisidhash(sapisid: str, origin: str = "https://www.googleapis.com") -> str:
    ts   = int(time.time())
    data = f"{ts} {sapisid} {origin}"
    sha1 = hashlib.sha1(data.encode("utf-8")).hexdigest()
    return f"SAPISIDHASH {ts}_{sha1}"


# ══════════════════════════════════════════════════════════════════════════════
# METHOD 1 — googleapis.com?alt=media  (direct authenticated download)
# ══════════════════════════════════════════════════════════════════════════════

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def googleapis_get_info(file_id: str, cookies) -> dict:
    """
    Fetch file metadata via Drive API v3 (no API key — uses cookie auth).
    Returns dict with: name, mimeType, size, id
    Raises RuntimeError on failure.
    """
    cookie_dict = _cookies_to_dict(cookies)
    sapisid = (
        cookie_dict.get("SAPISID")
        or cookie_dict.get("__Secure-1PAPISID")
        or cookie_dict.get("__Secure-3PAPISID")
        or ""
    )
    headers = {
        "User-Agent": _UA,
        "Cookie":     _cookies_to_header(cookies),
        "Referer":    "https://drive.google.com/",
        "Origin":     "https://drive.google.com",
        "X-Origin":   "https://drive.google.com",
    }
    if sapisid:
        headers["Authorization"] = _compute_sapisidhash(
            sapisid, origin="https://www.googleapis.com"
        )

    resp = requests.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"fields": "id,name,mimeType,size,shortcutDetails"},
        headers=headers,
        timeout=15,
    )
    if resp.status_code == 401:
        raise RuntimeError("googleapis info: 401 — cookies expired ya invalid hain")
    if resp.status_code == 403:
        raise RuntimeError("googleapis info: 403 — is file ka access nahi hai")
    if resp.status_code == 404:
        raise RuntimeError("googleapis info: 404 — file nahi mili ya delete ho gayi")
    if resp.status_code != 200:
        raise RuntimeError(f"googleapis info: HTTP {resp.status_code}")

    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"googleapis info error: {data['error'].get('message', data['error'])}")

    # Resolve shortcut to real file
    if data.get("mimeType") == "application/vnd.google-apps.shortcut":
        target = data.get("shortcutDetails", {}).get("targetId")
        if target:
            print(f"[GOOGLEAPIS] Shortcut resolved: {file_id} → {target}")
            return googleapis_get_info(target, cookies)

    return data


def googleapis_download_url(file_id: str, cookies) -> tuple:
    """
    Build an authenticated direct-download URL via googleapis.com?alt=media.
    Tries both cookie-based auth and export for Google Workspace docs.

    Returns (download_url, headers_dict, file_info_dict).
    Raises RuntimeError on failure.
    """
    cookie_dict = _cookies_to_dict(cookies)
    sapisid = (
        cookie_dict.get("SAPISID")
        or cookie_dict.get("__Secure-1PAPISID")
        or cookie_dict.get("__Secure-3PAPISID")
        or ""
    )

    headers = {
        "User-Agent": _UA,
        "Cookie":     _cookies_to_header(cookies),
        "Referer":    "https://drive.google.com/",
        "Origin":     "https://drive.google.com",
        "X-Origin":   "https://drive.google.com",
    }
    if sapisid:
        headers["Authorization"] = _compute_sapisidhash(
            sapisid, origin="https://www.googleapis.com"
        )

    # Step 1: Get file info
    try:
        info = googleapis_get_info(file_id, cookies)
    except RuntimeError:
        raise

    mime = info.get("mimeType", "")
    name = info.get("name", f"drive_file_{file_id}")

    # Google Workspace docs can't be downloaded as-is — use export
    EXPORT_MAP = {
        "application/vnd.google-apps.document":     ("application/pdf", "pdf"),
        "application/vnd.google-apps.spreadsheet":  ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
        "application/vnd.google-apps.presentation": ("application/pdf", "pdf"),
        "application/vnd.google-apps.drawing":      ("application/pdf", "pdf"),
    }
    if mime in EXPORT_MAP:
        export_mime, export_ext = EXPORT_MAP[mime]
        dl_url = (
            f"https://www.googleapis.com/drive/v3/files/{file_id}/export"
            f"?mimeType={export_mime}"
        )
        if not name.endswith(f".{export_ext}"):
            name = os.path.splitext(name)[0] + f".{export_ext}"
    else:
        dl_url = (
            f"https://www.googleapis.com/drive/v3/files/{file_id}"
            f"?alt=media&acknowledgeAbuse=true"
        )

    # Step 2: Verify the URL actually gives us a download (HEAD check)
    try:
        head = requests.head(
            dl_url, headers=headers,
            allow_redirects=True, timeout=15,
        )
        ct = head.headers.get("content-type", "")
        if head.status_code == 200 and not ct.startswith("text/html"):
            print(f"[GOOGLEAPIS] Direct download OK: {name} ({ct})")
            info["name"] = name
            return dl_url, headers, info
        # If redirected to HTML, it means auth failed
        if head.status_code in (401, 403):
            raise RuntimeError(f"googleapis HEAD: {head.status_code} — access denied")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"googleapis HEAD check failed: {e}")

    # Step 3: Try usercontent.google.com as alternate route
    uc_url = (
        f"https://drive.usercontent.google.com/download"
        f"?id={file_id}&export=download&authuser=0&confirm=t"
    )
    uc_headers = dict(headers)
    uc_headers["Authorization"] = _compute_sapisidhash(
        sapisid, origin="https://drive.usercontent.google.com"
    ) if sapisid else ""

    try:
        head2 = requests.head(
            uc_url, headers=uc_headers,
            allow_redirects=True, timeout=15,
        )
        ct2 = head2.headers.get("content-type", "")
        if head2.status_code == 200 and not ct2.startswith("text/html"):
            print(f"[GOOGLEAPIS] usercontent download OK: {name} ({ct2})")
            info["name"] = name
            return uc_url, uc_headers, info
    except requests.exceptions.RequestException:
        pass

    raise RuntimeError(
        "googleapis: dono routes (googleapis.com + usercontent) se download nahi hua. "
        "Cookies expired ho sakti hain ya file ka access nahi hai."
    )


def googleapis_stream_download(
    file_id: str,
    cookies,
    out_path: str,
    progress_cb=None,
    cancel_event: threading.Event = None,
) -> int:
    """
    Download a restricted Drive file via googleapis.com?alt=media.
    Writes to out_path. Returns bytes written.
    progress_cb(downloaded_bytes, total_bytes, speed_bps) called periodically.
    Raises RuntimeError on failure.
    """
    dl_url, headers, info = googleapis_download_url(file_id, cookies)
    name = info.get("name", "file")
    print(f"[GOOGLEAPIS] Streaming download: {name} → {out_path}")

    sess = requests.Session()
    resp = sess.get(dl_url, headers=headers, stream=True,
                    allow_redirects=True, timeout=(15, 120))

    if resp.status_code not in (200, 206):
        raise RuntimeError(f"googleapis stream: HTTP {resp.status_code}")

    ct = resp.headers.get("content-type", "")
    if ct.startswith("text/html"):
        raise RuntimeError(
            "googleapis stream: HTML response — cookies expired ya access nahi hai"
        )

    total = int(resp.headers.get("content-length", 0))
    done  = 0
    t0    = time.time()
    t_last = t0

    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=2 * 1024 * 1024):
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("googleapis: download cancelled")
            if not chunk:
                continue
            f.write(chunk)
            done += len(chunk)
            now = time.time()
            if progress_cb and now - t_last >= 1.5:
                speed = done / max(now - t0, 0.001)
                progress_cb(done, total, speed)
                t_last = now

    print(f"[GOOGLEAPIS] Done: {done // 1024} KB written to {out_path}")
    return done


# ══════════════════════════════════════════════════════════════════════════════
# METHOD 2 — yt-dlp  (best for videos, extracts stream URLs)
# ══════════════════════════════════════════════════════════════════════════════

def _write_netscape_cookies(cookies) -> str:
    """
    Write cookies to a Netscape-format temp file for yt-dlp.
    Returns path to the temp file.
    """
    cookie_dict = _cookies_to_dict(cookies)
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="ytdlp_cookies_")
    with os.fdopen(fd, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write("# This is a generated file. Do not edit.\n\n")
        for name, value in cookie_dict.items():
            # domain  flag  path  secure  expiry  name  value
            f.write(f".google.com\tTRUE\t/\tTRUE\t9999999999\t{name}\t{value}\n")
    return path


def ytdlp_get_streams(
    file_id: str,
    cookies,
    status_cb=None,
) -> dict:
    """
    Use yt-dlp to extract video/audio stream URLs for a Google Drive file.
    Works even for download-disabled/restricted videos.

    Returns dict:
    {
        "video_url":  str or None,
        "audio_url":  str or None,
        "title":      str,
        "ext":        str,        # e.g. "mp4"
        "requires_merge": bool,
        "headers":    dict,       # headers to send when downloading
        "formats":    list,       # full yt-dlp format list (for debug)
    }
    Raises RuntimeError on failure.
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp not installed — pip install yt-dlp")

    def _cb(msg):
        if status_cb:
            try: status_cb(msg)
            except Exception: pass

    drive_url = f"https://drive.google.com/file/d/{file_id}/view"
    cookie_path = None

    try:
        cookie_path = _write_netscape_cookies(cookies)
        _cb("🔍 yt-dlp se stream URLs extract ho rahi hain…")

        ydl_opts = {
            "quiet":          True,
            "no_warnings":    True,
            "cookiefile":     cookie_path,
            "extract_flat":   False,
            "skip_download":  True,
            "format":         "bestvideo+bestaudio/best",
            "noplaylist":     True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(drive_url, download=False)

        if not info:
            raise RuntimeError("yt-dlp: koi info nahi mili")

        title    = info.get("title", f"drive_{file_id}")
        ext      = info.get("ext", "mp4")
        formats  = info.get("formats", [])

        # Find best video-only and audio-only formats
        v_formats = [f for f in formats if f.get("vcodec") != "none" and f.get("acodec") == "none"]
        a_formats = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]
        mux_formats = [f for f in formats if f.get("vcodec") != "none" and f.get("acodec") != "none"]

        # Sort by quality (height for video, abr for audio)
        v_formats.sort(key=lambda f: (f.get("height") or 0), reverse=True)
        a_formats.sort(key=lambda f: (f.get("abr") or 0), reverse=True)
        mux_formats.sort(key=lambda f: (f.get("height") or 0), reverse=True)

        video_url = None
        audio_url = None
        requires_merge = False

        if v_formats and a_formats:
            video_url = v_formats[0].get("url")
            audio_url = a_formats[0].get("url")
            requires_merge = True
            _cb(f"✅ yt-dlp: separate video+audio streams mili! "
                f"({v_formats[0].get('height', '?')}p / {a_formats[0].get('abr', '?')}kbps)")
        elif mux_formats:
            video_url = mux_formats[0].get("url")
            requires_merge = False
            _cb(f"✅ yt-dlp: muxed stream mili ({mux_formats[0].get('height', '?')}p)")
        elif formats:
            video_url = formats[0].get("url")
            requires_merge = False
            _cb("✅ yt-dlp: generic stream mili")
        else:
            raise RuntimeError("yt-dlp: koi stream URL nahi mili formats mein")

        if not video_url:
            raise RuntimeError("yt-dlp: video URL empty hai")

        # Common headers yt-dlp needs when downloading these URLs
        http_headers = info.get("http_headers", {})
        if cookies:
            http_headers["Cookie"] = _cookies_to_header(cookies)

        print(f"[YTDLP] Streams extracted: video={bool(video_url)} "
              f"audio={bool(audio_url)} merge={requires_merge} title={title!r}")

        return {
            "video_url":      video_url,
            "audio_url":      audio_url,
            "title":          title,
            "ext":            ext,
            "requires_merge": requires_merge,
            "headers":        http_headers,
            "formats":        formats,
        }

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"yt-dlp extraction failed: {e}")
    finally:
        if cookie_path and os.path.exists(cookie_path):
            try: os.unlink(cookie_path)
            except Exception: pass


def ytdlp_is_available() -> bool:
    """Check if yt-dlp is importable."""
    try:
        import yt_dlp
        return True
    except ImportError:
        return False
