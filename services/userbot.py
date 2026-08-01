import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from database import all_user_ids, load_user

logger = logging.getLogger(__name__)

_clients: dict[int, TelegramClient] = {}


def get_client(user_id: int) -> TelegramClient | None:
    return _clients.get(user_id)


def set_client(user_id: int, client: TelegramClient) -> None:
    _clients[user_id] = client


def remove_client(user_id: int) -> None:
    _clients.pop(user_id, None)


def is_connected(user_id: int) -> bool:
    c = _clients.get(user_id)
    return c is not None and c.is_connected()


async def connect_user(user_id: int, api_id: int, api_hash: str) -> bool:
    data = load_user(user_id)
    session_str = data.get("session_string")
    if not session_str:
        return False
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    try:
        await client.connect()
        if await client.is_user_authorized():
            _clients[user_id] = client
            logger.info(f"User {user_id} connected via StringSession")
            return True
        await client.disconnect()
        return False
    except Exception as e:
        logger.error(f"User {user_id} connect error: {e}")
        return False


async def connect_all_users(api_id: int, api_hash: str) -> None:
    for uid in all_user_ids():
        data = load_user(uid)
        if data.get("session_string") and uid not in _clients:
            await connect_user(uid, api_id, api_hash)


async def disconnect_all() -> None:
    for uid, client in list(_clients.items()):
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:
            pass
    _clients.clear()
