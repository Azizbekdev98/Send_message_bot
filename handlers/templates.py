import logging
import os
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database import load_user, save_user, MEDIA_DIR
from keyboards import back_btn, templates_keyboard, template_detail_keyboard, tpl_interval_keyboard

logger = logging.getLogger(__name__)

MAIN = 0
WAIT_TPL_NAME, WAIT_TPL_MEDIA, WAIT_TPL_CAPTION, WAIT_EDIT_TEXT = 4, 5, 6, 7

DEFAULT_INTERVAL = 180


def _escape_md(text: str) -> str:
    for ch in ["*", "_", "`", "["]:
        text = text.replace(ch, f"\\{ch}")
    return text


def _tpl_text(tpl: dict) -> str:
    icon = "📷" if tpl.get("type") == "photo" else "📝"
    status = "✅ Faol" if tpl.get("is_active") else "⏸ To'xtatilgan"
    interval = tpl.get("interval_minutes", DEFAULT_INTERVAL)
    h, m = interval // 60, interval % 60
    time_str = f"{h} soat {m} daqiqa" if m else f"{h} soat"
    return (
        f"{icon} *{tpl['name']}*\n\n"
        f"{_escape_md(tpl['text'])}\n\n"
        f"Holat: {status}\n"
        f"Interval: ⏱ {time_str}"
    )


async def _show_tpl_detail(query, tpl: dict) -> None:
    """Shablon detail ni matn yoki foto xabarda ko'rsatish."""
    tpl_id = tpl["id"]
    is_active = tpl.get("is_active", False)
    keyboard = template_detail_keyboard(tpl_id, is_active)
    preview = _tpl_text(tpl)

    if tpl.get("type") == "photo" and os.path.exists(tpl.get("photo_path", "")):
        caption = preview if len(preview) <= 1024 else preview[:1020] + "..."
        with open(tpl["photo_path"], "rb") as f:
            await query.message.reply_photo(
                photo=f,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
        await query.message.delete()
    else:
        try:
            await query.edit_message_text(preview, reply_markup=keyboard, parse_mode="Markdown")
        except Exception:
            await query.message.reply_text(preview, reply_markup=keyboard, parse_mode="Markdown")
            await query.message.delete()


async def cb_templates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = load_user(user_id)
    templates = data["templates"]
    text = (
        "📝 *Shablonlar*\n\n✅ faol | ⏸ to'xtatilgan\nShablon tanlang:"
        if templates else
        "📝 *Shablonlar*\n\nHali shablon yo'q. Yangi qo'shing."
    )
    try:
        await query.edit_message_text(text, reply_markup=templates_keyboard(templates), parse_mode="Markdown")
    except Exception:
        await query.message.reply_text(text, reply_markup=templates_keyboard(templates), parse_mode="Markdown")
        await query.message.delete()
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

    await _show_tpl_detail(query, tpl)
    return MAIN


async def cb_tpl_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Shablon faollashtirish / to'xtatish."""
    query = update.callback_query
    user_id = update.effective_user.id
    tpl_id = int(query.data.split("_")[-1])
    data = load_user(user_id)
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        await query.answer("Shablon topilmadi!", show_alert=True)
        return MAIN

    tpl["is_active"] = not tpl.get("is_active", False)
    save_user(user_id, data)

    _update_scheduler(user_id, tpl_id, tpl["is_active"],
                      tpl.get("interval_minutes", DEFAULT_INTERVAL),
                      query.get_bot(), data)

    status = "▶️ Faollashtirildi" if tpl["is_active"] else "⏸ To'xtatildi"
    await query.answer(f"{status}: {tpl['name']}", show_alert=True)
    await _show_tpl_detail(query, tpl)
    return MAIN


async def cb_tpl_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Interval tanlash sahifasi."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    tpl_id = int(query.data.split("_")[-1])
    data = load_user(user_id)
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        return MAIN

    current = tpl.get("interval_minutes", DEFAULT_INTERVAL)
    text = f"⏱ *{tpl['name']}* — interval tanlang:"
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=tpl_interval_keyboard(tpl_id, current))
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=tpl_interval_keyboard(tpl_id, current))
        await query.message.delete()
    return MAIN


async def cb_tpl_set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Intervalni saqlash."""
    query = update.callback_query
    user_id = update.effective_user.id
    parts = query.data.split("_")
    tpl_id = int(parts[3])
    minutes = int(parts[4])
    data = load_user(user_id)
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        return MAIN

    tpl["interval_minutes"] = minutes
    save_user(user_id, data)

    if tpl.get("is_active") and data.get("is_running"):
        _update_scheduler(user_id, tpl_id, True, minutes, query.get_bot(), data)

    h, m = minutes // 60, minutes % 60
    time_str = f"{h} soat {m} daqiqa" if m else f"{h} soat"
    await query.answer(f"✅ Interval: {time_str}", show_alert=True)
    await _show_tpl_detail(query, tpl)
    return MAIN


def _update_scheduler(user_id: int, tpl_id: int, is_active: bool,
                      interval: int, bot, data: dict):
    """Shablon schedulerini yoqish yoki o'chirish."""
    try:
        from main import scheduler
        from services.sender import send_template
        job_id = f"send_{user_id}_tpl_{tpl_id}"

        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        if is_active and data.get("is_running"):
            scheduler.add_job(
                send_template,
                trigger="interval",
                minutes=interval,
                args=[bot, user_id, tpl_id],
                id=job_id,
                replace_existing=True,
            )
    except Exception as e:
        logger.error(f"Scheduler yangilash xato: {e}")


async def cb_add_template(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text(
            "📝 *Yangi Shablon*\n\nShablon *nomini* kiriting:",
            reply_markup=InlineKeyboardMarkup([[back_btn("templates", "❌ Bekor qilish")]]),
            parse_mode="Markdown",
        )
    except Exception:
        await query.message.reply_text(
            "📝 *Yangi Shablon*\n\nShablon *nomini* kiriting:",
            reply_markup=InlineKeyboardMarkup([[back_btn("templates", "❌ Bekor qilish")]]),
            parse_mode="Markdown",
        )
        await query.message.delete()
    return WAIT_TPL_NAME


async def msg_tpl_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❌ Nom bo'sh bo'lishi mumkin emas:")
        return WAIT_TPL_NAME
    context.user_data["new_tpl_name"] = name
    await update.message.reply_text(
        f"✅ Nom: *{name}*\n\n📷 *Rasm yuboring* yoki ✏️ *Matn yozing*:\n\n"
        f"Bekor qilish uchun /start bosing.",
        parse_mode="Markdown",
    )
    return WAIT_TPL_MEDIA


async def msg_tpl_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    data = load_user(user_id)
    tpl_id = data["next_template_id"]
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    photo_path = os.path.join(MEDIA_DIR, f"{user_id}_tpl_{tpl_id}.jpg")
    await tg_file.download_to_drive(photo_path)
    context.user_data["new_tpl_photo"] = photo_path
    await update.message.reply_text(
        "✅ Rasm qabul qilindi!\n\n*Caption* (matn) kiriting:\n\nBekor qilish uchun /start bosing.",
        parse_mode="Markdown",
    )
    return WAIT_TPL_CAPTION


async def msg_tpl_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    data = load_user(user_id)
    tpl = {
        "id": data["next_template_id"],
        "name": context.user_data.pop("new_tpl_name", "Nomsiz"),
        "type": "text",
        "text": update.message.text.strip(),
        "interval_minutes": DEFAULT_INTERVAL,
        "is_active": False,
        "created_at": datetime.now().isoformat(),
    }
    data["templates"].append(tpl)
    data["next_template_id"] += 1
    save_user(user_id, data)
    await update.message.reply_text(
        f"✅ Shablon saqlandi: *{tpl['name']}*\n\nInterval: 3 soat (o'zgartirish mumkin)",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 Shablonlarga", callback_data="templates")
        ]]),
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
        "interval_minutes": DEFAULT_INTERVAL,
        "is_active": False,
        "created_at": datetime.now().isoformat(),
    }
    data["templates"].append(tpl)
    data["next_template_id"] += 1
    save_user(user_id, data)
    await update.message.reply_text(
        f"✅ Shablon saqlandi: *{tpl['name']}* (📷 rasm)\n\nInterval: 3 soat",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 Shablonlarga", callback_data="templates")
        ]]),
        parse_mode="Markdown",
    )
    return MAIN


async def msg_tpl_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 Shablonlarga", callback_data="templates")
        ]]),
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
        return MAIN
    context.user_data["edit_tpl_id"] = tpl_id
    text = (
        f"✏️ *{_escape_md(tpl['name'])}* — yangi matnni kiriting:\n\n"
        f"_Hozirgi:_\n{_escape_md(tpl['text'])}"
    )
    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[back_btn(f"tpl_view_{tpl_id}", "❌ Bekor qilish")]]),
            parse_mode="Markdown",
        )
    except Exception:
        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[back_btn(f"tpl_view_{tpl_id}", "❌ Bekor qilish")]]),
            parse_mode="Markdown",
        )
        await query.message.delete()
    return WAIT_EDIT_TEXT


async def cb_tpl_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    tpl_id = int(query.data.split("_")[-1])
    data = load_user(user_id)
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        return MAIN

    try:
        from main import scheduler
        job_id = f"send_{user_id}_tpl_{tpl_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    except Exception:
        pass

    data["templates"] = [t for t in data["templates"] if t["id"] != tpl_id]
    save_user(user_id, data)
    await query.answer(f"🗑 '{tpl['name']}' o'chirildi!", show_alert=True)
    text = "📝 *Shablonlar*\n\nShablon tanlang:" if data["templates"] else "📝 *Shablonlar*\n\nHali shablon yo'q."
    try:
        await query.edit_message_text(text, reply_markup=templates_keyboard(data["templates"]), parse_mode="Markdown")
    except Exception:
        await query.message.reply_text(text, reply_markup=templates_keyboard(data["templates"]), parse_mode="Markdown")
        await query.message.delete()
    return MAIN
