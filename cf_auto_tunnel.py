"""
cf_auto_tunnel.py — Runs Cloudflared in background and syncs live URL with Cloudflare Worker.
Permanent WebApp URL: https://drive-bot.ftmdeveloperz.workers.dev
"""
import os
import re
import sys
import time
import shutil
import urllib.request
import json
import subprocess
import threading

WORKER_URL = "https://drive-bot.ftmdeveloperz.workers.dev"
SECRET_KEY = "drive_bot_secret_tunnel_2026"

def _find_cloudflared() -> str:
    # 1. System PATH
    found = shutil.which("cloudflared")
    if found:
        return found
    
    # 2. Local workspace directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(current_dir, "cloudflared.exe"),
        os.path.join(current_dir, "cloudflared"),
        "/usr/local/bin/cloudflared",
        "/usr/bin/cloudflared",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    # 3. If Linux, auto download binary
    if sys.platform.startswith("linux"):
        target = "/tmp/cloudflared"
        if not os.path.exists(target):
            try:
                print("[CF_TUNNEL] Downloading cloudflared for Linux...", flush=True)
                urllib.request.urlretrieve("https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64", target)
                os.chmod(target, 0o755)
                return target
            except Exception as e:
                print(f"[CF_TUNNEL] Could not auto-download cloudflared: {e}", flush=True)

    return None

def update_worker_target(target_url: str):
    try:
        req = urllib.request.Request(
            f"{WORKER_URL}/set_target",
            data=json.dumps({"target_url": target_url}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DriveBot/1.0",
                "X-Tunnel-Key": SECRET_KEY,
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[CF_TUNNEL] Synced with Worker! Result: {resp.read().decode('utf-8')}", flush=True)
    except Exception as e:
        print(f"[CF_TUNNEL] Failed to sync with Cloudflare Worker: {e}", flush=True)

def start_auto_tunnel_thread(port: int = 8080):
    bin_path = _find_cloudflared()
    if not bin_path:
        print("[CF_TUNNEL] cloudflared binary not found; auto-tunnel skipped.", flush=True)
        return

    print(f"[CF_TUNNEL] Starting Cloudflared tunnel for port {port}...", flush=True)
    try:
        proc = subprocess.Popen(
            [bin_path, "tunnel", "--protocol", "http2", "--url", f"http://127.0.0.1:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        print(f"[CF_TUNNEL] Failed to start cloudflared: {e}", flush=True)
        return

    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

    def monitor():
        current_tunnel = None
        for line in proc.stderr:
            match = url_pattern.search(line)
            if match:
                new_url = match.group(0)
                if new_url != current_tunnel:
                    current_tunnel = new_url
                    print(f"[CF_TUNNEL] Live Tunnel URL: {current_tunnel}", flush=True)
                    print(f"[CF_TUNNEL] Permanent URL: {WORKER_URL}", flush=True)
                    update_worker_target(current_tunnel)

    t = threading.Thread(target=monitor, daemon=True, name="cf-auto-tunnel")
    t.start()

if __name__ == "__main__":
    start_auto_tunnel_thread(8080)
    time.sleep(10)
