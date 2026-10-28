import os
import re
import json
import time
import hashlib
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

_FOLDER_MIME  = "application/vnd.google-apps.folder"
_GDRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
_TOKEN_URL    = "https://oauth2.googleapis.com/token"

_SCRAPE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ── Cookie helpers ────────────────────────────────────────────────────────────

def parse_cookie_str(cookie_str: str) -> dict:
    cookies = {}
    text = cookie_str.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "cookies" in data:
                arr = data["cookies"]
            elif isinstance(data, list):
                arr = data
            else:
                arr = []
            for item in arr:
                if isinstance(item, dict):
                    name  = item.get("name",  "").strip()
                    value = item.get("value", "").strip()
                    if name:
                        cookies[name] = value
            return cookies
        except Exception:
            pass
    for part in text.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def _cookies_to_str(cookies) -> str:
    if not cookies:
        return ""
    if isinstance(cookies, dict):
        return "; ".join(f"{k}={v}" for k, v in cookies.items())
    return str(cookies).strip()


def _sapisidhash(papisid: str, origin: str = "https://drive.google.com") -> str:
    ts     = str(int(time.time()))
    digest = hashlib.sha1(f"{ts} {papisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{digest}"


def _auth_headers_from_cookies(cookies: dict) -> dict:
    """
    Build Authorization + X-Goog-AuthUser headers from stored Google cookies.
    Works for Drive API v3 calls (same auth the browser uses).
    """
    papisid = (
        cookies.get("__Secure-1PAPISID")
        or cookies.get("SAPISID")
        or ""
    )
    if not papisid:
        return {}
    return {
        "Authorization":   _sapisidhash(papisid),
        "X-Goog-AuthUser": "0",
        "X-Origin":        "https://drive.google.com",
    }


# ── OAuth token refresh ───────────────────────────────────────────────────────

def refresh_oauth_access_token(refresh_token: str,
                               client_id: str = "",
                               client_secret: str = "") -> str | None:
    """
    Exchange a refresh_token for a fresh access_token.
    Falls back to env-vars for client_id / client_secret if not supplied.
    Returns the new access_token string, or None on failure.
    """
    cid  = client_id     or os.environ.get("GOOGLE_CLIENT_ID",     "")
    csec = client_secret or os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not cid or not csec or not refresh_token:
        return None
    try:
        resp = requests.post(
            _TOKEN_URL,
            data={
                "client_id":     cid,
                "client_secret": csec,
                "refresh_token": refresh_token,
                "grant_type":    "refresh_token",
            },
            timeout=15,
        )
        data = resp.json()
        token = data.get("access_token")
        if token:
            print("[OAUTH] Access token refreshed ✓")
        else:
            print(f"[OAUTH] Refresh failed: {data.get('error_description', data)}")
        return token
    except Exception as e:
        print(f"[OAUTH] refresh_oauth_access_token error: {e}")
        return None


# ── Google Drive API v3 core ──────────────────────────────────────────────────

def _gdrive_list_page(folder_id: str, auth_headers: dict,
                      api_key: str = "", page_token: str = "") -> dict:
    """
    One page of Drive API v3 files list.
    Returns raw API response dict, or {} on failure.
    """
    params = {
        "q":        f"'{folder_id}' in parents and trashed=false",
        "fields":   "nextPageToken,files(id,name,mimeType,size)",
        "pageSize": 1000,
        "orderBy":  "name",
    }
    if page_token:
        params["pageToken"] = page_token
    if api_key and not auth_headers:
        params["key"] = api_key

    try:
        resp = requests.get(
            _GDRIVE_FILES,
            params=params,
            headers=auth_headers,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        print(f"[GDRIVE API] list page status={resp.status_code} folder={folder_id}")
    except Exception as e:
        print(f"[GDRIVE API] _gdrive_list_page error {folder_id}: {e}")
    return {}


def _gdrive_get_folder_name(folder_id: str, auth_headers: dict,
                             api_key: str = "") -> str:
    """Fetch a folder's name from Drive API v3. Returns '' on failure."""
    params = {"fields": "id,name"}
    if api_key and not auth_headers:
        params["key"] = api_key
    try:
        resp = requests.get(
            f"{_GDRIVE_FILES}/{folder_id}",
            params=params,
            headers=auth_headers,
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("name", "")
    except Exception as e:
        print(f"[GDRIVE API] get_folder_name error {folder_id}: {e}")
    return ""


def _gdrive_scan_folder_recursive(folder_id: str, auth_headers: dict,
                                   api_key: str = "",
                                   name: str = "", _depth: int = 0) -> dict:
    """
    Recursively build a folder tree using Google Drive API v3.
    Subfolders are fetched in parallel (up to 16 workers).
    Returns tree dict: {id, name, subfolders, files, total_files}
    """
    if _depth == 0 and not name:
        name = _gdrive_get_folder_name(folder_id, auth_headers, api_key) or folder_id

    node = {
        "id":          folder_id,
        "name":        name,
        "subfolders":  [],
        "files":       [],
        "total_files": 0,
    }

    page_token = ""
    subfolder_entries = []

    while True:
        data = _gdrive_list_page(folder_id, auth_headers, api_key, page_token)
        if not data:
            break
        for f in data.get("files", []):
            fid   = f.get("id",   "")
            fname = f.get("name", "unnamed")
            mime  = f.get("mimeType", "")
            if mime == _FOLDER_MIME:
                subfolder_entries.append((fid, fname))
            else:
                node["files"].append({"id": fid, "name": fname, "mimeType": mime})
                node["total_files"] += 1
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    if subfolder_entries:
        workers = min(16, len(subfolder_entries))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {
                ex.submit(
                    _gdrive_scan_folder_recursive,
                    eid, auth_headers, api_key, ename, _depth + 1
                ): (eid, ename)
                for eid, ename in subfolder_entries
            }
            results = {}
            for future in as_completed(futures):
                eid, ename = futures[future]
                try:
                    results[(eid, ename)] = future.result()
                except Exception as e:
                    print(f"[GDRIVE API] subfolder error {eid}: {e}")
            for eid, ename in subfolder_entries:
                sub = results.get((eid, ename))
                if sub:
                    node["subfolders"].append(sub)
                    node["total_files"] += sub["total_files"]

    return node


# ── HTML scraping fallback ────────────────────────────────────────────────────

def _fetch_html_entries(folder_id: str, cookies: dict) -> tuple:
    """
    Scrape Google Drive folder page to extract entries.
    Returns (entries, folder_name).
    """
    try:
        resp = requests.get(
            f"https://drive.google.com/drive/folders/{folder_id}",
            cookies=cookies,
            headers={"User-Agent": _SCRAPE_UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=30,
            allow_redirects=True,
        )
    except Exception as e:
        print(f"[HTML] fetch error {folder_id}: {e}")
        return [], ""

    if resp.status_code != 200 or "accounts.google.com" in resp.url:
        print(f"[HTML] {folder_id} status={resp.status_code} url={resp.url[:80]}")
        return [], ""

    folder_name = ""
    _tm = re.search(r"<title>([^<]+)</title>", resp.text)
    if _tm:
        folder_name = re.sub(r"\s*[-–—]\s*Google Drive\s*$", "", _tm.group(1)).strip()

    m = re.search(r"window\['_DRIVE_ivd'\]\s*=\s*'(.*?)'\s*;", resp.text, re.DOTALL)
    if not m:
        print(f"[HTML] _DRIVE_ivd not found for {folder_id}")
        return [], folder_name

    try:
        decoded = m.group(1).encode("utf-8").decode("unicode_escape")
        outer   = json.loads(decoded)
    except Exception as e:
        print(f"[HTML] JSON parse error for {folder_id}: {e}")
        return [], folder_name

    entries = []
    for item in outer:
        if not isinstance(item, list):
            continue
        if item and isinstance(item[0], list):
            entries.extend(item)
        elif item and isinstance(item[0], str) and len(item) >= 4:
            entries.append(item)
    return entries, folder_name


def _html_build_tree(folder_id: str, cookies: dict,
                     name: str = "", _depth: int = 0) -> dict:
    """Recursively build a tree via HTML scraping with parallel subfolder fetch."""
    entries, detected_name = _fetch_html_entries(folder_id, cookies)

    if _depth == 0:
        name = detected_name or name or folder_id

    node = {
        "id":          folder_id,
        "name":        name,
        "subfolders":  [],
        "files":       [],
        "total_files": 0,
    }
    subfolder_entries = []

    for entry in entries:
        if not isinstance(entry, list) or len(entry) < 4:
            continue
        eid   = entry[0]
        ename = (entry[2] or "unnamed").strip()
        emime = entry[3] or ""
        if _FOLDER_MIME in emime:
            subfolder_entries.append((eid, ename))
        else:
            node["files"].append({"id": eid, "name": ename, "mimeType": emime})
            node["total_files"] += 1

    if subfolder_entries:
        workers = min(16, len(subfolder_entries))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {
                ex.submit(_html_build_tree, eid, cookies, ename, _depth + 1): (eid, ename)
                for eid, ename in subfolder_entries
            }
            results = {}
            for future in as_completed(futures):
                eid, ename = futures[future]
                try:
                    results[(eid, ename)] = future.result()
                except Exception as e:
                    print(f"[HTML] subfolder error {eid}: {e}")
            for eid, ename in subfolder_entries:
                sub = results.get((eid, ename))
                if sub:
                    node["subfolders"].append(sub)
                    node["total_files"] += sub["total_files"]

    return node


def _gdown_list_public(folder_id: str) -> list:
    """List public folder files via gdown. Returns [{id, name, path}]."""
    try:
        import gdown
        items = gdown.download_folder(id=folder_id, skip_download=True, quiet=True)
        files = []
        for item in (items or []):
            path   = getattr(item, "path", "") or ""
            fid    = getattr(item, "id",   None)
            name   = os.path.basename(path)
            parent = os.path.dirname(path)
            if fid and name:
                files.append({"id": fid, "name": name, "path": parent})
        return files
    except Exception as e:
        print(f"[GDOWN] Error: {e}")
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def all_files_from_node(node: dict, path_parts: list = None) -> list:
    """Flatten a tree node into [{id, name, path, mimeType}] list."""
    if path_parts is None:
        path_parts = []
    current_path = path_parts + [node["name"]]
    result = []
    for f in node.get("files", []):
        result.append({
            "id":       f["id"],
            "name":     f["name"],
            "path":     "/".join(current_path),
            "mimeType": f.get("mimeType", ""),
        })
    for sub in node.get("subfolders", []):
        result.extend(all_files_from_node(sub, current_path))
    return result


def _files_to_tree(folder_id: str, folder_name: str, files: list) -> dict:
    """Convert flat file list to a tree dict."""
    tree_files = [{"id": f["id"], "name": f["name"]} for f in files]
    return {
        "id":          folder_id,
        "name":        folder_name,
        "subfolders":  [],
        "files":       tree_files,
        "total_files": len(tree_files),
    }


def _count_files(node: dict) -> int:
    count = len(node.get("files", []))
    for sub in node.get("subfolders", []):
        count += _count_files(sub)
    return count


def fallback_scan_folder(folder_id: str, cookies: dict = None) -> list:
    """
    Direct scan without external API.
    Private (cookies): HTML scraping. Public (no cookies): gdown.
    Returns [{id, name, path}].
    """
    if cookies:
        print(f"[HTML] Scraping (private) folder {folder_id}")
        tree  = _html_build_tree(folder_id, cookies)
        files = all_files_from_node(tree)
        print(f"[HTML] Got {len(files)} file(s) ✓" if files else f"[HTML] 0 files for {folder_id}")
        return files

    print(f"[GDOWN] Public folder {folder_id}")
    files = _gdown_list_public(folder_id)
    print(f"[GDOWN] Got {len(files)} file(s) ✓" if files else f"[GDOWN] 0 files for {folder_id}")
    return files


def get_folder_name(folder_id: str, cookies=None, api_key: str = "") -> str | None:
    """Fetch real folder name. Returns None on failure."""
    # Try API key first (fast, no auth needed for public)
    _api_key = api_key or os.environ.get("GDRIVE_API_KEY", "")
    if _api_key:
        name = _gdrive_get_folder_name(folder_id, {}, _api_key)
        if name:
            return name

    # Try cookies-based auth
    if cookies:
        cookie_dict = cookies if isinstance(cookies, dict) else parse_cookie_str(cookies)
        auth_hdrs = _auth_headers_from_cookies(cookie_dict)
        if auth_hdrs:
            name = _gdrive_get_folder_name(folder_id, auth_hdrs)
            if name:
                return name
        # HTML scrape as last resort
        _, name = _fetch_html_entries(folder_id, cookie_dict)
        if name:
            return name

    return None


def build_folder_tree(folder_id: str,
                      cookies=None,
                      name: str = "Root",
                      access_token: str = "",
                      refresh_token: str = "",
                      _depth: int = 0) -> dict:
    """
    Build a full folder tree using the best available method:

    Priority order:
      1. OAuth access_token  → Drive API v3 (most reliable, works for any folder)
      2. Cookies             → Drive API v3 with SAPISIDHASH auth (private folders)
      3. API key             → Drive API v3 (public folders only)
      4. HTML scraping       → direct Google Drive page scrape (cookies required)
      5. gdown               → public folder last resort

    Returns tree dict: {id, name, subfolders, files, total_files}
    """
    _api_key    = os.environ.get("GDRIVE_API_KEY", "")
    _client_id  = os.environ.get("GOOGLE_CLIENT_ID", "")
    _client_sec = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    cookie_dict = {}
    if cookies:
        cookie_dict = cookies if isinstance(cookies, dict) else parse_cookie_str(cookies)

    # ── 1. OAuth access_token ─────────────────────────────────────────────────
    token = access_token
    if token:
        print(f"[GDRIVE] OAuth token scan: {folder_id}")
        try:
            tree = _gdrive_scan_folder_recursive(
                folder_id, {"Authorization": f"Bearer {token}"}, name=name
            )
            if tree.get("total_files") or tree.get("files") or tree.get("subfolders"):
                print(f"[GDRIVE] OAuth: {tree['total_files']} file(s) ✓")
                return tree
        except Exception as e:
            print(f"[GDRIVE] OAuth scan failed, trying refresh: {e}")

        # Try refresh if token failed
        if refresh_token and (_client_id and _client_sec):
            new_token = refresh_oauth_access_token(refresh_token, _client_id, _client_sec)
            if new_token:
                try:
                    tree = _gdrive_scan_folder_recursive(
                        folder_id,
                        {"Authorization": f"Bearer {new_token}"},
                        name=name,
                    )
                    if tree.get("total_files") or tree.get("files") or tree.get("subfolders"):
                        print(f"[GDRIVE] Refreshed token: {tree['total_files']} file(s) ✓")
                        return tree
                except Exception as e:
                    print(f"[GDRIVE] Refreshed token scan also failed: {e}")

    # ── 2. Cookies → SAPISIDHASH auth ─────────────────────────────────────────
    if cookie_dict:
        auth_hdrs = _auth_headers_from_cookies(cookie_dict)
        if auth_hdrs:
            print(f"[GDRIVE] SAPISIDHASH scan: {folder_id}")
            try:
                tree = _gdrive_scan_folder_recursive(
                    folder_id, auth_hdrs, name=name
                )
                if tree.get("total_files") or tree.get("files") or tree.get("subfolders"):
                    print(f"[GDRIVE] SAPISIDHASH: {tree['total_files']} file(s) ✓")
                    return tree
            except Exception as e:
                print(f"[GDRIVE] SAPISIDHASH scan failed: {e}")

    # ── 3. API key (public folders) ───────────────────────────────────────────
    if _api_key and not cookie_dict:
        print(f"[GDRIVE] API key scan: {folder_id}")
        try:
            tree = _gdrive_scan_folder_recursive(
                folder_id, {}, api_key=_api_key, name=name
            )
            if tree.get("total_files") or tree.get("files") or tree.get("subfolders"):
                print(f"[GDRIVE] API key: {tree['total_files']} file(s) ✓")
                return tree
        except Exception as e:
            print(f"[GDRIVE] API key scan failed: {e}")

    # ── 4. HTML scraping (cookies) ────────────────────────────────────────────
    if cookie_dict:
        print(f"[GDRIVE] HTML scrape fallback: {folder_id}")
        try:
            tree = _html_build_tree(folder_id, cookie_dict, name=name)
            if tree.get("total_files") or tree.get("files") or tree.get("subfolders"):
                print(f"[GDRIVE] HTML scrape: {tree['total_files']} file(s) ✓")
                return tree
        except Exception as e:
            print(f"[GDRIVE] HTML scrape failed: {e}")

    # ── 5. gdown (public) ─────────────────────────────────────────────────────
    if not cookie_dict:
        print(f"[GDRIVE] gdown fallback: {folder_id}")
        try:
            files = _gdown_list_public(folder_id)
            if files:
                label = name if name not in ("Root", "") else "Drive Folder"
                return _files_to_tree(folder_id, label, files)
        except Exception as e:
            print(f"[GDRIVE] gdown failed: {e}")

    return {
        "id":          folder_id,
        "name":        name if name not in ("Root", "") else "Drive Folder",
        "subfolders":  [],
        "files":       [],
        "total_files": 0,
    }


# ── Drive API v3 File Resolver ────────────────────────────────────────────────

_GDRIVE_FILE_FIELDS = (
    "id,name,mimeType,size,md5Checksum,webContentLink,"
    "exportLinks,parents,trashed,capabilities"
)

_WORKSPACE_MIMES = {
    "application/vnd.google-apps.document":     "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.google-apps.spreadsheet":  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.google-apps.presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.google-apps.drawing":      "image/svg+xml",
    "application/vnd.google-apps.script":       "application/vnd.google-apps.script+json",
}

_WORKSPACE_EXTS = {
    "application/vnd.google-apps.document":     ".docx",
    "application/vnd.google-apps.spreadsheet":  ".xlsx",
    "application/vnd.google-apps.presentation": ".pptx",
    "application/vnd.google-apps.drawing":      ".svg",
    "application/vnd.google-apps.script":       ".json",
}


def _build_auth_headers(access_token: str = "", cookies: dict = None) -> dict:
    """Return the best Authorization header dict — OAuth Bearer preferred over SAPISIDHASH."""
    if access_token:
        return {"Authorization": f"Bearer {access_token}"}
    if cookies:
        return _auth_headers_from_cookies(cookies)
    return {}


def resolve_file_info(file_id: str,
                      cookies: dict = None,
                      access_token: str = "",
                      refresh_token: str = "") -> dict:
    """
    Fetch complete file metadata from Google Drive API v3.

    Priority: OAuth Bearer → SAPISIDHASH (cookies) → API key → public fallback.

    Returns dict:
      id, name, mime_type, size (int bytes), md5, download_url,
      auth_headers, web_content_link, export_links, method, is_workspace
    Returns {} on complete failure.
    """
    _api_key    = os.environ.get("GDRIVE_API_KEY",      "")
    _client_id  = os.environ.get("GOOGLE_CLIENT_ID",    "")
    _client_sec = os.environ.get("GOOGLE_CLIENT_SECRET","")

    cookie_dict = cookies or {}

    def _call_api(hdrs: dict, key: str = "") -> dict | None:
        params = {"fields": _GDRIVE_FILE_FIELDS, "supportsAllDrives": "true"}
        if key and not hdrs:
            params["key"] = key
        try:
            resp = requests.get(
                f"{_GDRIVE_FILES}/{file_id}",
                params=params,
                headers={**hdrs, "User-Agent": _SCRAPE_UA},
                timeout=20,
            )
            if resp.status_code == 200:
                return resp.json()
            print(f"[RESOLVER] API status={resp.status_code} for {file_id}")
        except Exception as e:
            print(f"[RESOLVER] API error {file_id}: {e}")
        return None

    # ── Try with OAuth token ───────────────────────────────────────────────────
    token = access_token
    data  = None
    method = ""

    if token:
        data = _call_api({"Authorization": f"Bearer {token}"})
        if data:
            method = "oauth"
        elif refresh_token and _client_id and _client_sec:
            new_tok = refresh_oauth_access_token(refresh_token, _client_id, _client_sec)
            if new_tok:
                data = _call_api({"Authorization": f"Bearer {new_tok}"})
                if data:
                    token  = new_tok
                    method = "oauth_refreshed"

    # ── Try with SAPISIDHASH ───────────────────────────────────────────────────
    if data is None and cookie_dict:
        auth_hdrs = _auth_headers_from_cookies(cookie_dict)
        if auth_hdrs:
            data = _call_api(auth_hdrs)
            if data:
                method = "sapisidhash"

    # ── Try with API key ───────────────────────────────────────────────────────
    if data is None and _api_key:
        data = _call_api({}, key=_api_key)
        if data:
            method = "apikey"

    # ── Last resort: scrape Drive preview page to extract filename from title ──
    # Works even for download-disabled files — preview page is always accessible.
    if not data and cookie_dict:
        try:
            _cookie_hdr = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
            _prev_resp = requests.get(
                f"https://drive.google.com/file/d/{file_id}/preview",
                headers={
                    "User-Agent":      _SCRAPE_UA,
                    "Cookie":          _cookie_hdr,
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=20,
                allow_redirects=True,
            )
            if _prev_resp.status_code == 200 and "accounts.google.com" not in _prev_resp.url:
                _title_m = re.search(r"<title>([^<]+)</title>", _prev_resp.text, re.I)
                if _title_m:
                    _raw_title = _title_m.group(1).strip()
                    _raw_title = re.sub(
                        r"\s*[-–|]\s*Google\s*Drive\s*$", "", _raw_title, flags=re.I
                    ).strip()
                    if _raw_title:
                        _ext = os.path.splitext(_raw_title)[1].lower()
                        _EXT_TO_MIME = {
                            ".pdf":  "application/pdf",
                            ".doc":  "application/msword",
                            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            ".xls":  "application/vnd.ms-excel",
                            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            ".ppt":  "application/vnd.ms-powerpoint",
                            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                            ".zip":  "application/zip",
                            ".txt":  "text/plain",
                            ".jpg":  "image/jpeg",
                            ".jpeg": "image/jpeg",
                            ".png":  "image/png",
                            ".gif":  "image/gif",
                            ".mp4":  "video/mp4",
                            ".mp3":  "audio/mpeg",
                        }
                        _inferred_mime = _EXT_TO_MIME.get(_ext, "")
                        print(
                            f"[RESOLVER] Preview scrape fallback: "
                            f"{_raw_title!r} mime={_inferred_mime!r}"
                        )
                        return {
                            "id":               file_id,
                            "name":             _raw_title,
                            "mime_type":        _inferred_mime,
                            "size":             0,
                            "md5":              "",
                            "download_url":     (
                                f"https://drive.usercontent.google.com/download"
                                f"?id={file_id}&export=download&authuser=0&confirm=t"
                            ),
                            "auth_headers":     _auth_headers_from_cookies(cookie_dict),
                            "web_content_link": "",
                            "export_links":     {},
                            "method":           "preview_scrape",
                            "is_workspace":     False,
                        }
        except Exception as _scrape_err:
            print(f"[RESOLVER] Preview scrape failed for {file_id}: {_scrape_err}")

    if not data:
        print(f"[RESOLVER] All methods failed for {file_id}")
        return {}

    raw_name  = data.get("name", "")
    mime_type = data.get("mimeType", "")
    size      = int(data.get("size", 0) or 0)
    md5       = data.get("md5Checksum", "")
    wcl       = data.get("webContentLink", "")
    exp_links = data.get("exportLinks", {})
    is_ws     = mime_type.startswith("application/vnd.google-apps.")

    # ── Best download URL + auth headers ──────────────────────────────────────
    if is_ws:
        # Google Workspace file → export to Office format
        export_mime = _WORKSPACE_MIMES.get(mime_type, "application/pdf")
        ext         = _WORKSPACE_EXTS.get(mime_type, ".pdf")
        download_url = (
            exp_links.get(export_mime)
            or f"https://www.googleapis.com/drive/v3/files/{file_id}"
              f"/export?mimeType={requests.utils.quote(export_mime)}&supportsAllDrives=true"
        )
        # Append file extension to name if missing
        if not raw_name.lower().endswith(ext):
            raw_name = raw_name + ext
        auth_headers = _build_auth_headers(token, cookie_dict)
    elif method in ("oauth", "oauth_refreshed"):
        # Direct API stream — fastest, no redirect needed
        download_url = (
            f"https://www.googleapis.com/drive/v3/files/{file_id}"
            f"?alt=media&supportsAllDrives=true"
        )
        auth_headers = {"Authorization": f"Bearer {token}"}
    elif method == "sapisidhash":
        # Same URL, SAPISIDHASH auth
        download_url = (
            f"https://www.googleapis.com/drive/v3/files/{file_id}"
            f"?alt=media&supportsAllDrives=true"
        )
        auth_headers = _auth_headers_from_cookies(cookie_dict)
    elif wcl:
        download_url = wcl
        auth_headers = {}
    else:
        download_url = (
            f"https://drive.usercontent.google.com/download"
            f"?id={file_id}&export=download&authuser=0&confirm=t"
        )
        auth_headers = {}

    result = {
        "id":               file_id,
        "name":             raw_name,
        "mime_type":        mime_type,
        "size":             size,
        "md5":              md5,
        "download_url":     download_url,
        "auth_headers":     auth_headers,
        "web_content_link": wcl,
        "export_links":     exp_links,
        "method":           method,
        "is_workspace":     is_ws,
        "_token":           token,   # may be refreshed — caller can save it
    }
    print(
        f"[RESOLVER] {file_id} → {raw_name!r} ({mime_type}) "
        f"{size} bytes method={method}"
    )
    return result


def download_file_direct(file_id: str,
                         dest_path: str,
                         auth_headers: dict,
                         download_url: str = "",
                         chunk_size: int = 4 * 1024 * 1024,
                         progress_cb=None,
                         cancel_fn=None) -> int:
    """
    Stream-download a Google Drive file directly using API v3 alt=media.
    Uses the caller-supplied auth_headers (Bearer or SAPISIDHASH).

    progress_cb(downloaded_bytes, total_bytes, speed_bps, elapsed_s, eta_s)
    cancel_fn() → True to abort (raises RuntimeError).
    Returns file size in bytes.
    """
    url = download_url or (
        f"https://www.googleapis.com/drive/v3/files/{file_id}"
        f"?alt=media&supportsAllDrives=true"
    )
    hdrs = {
        "User-Agent":      _SCRAPE_UA,
        "Accept-Encoding": "identity",
        **auth_headers,
    }

    resp = requests.get(url, headers=hdrs, stream=True, timeout=(20, 120))

    if resp.status_code == 401:
        raise PermissionError(f"[DIRECT DL] 401 Unauthorized — token expired for {file_id}")
    if resp.status_code == 403:
        try:
            msg = resp.json().get("error", {}).get("message", "Forbidden")
        except Exception:
            msg = "Forbidden"
        raise PermissionError(f"[DIRECT DL] 403 {msg} for {file_id}")
    if resp.status_code != 200:
        raise RuntimeError(f"[DIRECT DL] HTTP {resp.status_code} for {file_id}")

    total = int(resp.headers.get("Content-Length", 0) or 0)
    downloaded = 0
    start_t = time.monotonic()

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with open(dest_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if cancel_fn and cancel_fn():
                raise RuntimeError("Download cancelled")
            if chunk:
                fh.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    elapsed = time.monotonic() - start_t
                    speed   = downloaded / elapsed if elapsed > 0 else 0
                    eta     = (total - downloaded) / speed if (speed > 0 and total > downloaded) else 0
                    try:
                        progress_cb(downloaded, total, speed, elapsed, eta)
                    except Exception:
                        pass

    return downloaded


def list_folder_files_flat(folder_id: str,
                           cookies=None,
                           access_token: str = "",
                           refresh_token: str = "") -> list:
    """
    List all files in a folder and subfolders.
    Returns [(file_id, path/filename)] sorted naturally.
    Raises RuntimeError if nothing found.
    """
    tree = build_folder_tree(
        folder_id,
        cookies=cookies,
        access_token=access_token,
        refresh_token=refresh_token,
    )
    files = all_files_from_node(tree)
    if not files:
        raise RuntimeError("Folder mein koi file nahi mili.")

    result = [
        (f["id"], (f["path"] + "/" + f["name"]) if f.get("path") else f["name"],
         f.get("mimeType", ""))
        for f in files
    ]
    result.sort(key=lambda x: [
        int(c) if c.isdigit() else c.lower()
        for c in re.split(r"(\d+)", x[1])
    ])
    print(f"[GDRIVE] list_folder_files_flat: {len(result)} file(s) ✓")
    return result
