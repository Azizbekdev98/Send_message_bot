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
            [InlineKeyboardButton("📢 Barcha guruhlarga yuborish", callback_data="admin_broadcast")],
            [InlineKeyboardButton("« Orqaga", callback_data="main_menu")],
        ])
    )


async def cb_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Barcha userlarning guruhlarini ko'rsatish va shablon tanlash."""
    if update.effective_user.id != config.ADMIN_ID:
        return
    query = update.callback_query
    await query.answer()

    # Admin o'z shablonlarini ko'rsatamiz
    data = load_user(config.ADMIN_ID)
    templates = data.get("templates", [])

    if not templates:
        await query.edit_message_text(
            "❌ Sizda shablon yo'q.\n\n📝 Avval shablon yarating.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Orqaga", callback_data="admin_panel")
            ]])
        )
        return

    # Barcha guruhlar statistikasi
    all_groups = _collect_all_groups()
    total_groups = len(all_groups)
    total_users = len([uid for uid in all_user_ids()
                       if uid != config.ADMIN_ID and load_user(uid).get("groups")])

    buttons = []
    for tpl in templates:
        icon = "📷" if tpl.get("type") == "photo" else "📝"
        buttons.append([InlineKeyboardButton(
            f"{icon} {tpl['name']}",
            callback_data=f"broadcast_tpl_{tpl['id']}"
        )])
    buttons.append([InlineKeyboardButton("« Orqaga", callback_data="admin_panel")])

    await query.edit_message_text(
        f"📢 *Barcha guruhlarga yuborish*\n\n"
        f"👥 Foydalanuvchilar: *{total_users}* ta\n"
        f"📌 Jami guruhlar: *{total_groups}* ta\n\n"
        f"Qaysi shablonni yuborasiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def cb_broadcast_tpl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tanlangan shablonni barcha guruhlarga yuborish."""
    if update.effective_user.id != config.ADMIN_ID:
        return
    query = update.callback_query
    await query.answer()

    tpl_id = int(query.data.split("_")[-1])
    data = load_user(config.ADMIN_ID)
    tpl = next((t for t in data["templates"] if t["id"] == tpl_id), None)
    if not tpl:
        return

    await query.edit_message_text(
        f"📢 *{tpl['name']}* — yuborilmoqda...\n\nKuting.",
        parse_mode="Markdown"
    )

    all_groups = _collect_all_groups()
    ok = fail = skip = 0

    for chat_id, info in all_groups.items():
        uid = info["user_id"]
        from services.userbot import get_client
        client = get_client(uid)
        if not client:
            skip += 1
            continue
        try:
            import os
            if tpl.get("type") == "photo" and os.path.exists(tpl.get("photo_path", "")):
                try:
                    await client.send_file(chat_id, tpl["photo_path"], caption=tpl["text"])
                except Exception:
                    await client.send_message(chat_id, tpl["text"])
            else:
                await client.send_message(chat_id, tpl["text"])
            ok += 1
        except Exception:
            fail += 1
        import asyncio
        await asyncio.sleep(1)

    await query.edit_message_text(
        f"✅ *Yuborish tugadi!*\n\n"
        f"📌 Jami guruhlar: {len(all_groups)}\n"
        f"✅ Muvaffaqiyatli: {ok}\n"
        f"❌ Xato: {fail}\n"
        f"⏭ O'tkazib yuborildi (ulanmagan): {skip}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("« Admin Panel", callback_data="admin_panel")
        ]])
    )


def _collect_all_groups() -> dict:
    """Barcha userlarning guruhlarini chat_id bo'yicha jamlaydi.
    Bir guruh bir necha userda bo'lsa — birinchi topilgani olinadi."""
    result = {}
    for uid in all_user_ids():
        if uid == config.ADMIN_ID:
            continue
        data = load_user(uid)
        if not data.get("session_string"):
            continue
        for g in data.get("groups", []):
            chat_id = g["chat_id"]
            if chat_id not in result:
                result[chat_id] = {
                    "user_id": uid,
                    "title": g.get("title", str(chat_id)),
                }
    return result


async def cb_admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Admin panel — /admin buyrug'ini qayta yuboring.",
        reply_markup=None
    )
