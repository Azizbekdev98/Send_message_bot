import asyncio
import logging
import os

from telethon.errors import (
    FloodWaitError,
    SlowModeWaitError,
    ChatWriteForbiddenError,
    UserBannedInChannelError,
    ChannelPrivateError,
    UserNotParticipantError,
    ChatSendMediaForbiddenError,
    ChatSendPhotosForbiddenError,
    ChatRestrictedError,
)

from database import load_user, save_user, update_stats, update_failed_groups
from services.userbot import is_connected, get_client

logger = logging.getLogger(__name__)


async def _add_contacts_to_group(client, user_id: int, chat_id, title: str, to_add: list) -> int:
    """Guruhga berilgan kontaktlar ro'yxatini qo'shadi. Qo'shilganlar sonini qaytaradi."""
    from telethon.tl.functions.channels import InviteToChannelRequest
    from telethon.errors import UserPrivacyRestrictedError, UserNotMutualContactError, ChatAdminRequiredError, UserAlreadyParticipantError

    if not to_add:
        return 0

    added = 0
    for user in to_add:
        try:
            await client(InviteToChannelRequest(chat_id, [user]))
            added += 1
            logger.info(f"[{user_id}] guruhga qo'shildi: {user.first_name} → {title}")
        except ChatAdminRequiredError:
            logger.info(f"[{user_id}] {title}: admin huquqi kerak, o'tkazildi")
            break
        except UserAlreadyParticipantError:
            continue
        except (UserPrivacyRestrictedError, UserNotMutualContactError):
            continue
        except Exception as e:
            logger.warning(f"[{user_id}] qo'shishda xato ({user.first_name} → {title}): {type(e).__name__}: {e}")
            continue
        await asyncio.sleep(1)

    return added


async def _get_required_members(client, entity, after_msg_id: int) -> int:
    """Bot javobidan nechta odam qo'shish kerakligini o'qiydi va tasdiqlash tugmasini bosadi."""
    import re
    await asyncio.sleep(3)
    count_found = 0
    try:
        msgs = await client.get_messages(entity, limit=5)
        for msg in msgs:
            if not msg or msg.id <= after_msg_id:
                continue
            if not msg.sender or not getattr(msg.sender, 'bot', False):
                continue
            text = msg.text or msg.message or ""
            if not count_found:
                numbers = re.findall(r'\b(\d+)\b', text)
                for n in numbers:
                    c = int(n)
                    if 1 <= c <= 50:
                        logger.info(f"Bot javobidan talab: {c} odam, xabar: {text[:80]}")
                        count_found = c
                        break
            # Barcha tugmalarni ko'rib chiqish
            if msg.buttons:
                # Avval URL tugmalardan kanalga a'zo bo'lish
                for row in msg.buttons:
                    for btn in row:
                        url = getattr(btn, 'url', None) or ""
                        if url and ("t.me/" in url or "telegram.me/" in url):
                            try:
                                username = url.split("t.me/")[-1].split("telegram.me/")[-1].split("?")[0].strip("/")
                                if username:
                                    from telethon.tl.functions.channels import JoinChannelRequest
                                    await client(JoinChannelRequest(username))
                                    logger.info(f"Kanalga a'zo bo'lindi: {username}")
                                    await asyncio.sleep(2)
                            except Exception as e:
                                logger.warning(f"Kanalga a'zo bo'lishda xato: {e}")

                # Keyin barcha callback tugmalarini bosamiz
                for row in msg.buttons:
                    for btn in row:
                        if not getattr(btn, 'url', None):
                            try:
                                await btn.click()
                                logger.info(f"Anti-spam bot tugmasi bosildi: {btn.text}")
                                await asyncio.sleep(1)
                            except Exception:
                                pass
    except Exception:
        pass
    return count_found


async def send_template(bot, user_id: int, tpl_id: int) -> None:
    """Bitta shablon uchun yuborish."""
    data = load_user(user_id)
    if not data["is_running"]:
        return
    if not is_connected(user_id):
        logger.warning(f"[{user_id}] Client not connected")
        return

    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl or not tpl.get("is_active"):
        return
    if not data["groups"]:
        return

    client = get_client(user_id)
    is_photo = tpl.get("type") == "photo"
    photo_path = tpl.get("photo_path", "") if is_photo else ""

    # Kontaktlarni bir marta olamiz
    contacts = []
    try:
        from telethon.tl.functions.contacts import GetContactsRequest
        result = await client(GetContactsRequest(hash=0))
        contacts = [u for u in result.users if not u.bot]
        logger.info(f"[{user_id}] {len(contacts)} ta kontakt olindi")
    except Exception as e:
        logger.warning(f"[{user_id}] Kontaktlarni olishda xato: {e}")
    text = tpl["text"]

    ok = fail = 0
    failures: dict = {}
    recovered: set = set()
    contact_offset = 0  # har guruhga boshqa-boshqa kontakt qo'shish uchun

    REASONS = {
        "UserNotParticipantError": "Siz bu guruhga a'zo emassiz",
        "ChatWriteForbiddenError": "Bu guruhda faqat adminlar yoza oladi",
        "UserBannedInChannelError": "Siz bu guruhdan ban qilingansiz",
        "ChannelPrivateError": "Bu guruh yopiq yoki o'chirilgan",
    }

    for group in data["groups"]:
        chat_id = group["chat_id"]
        title = group.get("title", str(chat_id))
        try:
            try:
                entity = await client.get_input_entity(chat_id)
            except Exception:
                entity = chat_id

            # Xabar yuborish
            sent_msg = None
            if is_photo and os.path.exists(photo_path):
                try:
                    sent_msg = await client.send_file(entity, photo_path, caption=text)
                except (ChatSendMediaForbiddenError, ChatSendPhotosForbiddenError):
                    sent_msg = await client.send_message(entity, text)
            else:
                sent_msg = await client.send_message(entity, text)

            # Xabar o'chirilmagunicha odam qo'shib qayta yuboramiz (max 5 urinish)
            for attempt in range(5):
                await asyncio.sleep(3)
                try:
                    check = await client.get_messages(entity, ids=sent_msg.id)
                    msg_deleted = check is None or (hasattr(check, 'id') is False)
                except Exception:
                    msg_deleted = False

                if not msg_deleted:
                    break  # Xabar turibdi — muvaffaqiyatli

                # Bot javobidan nechta odam kerakligini o'qiymiz va tugmani bosamiz
                required = await _get_required_members(client, entity, sent_msg.id)
                needed = required if required > 0 else 5
                logger.info(f"[{user_id}] {title}: o'chirildi, {needed} odam qo'shamiz")

                # Rotatsiya: har guruhga boshqa kontaktlar
                if contacts:
                    start = contact_offset % len(contacts)
                    to_add = (contacts[start:] + contacts[:start])[:needed]
                    contact_offset += needed
                else:
                    to_add = []

                added = await _add_contacts_to_group(client, user_id, entity, title, to_add=to_add)
                if not added:
                    logger.info(f"[{user_id}] {title}: kontakt qo'shib bo'lmadi")
                    break

                await asyncio.sleep(3)
                try:
                    if is_photo and os.path.exists(photo_path):
                        try:
                            sent_msg = await client.send_file(entity, photo_path, caption=text)
                        except (ChatSendMediaForbiddenError, ChatSendPhotosForbiddenError):
                            sent_msg = await client.send_message(entity, text)
                    else:
                        sent_msg = await client.send_message(entity, text)
                except Exception:
                    break

            ok += 1
            recovered.add(chat_id)
            logger.info(f"[{user_id}] tpl={tpl_id} ✅ {title}")

        except FloodWaitError as e:
            logger.warning(f"[{user_id}] FloodWait {e.seconds}s")
            await asyncio.sleep(min(e.seconds, 60))
            try:
                await client.send_message(entity, text)
                ok += 1
            except Exception as e2:
                fail += 1
                failures[chat_id] = {"title": title, "reason": f"Flood + xato: {type(e2).__name__}"}

        except SlowModeWaitError as e:
            logger.warning(f"[{user_id}] SlowMode {e.seconds}s — {title}")
            await asyncio.sleep(min(e.seconds, 60))
            try:
                if is_photo and os.path.exists(photo_path):
                    try:
                        await client.send_file(entity, photo_path, caption=text)
                    except (ChatSendMediaForbiddenError, ChatSendPhotosForbiddenError):
                        await client.send_message(entity, text)
                else:
                    await client.send_message(entity, text)
                ok += 1
            except Exception:
                fail += 1
                failures[chat_id] = {"title": title, "reason": f"Guruhda cheklangan rejim — {e.seconds} soniya kutish kerak"}

        except UserNotParticipantError:
            fail += 1
            failures[chat_id] = {"title": title, "reason": REASONS["UserNotParticipantError"]}

        except (ChatWriteForbiddenError, ChatRestrictedError):
            fail += 1
            failures[chat_id] = {"title": title, "reason": "Bu guruhda faqat adminlar yoza oladi"}

        except UserBannedInChannelError:
            fail += 1
            failures[chat_id] = {"title": title, "reason": "Siz bu guruhdan ban qilingansiz"}

        except ChannelPrivateError:
            fail += 1
            failures[chat_id] = {"title": title, "reason": "Bu guruh yopiq yoki o'chirilgan"}

        except Exception as e:
            fail += 1
            err = str(e)[:60] if str(e) else type(e).__name__
            failures[chat_id] = {"title": title, "reason": f"Noma'lum xato: {err}"}
            logger.error(f"[{user_id}] tpl={tpl_id} '{title}': {e}")

        await asyncio.sleep(2)

    update_stats(user_id, ok, fail, tpl_id=tpl_id)
    if failures or recovered:
        update_failed_groups(user_id, failures, recovered=recovered)
    logger.info(f"[{user_id}] tpl={tpl_id} done — ok:{ok} fail:{fail}")


async def send_for_user(application, user_id: int) -> None:
    """Eski kod bilan moslik uchun — barcha faol shablonlarni yuboradi."""
    data = load_user(user_id)
    for tpl in data["templates"]:
        if tpl.get("is_active"):
            await send_template(application.bot, user_id, tpl["id"])
