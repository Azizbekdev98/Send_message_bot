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

SESSION_FILE = "userbot_session"
tele_client: TelegramClient | None = None

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DATA_FILE = "data.json"

MAIN, WAIT_TPL_NAME, WAIT_TPL_MEDIA, WAIT_TPL_CAPTION, WAIT_EDIT_TEXT = range(5)
MEDIA_DIR = "media"

scheduler = AsyncIOScheduler()


# ─── Data helpers ────────────────────────────────────────────────────────────

def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        default = {
            "groups": [],
            "templates": [],
            "active_template_id": None,
            "interval_minutes": 180,
            "is_running": False,
            "next_template_id": 1,
            "stats": {
                "total_sent": 0,
                "successful": 0,
                "failed": 0,
                "last_sent": None,
            },
        }
        save_data(default)
        return default
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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


# ─── Main menu ───────────────────────────────────────────────────────────────

def _main_text(data: dict) -> str:
    status = "✅ Ishlayapti" if data["is_running"] else "⏸ To'xtatilgan"
    return (
        f"🤖 *Reklama Boti*\n\n"
        f"Holat: {status}\n"
        f"Guruhlar: {len(data['groups'])} ta\n"
        f"Shablonlar: {len(data['templates'])} ta\n\n"
        f"Bo'limni tanlang:"
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Ruxsat yo'q!")
        return ConversationHandler.END
    data = load_data()
    await update.message.reply_text(
        _main_text(data),
        reply_markup=main_keyboard(data["is_running"]),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = load_data()
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
    data = load_data()
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
    tpl_id = int(query.data.split("_")[-1])
    data = load_data()
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return MAIN
    is_active = data["active_template_id"] == tpl_id
    activate_label = "✅ Faol (tanlangan)" if is_active else "☑️ Faollashtirish"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(activate_label, callback_data=f"tpl_select_{tpl_id}")],
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"tpl_edit_{tpl_id}")],
        [InlineKeyboardButton("🗑 O'chirish", callback_data=f"tpl_delete_{tpl_id}")],
        [back_btn("templates")],
    ])
    is_photo = tpl.get("type") == "photo"
    icon = "📷" if is_photo else "📝"
    preview = f"{icon} *{tpl['name']}*\n\n{tpl['text']}"
    if is_photo:
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
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❌ Nom bo'sh bo'lishi mumkin emas. Qayta kiriting:")
        return WAIT_TPL_NAME
    context.user_data["new_tpl_name"] = name
    await update.message.reply_text(
        f"✅ Nom: *{name}*\n\n"
        "📷 *Rasm yuboring* (rasm + caption uchun)\n"
        "yoki\n"
        "✏️ *Matn yozing* (faqat matn uchun):",
        parse_mode="Markdown",
    )
    return WAIT_TPL_MEDIA


async def msg_tpl_media_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    os.makedirs(MEDIA_DIR, exist_ok=True)
    data = load_data()
    tpl_id = data["next_template_id"]
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    photo_path = os.path.join(MEDIA_DIR, f"tpl_{tpl_id}.jpg")
    await tg_file.download_to_drive(photo_path)
    context.user_data["new_tpl_photo"] = photo_path
    await update.message.reply_text(
        "✅ Rasm qabul qilindi!\n\nEndi *caption* (rasm ostidagi matn) kiriting:",
        parse_mode="Markdown",
    )
    return WAIT_TPL_CAPTION


async def msg_tpl_media_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    data = load_data()
    tpl = {
        "id": data["next_template_id"],
        "name": context.user_data.pop("new_tpl_name", "Nomsiz"),
        "type": "text",
        "text": update.message.text.strip(),
        "created_at": datetime.now().isoformat(),
    }
    data["templates"].append(tpl)
    data["next_template_id"] += 1
    save_data(data)
    await update.message.reply_text(
        f"✅ Shablon saqlandi: *{tpl['name']}*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Shablonlarga", callback_data="templates")]]),
        parse_mode="Markdown",
    )
    return MAIN


async def msg_tpl_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    data = load_data()
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
    save_data(data)
    await update.message.reply_text(
        f"✅ Shablon saqlandi: *{tpl['name']}* (📷 rasm + matn)",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Shablonlarga", callback_data="templates")]]),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_tpl_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    tpl_id = int(query.data.split("_")[-1])
    data = load_data()
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return MAIN
    data["active_template_id"] = tpl_id
    save_data(data)
    await query.answer(f"✅ '{tpl['name']}' faollashtirildi!", show_alert=True)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Faol (tanlangan)", callback_data=f"tpl_select_{tpl_id}")],
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"tpl_edit_{tpl_id}")],
        [InlineKeyboardButton("🗑 O'chirish", callback_data=f"tpl_delete_{tpl_id}")],
        [back_btn("templates")],
    ])
    await query.edit_message_text(
        f"📝 *{tpl['name']}*\n\n{tpl['text']}",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
    return MAIN


async def cb_tpl_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    tpl_id = int(query.data.split("_")[-1])
    data = load_data()
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return MAIN
    context.user_data["edit_tpl_id"] = tpl_id
    await query.edit_message_text(
        f"✏️ *{tpl['name']}* — yangi matnni kiriting:\n\n"
        f"_Hozirgi matn:_\n{tpl['text']}",
        reply_markup=InlineKeyboardMarkup([[back_btn(f"tpl_view_{tpl_id}", "❌ Bekor qilish")]]),
        parse_mode="Markdown",
    )
    return WAIT_EDIT_TEXT


async def msg_tpl_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    tpl_id = context.user_data.pop("edit_tpl_id", None)
    if tpl_id is None:
        await update.message.reply_text("Xatolik yuz berdi. /start bosing.")
        return MAIN
    data = load_data()
    for t in data["templates"]:
        if t["id"] == tpl_id:
            t["text"] = update.message.text.strip()
            break
    save_data(data)
    await update.message.reply_text(
        "✅ Shablon yangilandi!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Shablonlarga", callback_data="templates")]]),
    )
    return MAIN


async def cb_tpl_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    tpl_id = int(query.data.split("_")[-1])
    data = load_data()
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return MAIN
    data["templates"] = [t for t in data["templates"] if t["id"] != tpl_id]
    if data["active_template_id"] == tpl_id:
        data["active_template_id"] = None
    save_data(data)
    await query.answer(f"🗑 '{tpl['name']}' o'chirildi!", show_alert=True)
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


# ─── Groups ──────────────────────────────────────────────────────────────────

PAGE_SIZE = 20


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
    data = load_data()
    groups = data["groups"]
    text = (
        f"👥 *Mening Guruhlarim*\n\n{len(groups)} ta guruh tanlangan\n\n"
        f"O'chirish uchun guruh tugmasini bosing:"
        if groups else
        "👥 *Mening Guruhlarim*\n\nHali guruh tanlanmagan.\n\n🔄 Guruhlarni yuklash tugmasini bosing."
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
        title = d["title"][:28]
        buttons.append([InlineKeyboardButton(
            f"{icon} {title}", callback_data=f"tgl_group_{start + i}"
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
        f"Tanlangan: *{added}* ta\n\n"
        f"✅ tanlangan | ➕ tanlash uchun bosing:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def cb_fetch_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if tele_client is None or not tele_client.is_connected():
        await query.answer("❌ Telethon ulanmagan! auth.py ni ishga tushiring.", show_alert=True)
        return MAIN
    await query.edit_message_text("⏳ Guruhlar yuklanmoqda...")
    dialogs = []
    async for dialog in tele_client.iter_dialogs():
        entity = dialog.entity
        is_group = dialog.is_group
        is_supergroup = dialog.is_channel and getattr(entity, "megagroup", False)
        is_broadcast = dialog.is_channel and getattr(entity, "broadcast", False)
        can_post_in_broadcast = (
            is_broadcast
            and getattr(entity, "admin_rights", None) is not None
            and getattr(entity.admin_rights, "post_messages", False)
        )
        if is_group or is_supergroup or can_post_in_broadcast:
            dialogs.append({
                "chat_id": dialog.id,
                "title": dialog.title or str(dialog.id),
            })
    context.user_data["fetched_dialogs"] = dialogs
    context.user_data["dlg_page"] = 0
    data = load_data()
    existing_ids = {g["chat_id"] for g in data["groups"]}
    await _show_dialogs_page(query, dialogs, existing_ids, 0)
    return MAIN


async def cb_toggle_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    idx = int(query.data.split("_")[-1])
    dialogs = context.user_data.get("fetched_dialogs", [])
    if idx >= len(dialogs):
        await query.answer("Xatolik!", show_alert=True)
        return MAIN
    d = dialogs[idx]
    data = load_data()
    existing = next((g for g in data["groups"] if g["chat_id"] == d["chat_id"]), None)
    if existing:
        data["groups"] = [g for g in data["groups"] if g["chat_id"] != d["chat_id"]]
        save_data(data)
        await query.answer(f"❌ '{d['title'][:20]}' olib tashlandi")
    else:
        data["groups"].append({
            "chat_id": d["chat_id"],
            "title": d["title"],
            "added_at": datetime.now().isoformat(),
        })
        save_data(data)
        await query.answer(f"✅ '{d['title'][:20]}' qo'shildi")
    page = context.user_data.get("dlg_page", 0)
    existing_ids = {g["chat_id"] for g in data["groups"]}
    await _show_dialogs_page(query, dialogs, existing_ids, page)
    return MAIN


async def cb_dlg_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    page = int(query.data.split("_")[-1])
    context.user_data["dlg_page"] = page
    dialogs = context.user_data.get("fetched_dialogs", [])
    if not dialogs:
        await query.answer("Avval guruhlarni yuklang!", show_alert=True)
        return MAIN
    data = load_data()
    existing_ids = {g["chat_id"] for g in data["groups"]}
    await _show_dialogs_page(query, dialogs, existing_ids, page)
    return MAIN


async def cb_remove_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chat_id_str = query.data[len("rm_group_"):]
    data = load_data()
    group = next((g for g in data["groups"] if str(g["chat_id"]) == chat_id_str), None)
    if not group:
        await query.answer("Guruh topilmadi!", show_alert=True)
        return MAIN
    data["groups"] = [g for g in data["groups"] if str(g["chat_id"]) != chat_id_str]
    save_data(data)
    await query.answer(f"🗑 '{group.get('title', '')}' olib tashlandi!", show_alert=True)
    groups = data["groups"]
    text = (
        f"👥 *Mening Guruhlarim*\n\n{len(groups)} ta guruh tanlangan\n\nO'chirish uchun tugmani bosing:"
        if groups else
        "👥 *Mening Guruhlarim*\n\nHali guruh tanlanmagan."
    )
    await query.edit_message_text(text, reply_markup=_groups_keyboard(groups), parse_mode="Markdown")
    return MAIN


# ─── Settings ────────────────────────────────────────────────────────────────

def _interval_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} daqiqa"
    h = minutes // 60
    return f"{h} soat"


def _settings_keyboard(current: int) -> InlineKeyboardMarkup:
    # (minutes, display)
    options = [1, 60, 120, 180, 360, 720]
    rows = []
    row = []
    for m in options:
        tick = "✅ " if m == current else ""
        label = f"{tick}{_interval_label(m)}"
        row.append(InlineKeyboardButton(label, callback_data=f"set_interval_{m}"))
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
    data = load_data()
    current = data.get("interval_minutes", 180)
    await query.edit_message_text(
        f"⚙️ *Sozlamalar*\n\nHozirgi interval: *{_interval_label(current)}*\n\nYangi interval tanlang:",
        reply_markup=_settings_keyboard(current),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    minutes = int(query.data.split("_")[-1])
    data = load_data()
    data["interval_minutes"] = minutes
    save_data(data)
    if data["is_running"]:
        _reschedule(context.application, minutes)
    label = _interval_label(minutes)
    await query.answer(f"✅ Interval {label}ga o'rnatildi!", show_alert=True)
    await query.edit_message_text(
        f"⚙️ *Sozlamalar*\n\nHozirgi interval: *{label}*\n\nYangi interval tanlang:",
        reply_markup=_settings_keyboard(minutes),
        parse_mode="Markdown",
    )
    return MAIN


# ─── Stats ───────────────────────────────────────────────────────────────────

async def cb_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = load_data()
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
    text = (
        f"📊 *Statistika*\n\n"
        f"🔄 Holat: {status}\n"
        f"⏰ Interval: {_interval_label(data.get('interval_minutes', 180))}\n"
        f"👥 Guruhlar: {len(data['groups'])} ta\n"
        f"📝 Shablonlar: {len(data['templates'])} ta\n"
        f"✅ Faol shablon: {active_tpl['name'] if active_tpl else 'Tanlanmagan'}\n\n"
        f"📤 Jami yuborildi: {stats['total_sent']}\n"
        f"✅ Muvaffaqiyatli: {stats['successful']}\n"
        f"❌ Xatolik: {stats['failed']}\n"
        f"🕐 Oxirgi yuborilgan: {last_sent}"
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[back_btn("main_menu")]]),
        parse_mode="Markdown",
    )
    return MAIN


# ─── Sending logic ───────────────────────────────────────────────────────────

async def _do_send(application: Application) -> None:
    global tele_client
    data = load_data()
    if not data["is_running"]:
        return
    if tele_client is None or not tele_client.is_connected():
        logger.error("Telethon client not connected — run auth.py first")
        return
    active_id = data.get("active_template_id")
    if not active_id:
        logger.warning("No active template — skipping send cycle")
        return
    tpl = next((t for t in data["templates"] if t["id"] == active_id), None)
    if not tpl:
        logger.warning("Active template missing from list — skipping")
        return
    groups = data["groups"]
    if not groups:
        logger.warning("No groups configured — skipping send cycle")
        return

    is_photo = tpl.get("type") == "photo"
    photo_path = tpl.get("photo_path", "") if is_photo else ""
    caption = tpl["text"] or None

    async def _send_one(cid):
        if is_photo and os.path.exists(photo_path):
            await tele_client.send_file(cid, photo_path, caption=caption)
        else:
            await tele_client.send_message(cid, tpl["text"])

    ok = fail = 0
    for group in groups:
        chat_id = group["chat_id"]
        title = group.get("title", str(chat_id))
        try:
            await _send_one(chat_id)
            ok += 1
            logger.info(f"Sent to {title}")
        except FloodWaitError as e:
            logger.warning(f"FloodWait {e.seconds}s for {title}")
            await asyncio.sleep(e.seconds)
            try:
                await _send_one(chat_id)
                ok += 1
            except Exception:
                fail += 1
        except (ChatWriteForbiddenError, UserBannedInChannelError,
                ChannelPrivateError, UserNotParticipantError) as e:
            logger.warning(f"Cannot send to {title}: {type(e).__name__}")
            fail += 1
        except Exception as e:
            logger.error(f"Error sending to {title}: {e}")
            fail += 1
        await asyncio.sleep(2)

    data = load_data()
    data["stats"]["total_sent"] += ok
    data["stats"]["successful"] += ok
    data["stats"]["failed"] += fail
    data["stats"]["last_sent"] = datetime.now().isoformat()
    save_data(data)
    logger.info(f"Cycle done — sent: {ok}, failed: {fail}")


def _reschedule(application: Application, minutes: int) -> None:
    scheduler.add_job(
        _do_send,
        "interval",
        minutes=minutes,
        args=[application],
        id="send_job",
        replace_existing=True,
    )
    logger.info(f"Scheduler set to every {minutes} minute(s)")


# ─── Start / Stop ────────────────────────────────────────────────────────────

async def cb_start_sending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    data = load_data()
    if not data["active_template_id"]:
        await query.answer("❌ Avval faol shablon tanlang!", show_alert=True)
        return MAIN
    if not data["groups"]:
        await query.answer("❌ Avval guruh qo'shing!", show_alert=True)
        return MAIN
    data["is_running"] = True
    save_data(data)
    _reschedule(context.application, data.get("interval_minutes", 180))
    await query.answer("✅ Yuborish boshlandi!", show_alert=True)
    await query.edit_message_text(
        _main_text(data),
        reply_markup=main_keyboard(True),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_stop_sending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    data = load_data()
    data["is_running"] = False
    save_data(data)
    if scheduler.get_job("send_job"):
        scheduler.remove_job("send_job")
    await query.answer("⏸ Yuborish to'xtatildi!", show_alert=True)
    await query.edit_message_text(
        _main_text(data),
        reply_markup=main_keyboard(False),
        parse_mode="Markdown",
    )
    return MAIN


# ─── Lifecycle ───────────────────────────────────────────────────────────────

async def post_init(application: Application) -> None:
    global tele_client
    if not os.path.exists(f"{SESSION_FILE}.session"):
        logger.error("❌ Session fayli topilmadi! Avval 'python3 auth.py' ni ishga tushiring.")
    else:
        tele_client = TelegramClient(
            SESSION_FILE,
            api_id=config.API_ID,
            api_hash=config.API_HASH,
        )
        await tele_client.connect()
        if not await tele_client.is_user_authorized():
            logger.error("❌ Session muddati o'tgan! Avval 'python3 auth.py' ni qayta ishga tushiring.")
            tele_client = None
        else:
            me = await tele_client.get_me()
            logger.info(f"Telethon ulandi: {me.first_name} (@{me.username})")

    scheduler.start()
    data = load_data()
    if data["is_running"] and data.get("active_template_id") and data["groups"]:
        _reschedule(application, data.get("interval_minutes", 180))
        logger.info("Scheduled sending resumed after restart")


async def post_shutdown(application: Application) -> None:
    global tele_client
    if tele_client and tele_client.is_connected():
        await tele_client.disconnect()
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
                # Templates
                CallbackQueryHandler(cb_templates, pattern="^templates$"),
                CallbackQueryHandler(cb_tpl_view, pattern=r"^tpl_view_\d+$"),
                CallbackQueryHandler(cb_add_template_start, pattern="^add_template$"),
                CallbackQueryHandler(cb_tpl_select, pattern=r"^tpl_select_\d+$"),
                CallbackQueryHandler(cb_tpl_edit_start, pattern=r"^tpl_edit_\d+$"),
                CallbackQueryHandler(cb_tpl_delete, pattern=r"^tpl_delete_\d+$"),
                # Groups
                CallbackQueryHandler(cb_groups, pattern="^groups$"),
                CallbackQueryHandler(cb_fetch_groups, pattern="^fetch_groups$"),
                CallbackQueryHandler(cb_toggle_group, pattern=r"^tgl_group_\d+$"),
                CallbackQueryHandler(cb_dlg_page, pattern=r"^dlg_page_\d+$"),
                CallbackQueryHandler(cb_remove_group, pattern=r"^rm_group_"),
                # Settings
                CallbackQueryHandler(cb_settings, pattern="^settings$"),
                CallbackQueryHandler(cb_set_interval, pattern=r"^set_interval_\d+$"),
                # Stats
                CallbackQueryHandler(cb_stats, pattern="^stats$"),
                # Start/Stop
                CallbackQueryHandler(cb_start_sending, pattern="^start_sending$"),
                CallbackQueryHandler(cb_stop_sending, pattern="^stop_sending$"),
            ],
            WAIT_TPL_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_name),
                CallbackQueryHandler(cb_templates, pattern="^templates$"),
            ],
            WAIT_TPL_MEDIA: [
                MessageHandler(filters.PHOTO, msg_tpl_media_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_media_text),
                CallbackQueryHandler(cb_templates, pattern="^templates$"),
            ],
            WAIT_TPL_CAPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_caption),
            ],
            WAIT_EDIT_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_tpl_edit_text),
                CallbackQueryHandler(cb_tpl_view, pattern=r"^tpl_view_\d+$"),
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
