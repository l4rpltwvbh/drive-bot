import os
import time
from dotenv import load_dotenv
load_dotenv()
import dns.resolver
try:
    dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
    dns.resolver.default_resolver.nameservers = ['8.8.8.8', '1.1.1.1']
except Exception:
    pass
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI") or os.environ.get("MONGODB_URI") or "mongodb+srv://ftmbotzx:ftm@ftmbotzx.dapowof.mongodb.net/?appName=ftmbotzx"
DB_NAME = os.environ.get("DB_NAME", "drivebot")
_client = MongoClient(MONGO_URI)
_db = _client[DB_NAME]
settings_col      = _db["user_settings"]
db_topics_col     = _db["db_group_topics"]
users_col         = _db["users"]
download_hist_col  = _db["download_history"]
google_cookies_col = _db["google_cookies"]
ultra_plans_col   = _db["ultra_plans"]
ftm_session_col   = _db["ftm_session"]
file_cache_col      = _db["file_cache"]
folder_cache_col    = _db["folder_cache"]
drive_tree_cache_col = _db["drive_tree_cache"]
admins_col          = _db["admins"]
dump_exclude_col    = _db["dump_exclude"]


def get_admin_ids() -> list:
    """Return list of admin user IDs stored in DB."""
    return [doc["user_id"] for doc in admins_col.find({}, {"user_id": 1})]


def add_admin(user_id: int):
    admins_col.update_one({"user_id": user_id}, {"$set": {"user_id": user_id, "added_at": time.time()}}, upsert=True)


def remove_admin(user_id: int):
    admins_col.delete_one({"user_id": user_id})

FOLDER_TREE_TTL = 6 * 3600

SPEED_THREADS = {"normal": 4, "fast": 8, "max": 16}

DEFAULT_SETTINGS = {
    "upload_type": "video",
    "thumb_type": "auto",
    "custom_thumb_file_id": None,
    "folder_filter": "all",
    "speed_preset": "max",
}


def get_settings(user_id: int) -> dict:
    doc = settings_col.find_one({"user_id": user_id})
    if not doc:
        return dict(DEFAULT_SETTINGS)
    return {
        "upload_type":          doc.get("upload_type", "video"),
        "thumb_type":           doc.get("thumb_type", "auto"),
        "custom_thumb_file_id": doc.get("custom_thumb_file_id"),
        "folder_filter":        doc.get("folder_filter", "all"),
        "speed_preset":         doc.get("speed_preset", "max"),
    }


def set_upload_type(user_id: int, upload_type: str):
    settings_col.update_one({"user_id": user_id}, {"$set": {"upload_type": upload_type}}, upsert=True)


def set_thumb_type(user_id: int, thumb_type: str):
    settings_col.update_one({"user_id": user_id}, {"$set": {"thumb_type": thumb_type}}, upsert=True)


def set_custom_thumb(user_id: int, file_id: str):
    settings_col.update_one(
        {"user_id": user_id},
        {"$set": {"thumb_type": "custom", "custom_thumb_file_id": file_id}},
        upsert=True,
    )


def set_folder_filter(user_id: int, value: str):
    settings_col.update_one({"user_id": user_id}, {"$set": {"folder_filter": value}}, upsert=True)


def set_speed_preset(user_id: int, value: str):
    settings_col.update_one({"user_id": user_id}, {"$set": {"speed_preset": value}}, upsert=True)


def get_all_custom_thumbs() -> list:
    return list(settings_col.find(
        {"thumb_type": "custom", "custom_thumb_file_id": {"$ne": None}},
        {"user_id": 1, "custom_thumb_file_id": 1},
    ))


# ── User registry ─────────────────────────────────────────────────────────────

def save_user(user_id: int, name: str) -> bool:
    """Save/update user. Returns True if this is a brand-new user."""
    result = users_col.update_one(
        {"user_id": user_id},
        {
            "$set":       {"name": name},
            "$setOnInsert": {"user_id": user_id, "first_seen": time.time(), "total_downloads": 0},
        },
        upsert=True,
    )
    return result.upserted_id is not None


def get_all_users() -> list:
    return list(users_col.find({}, {"user_id": 1, "name": 1}))


def increment_downloads(user_id: int):
    users_col.update_one({"user_id": user_id}, {"$inc": {"total_downloads": 1}})


def get_user_downloads(user_id: int) -> int:
    doc = users_col.find_one({"user_id": user_id}, {"total_downloads": 1})
    return (doc or {}).get("total_downloads", 0)


# ── Delta Mode ────────────────────────────────────────────────────────────────

def get_delta_settings(user_id: int) -> dict:
    doc = settings_col.find_one({"user_id": user_id})
    if not doc:
        return {"delta_mode": False, "delta_channel_id": None, "delta_channel_title": None}
    return {
        "delta_mode":          doc.get("delta_mode", False),
        "delta_channel_id":    doc.get("delta_channel_id"),
        "delta_channel_title": doc.get("delta_channel_title"),
    }


def set_delta_channel(user_id: int, channel_id: int, channel_title: str):
    settings_col.update_one(
        {"user_id": user_id},
        {"$set": {"delta_channel_id": channel_id, "delta_channel_title": channel_title, "delta_mode": False}},
        upsert=True,
    )


def set_delta_mode(user_id: int, enabled: bool):
    settings_col.update_one({"user_id": user_id}, {"$set": {"delta_mode": enabled}}, upsert=True)


def clear_delta_channel(user_id: int):
    settings_col.update_one(
        {"user_id": user_id},
        {"$set": {"delta_channel_id": None, "delta_channel_title": None, "delta_mode": False}},
        upsert=True,
    )


# ── DB Group Topics ───────────────────────────────────────────────────────────

def get_db_group_topic(user_id: int):
    doc = db_topics_col.find_one({"user_id": user_id})
    return doc["thread_id"] if doc else None


def set_db_group_topic(user_id: int, thread_id: int):
    db_topics_col.update_one(
        {"user_id": user_id},
        {"$set": {"thread_id": thread_id}},
        upsert=True,
    )


def get_user_count() -> int:
    return users_col.count_documents({})


def get_all_user_ids() -> list:
    return [d["user_id"] for d in users_col.find({}, {"user_id": 1})]


def get_users_page(page: int, per_page: int = 8) -> list:
    """Return one page of users sorted by first_seen descending (newest first)."""
    skip = (page - 1) * per_page
    return list(
        users_col.find(
            {},
            {"user_id": 1, "name": 1, "first_seen": 1, "total_downloads": 1},
        ).sort("first_seen", -1).skip(skip).limit(per_page)
    )


def set_caption_prefix(user_id: int, prefix: str):
    settings_col.update_one(
        {"user_id": user_id},
        {"$set": {"caption_prefix": prefix}},
        upsert=True,
    )


def get_caption_prefix(user_id: int) -> str:
    doc = settings_col.find_one({"user_id": user_id}, {"caption_prefix": 1})
    return (doc or {}).get("caption_prefix", "") or ""


def set_caption_template(user_id: int, template: str):
    settings_col.update_one(
        {"user_id": user_id},
        {"$set": {"caption_template": template}},
        upsert=True,
    )


def get_caption_template(user_id: int) -> str:
    doc = settings_col.find_one({"user_id": user_id}, {"caption_template": 1})
    return (doc or {}).get("caption_template", "") or ""


# ── Google Cookies ────────────────────────────────────────────────────────────

def save_google_cookies(user_id: int, cookie_str: str):
    google_cookies_col.update_one(
        {"user_id": user_id},
        {"$set": {"cookie_str": cookie_str, "saved_at": time.time()}},
        upsert=True,
    )


def get_google_cookies(user_id: int) -> str | None:
    doc = google_cookies_col.find_one({"user_id": user_id})
    return doc["cookie_str"] if doc else None


def delete_google_cookies(user_id: int):
    google_cookies_col.delete_one({"user_id": user_id})


# ── OAuth Tokens ──────────────────────────────────────────────────────────────

oauth_tokens_col = _db["oauth_tokens"]

def save_oauth_tokens(user_id: int, access_token: str, refresh_token: str, expiry: float, email: str = "", name: str = ""):
    oauth_tokens_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "access_token":  access_token,
            "refresh_token": refresh_token,
            "expiry":        expiry,
            "email":         email,
            "name":          name,
            "saved_at":      time.time(),
        }},
        upsert=True,
    )

def get_oauth_tokens(user_id: int) -> dict | None:
    return oauth_tokens_col.find_one({"user_id": user_id})

def delete_oauth_tokens(user_id: int):
    oauth_tokens_col.delete_one({"user_id": user_id})


# ── Download History ──────────────────────────────────────────────────────────

def save_download_history(user_id: int, filename: str, size_bytes: int,
                          file_type: str, source_url: str, folder_url: str = None):
    download_hist_col.insert_one({
        "user_id":    user_id,
        "filename":   filename,
        "size_bytes": size_bytes,
        "file_type":  file_type,
        "source_url": source_url,
        "folder_url": folder_url,
        "ts":         time.time(),
    })
    increment_downloads(user_id)


def get_download_history(user_id: int, limit: int = 10) -> list:
    return list(
        download_hist_col.find(
            {"user_id": user_id},
            {"filename": 1, "size_bytes": 1, "file_type": 1, "ts": 1, "source_url": 1},
        ).sort("ts", -1).limit(limit)
    )


def get_user_full(user_id: int) -> dict:
    """Return combined user info: registry + settings + download count."""
    user_doc = users_col.find_one({"user_id": user_id}) or {}
    sett_doc = settings_col.find_one({"user_id": user_id}) or {}
    return {"user": user_doc, "settings": sett_doc}


def clear_database():
    settings_col.delete_many({})
    db_topics_col.delete_many({})
    users_col.delete_many({})
    download_hist_col.delete_many({})
    google_cookies_col.delete_many({})
    ultra_plans_col.delete_many({})


# ── Ultra Plan ────────────────────────────────────────────────────────────────

def has_ultra_plan(user_id: int) -> bool:
    doc = ultra_plans_col.find_one({"user_id": user_id})
    if not doc:
        return False
    expires_at = doc.get("expires_at")
    if expires_at and time.time() > expires_at:
        ultra_plans_col.delete_one({"user_id": user_id})
        return False
    return True


def add_ultra_plan(user_id: int, duration_days: int):
    expires_at = time.time() + duration_days * 86400
    ultra_plans_col.update_one(
        {"user_id": user_id},
        {"$set": {"expires_at": expires_at, "added_at": time.time(), "duration_days": duration_days}},
        upsert=True,
    )


def remove_ultra_plan(user_id: int):
    ultra_plans_col.delete_one({"user_id": user_id})


def get_ultra_plan(user_id: int) -> dict | None:
    doc = ultra_plans_col.find_one({"user_id": user_id})
    if not doc:
        return None
    expires_at = doc.get("expires_at")
    if expires_at and time.time() > expires_at:
        ultra_plans_col.delete_one({"user_id": user_id})
        return None
    return doc


# ── FTM Alpha Mode ────────────────────────────────────────────────────────────

def get_ftm_alpha(user_id: int) -> bool:
    doc = settings_col.find_one({"user_id": user_id}, {"ftm_alpha": 1})
    return bool((doc or {}).get("ftm_alpha", False))


def set_ftm_alpha(user_id: int, enabled: bool):
    settings_col.update_one({"user_id": user_id}, {"$set": {"ftm_alpha": enabled}}, upsert=True)


# ── File Cache (drive_file_id → dump_msg_id) ──────────────────────────────────

def get_file_cache(drive_file_id: str) -> dict | None:
    """Return cached dump channel info for a drive file, or None if not cached."""
    return file_cache_col.find_one({"drive_file_id": drive_file_id})


def set_file_cache(drive_file_id: str, dump_msg_id: int, fname: str,
                   file_type: str, file_size: int):
    """Save a drive file → dump channel message mapping."""
    file_cache_col.update_one(
        {"drive_file_id": drive_file_id},
        {"$set": {
            "dump_msg_id": dump_msg_id,
            "fname":       fname,
            "file_type":   file_type,
            "file_size":   file_size,
            "ts":          time.time(),
        }},
        upsert=True,
    )


# ── Drive Folder Tree Cache (folder_id → full tree structure) ─────────────────

def get_drive_folder_tree(folder_id: str) -> dict | None:
    """Return cached folder tree (structure + real name), or None if not cached/expired."""
    doc = drive_tree_cache_col.find_one({"folder_id": folder_id})
    if not doc:
        return None
    if time.time() - doc.get("ts", 0) > FOLDER_TREE_TTL:
        drive_tree_cache_col.delete_one({"folder_id": folder_id})
        return None
    return doc.get("tree")


def set_drive_folder_tree(folder_id: str, tree: dict):
    """Save folder tree (with real folder name) to cache."""
    drive_tree_cache_col.update_one(
        {"folder_id": folder_id},
        {"$set": {
            "tree":        tree,
            "folder_name": tree.get("name", ""),
            "total_files": tree.get("total_files", 0),
            "ts":          time.time(),
        }},
        upsert=True,
    )


# ── Cache Stats & Clear ───────────────────────────────────────────────────────

def get_cache_stats() -> dict:
    """Return counts and sizes for all three cache collections."""
    import time as _time
    now = _time.time()

    tree_docs   = list(drive_tree_cache_col.find({}, {"folder_id":1,"folder_name":1,"total_files":1,"ts":1}))
    folder_docs = list(folder_cache_col.find({},     {"folder_id":1,"ts":1,"files":1}))
    file_docs   = list(file_cache_col.find({},        {"drive_file_id":1,"fname":1,"file_size":1,"ts":1}))

    def _age(ts):
        diff = now - (ts or 0)
        if diff < 60:       return f"{int(diff)}s"
        if diff < 3600:     return f"{int(diff/60)}m"
        if diff < 86400:    return f"{int(diff/3600)}h"
        return f"{int(diff/86400)}d"

    total_file_size = sum(d.get("file_size", 0) for d in file_docs)

    return {
        "tree":   {"count": len(tree_docs),   "docs": tree_docs},
        "folder": {"count": len(folder_docs), "docs": folder_docs},
        "file":   {"count": len(file_docs),   "total_size": total_file_size, "docs": file_docs},
        "age_fn": _age,
    }


def clear_tree_cache(folder_id: str = None) -> int:
    """Delete tree cache. Pass folder_id to clear one, None to clear all. Returns deleted count."""
    if folder_id:
        r = drive_tree_cache_col.delete_one({"folder_id": folder_id})
    else:
        r = drive_tree_cache_col.delete_many({})
    return r.deleted_count


def clear_file_cache(file_id: str = None) -> int:
    """Delete file cache. Pass file_id to clear one, None to clear all. Returns deleted count."""
    if file_id:
        r = file_cache_col.delete_one({"drive_file_id": file_id})
    else:
        r = file_cache_col.delete_many({})
    return r.deleted_count


def clear_folder_cache(folder_id: str = None) -> int:
    """Delete folder cache. Pass folder_id to clear one, None to clear all. Returns deleted count."""
    if folder_id:
        r = folder_cache_col.delete_one({"folder_id": folder_id})
    else:
        r = folder_cache_col.delete_many({})
    return r.deleted_count


# ── Folder Cache (folder_id → file results) ───────────────────────────────────

def get_folder_cache(folder_id: str) -> dict | None:
    """Return cached folder file list, or None if not cached."""
    return folder_cache_col.find_one({"folder_id": folder_id})


def set_folder_cache(folder_id: str, files: list, folder_url: str = None):
    """Save folder processing results: list of {drive_file_id, dump_msg_id, fname, file_type, file_size}."""
    folder_cache_col.update_one(
        {"folder_id": folder_id},
        {"$set": {"files": files, "folder_url": folder_url, "ts": time.time()}},
        upsert=True,
    )


# ── FTM Session ───────────────────────────────────────────────────────────────

def get_ftm_session() -> str | None:
    doc = ftm_session_col.find_one({"_id": "ftm"})
    return doc.get("session_string") if doc else None


def set_ftm_session(session_string: str):
    ftm_session_col.update_one(
        {"_id": "ftm"},
        {"$set": {"session_string": session_string}},
        upsert=True,
    )


def delete_ftm_session():
    ftm_session_col.delete_one({"_id": "ftm"})


def get_expiring_plans(within_days: int = 3) -> list:
    now = time.time()
    cutoff = now + within_days * 86400
    docs = ultra_plans_col.find({
        "expires_at": {"$gt": now, "$lte": cutoff}
    })
    return list(docs)


# ── Dump Channel Exclude ───────────────────────────────────────────────────────

def add_dump_exclude(user_id: int):
    """Exclude a user from dump channel and folder DB channel logging."""
    dump_exclude_col.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "added_at": time.time()}},
        upsert=True,
    )


def remove_dump_exclude(user_id: int):
    """Remove a user from the dump exclude list."""
    dump_exclude_col.delete_one({"user_id": user_id})


def is_dump_excluded(user_id: int) -> bool:
    """Return True if this user's files should NOT go to dump/folder-DB channel."""
    return dump_exclude_col.find_one({"user_id": user_id}) is not None


def get_dump_excluded_users() -> list:
    """Return list of all excluded user IDs."""
    return [doc["user_id"] for doc in dump_exclude_col.find({}, {"user_id": 1})]


# ── Global Bot Config (file tag, etc.) ───────────────────────────────────────

global_config_col = _db["global_config"]


def get_file_tag_settings() -> dict:
    """Return global file tag settings: {tag: str, enabled: bool}."""
    doc = global_config_col.find_one({"_id": "file_tag"}) or {}
    return {
        "tag":     doc.get("tag", ""),
        "enabled": doc.get("enabled", False),
    }


def set_file_tag(tag: str):
    """Set (and enable) the global file tag."""
    global_config_col.update_one(
        {"_id": "file_tag"},
        {"$set": {"tag": tag.strip(), "enabled": True, "updated_at": time.time()}},
        upsert=True,
    )


def set_file_tag_enabled(enabled: bool):
    """Toggle the global file tag on or off."""
    global_config_col.update_one(
        {"_id": "file_tag"},
        {"$set": {"enabled": enabled, "updated_at": time.time()}},
        upsert=True,
    )


def clear_file_tag():
    """Remove the global file tag entirely."""
    global_config_col.delete_one({"_id": "file_tag"})
