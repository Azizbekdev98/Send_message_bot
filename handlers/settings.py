import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from database import load_user, save_user
from keyboards import back_btn, main_keyboard

logger = logging.getLogger(__name__)

MAIN = 0


def _main_text(data: dict) -> str:
    status = "✅ Ishlayapti" if data["is_running"] else "⏸ To'xtatilgan"
    phone = data.get("phone") or "—"
    active = sum(1 for t in data["templates"] if t.get("is_active"))
    return (
        f"🤖 *Reklama Boti*\n\n"
        f"📱 Telefon: `{phone}`\n"
        f"Holat: {status}\n"
        f"Guruhlar: {len(data['groups'])} ta\n"
        f"Shablonlar: {len(data['templates'])} ta ({active} faol)\n\n"
        f"Bo'limni tanlang:"
    )


async def cb_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from telegram import InlineKeyboardButton
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = load_user(user_id)
    templates = data["templates"]

    buttons = []
    for t in templates:
        m = t.get("interval_minutes", 180)
        h, mn = m // 60, m % 60
        time_str = f"{h}s {mn}d" if mn else f"{h} soat"
        icon = "✅" if t.get("is_active") else "⏸"
        buttons.append([InlineKeyboardButton(
            f"{icon} {t['name']} — {time_str}",
            callback_data=f"tpl_interval_{t['id']}"
        )])
    buttons.append([back_btn("main_menu")])

    text = (
        "⚙️ *Sozlamalar*\n\nInterval o'zgartirish uchun shablon bosing:"
        if templates else
        "⚙️ *Sozlamalar*\n\nHali shablon yo'q."
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )
    return MAIN


async def cb_start_sending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from services.userbot import is_connected
    from services.sender import send_template
    query = update.callback_query
    user_id = update.effective_user.id
    data = load_user(user_id)

    active = [t for t in data["templates"] if t.get("is_active")]
    if not active:
        await query.answer("❌ Avval shablon faollashtiring!", show_alert=True)
        return MAIN
    if not data["groups"]:
        await query.answer("❌ Avval guruh qo'shing!", show_alert=True)
        return MAIN
    if not is_connected(user_id):
        await query.answer("❌ Sessiya ulanmagan! /start bosing.", show_alert=True)
        return MAIN

    data["is_running"] = True
    save_user(user_id, data)

    # Darhol yuborish + scheduler
    from main import scheduler
    for tpl in active:
        job_id = f"send_{user_id}_tpl_{tpl['id']}"
        scheduler.add_job(
            send_template,
            trigger="interval",
            minutes=tpl.get("interval_minutes", 180),
            args=[context.bot, user_id, tpl["id"]],
            id=job_id,
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(minutes=tpl.get("interval_minutes", 180)),
        )
        # Birinchi yuborishni darhol bajarish
        context.application.create_task(send_template(context.bot, user_id, tpl["id"]))

    await query.answer(f"✅ {len(active)} ta shablon yuborilmoqda!", show_alert=True)
    try:
        await query.edit_message_text(_main_text(data), parse_mode="Markdown")
    except Exception:
        pass
    return MAIN


async def cb_stop_sending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_id = update.effective_user.id
    data = load_user(user_id)
    data["is_running"] = False
    save_user(user_id, data)

    # Barcha shablon joblarini to'xtatish
    from main import scheduler
    for tpl in data["templates"]:
        job_id = f"send_{user_id}_tpl_{tpl['id']}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

    await query.answer("⏸ Yuborish to'xtatildi!", show_alert=True)
    try:
        await query.edit_message_text(_main_text(data), parse_mode="Markdown")
    except Exception:
        pass
    return MAIN


async def cb_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = load_user(user_id)
    stats = data["stats"]
    last_sent = stats.get("last_sent")
    if last_sent:
        try:
            last_sent = datetime.fromisoformat(last_sent).strftime("%d.%m.%Y %H:%M")
        except Exception:
            pass
    else:
        last_sent = "Hali yuborilmagan"

    active = [t for t in data["templates"] if t.get("is_active")]
    tpl_lines = "\n".join(
        f"• {t['name']} — {t.get('interval_minutes', 180) // 60}s"
        for t in active
    ) or "Tanlanmagan"

    status = "✅ Ishlayapti" if data["is_running"] else "⏸ To'xtatilgan"
    await query.edit_message_text(
        f"📊 *Statistika*\n\n"
        f"🔄 Holat: {status}\n"
        f"👥 Guruhlar: {len(data['groups'])} ta\n"
        f"📝 Faol shablonlar:\n{tpl_lines}\n\n"
        f"📤 Jami yuborildi: {stats['total_sent']}\n"
        f"✅ Muvaffaqiyatli: {stats['successful']}\n"
        f"❌ Xatolik: {stats['failed']}\n"
        f"🕐 Oxirgi: {last_sent}",
        reply_markup=InlineKeyboardMarkup([[back_btn("main_menu")]]),
        parse_mode="Markdown",
    )
    return MAIN
