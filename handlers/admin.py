from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import config
from database import load_user, save_user, all_user_ids, session_exists
from handlers.payment import has_active_subscription

WAIT_GIFT_ID = 50


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel — faqat admin uchun."""
    if update.effective_user.id != config.ADMIN_ID:
        return

    from services.userbot import get_client
    ids = [uid for uid in all_user_ids() if uid != config.ADMIN_ID]

    total = len(ids)
    active_sub = 0
    running = 0
    no_session = 0

    lines = []
    for uid in sorted(ids):
        data = load_user(uid)
        phone = data.get("phone") or "—"
        has_session = bool(data.get("session_string"))
        is_running = data.get("is_running", False)
        connected = bool(get_client(uid))

        expires = data.get("subscription_expires")
        if expires:
            exp = datetime.fromisoformat(expires)
            if exp > datetime.now():
                days = (exp - datetime.now()).days
                sub = f"✅ {days}k"
                active_sub += 1
            else:
                sub = "❌ tugagan"
        else:
            sub = "❌ yo'q"

        if not has_session:
            no_session += 1

        if is_running:
            running += 1

        if connected:
            icon = "🟢"
        elif has_session:
            icon = "🟡"
        else:
            icon = "⚪"

        send_status = " 📢" if is_running else ""
        lines.append(f"{icon} `{uid}`{send_status}\n📱 {phone} | 💳 {sub}")

    summary = (
        f"👥 *Admin Panel*\n\n"
        f"Jami: *{total}* ta\n"
        f"Obunali: *{active_sub}* ta\n"
        f"Reklama yubormoqda: *{running}* ta\n"
        f"Sessiyasiz: *{no_session}* ta\n"
        f"─────────────────\n"
    )

    text = summary + "\n\n".join(lines) if lines else summary + "Hech kim yo'q"

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎁 Sovga qilish", callback_data="admin_gift")
        ]])
    )


async def cb_admin_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sovga berish — user ID so'raydi."""
    if update.effective_user.id != config.ADMIN_ID:
        return
    query = update.callback_query
    await query.answer()

    # Ro'yxat tugmalar ko'rinishida
    ids = [uid for uid in all_user_ids() if uid != config.ADMIN_ID]
    if not ids:
        await query.edit_message_text("Foydalanuvchilar yo'q.")
        return

    buttons = []
    for uid in sorted(ids):
        data = load_user(uid)
        phone = data.get("phone") or str(uid)
        expires = data.get("subscription_expires")
        if expires and datetime.fromisoformat(expires) > datetime.now():
            days = (datetime.fromisoformat(expires) - datetime.now()).days
            label = f"{phone} ✅{days}k"
        else:
            label = f"{phone} ❌"
        buttons.append([InlineKeyboardButton(label, callback_data=f"gift_{uid}")])

    buttons.append([InlineKeyboardButton("« Orqaga", callback_data="admin_back")])

    await query.edit_message_text(
        "🎁 *Kimga 1 oylik sovga?*\n\nFoydalanuvchini tanlang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def cb_gift_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tanlangan usерга 30 kun qo'shish."""
    if update.effective_user.id != config.ADMIN_ID:
        return
    query = update.callback_query
    await query.answer()

    uid = int(query.data.split("_")[1])
    data = load_user(uid)

    # Mavjud obunaga qo'shamiz yoki yangisini boshlaymiz
    expires = data.get("subscription_expires")
    if expires:
        base = datetime.fromisoformat(expires)
        if base < datetime.now():
            base = datetime.now()
    else:
        base = datetime.now()

    new_exp = base + timedelta(days=30)
    data["subscription_expires"] = new_exp.isoformat()
    save_user(uid, data)

    phone = data.get("phone") or str(uid)
    exp_str = new_exp.strftime("%d.%m.%Y")

    # Foydalanuvchiga xabar
    try:
        await context.bot.send_message(
            uid,
            f"🎁 *Sizga 1 oylik obuna sovga qilindi!*\n\n"
            f"Muddati: *{exp_str}* gacha\n\n"
            f"/start bosing.",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    await query.edit_message_text(
        f"✅ *Sovga berildi!*\n\n"
        f"👤 {phone}\n"
        f"📅 {exp_str} gacha obuna uzaytirildi.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("« Orqaga", callback_data="admin_back")
        ]])
    )


async def cb_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tugma orqali admin panelni ochish."""
    if update.effective_user.id != config.ADMIN_ID:
        return
    query = update.callback_query
    await query.answer()
    # cmd_admin mantiqini inline ko'rsatamiz
    from services.userbot import get_client
    ids = [uid for uid in all_user_ids() if uid != config.ADMIN_ID]
    total = len(ids)
    active_sub = running = no_session = 0
    lines = []
    for uid in sorted(ids):
        data = load_user(uid)
        phone = data.get("phone") or "—"
        has_session = bool(data.get("session_string"))
        is_running = data.get("is_running", False)
        connected = bool(get_client(uid))
        expires = data.get("subscription_expires")
        if expires:
            exp = datetime.fromisoformat(expires)
            if exp > datetime.now():
                days = (exp - datetime.now()).days
                sub = f"✅ {days}k"
                active_sub += 1
            else:
                sub = "❌ tugagan"
        else:
            sub = "❌ yo'q"
        if not has_session:
            no_session += 1
        if is_running:
            running += 1
        icon = "🟢" if connected else ("🟡" if has_session else "⚪")
        send_status = " 📢" if is_running else ""
        lines.append(f"{icon} `{uid}`{send_status}\n📱 {phone} | 💳 {sub}")

    text = (
        f"👥 *Admin Panel*\n\n"
        f"Jami: *{total}* ta\n"
        f"Obunali: *{active_sub}* ta\n"
        f"Reklama yubormoqda: *{running}* ta\n"
        f"Sessiyasiz: *{no_session}* ta\n"
        f"─────────────────\n\n"
    ) + ("\n\n".join(lines) if lines else "Hech kim yo'q")

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Sovga qilish", callback_data="admin_gift")],
            [InlineKeyboardButton("« Orqaga", callback_data="main_menu")],
        ])
    )


async def cb_admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Admin panel — /admin buyrug'ini qayta yuboring.",
        reply_markup=None
    )
