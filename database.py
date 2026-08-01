import json
import os
from datetime import datetime

USERS_DIR = "users"
MEDIA_DIR = "media"
SESSIONS_DIR = "sessions"
COLLECTED_GROUPS_FILE = "collected_groups.json"

os.makedirs(USERS_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(SESSIONS_DIR, exist_ok=True)


def is_group_collected(chat_id: int) -> bool:
    if not os.path.exists(COLLECTED_GROUPS_FILE):
        return False
    with open(COLLECTED_GROUPS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return chat_id in data


def mark_group_collected(chat_id: int) -> None:
    if os.path.exists(COLLECTED_GROUPS_FILE):
        with open(COLLECTED_GROUPS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = []
    if chat_id not in data:
        data.append(chat_id)
        with open(COLLECTED_GROUPS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)

MAX_USERS = 200


def _user_file(user_id: int) -> str:
    return os.path.join(USERS_DIR, f"{user_id}.json")


def load_user(user_id: int) -> dict:
    path = _user_file(user_id)
    if not os.path.exists(path):
        default = {
            "user_id": user_id,
            "phone": None,
            "groups": [],
            "templates": [],
            "is_running": False,
            "next_template_id": 1,
            "stats": {
                "total_sent": 0,
                "successful": 0,
                "failed": 0,
                "last_sent": None,
            },
        }
        save_user(user_id, default)
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_user(user_id: int, data: dict) -> None:
    path = _user_file(user_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(path, 0o777)


def all_user_ids() -> list[int]:
    ids = []
    for fname in os.listdir(USERS_DIR):
        if fname.endswith(".json"):
            try:
                ids.append(int(fname[:-5]))
            except ValueError:
                pass
    return ids


def session_exists(user_id: int) -> bool:
    data = load_user(user_id)
    return bool(data.get("session_string"))


def active_users_count() -> int:
    return len([uid for uid in all_user_ids() if session_exists(uid)])


def update_stats(user_id: int, ok: int, fail: int, tpl_id: int = None) -> None:
    data = load_user(user_id)
    data["stats"]["total_sent"] += ok
    data["stats"]["successful"] += ok
    data["stats"]["failed"] += fail
    data["stats"]["last_sent"] = datetime.now().isoformat()
    if tpl_id is not None:
        now = datetime.now().isoformat()
        for tpl in data["templates"]:
            if tpl["id"] == tpl_id:
                tpl["last_sent"] = now
                break
    save_user(user_id, data)


def update_failed_groups(user_id: int, failures: dict, recovered: set = None) -> None:
    """failures = {chat_id: {"title": str, "reason": str}}, recovered = {chat_id, ...}"""
    data = load_user(user_id)
    stored = data.setdefault("failed_groups", {})
    now = datetime.now().isoformat()
    for chat_id, info in failures.items():
        stored[str(chat_id)] = {
            "title": info["title"],
            "reason": info["reason"],
            "time": now,
        }
    for chat_id in (recovered or set()):
        stored.pop(str(chat_id), None)
    save_user(user_id, data)


def clear_failed_group(user_id: int, chat_id: int) -> None:
    data = load_user(user_id)
    stored = data.get("failed_groups", {})
    stored.pop(str(chat_id), None)
    data["failed_groups"] = stored
    save_user(user_id, data)
