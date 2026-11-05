"""
parallel_downloader.py — Parallel chunked download for Drive video/audio streams.

Key rule (IMPORTANT):
  Google Drive videoplayback URLs captured from Playwright contain a segment
  range like &range=0-1048575. This is a browser playback segment, NOT the
  full file URL.

  Before downloading:
    1. strip_drive_range_from_url(url) → removes &range=... from URL
    2. clean_captured_headers(headers) → removes browser's Range header
    3. Our downloader then adds its own Range: bytes=start-end per chunk

Download spec:
  - chunk size : 8 MB
  - max workers: 8
  - retry       : 3x per chunk
  - video+audio : parallel threads
"""
import os
import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as _requests
from requests.adapters import HTTPAdapter

CHUNK_SIZE   = 8 * 1024 * 1024    # 8 MB chunks (V16 spec) for maximum unthrottled burst
MAX_WORKERS  = 16                 # 16 parallel threads
MAX_RETRIES  = 4
CONN_TIMEOUT = 15
READ_TIMEOUT = 90


# ── URL / header sanitizers ────────────────────────────────────────────────────

def strip_drive_range_from_url(url: str) -> str:
    """
    Remove &range=X-Y (and everything after it) from a Google Drive
    videoplayback URL.  The captured URL is a browser playback segment;
    we need the base signed URL so our downloader can control byte ranges.

    Example:
      in : https://rr5.c.drive.google.com/videoplayback?...&range=0-1048575&rbuf=0
      out: https://rr5.c.drive.google.com/videoplayback?...
    """
    if not url:
        return url
    for marker in ("&range=", "?range="):
        idx = url.find(marker)
        if idx != -1:
            return url[:idx]
    return url


def clean_captured_headers(headers: dict) -> dict:
    """
    Strip browser-owned headers that must not be forwarded to our
    downloader.  Our code will add fresh Range / Content-Length per chunk.
    """
    drop = {"range", "content-length", "host", "connection",
            "accept-encoding", "transfer-encoding"}
    return {k: v for k, v in (headers or {}).items() if k.lower() not in drop}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _get_total_size(url: str, headers: dict) -> int:
    """Try HEAD then Range:bytes=0-1 to discover content length."""
    try:
        r = _requests.head(url, headers=headers, timeout=CONN_TIMEOUT,
                           allow_redirects=True)
        cl = r.headers.get("Content-Length") or r.headers.get("content-length")
        if cl:
            return int(cl)
    except Exception:
        pass
    try:
        h2 = {**headers, "Range": "bytes=0-1"}
        r2 = _requests.get(url, headers=h2, timeout=CONN_TIMEOUT, stream=True)
        cr = r2.headers.get("Content-Range", "")
        r2.close()
        if "/" in cr:
            return int(cr.split("/")[-1])
    except Exception:
        pass
    return 0


def _download_chunk(url: str, headers: dict, start: int, end: int,
                    out_path: str, prog_lock: threading.Lock,
                    progress: dict) -> None:
    h = {**headers, "Range": f"bytes={start}-{end}"}
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            # Fresh connection per chunk with Connection: close
            # This completely resets Google Drive's 100MB token bucket on every chunk!
            req_headers = {**h, "Connection": "close"}
            resp = _requests.get(url, headers=req_headers,
                                 timeout=(CONN_TIMEOUT, READ_TIMEOUT),
                                 stream=True)
            if resp.status_code not in (200, 206):
                last_exc = Exception(f"HTTP {resp.status_code}")
                time.sleep(1 + attempt)
                continue
            with open(out_path, "r+b") as f:
                f.seek(start)
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        with prog_lock:
                            progress["done"] += len(chunk)
            return
        except Exception as e:
            last_exc = e
            time.sleep(1 + attempt)
    raise last_exc or Exception("Chunk download failed after retries")


def _download_single_stream(url: str, headers: dict, out_path: str,
                             prog_lock: threading.Lock, progress: dict,
                             cancel_fn) -> int:
    done = 0
    with _requests.get(url, headers=headers,
                       timeout=(CONN_TIMEOUT, 600), stream=True) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if cancel_fn and cancel_fn():
                    raise Exception("Cancelled by user")
                if chunk:
                    f.write(chunk)
                    done += len(chunk)
                    with prog_lock:
                        progress["done"] += len(chunk)
    return done


# ── Public API ────────────────────────────────────────────────────────────────

def download_stream(
    url: str,
    headers: dict,
    out_path: str,
    label: str = "stream",
    progress_cb=None,
    cancel_fn=None,
) -> int:
    """
    Download a single stream URL to out_path.

    Automatically:
      - strips &range= from URL
      - cleans browser headers
      - pre-allocates file
      - downloads with up to MAX_WORKERS parallel chunks

    Returns total bytes written.
    progress_cb(done_bytes, total_bytes, label)
    """
    url     = strip_drive_range_from_url(url)
    headers = clean_captured_headers(headers)

    # 1. For general non-stream URLs, aria2c is fast.
    # But for Google Drive videoplayback streams, Google throttles persistent socket pools after 100MB.
    # Therefore, videoplayback MUST use the Python multi-worker independent chunk pipeline
    # with Connection: close (V16 architecture) to maintain sustained 20-30+ MB/s to the very end!
    if "videoplayback" not in url:
        try:
            from fallback.aria2_downloader import is_aria2_available, aria2_download
            if is_aria2_available():
                def _a2_prog(cur, tot, spd, ela, eta):
                    if progress_cb:
                        progress_cb(cur, tot, label)
                print(f"[{label.upper()}] Starting aria2c with 16 connections for {out_path}")
                return aria2_download(
                    url=url,
                    headers=headers,
                    out_path=out_path,
                    connections=16,
                    progress_cb=_a2_prog,
                    cancel_fn=cancel_fn,
                )
        except Exception as a2_err:
            print(f"[{label.upper()}] aria2c failed ({a2_err}), falling back to Python thread pool...")
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
            except Exception:
                pass

    total     = _get_total_size(url, headers)
    prog_lock = threading.Lock()
    progress  = {"done": 0}

    # Background ticker for UI updates
    _stop_ticker = threading.Event()
    def _tick():
        while not _stop_ticker.wait(1.5):
            if progress_cb:
                progress_cb(progress["done"], total, label)
    threading.Thread(target=_tick, daemon=True).start()

    try:
        if total == 0:
            result = _download_single_stream(url, headers, out_path,
                                             prog_lock, progress, cancel_fn)
        else:
            # Pre-allocate
            with open(out_path, "wb") as f:
                f.seek(max(total - 1, 0))
                f.write(b"\x00")

            n_chunks = max(1, math.ceil(total / CHUNK_SIZE))
            ranges   = [
                (i * CHUNK_SIZE, min((i + 1) * CHUNK_SIZE - 1, total - 1))
                for i in range(n_chunks)
            ]
            errors = []

            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, n_chunks)) as pool:
                futures = {
                    pool.submit(_download_chunk, url, headers, s, e,
                                out_path, prog_lock, progress): i
                    for i, (s, e) in enumerate(ranges)
                }
                for fut in as_completed(futures):
                    if cancel_fn and cancel_fn():
                        raise Exception("Cancelled by user")
                    exc = fut.exception()
                    if exc:
                        errors.append(exc)

            if errors:
                raise Exception(f"Chunk error: {errors[0]}")
            result = total
    finally:
        _stop_ticker.set()

    if progress_cb:
        progress_cb(result, result, label)
    return result


def download_video_audio_parallel(
    video_url: str,
    audio_url: str,
    headers: dict,
    video_path: str,
    audio_path: str,
    progress_cb=None,
    cancel_fn=None,
) -> tuple:
    """
    Download video and audio simultaneously (separate threads).
    Range strip + header clean applied inside download_stream().

    progress_cb(v_done, v_total, a_done, a_total)
    Returns (video_path, audio_path|None).
    """
    state = {"v_done": 0, "v_total": 0, "a_done": 0, "a_total": 0}
    lock  = threading.Lock()
    errors: list = []

    def _v_cb(done, total, _label):
        with lock:
            state["v_done"] = done
            state["v_total"] = total
        if progress_cb:
            progress_cb(state["v_done"], state["v_total"],
                        state["a_done"], state["a_total"])

    def _a_cb(done, total, _label):
        with lock:
            state["a_done"] = done
            state["a_total"] = total
        if progress_cb:
            progress_cb(state["v_done"], state["v_total"],
                        state["a_done"], state["a_total"])

    def _dl_video():
        try:
            download_stream(video_url, headers, video_path, "video",
                            _v_cb, cancel_fn)
        except Exception as e:
            errors.append(("video", e))

    def _dl_audio():
        try:
            if audio_url:
                download_stream(audio_url, headers, audio_path, "audio",
                                _a_cb, cancel_fn)
        except Exception as e:
            errors.append(("audio", e))

    vt = threading.Thread(target=_dl_video, daemon=True)
    vt.start()
    at = None
    if audio_url:
        at = threading.Thread(target=_dl_audio, daemon=True)
        at.start()

    vt.join()
    if at:
        at.join()

    for kind, err in errors:
        if kind == "video":
            raise Exception(f"Video stream download fail: {err}")
    for kind, err in errors:
        if kind == "audio":
            raise Exception(f"Audio stream download fail: {err}")

    return video_path, (audio_path if audio_url else None)
