"""
aria2_downloader.py — High-speed chunk downloader using aria2c with parallel socket connections.
Falls back to python multi-threading if aria2c binary is not available.
"""
import os
import re
import time
import shutil
import subprocess
import threading
from typing import Optional, Callable


def is_aria2_available() -> bool:
    """Return True if aria2c binary is present on PATH."""
    return shutil.which("aria2c") is not None


def _parse_size(val_str: str) -> int:
    val_str = val_str.strip().upper()
    multipliers = {
        "KIB": 1024,
        "KB": 1000,
        "MIB": 1024 * 1024,
        "MB": 1000 * 1000,
        "GIB": 1024 * 1024 * 1024,
        "GB": 1000 * 1000 * 1000,
        "TIB": 1024 * 1024 * 1024 * 1024,
        "TB": 1000 * 1000 * 1000 * 1000,
        "B": 1,
    }
    for unit, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if val_str.endswith(unit):
            try:
                num = float(val_str[:-len(unit)].strip())
                return int(num * mult)
            except Exception:
                pass
    try:
        return int(float(val_str))
    except Exception:
        return 0


def _parse_eta(eta_str: str) -> float:
    if not eta_str:
        return 0.0
    m = re.match(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", eta_str.strip())
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return (int(h) if h else 0) * 3600 + (int(mn) if mn else 0) * 60 + (int(s) if s else 0)


_ARIA2_RE = re.compile(
    r"\[#\w+\s+([0-9.]+[KMGT]?i?B)/([0-9.]+[KMGT]?i?B)\((\d+)%\)\s+CN:(\d+)\s+DL:([0-9.]+[KMGT]?i?B)(?:\s+ETA:(\w+))?\]"
)


def aria2_download(
    url: str,
    headers: dict,
    out_path: str,
    connections: int = 16,
    progress_cb: Optional[Callable] = None,
    cancel_fn: Optional[Callable] = None,
) -> int:
    """
    Download a file or stream using aria2c with `connections` parallel workers.
    Streams progress to `progress_cb(downloaded, total, speed, elapsed, eta)`.
    Raises Exception on failure or cancellation.
    Returns total downloaded bytes.
    """
    out_dir = os.path.dirname(os.path.abspath(out_path))
    out_name = os.path.basename(out_path)
    os.makedirs(out_dir, exist_ok=True)

    split_count = max(connections * 4, 32)
    cmd = [
        "aria2c",
        "--summary-interval=1",
        f"-x{connections}",
        f"-s{split_count}",
        "-j1",
        "-k1M",
        "--min-split-size=1M",
        f"--max-connection-per-server={connections}",
        f"--split={split_count}",
        "--piece-length=1M",
        "--disk-cache=32M",
        "--continue=true",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--file-allocation=none",
        "--check-certificate=false",
        "--retry-wait=2",
        "--max-tries=5",
        "--timeout=30",
        "-d", out_dir,
        "-o", out_name,
    ]

    for k, v in (headers or {}).items():
        if k.lower() not in ("range", "content-length", "host", "connection"):
            cmd.append(f"--header={k}: {v}")

    cmd.append(url)

    t0 = time.time()
    last_update = 0.0
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    total_bytes = 0
    done_bytes = 0

    try:
        while True:
            if cancel_fn and cancel_fn():
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
                raise Exception("Download cancelled by user")

            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
                continue

            m = _ARIA2_RE.search(line)
            if m:
                cur_str, tot_str, pct, cn, spd_str, eta_str = m.groups()
                done_bytes = _parse_size(cur_str)
                total_bytes = _parse_size(tot_str)
                speed_bps = _parse_size(spd_str)
                eta_secs = _parse_eta(eta_str) if eta_str else (
                    (total_bytes - done_bytes) / speed_bps if speed_bps > 0 else 0
                )
                elapsed = time.time() - t0

                now = time.time()
                if progress_cb and (now - last_update >= 1.0):
                    last_update = now
                    try:
                        progress_cb(done_bytes, total_bytes, speed_bps, elapsed, eta_secs)
                    except Exception:
                        pass

        ret = proc.wait()
        if ret != 0:
            raise RuntimeError(f"aria2c exited with code {ret}")

        final_size = os.path.getsize(out_path) if os.path.exists(out_path) else done_bytes
        if progress_cb:
            try:
                progress_cb(final_size, final_size, 0, time.time() - t0, 0)
            except Exception:
                pass
        return final_size

    finally:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
