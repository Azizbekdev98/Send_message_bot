import asyncio
import json
import logging
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChatWriteForbiddenError,
    UserBannedInChannelError,
    ChannelPrivateError,
    UserNotParticipantError,
    ChatSendMediaForbiddenError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SESSIONS_DIR = "sessions"
USERS_DIR = "users"
MEDIA_DIR = "media"
MAX_USERS = 10
PAGE_SIZE = 20

os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(USERS_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)

(MAIN, WAIT_PHONE, WAIT_CODE, WAIT_2FA,
 WAIT_TPL_NAME, WAIT_TPL_MEDIA, WAIT_TPL_CAPTION, WAIT_EDIT_TEXT) = range(8)

scheduler = AsyncIOScheduler()
user_clients: dict[int, TelegramClient] = {}
phone_code_hashes: dict[int, str] = {}
phone_numbers: dict[int, str] = {}


# ─── User data helpers ────────────────────────────────────────────────────────

def user_data_file(user_id: int) -> str:
    return os.path.join(USERS_DIR, f"{user_id}.json")


def load_user(user_id: int) -> dict:
    f = user_data_file(user_id)
    if not os.path.exists(f):
        default = {
            "user_id": user_id,
            "phone": None,
            "groups": [],
            "templates": [],
            "active_template_id": None,
            "interval_minutes": 180,
            "is_running": False,
            "next_template_id": 1,
            "stats": {"total_sent": 0, "successful": 0, "failed": 0, "last_sent": None},
        }
        save_user(user_id, default)
        return default
    with open(f, "r", encoding="utf-8") as fp:
        return json.load(fp)


def save_user(user_id: int, data: dict) -> None:
    with open(user_data_file(user_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def registered_user_ids() -> list[int]:
    ids = []
    for fname in os.listdir(USERS_DIR):
        if fname.endswith(".json"):
            try:
                ids.append(int(fname[:-5]))
            except ValueError:
                pass
    return ids


def session_exists(user_id: int) -> bool:
    return os.path.exists(os.path.join(SESSIONS_DIR, f"{user_id}.session"))


def active_users_count() -> int:
    return len([uid for uid in registered_user_ids() if session_exists(uid)])


def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID


# ─── Keyboards ───────────────────────────────────────────────────────────────

def main_keyboard(is_running: bool) -> InlineKeyboardMarkup:
    toggle_label = "⏹ To'xtatish" if is_running else "▶️ Boshlash"
    toggle_cb = "stop_sending" if is_running else "start_sending"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Shablonlar", callback_data="templates")],
        [InlineKeyboardButton("👥 Mening Guruhlarim", callback_data="groups")],
        [InlineKeyboardButton("⚙️ Sozlamalar", callback_data="settings")],
        [InlineKeyboardButton("📊 Statistika", callback_data="stats")],
        [InlineKeyboardButton(toggle_label, callback_data=toggle_cb)],
    ])


def back_btn(cb: str, label: str = "🔙 Orqaga") -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=cb)


def _main_text(data: dict) -> str:
    status = "✅ Ishlayapti" if data["is_running"] else "⏸ To'xtatilgan"
    phone = data.get("phone") or "Noma'lum"
    return (
        f"🤖 *Reklama Boti*\n\n"
        f"📱 Telefon: `{phone}`\n"
        f"Holat: {status}\n"
        f"Guruhlar: {len(data['groups'])} ta\n"
        f"Shablonlar: {len(data['templates'])} ta\n\n"
        f"Bo'limni tanlang:"
    )


# ─── Start / Login ────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id

    if session_exists(user_id) and user_id in user_clients:
        data = load_user(user_id)
        await update.message.reply_text(
            _main_text(data),
            reply_markup=main_keyboard(data["is_running"]),
            parse_mode="Markdown",
        )
        return MAIN

    if not session_exists(user_id):
        count = active_users_count()
        if count >= MAX_USERS and not is_admin(user_id):
            await update.message.reply_text(
                f"❌ Botda joy yo'q!\n\n"
                f"Hozirda {count}/{MAX_USERS} ta foydalanuvchi bor.\n"
                f"Keyinroq urinib ko'ring."
            )
            return ConversationHandler.END

        await update.message.reply_text(
            "👋 *Xush kelibsiz!*\n\n"
            "Botdan foydalanish uchun Telegram raqamingizni kiriting:\n\n"
            "📱 Misol: `+998901234567`",
            parse_mode="Markdown",
        )
        return WAIT_PHONE

    await _connect_user(user_id, context.application)
    data = load_user(user_id)
    await update.message.reply_text(
        _main_text(data),
        reply_markup=main_keyboard(data["is_running"]),
        parse_mode="Markdown",
    )
    return MAIN


async def msg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    phone = update.message.text.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    session_path = os.path.join(SESSIONS_DIR, str(user_id))
    client = TelegramClient(session_path, config.API_ID, config.API_HASH)
    await client.connect()

    try:
        result = await client.send_code_request(phone)
        phone_code_hashes[user_id] = result.phone_code_hash
        phone_numbers[user_id] = phone
        user_clients[user_id] = client

        await update.message.reply_text(
            f"✅ Kod yuborildi: `{phone}`\n\n"
            "📲 Telegramga kelgan *tasdiqlash kodini* kiriting:",
            parse_mode="Markdown",
        )
        return WAIT_CODE
    except Exception as e:
        await client.disconnect()
        await update.message.reply_text(f"❌ Xato: {e}\n\nQayta urinib ko'ring:")
        return WAIT_PHONE


async def msg_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    code = update.message.text.strip().replace(" ", "")
    client = user_clients.get(user_id)
    if not client:
        await update.message.reply_text("❌ Xatolik. /start bosing.")
        return ConversationHandler.END

    try:
        await client.sign_in(
            phone=phone_numbers[user_id],
            code=code,
            phone_code_hash=phone_code_hashes[user_id],
        )
        data = load_user(user_id)
        data["phone"] = phone_numbers[user_id]
        save_user(user_id, data)
        phone_code_hashes.pop(user_id, None)
        phone_numbers.pop(user_id, None)
        me = await client.get_me()
        await update.message.reply_text(
            f"✅ *Muvaffaqiyatli kirildi!*\n\n"
            f"👤 {me.first_name} (@{me.username or 'username yo`q'})",
            reply_markup=main_keyboard(False),
            parse_mode="Markdown",
        )
        return MAIN
    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔐 *2FA parol* kerak.\n\nParolni kiriting:",
            parse_mode="Markdown",
        )
        return WAIT_2FA
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await update.message.reply_text("❌ Kod noto'g'ri yoki muddati o'tgan. Qayta kiriting:")
        return WAIT_CODE
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {e}")
        return WAIT_CODE


async def msg_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    password = update.message.text.strip()
    client = user_clients.get(user_id)
    if not client:
        await update.message.reply_text("❌ Xatolik. /start bosing.")
        return ConversationHandler.END

    try:
        await client.sign_in(password=password)
        data = load_user(user_id)
        data["phone"] = phone_numbers.get(user_id, data.get("phone"))
        save_user(user_id, data)
        phone_code_hashes.pop(user_id, None)
        phone_numbers.pop(user_id, None)
        me = await client.get_me()
        await update.message.reply_text(
            f"✅ *Muvaffaqiyatli kirildi!*\n\n"
            f"👤 {me.first_name} (@{me.username or 'username yo`q'})",
            reply_markup=main_keyboard(False),
            parse_mode="Markdown",
        )
        return MAIN
    except Exception as e:
        await update.message.reply_text(f"❌ Parol xato: {e}\nQayta kiriting:")
        return WAIT_2FA


async def cb_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = load_user(user_id)
    await query.edit_message_text(
        _main_text(data),
        reply_markup=main_keyboard(data["is_running"]),
        parse_mode="Markdown",
    )
    return MAIN


# ─── Templates ───────────────────────────────────────────────────────────────

def _templates_keyboard(templates: list, active_id) -> InlineKeyboardMarkup:
    buttons = []
    for t in templates:
        prefix = "✅ " if t["id"] == active_id else ""
        buttons.append([InlineKeyboardButton(f"{prefix}{t['name']}", callback_data=f"tpl_view_{t['id']}")])
    buttons.append([InlineKeyboardButton("➕ Yangi Shablon", callback_data="add_template")])
    buttons.append([back_btn("main_menu")])
    return InlineKeyboardMarkup(buttons)


async def cb_templates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = load_user(user_id)
    templates = data["templates"]
    text = (
        "📝 *Shablonlar*\n\nShablon tanlang yoki yangi qo'shing:"
        if templates else
        "📝 *Shablonlar*\n\nHali shablon yo'q. Yangi shablon qo'shing."
    )
    await query.edit_message_text(
        text,
        reply_markup=_templates_keyboard(templates, data["active_template_id"]),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_tpl_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    tpl_id = int(query.data.split("_")[-1])
    data = load_user(user_id)
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return MAIN
    is_active = data["active_template_id"] == tpl_id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Faol" if is_active else "☑️ Faollashtirish", callback_data=f"tpl_select_{tpl_id}")],
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"tpl_edit_{tpl_id}")],
        [InlineKeyboardButton("🗑 O'chirish", callback_data=f"tpl_delete_{tpl_id}")],
        [back_btn("templates")],
    ])
    icon = "📷" if tpl.get("type") == "photo" else "📝"
    preview = f"{icon} *{tpl['name']}*\n\n{tpl['text']}"
    if tpl.get("type") == "photo":
        photo_path = tpl.get("photo_path", "")
        if os.path.exists(photo_path):
            await query.message.reply_photo(
                photo=open(photo_path, "rb"),
                caption=preview,
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
            await query.message.delete()
            return MAIN
    await query.edit_message_text(preview, reply_markup=keyboard, parse_mode="Markdown")
    return MAIN


async def cb_add_template_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📝 *Yangi Shablon*\n\nShablon *nomini* kiriting:",
        reply_markup=InlineKeyboardMarkup([[back_btn("templates", "❌ Bekor qilish")]]),
        parse_mode="Markdown",
    )
    return WAIT_TPL_NAME


async def msg_tpl_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❌ Nom bo'sh bo'lishi mumkin emas:")
        return WAIT_TPL_NAME
    context.user_data["new_tpl_name"] = name
    await update.message.reply_text(
        f"✅ Nom: *{name}*\n\n"
        "📷 *Rasm yuboring* yoki ✏️ *Matn yozing*:",
        parse_mode="Markdown",
    )
    return WAIT_TPL_MEDIA


async def msg_tpl_media_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    data = load_user(user_id)
    tpl_id = data["next_template_id"]
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    photo_path = os.path.join(MEDIA_DIR, f"{user_id}_tpl_{tpl_id}.jpg")
    await tg_file.download_to_drive(photo_path)
    context.user_data["new_tpl_photo"] = photo_path
    await update.message.reply_text(
        "✅ Rasm qabul qilindi!\n\n*Caption* (matn) kiriting:",
        parse_mode="Markdown",
    )
    return WAIT_TPL_CAPTION


async def msg_tpl_media_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    data = load_user(user_id)
    tpl = {
        "id": data["next_template_id"],
        "name": context.user_data.pop("new_tpl_name", "Nomsiz"),
        "type": "text",
        "text": update.message.text.strip(),
        "created_at": datetime.now().isoformat(),
    }
    data["templates"].append(tpl)
    data["next_template_id"] += 1
    save_user(user_id, data)
    await update.message.reply_text(
        f"✅ Shablon saqlandi: *{tpl['name']}*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Shablonlarga", callback_data="templates")]]),
        parse_mode="Markdown",
    )
    return MAIN


async def msg_tpl_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    data = load_user(user_id)
    tpl = {
        "id": data["next_template_id"],
        "name": context.user_data.pop("new_tpl_name", "Nomsiz"),
        "type": "photo",
        "photo_path": context.user_data.pop("new_tpl_photo", ""),
        "text": update.message.text.strip(),
        "created_at": datetime.now().isoformat(),
    }
    data["templates"].append(tpl)
    data["next_template_id"] += 1
    save_user(user_id, data)
    await update.message.reply_text(
        f"✅ Shablon saqlandi: *{tpl['name']}* (📷 rasm + matn)",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Shablonlarga", callback_data="templates")]]),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_tpl_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    tpl_id = int(query.data.split("_")[-1])
    data = load_user(user_id)
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return MAIN
    data["active_template_id"] = tpl_id
    save_user(user_id, data)
    await query.answer(f"✅ '{tpl['name']}' faollashtirildi!", show_alert=True)
    await query.edit_message_text(
        f"📝 *{tpl['name']}*\n\n{tpl['text']}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Faol", callback_data=f"tpl_select_{tpl_id}")],
            [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"tpl_edit_{tpl_id}")],
            [InlineKeyboardButton("🗑 O'chirish", callback_data=f"tpl_delete_{tpl_id}")],
            [back_btn("templates")],
        ]),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_tpl_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    tpl_id = int(query.data.split("_")[-1])
    data = load_user(user_id)
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return MAIN
    context.user_data["edit_tpl_id"] = tpl_id
    await query.edit_message_text(
        f"✏️ *{tpl['name']}* — yangi matnni kiriting:\n\n_Hozirgi:_\n{tpl['text']}",
        reply_markup=InlineKeyboardMarkup([[back_btn(f"tpl_view_{tpl_id}", "❌ Bekor qilish")]]),
        parse_mode="Markdown",
    )
    return WAIT_EDIT_TEXT


async def msg_tpl_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    tpl_id = context.user_data.pop("edit_tpl_id", None)
    if tpl_id is None:
        await update.message.reply_text("Xatolik. /start bosing.")
        return MAIN
    data = load_user(user_id)
    for t in data["templates"]:
        if t["id"] == tpl_id:
            t["text"] = update.message.text.strip()
            break
    save_user(user_id, data)
    await update.message.reply_text(
        "✅ Shablon yangilandi!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Shablonlarga", callback_data="templates")]]),
    )
    return MAIN


async def cb_tpl_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    tpl_id = int(query.data.split("_")[-1])
    data = load_user(user_id)
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return MAIN
    data["templates"] = [t for t in data["templates"] if t["id"] != tpl_id]
    if data["active_template_id"] == tpl_id:
        data["active_template_id"] = None
    save_user(user_id, data)
    await query.answer(f"🗑 '{tpl['name']}' o'chirildi!", show_alert=True)
    templates = data["templates"]
    await query.edit_message_text(
        "📝 *Shablonlar*\n\nShablon tanlang:" if templates else "📝 *Shablonlar*\n\nHali shablon yo'q.",
        reply_markup=_templates_keyboard(templates, data["active_template_id"]),
        parse_mode="Markdown",
    )
    return MAIN


# ─── Groups ──────────────────────────────────────────────────────────────────

def _groups_keyboard(groups: list) -> InlineKeyboardMarkup:
    buttons = []
    for g in groups:
        title = (g.get("title") or str(g["chat_id"]))[:30]
        buttons.append([InlineKeyboardButton(f"❌ {title}", callback_data=f"rm_group_{g['chat_id']}")])
    buttons.append([InlineKeyboardButton("🔄 Guruhlarni yuklash", callback_data="fetch_groups")])
    buttons.append([back_btn("main_menu")])
    return InlineKeyboardMarkup(buttons)


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
    await query.edit_message_text(text, reply_markup=_groups_keyboard(groups), parse_mode="Markdown")
    return MAIN


async def _show_dialogs_page(query, dialogs: list, existing_ids: set, page: int) -> None:
    start = page * PAGE_SIZE
    chunk = dialogs[start: start + PAGE_SIZE]
    buttons = []
    for i, d in enumerate(chunk):
        is_added = d["chat_id"] in existing_ids
        icon = "✅" if is_added else "➕"
        buttons.append([InlineKeyboardButton(
            f"{icon} {d['title'][:28]}", callback_data=f"tgl_group_{start + i}"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"dlg_page_{page - 1}"))
    if start + PAGE_SIZE < len(dialogs):
        nav.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"dlg_page_{page + 1}"))
    if nav:
        buttons.append(nav)
    added = sum(1 for d in dialogs if d["chat_id"] in existing_ids)
    buttons.append([back_btn("groups")])
    total_pages = (len(dialogs) - 1) // PAGE_SIZE + 1
    await query.edit_message_text(
        f"📋 *Guruhlaringiz* — {len(dialogs)} ta (sahifa {page + 1}/{total_pages})\n"
        f"Tanlangan: *{added}* ta\n\n✅ tanlangan | ➕ tanlash uchun bosing:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def cb_fetch_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    client = user_clients.get(user_id)
    if not client or not client.is_connected():
        await query.answer("❌ Telethon ulanmagan! /start bosing.", show_alert=True)
        return MAIN
    await query.edit_message_text("⏳ Guruhlar yuklanmoqda...")
    dialogs = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        is_group = dialog.is_group
        is_supergroup = dialog.is_channel and getattr(entity, "megagroup", False)
        is_broadcast = dialog.is_channel and getattr(entity, "broadcast", False)
        can_post = is_broadcast and getattr(entity, "admin_rights", None) and getattr(entity.admin_rights, "post_messages", False)
        if is_group or is_supergroup or can_post:
            dialogs.append({"chat_id": dialog.id, "title": dialog.title or str(dialog.id)})
    context.user_data["fetched_dialogs"] = dialogs
    context.user_data["dlg_page"] = 0
    data = load_user(user_id)
    existing_ids = {g["chat_id"] for g in data["groups"]}
    await _show_dialogs_page(query, dialogs, existing_ids, 0)
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
        data["groups"].append({"chat_id": d["chat_id"], "title": d["title"], "added_at": datetime.now().isoformat()})
        await query.answer(f"✅ '{d['title'][:20]}' qo'shildi")
    save_user(user_id, data)
    existing_ids = {g["chat_id"] for g in data["groups"]}
    await _show_dialogs_page(query, dialogs, existing_ids, context.user_data.get("dlg_page", 0))
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
    await _show_dialogs_page(query, dialogs, existing_ids, page)
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
    await query.edit_message_text(text, reply_markup=_groups_keyboard(groups), parse_mode="Markdown")
    return MAIN


# ─── Settings ────────────────────────────────────────────────────────────────

def _interval_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} daqiqa"
    return f"{minutes // 60} soat"


def _settings_keyboard(current: int) -> InlineKeyboardMarkup:
    options = [1, 60, 120, 180, 360, 720]
    rows = []
    row = []
    for m in options:
        tick = "✅ " if m == current else ""
        row.append(InlineKeyboardButton(f"{tick}{_interval_label(m)}", callback_data=f"set_interval_{m}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([back_btn("main_menu")])
    return InlineKeyboardMarkup(rows)


async def cb_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = load_user(user_id)
    current = data.get("interval_minutes", 180)
    await query.edit_message_text(
        f"⚙️ *Sozlamalar*\n\nHozirgi interval: *{_interval_label(current)}*\n\nYangi interval tanlang:",
        reply_markup=_settings_keyboard(current),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    minutes = int(query.data.split("_")[-1])
    data = load_user(user_id)
    data["interval_minutes"] = minutes
    save_user(user_id, data)
    if data["is_running"]:
        _reschedule_user(context.application, user_id, minutes)
    await query.answer(f"✅ Interval {_interval_label(minutes)}ga o'rnatildi!", show_alert=True)
    await query.edit_message_text(
        f"⚙️ *Sozlamalar*\n\nHozirgi interval: *{_interval_label(minutes)}*\n\nYangi interval tanlang:",
        reply_markup=_settings_keyboard(minutes),
        parse_mode="Markdown",
    )
    return MAIN


# ─── Stats ───────────────────────────────────────────────────────────────────

async def cb_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = load_user(user_id)
    stats = data["stats"]
    active_tpl = next((t for t in data["templates"] if t["id"] == data["active_template_id"]), None)
    last_sent = stats.get("last_sent")
    if last_sent:
        try:
            last_sent = datetime.fromisoformat(last_sent).strftime("%d.%m.%Y %H:%M")
        except Exception:
            pass
    else:
        last_sent = "Hali yuborilmagan"
    status = "✅ Ishlayapti" if data["is_running"] else "⏸ To'xtatilgan"
    await query.edit_message_text(
        f"📊 *Statistika*\n\n"
        f"🔄 Holat: {status}\n"
        f"⏰ Interval: {_interval_label(data.get('interval_minutes', 180))}\n"
        f"👥 Guruhlar: {len(data['groups'])} ta\n"
        f"📝 Faol shablon: {active_tpl['name'] if active_tpl else 'Tanlanmagan'}\n\n"
        f"📤 Jami yuborildi: {stats['total_sent']}\n"
        f"✅ Muvaffaqiyatli: {stats['successful']}\n"
        f"❌ Xatolik: {stats['failed']}\n"
        f"🕐 Oxirgi: {last_sent}",
        reply_markup=InlineKeyboardMarkup([[back_btn("main_menu")]]),
        parse_mode="Markdown",
    )
    return MAIN


# ─── Sending logic ───────────────────────────────────────────────────────────

async def _do_send(application: Application, user_id: int) -> None:
    data = load_user(user_id)
    if not data["is_running"]:
        return
    client = user_clients.get(user_id)
    if not client or not client.is_connected():
        logger.warning(f"User {user_id}: client not connected")
        return
    active_id = data.get("active_template_id")
    if not active_id:
        return
    tpl = next((t for t in data["templates"] if t["id"] == active_id), None)
    if not tpl or not data["groups"]:
        return

    is_photo = tpl.get("type") == "photo"
    photo_path = tpl.get("photo_path", "") if is_photo else ""
    skipped_member_req = []
    ok = fail = 0

    for group in data["groups"]:
        chat_id = group["chat_id"]
        title = group.get("title", str(chat_id))
        try:
            if is_photo and os.path.exists(photo_path):
                try:
                    await client.send_file(chat_id, photo_path, caption=tpl["text"])
                except ChatSendMediaForbiddenError:
                    # Rasm yuborib bo'lmasa — faqat text yuboramiz
                    await client.send_message(chat_id, tpl["text"])
                    logger.info(f"Media forbidden in {title}, sent text only")
            else:
                await client.send_message(chat_id, tpl["text"])
            ok += 1
            logger.info(f"[{user_id}] Sent to {title}")
        except FloodWaitError as e:
            logger.warning(f"FloodWait {e.seconds}s for {title}")
            await asyncio.sleep(e.seconds)
            try:
                await client.send_message(chat_id, tpl["text"])
                ok += 1
            except Exception:
                fail += 1
        except UserNotParticipantError:
            # A'zo bo'lish talab qilinsa — o'tkazib yuboramiz
            skipped_member_req.append(title)
            logger.warning(f"Members required in {title}, skipped")
        except (ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError) as e:
            logger.warning(f"Cannot send to {title}: {type(e).__name__}")
            fail += 1
        except Exception as e:
            logger.error(f"Error sending to {title}: {e}")
            fail += 1
        await asyncio.sleep(2)

    data = load_user(user_id)
    data["stats"]["total_sent"] += ok
    data["stats"]["successful"] += ok
    data["stats"]["failed"] += fail
    data["stats"]["last_sent"] = datetime.now().isoformat()
    save_user(user_id, data)
    logger.info(f"[{user_id}] Cycle done — sent: {ok}, failed: {fail}, skipped: {len(skipped_member_req)}")

    # A'zo talab qilgan guruhlar haqida foydalanuvchiga xabar
    if skipped_member_req:
        try:
            names = "\n".join(f"• {n}" for n in skipped_member_req[:10])
            await application.bot.send_message(
                chat_id=user_id,
                text=(
                    f"⚠️ Quyidagi guruhlar a'zo qo'shishni talab qildi — o'tkazib yuborildi:\n\n{names}\n\n"
                    f"Bu guruhlariga qo'lda a'zo qo'shing yoki ularni ro'yxatdan olib tashlang."
                ),
            )
        except Exception:
            pass


def _reschedule_user(application: Application, user_id: int, minutes: int, run_now: bool = False) -> None:
    from datetime import timedelta
    job_id = f"send_{user_id}"
    kwargs = dict(
        trigger="interval",
        minutes=minutes,
        args=[application, user_id],
        id=job_id,
        replace_existing=True,
    )
    if run_now:
        kwargs["next_run_time"] = datetime.now() + timedelta(seconds=3)
    scheduler.add_job(_do_send, **kwargs)


async def cb_start_sending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    data = load_user(user_id)
    if not data["active_template_id"]:
        await query.answer("❌ Avval faol shablon tanlang!", show_alert=True)
        return MAIN
    if not data["groups"]:
        await query.answer("❌ Avval guruh qo'shing!", show_alert=True)
        return MAIN
    client = user_clients.get(user_id)
    if not client or not client.is_connected():
        await query.answer("❌ Sessiya ulanmagan! /start bosing.", show_alert=True)
        return MAIN
    data["is_running"] = True
    save_user(user_id, data)
    _reschedule_user(context.application, user_id, data.get("interval_minutes", 180), run_now=True)
    await query.answer("✅ Yuborish boshlandi!", show_alert=True)
    await query.edit_message_text(
        _main_text(data),
        reply_markup=main_keyboard(True),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_stop_sending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    data = load_user(user_id)
    data["is_running"] = False
    save_user(user_id, data)
    job_id = f"send_{user_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    await query.answer("⏸ Yuborish to'xtatildi!", show_alert=True)
    await query.edit_message_text(
        _main_text(data),
        reply_markup=main_keyboard(False),
        parse_mode="Markdown",
    )
    return MAIN


# ─── Connect existing users ───────────────────────────────────────────────────

async def _connect_user(user_id: int, application: Application) -> bool:
    session_path = os.path.join(SESSIONS_DIR, str(user_id))
    client = TelegramClient(session_path, config.API_ID, config.API_HASH)
    try:
        await client.connect()
        if await client.is_user_authorized():
            user_clients[user_id] = client
            data = load_user(user_id)
            if data["is_running"] and data.get("active_template_id") and data["groups"]:
                _reschedule_user(application, user_id, data.get("interval_minutes", 180))
                logger.info(f"User {user_id}: sending resumed")
            return True
        else:
            await client.disconnect()
            return False
    except Exception as e:
        logger.error(f"User {user_id} connect error: {e}")
        return False


# ─── Lifecycle ───────────────────────────────────────────────────────────────

async def post_init(application: Application) -> None:
    scheduler.start()
    for uid in registered_user_ids():
        if session_exists(uid):
            await _connect_user(uid, application)
    logger.info(f"Bot ishga tushdi. Faol foydalanuvchilar: {len(user_clients)}")


async def post_shutdown(application: Application) -> None:
    for client in user_clients.values():
        if client.is_connected():
            await client.disconnect()
    if scheduler.running:
        scheduler.shutdown(wait=False)


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            MAIN: [
                CallbackQueryHandler(cb_main_menu, pattern="^main_menu$"),
                CallbackQueryHandler(cb_templates, pattern="^templates$"),
                CallbackQueryHandler(cb_tpl_view, pattern=r"^tpl_view_\d+$"),
                CallbackQueryHandler(cb_add_template_start, pattern="^add_template$"),
                CallbackQueryHandler(cb_tpl_select, pattern=r"^tpl_select_\d+$"),
                CallbackQueryHandler(cb_tpl_edit_start, pattern=r"^tpl_edit_\d+$"),
                CallbackQueryHandler(cb_tpl_delete, pattern=r"^tpl_delete_\d+$"),
                CallbackQueryHandler(cb_groups, pattern="^groups$"),
                CallbackQueryHandler(cb_fetch_groups, pattern="^fetch_groups$"),
                CallbackQueryHandler(cb_toggle_group, pattern=r"^tgl_group_\d+$"),
                CallbackQueryHandler(cb_dlg_page, pattern=r"^dlg_page_\d+$"),
                CallbackQueryHandler(cb_remove_group, pattern=r"^rm_group_"),
                CallbackQueryHandler(cb_settings, pattern="^settings$"),
                CallbackQueryHandler(cb_set_interval, pattern=r"^set_interval_\d+$"),
                CallbackQueryHandler(cb_stats, pattern="^stats$"),
                CallbackQueryHandler(cb_start_sending, pattern="^start_sending$"),
                CallbackQueryHandler(cb_stop_sending, pattern="^stop_sending$"),
            ],
            WAIT_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_phone),
            ],
            WAIT_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_code),
            ],
            WAIT_2FA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_2fa),
            ],
            WAIT_TPL_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_name),
                CallbackQueryHandler(cb_templates, pattern="^templates$"),
            ],
            WAIT_TPL_MEDIA: [
                MessageHandler(filters.PHOTO, msg_tpl_media_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_media_text),
            ],
            WAIT_TPL_CAPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_caption),
            ],
            WAIT_EDIT_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_edit_text),
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        per_message=False,
    )

    application.add_handler(conv)
    logger.info("Bot ishga tushdi...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
