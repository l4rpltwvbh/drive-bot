"""
ftm_drive_fallback.py — Google Drive video fallback.

Triggered when CDN download fails (404/403/size=0).
Uses saved Google cookies to capture real video/audio stream URLs,
downloads in parallel (8MB chunks, 8 workers), merges, uploads to Telegram.

Fully respects user settings:
  - upload_type  (video / document)
  - thumb_type   (auto / custom / none)
  - caption_template
  - draw_upload_card style progress bar
  - filename: <drive_title>@ftmbotzx.<ext>
"""
import os
import re
import math
import html
import datetime
import itertools
import subprocess
import shutil
import tempfile
import time

import db as _db

from fallback.naming import make_ftm_output_name
from fallback.stream_capture import capture_drive_video_streams
from fallback.parallel_downloader import (
    download_video_audio_parallel,
    strip_drive_range_from_url,
    clean_captured_headers,
)
from fallback.merge_media import merge_video_audio
from fallback.restricted_dl import (
    ytdlp_get_streams,
    ytdlp_is_available,
    googleapis_stream_download,
    googleapis_get_info,
)

DOWNLOADS_DIR = "downloads"

# ── Spinner ───────────────────────────────────────────────────────────────────
_SPINNER = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
def _spin(): return next(_SPINNER)

# ── HTML escape ───────────────────────────────────────────────────────────────
def _h(s): return html.escape(str(s))

# ── Format helpers ────────────────────────────────────────────────────────────
def _fmt_size(n):
    if n < 1024:        return f"{n:.0f} B"
    if n < 1024**2:     return f"{n/1024:.2f} KB"
    if n < 1024**3:     return f"{n/1024**2:.2f} MB"
    return f"{n/1024**3:.2f} GB"

def _fmt_speed(bps):
    if bps < 1024**2:
        return f"{bps/1024:.2f} KB/s" if bps >= 1024 else f"{bps:.0f} B/s"
    return f"{bps/1024**2:.2f} MB/s"

def _fmt_eta(sec):
    if sec <= 0 or not math.isfinite(sec): return "∞"
    sec = int(sec)
    if sec < 60:   return f"{sec}s"
    if sec < 3600: m, s = divmod(sec, 60); return f"{m}m {s}s"
    h_, r = divmod(sec, 3600); m, s = divmod(r, 60); return f"{h_}h {m}m {s}s"

def _fmt_elapsed(sec):
    sec = int(sec)
    if sec < 60:   return f"{sec}s"
    if sec < 3600: m, s = divmod(sec, 60); return f"{m}m {s}s"
    h_, r = divmod(sec, 3600); m, s = divmod(r, 60); return f"{h_}h {m}m {s}s"

def _fmt_pct(done, total):
    return f"{done/total*100:.1f}%" if total > 0 else _fmt_size(done)

def _sys_stats():
    cpu, ram = 0.0, 0.0
    try:
        if os.path.exists("/proc/stat") and os.path.exists("/proc/meminfo"):
            with open("/proc/stat") as f:
                v = list(map(float, f.readline().split()[1:]))
                idle, total = v[3] + (v[4] if len(v) > 4 else 0), sum(v)
            time.sleep(0.05)
            with open("/proc/stat") as f:
                v2 = list(map(float, f.readline().split()[1:]))
                idle2, total2 = v2[3] + (v2[4] if len(v2) > 4 else 0), sum(v2)
            td = total2 - total
            cpu = 100.0 * (td - (idle2 - idle)) / td if td else 0.0
            mt = ma = 0
            with open("/proc/meminfo") as f:
                for ln in f:
                    if ln.startswith("MemTotal:"):     mt = int(ln.split()[1])
                    elif ln.startswith("MemAvailable:"): ma = int(ln.split()[1])
            if mt: ram = 100.0 * (mt - ma) / mt
    except Exception:
        pass
    return round(cpu, 1), round(ram, 1)

def _draw_upload_card(title, file_size, uploaded, speed, elapsed, eta,
                      cpu, ram, file_index=1, total_files=1):
    bar_width = 20
    pct  = uploaded / file_size if file_size > 0 else 0
    bar  = "█" * int(bar_width * pct) + "░" * (bar_width - int(bar_width * pct))
    t    = (title[:28] + "…") if len(title) > 31 else title
    idx  = f"  [{file_index}/{total_files}]" if total_files > 1 else ""
    spin = _spin()
    remaining = _fmt_size(max(0, file_size - uploaded))
    return (
        f"<pre>"
        f"╭━━━━━〔 {spin} 📤 UPLOADING{idx} 〕━━━━━╮\n"
        f"│  📄 {t}\n"
        f"│\n"
        f"│  [{bar}]  {pct*100:.1f}%\n"
        f"│  📦 {_fmt_size(uploaded)} / {_fmt_size(file_size)}\n"
        f"│  📉 Remaining: {remaining}\n"
        f"│\n"
        f"│  ⚡️ Speed  : {_fmt_speed(speed)}\n"
        f"│  ⏱️ Elapsed: {_fmt_elapsed(elapsed)}\n"
        f"│  ⏳ ETA    : {_fmt_eta(eta)}\n"
        f"│  💻 CPU: {cpu:.1f}%   RAM: {ram:.1f}%\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
        f"</pre>"
    )

# ── Filename helpers ──────────────────────────────────────────────────────────
def _clean_name(name: str) -> str:
    name = name.replace("+", " ")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"[. ]+$", "", name)
    return name or "video"

def _resolve_filename(original_filename, streams_title, file_id) -> tuple:
    """
    Returns (display_name_no_ext, ext) where:
      display_name_no_ext = clean title for captions / status bar
      ext                 = file extension with dot (e.g. ".mp4")
    Priority: hint with ext → streams.title (API returns full filename with ext) → drive_{id}
    """
    ext = ".mp4"   # fallback; we always produce mp4 from merge

    if original_filename:
        base = os.path.basename(original_filename)
        name_part, ext_part = os.path.splitext(base)
        name_part = _clean_name(name_part)
        if ext_part:
            ext = ext_part.lower()
        if name_part and name_part.lower() not in ("drive_video", "video", "file"):
            return name_part, ext

    if streams_title and streams_title.strip():
        raw = streams_title.strip()
        # Drive API returns the real filename including extension (e.g. "Meeting.mp4")
        # Extract extension if present so it doesn't end up in the display name
        name_part, ext_part = os.path.splitext(raw)
        if ext_part and 2 <= len(ext_part) <= 6:
            t = _clean_name(name_part)
            resolved_ext = ext_part.lower()
        else:
            t = _clean_name(raw)
            resolved_ext = ext
        if t and t.lower() not in ("drive_video", "video", "file"):
            return t, resolved_ext

    return f"drive_{file_id[:8]}", ext

# ── Caption builder (mirrors bot.py _render_caption + _do_upload) ─────────────
def _render_caption(template, filename, size, file_type, duration, resolution):
    now = datetime.datetime.utcnow()
    replacements = {
        "{filename}":   filename,
        "{size}":       size,
        "{type}":       file_type,
        "{mimetype}":   "",
        "{duration}":   duration,
        "{resolution}": resolution,
        "{date}":       now.strftime("%Y-%m-%d"),
        "{time}":       now.strftime("%H:%M UTC"),
    }
    result_lines = []
    for line in template.split("\n"):
        skip = any(k in line and not v for k, v in replacements.items())
        if not skip:
            for k, v in replacements.items():
                line = line.replace(k, v)
            result_lines.append(line)
    result = "\n".join(result_lines)
    return re.sub(r'\n{3,}', '\n\n', result).strip()

def _build_caption(uid, display_name, file_size, meta, file_type):
    tpl = _db.get_caption_template(uid)
    dur_str = ""
    res_str = ""
    if meta.get("duration"):
        m_, s_ = divmod(meta["duration"], 60)
        dur_str = f"{m_}m {s_:02d}s"
    if meta.get("width") and meta.get("height"):
        res_str = f"{meta['width']}×{meta['height']}"

    if tpl:
        return _render_caption(
            tpl,
            filename=display_name,
            size=_fmt_size(file_size),
            file_type=file_type,
            duration=dur_str,
            resolution=res_str,
        )
    # Default caption
    caption = f"🎬 <b>{_h(display_name)}</b>\n📦 <b>Size:</b> {_fmt_size(file_size)}"
    if dur_str: caption += f"\n⏱ <b>Duration:</b> {dur_str}"
    if res_str: caption += f"\n📐 <b>Resolution:</b> {res_str}"
    return caption

# ── ffprobe / ffmpeg ──────────────────────────────────────────────────────────
def _find_bin(name):
    import shutil as _sh
    found = _sh.which(name)
    if found: return found
    for p in ("/usr/bin", "/usr/local/bin"):
        fp = os.path.join(p, name)
        if os.path.isfile(fp) and os.access(fp, os.X_OK): return fp
    return name

_FFMPEG  = _find_bin("ffmpeg")
_FFPROBE = _find_bin("ffprobe")

def _get_video_meta(path):
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

def _gen_thumbnail(video_path, out, duration=0):
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

# ── Main entry point ──────────────────────────────────────────────────────────
def ftm_drive_fallback(
    client,
    message,
    uid: int,
    file_id: str,
    cookies: dict,
    original_filename: str = None,
    status_msg=None,
    file_index: int = 1,
    total: int = 1,
    cancel_fn=None,
    thumb_type: str = "auto",
    custom_thumb_path: str = None,
    post_send_fn=None,
):
    from pyrogram import enums
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    CANCEL_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Cancel", callback_data="cancel")]])
    DONE_KB   = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️  Settings", callback_data="settings_open")]])

    prefix = f"[{file_index}/{total}] " if total > 1 else ""
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)

    # ── Load user settings ────────────────────────────────────────────────
    try:
        s           = _db.get_settings(uid)
        upload_type = s.get("upload_type", "video")
        tt          = thumb_type   # already resolved by caller from db
    except Exception:
        upload_type = "video"
        tt          = thumb_type

    def _edit(txt, markup=None):
        if not status_msg: return
        try:
            status_msg.edit_text(txt, parse_mode=enums.ParseMode.HTML, reply_markup=markup)
        except Exception: pass

    def _cancelled():
        return bool(cancel_fn and cancel_fn())

    tmp_dir = None
    video_tmp = audio_tmp = output_path = thumb_path = None

    try:
        # ── 1. Capture streams ────────────────────────────────────────────
        _edit(
            f"<b>{prefix}🎭 Fallback Mode Active</b>\n\n"
            f"📄 <b>{_h(original_filename or 'Fetching info…')}</b>\n\n"
            "Drive video stream capture ho raha hai…\n"
            "<i>(30-60 sec lag sakte hain)</i>",
            CANCEL_KB,
        )

        def _status_cb(msg): _edit(f"<b>{prefix}🎭 Fallback:</b> {msg}", CANCEL_KB)

        # ── Try Method 1: get_video_info API + Playwright ──────────────────
        streams        = None
        _stream_err    = None
        _ytdlp_streams = None
        _ytdlp_err     = None

        try:
            streams = capture_drive_video_streams(
                file_id=file_id, cookies=cookies,
                status_cb=_status_cb, timeout_s=120,
            )
            print(f"[FTM_FALLBACK] stream_capture OK for {file_id}")
        except Exception as _sc_err:
            _stream_err = str(_sc_err)
            print(f"[FTM_FALLBACK] stream_capture failed: {_sc_err}")

        # ── Try Method 2: yt-dlp (if stream_capture failed) ───────────────
        if streams is None and ytdlp_is_available():
            _edit(
                f"<b>{prefix}🔄 yt-dlp se try ho raha hai…</b>\n\n"
                f"📄 <b>{_h(original_filename or 'Fetching info…')}</b>\n"
                "<i>Drive streams capture ho rahi hain via yt-dlp…</i>",
                CANCEL_KB,
            )
            try:
                _ytdlp_streams = ytdlp_get_streams(
                    file_id=file_id, cookies=cookies,
                    status_cb=_status_cb,
                )
                print(f"[FTM_FALLBACK] yt-dlp OK for {file_id}: "
                      f"video={bool(_ytdlp_streams.get('video_url'))} "
                      f"audio={bool(_ytdlp_streams.get('audio_url'))}")
            except Exception as _yt_err:
                _ytdlp_err = str(_yt_err)
                print(f"[FTM_FALLBACK] yt-dlp failed: {_yt_err}")

        # ── If both stream methods failed, try googleapis direct download ──
        if streams is None and _ytdlp_streams is None:
            _edit(
                f"<b>{prefix}🌐 googleapis direct download try ho raha hai…</b>\n\n"
                f"📄 <b>{_h(original_filename or 'Fetching info…')}</b>",
                CANCEL_KB,
            )
            tmp_dir     = tempfile.mkdtemp(prefix="ftmfb_", dir="/tmp")
            _gapi_name  = (original_filename or f"drive_{file_id[:8]}.mp4")
            _gapi_clean = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", _gapi_name).strip() or "file"
            _gapi_path  = os.path.join(tmp_dir, _gapi_clean)

            def _gapi_progress(done, total, speed):
                pct = f"{done/total*100:.1f}%" if total else _fmt_size(done)
                _edit(
                    f"<b>{prefix}⬇️ googleapis Download</b>\n\n"
                    f"📄 <b>{_h(_gapi_clean)}</b>\n"
                    f"📦 {_fmt_size(done)} / {_fmt_size(total) if total else '?'} ({pct})\n"
                    f"⚡️ {_fmt_speed(speed)}",
                    CANCEL_KB,
                )

            try:
                googleapis_stream_download(
                    file_id=file_id, cookies=cookies,
                    out_path=_gapi_path,
                    progress_cb=_gapi_progress,
                )
                # Build a fake upload flow for this direct file
                file_size   = os.path.getsize(_gapi_path)
                meta        = _get_video_meta(_gapi_path)
                display_no_ext, ext = _resolve_filename(original_filename, None, file_id)
                display_name = display_no_ext
                final_name   = make_ftm_output_name(display_no_ext + ext, ext)
                output_path  = os.path.join(DOWNLOADS_DIR, final_name)
                shutil.move(_gapi_path, output_path)
                file_type    = "Video" if upload_type == "video" and meta.get("duration", 0) > 0 else "Document"
                caption      = _build_caption(uid, display_name, file_size, meta, file_type)
                if tt == "custom" and custom_thumb_path and os.path.exists(custom_thumb_path):
                    thumb_path = custom_thumb_path
                elif tt != "none" and meta.get("duration", 0) > 0:
                    _tp = output_path + "_thumb.jpg"
                    thumb_path = _tp if _gen_thumbnail(output_path, _tp, meta["duration"]) else None
                # Upload
                up_st = {"t0": time.time(), "last": 0.0, "prev_b": 0, "prev_t": time.time(), "win": []}
                def _up_progress_gapi(current, total_b):
                    now = time.time()
                    dt = now - up_st["prev_t"]; db_b = current - up_st["prev_b"]
                    if dt > 0 and db_b > 0:
                        up_st["win"].append(db_b / dt)
                        if len(up_st["win"]) > 12: up_st["win"].pop(0)
                    up_st["prev_b"] = current; up_st["prev_t"] = now
                    if now - up_st["last"] < 2.5: return
                    up_st["last"] = now
                    spd = sum(up_st["win"]) / len(up_st["win"]) if up_st["win"] else 0
                    ela = now - up_st["t0"]
                    eta = (total_b - current) / spd if spd > 0 else float("inf")
                    cpu, ram = _sys_stats()
                    _edit(_draw_upload_card(display_name, total_b, current, spd, ela, eta, cpu, ram, file_index, total), CANCEL_KB)
                cpu0, ram0 = _sys_stats()
                _edit(_draw_upload_card(display_name, file_size, 0, 0, 0, float("inf"), cpu0, ram0, file_index, total), CANCEL_KB)
                if upload_type == "video" and meta.get("duration", 0) > 0:
                    sent = client.send_video(
                        chat_id=message.chat.id, video=output_path,
                        caption=caption, parse_mode=enums.ParseMode.HTML,
                        thumb=thumb_path, duration=meta.get("duration", 0),
                        width=meta.get("width", 0), height=meta.get("height", 0),
                        supports_streaming=True, progress=_up_progress_gapi,
                    )
                else:
                    sent = client.send_document(
                        chat_id=message.chat.id, document=output_path,
                        caption=caption, parse_mode=enums.ParseMode.HTML,
                        thumb=thumb_path, progress=_up_progress_gapi,
                    )
                _edit(f"✅ <b>{prefix}Done! (googleapis)</b>", DONE_KB)
                if post_send_fn and sent:
                    try: post_send_fn(sent, display_name, file_size, meta)
                    except Exception as pse: print(f"[FTM_FALLBACK] post_send_fn error: {pse}")
                return sent
            except Exception as _gapi_err:
                print(f"[FTM_FALLBACK] googleapis also failed: {_gapi_err}")
                raise RuntimeError(
                    f"Teeno methods fail ho gaye:\n"
                    f"• stream_capture: {_stream_err or 'N/A'}\n"
                    f"• yt-dlp: {_ytdlp_err or 'N/A'}\n"
                    f"• googleapis: {_gapi_err}"
                )

        if _cancelled():
            _edit(f"<b>{prefix}🚫 Cancelled.</b>"); return None

        # ── Build unified stream vars from whichever method worked ─────────
        if streams is not None:
            # Method 1 (stream_capture) worked
            display_no_ext, ext = _resolve_filename(
                original_filename, streams.title, file_id
            )
            video_url  = strip_drive_range_from_url(streams.video_url)
            audio_url  = strip_drive_range_from_url(streams.audio_url) if streams.audio_url else None
            dl_headers = clean_captured_headers(streams.headers)
        else:
            # Method 2 (yt-dlp) worked
            display_no_ext, ext = _resolve_filename(
                original_filename, _ytdlp_streams.get("title"), file_id
            )
            video_url  = strip_drive_range_from_url(_ytdlp_streams["video_url"])
            audio_url  = strip_drive_range_from_url(_ytdlp_streams.get("audio_url") or "")
            audio_url  = audio_url or None
            dl_headers = _ytdlp_streams.get("headers", {})

        display_name = display_no_ext
        final_name   = make_ftm_output_name(display_no_ext + ext, ext)
        has_audio    = bool(audio_url)

        _edit(
            f"<b>{prefix}✅ Stream Captured!</b>\n\n"
            f"📄 <b>{_h(display_name)}</b>\n"
            f"🎬 Video: ✅   🎵 Audio: {'✅' if has_audio else '❌ (muxed)'}\n\n"
            "<i>Download shuru ho raha hai…</i>",
            CANCEL_KB,
        )

        # ── 3. Temp paths ─────────────────────────────────────────────────
        tmp_dir     = tempfile.mkdtemp(prefix="ftmfb_", dir="/tmp")
        video_tmp   = os.path.join(tmp_dir, "video_stream.mp4")
        audio_tmp   = os.path.join(tmp_dir, "audio_stream.mp4") if has_audio else None
        output_path = os.path.join(DOWNLOADS_DIR, final_name)

        # ── 4. Parallel download ──────────────────────────────────────────
        dl_st = {"v": 0, "vt": 0, "a": 0, "at": 0, "last": 0.0}

        def _dl_progress(v_done, v_total, a_done, a_total):
            dl_st.update(v=v_done, vt=v_total, a=a_done, at=a_total)
            now = time.time()
            if now - dl_st["last"] < 2.5: return
            dl_st["last"] = now
            _edit(
                f"<b>{prefix}⬇️ Downloading</b>\n\n"
                f"📄 <b>{_h(display_name)}</b>\n"
                f"🎬 <b>Video:</b> {_fmt_pct(v_done, v_total)}\n"
                f"🎵 <b>Audio:</b> {_fmt_pct(a_done, a_total) if has_audio else 'N/A'}\n\n"
                "<i>8 MB chunks • 8 workers • parallel</i>",
                CANCEL_KB,
            )

        download_video_audio_parallel(
            video_url=video_url, audio_url=audio_url, headers=dl_headers,
            video_path=video_tmp, audio_path=audio_tmp,
            progress_cb=_dl_progress, cancel_fn=_cancelled,
        )

        if _cancelled():
            _edit(f"<b>{prefix}🚫 Cancelled.</b>"); return None

        # ── 5. Merge ──────────────────────────────────────────────────────
        _edit(f"<b>{prefix}🔀 Merging…</b>\n\n📄 <b>{_h(display_name)}</b>", CANCEL_KB)
        output_path = merge_video_audio(video_tmp, audio_tmp, output_path)
        video_tmp = audio_tmp = None

        if _cancelled():
            _edit(f"<b>{prefix}🚫 Cancelled.</b>"); return None

        # ── 6. Metadata + thumbnail ───────────────────────────────────────
        _edit(f"<b>{prefix}🔍 Metadata…</b>\n\n📄 <b>{_h(display_name)}</b>", CANCEL_KB)
        file_size = os.path.getsize(output_path)
        meta      = _get_video_meta(output_path)

        if tt == "custom" and custom_thumb_path and os.path.exists(custom_thumb_path):
            thumb_path = custom_thumb_path
        elif tt != "none" and meta.get("duration", 0) > 0:
            _tp = output_path + "_thumb.jpg"
            thumb_path = _tp if _gen_thumbnail(output_path, _tp, meta["duration"]) else None

        # ── 7. Caption (user template or default) ─────────────────────────
        file_type = "Video" if upload_type == "video" and meta.get("duration", 0) > 0 else "Document"
        caption   = _build_caption(uid, display_name, file_size, meta, file_type)

        # ── 8. Upload progress card ───────────────────────────────────────
        up_st = {"t0": time.time(), "last": 0.0,
                 "prev_b": 0, "prev_t": time.time(), "win": []}

        def _up_progress(current, total_b):
            now = time.time()
            dt = now - up_st["prev_t"];  db_b = current - up_st["prev_b"]
            if dt > 0 and db_b > 0:
                up_st["win"].append(db_b / dt)
                if len(up_st["win"]) > 12: up_st["win"].pop(0)
            up_st["prev_b"] = current;  up_st["prev_t"] = now
            if now - up_st["last"] < 2.5: return
            up_st["last"] = now
            spd = sum(up_st["win"]) / len(up_st["win"]) if up_st["win"] else 0
            ela = now - up_st["t0"]
            eta = (total_b - current) / spd if spd > 0 else float("inf")
            cpu, ram = _sys_stats()
            _edit(_draw_upload_card(display_name, total_b, current,
                                    spd, ela, eta, cpu, ram, file_index, total), CANCEL_KB)

        cpu0, ram0 = _sys_stats()
        _edit(_draw_upload_card(display_name, file_size, 0, 0, 0,
                                float("inf"), cpu0, ram0, file_index, total), CANCEL_KB)

        # ── 9. Send to user ───────────────────────────────────────────────
        if upload_type == "video" and meta.get("duration", 0) > 0:
            sent = client.send_video(
                chat_id=message.chat.id,
                video=output_path,
                caption=caption,
                parse_mode=enums.ParseMode.HTML,
                thumb=thumb_path,
                duration=meta.get("duration", 0),
                width=meta.get("width", 0),
                height=meta.get("height", 0),
                supports_streaming=True,
                progress=_up_progress,
            )
        else:
            sent = client.send_document(
                chat_id=message.chat.id,
                document=output_path,
                caption=caption,
                parse_mode=enums.ParseMode.HTML,
                thumb=thumb_path,
                progress=_up_progress,
            )

        _edit(f"✅ <b>{prefix}Done!</b>", DONE_KB)

        # ── 10. Post-send routing ─────────────────────────────────────────
        if post_send_fn and sent:
            try:
                post_send_fn(sent, display_name, file_size, meta)
            except Exception as pse:
                print(f"[FTM_FALLBACK] post_send_fn error: {pse}")

        return sent

    except Exception as e:
        import traceback
        print(f"[FTM_FALLBACK] uid={uid} fid={file_id} error: {e}\n{traceback.format_exc()}")
        _edit(
            f"<b>{prefix}❌ Fallback fail hua:</b>\n"
            f"<code>{_h(str(e)[:400])}</code>\n\n"
            "Google login check karein: /login ya /gcookies"
        )
        return None

    finally:
        for p in [video_tmp, audio_tmp]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
        if tmp_dir and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if output_path and os.path.exists(output_path):
            try: os.remove(output_path)
            except Exception: pass
        if thumb_path and thumb_path.endswith("_thumb.jpg") and os.path.exists(thumb_path):
            try: os.remove(thumb_path)
            except Exception: pass
