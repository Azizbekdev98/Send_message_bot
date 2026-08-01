from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

import config
from database import load_user

WAIT_SUPPORT_MSG = 60


async def cb_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adminga murojaat tugmasi."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✍️ *Adminga xabar*\n\n"
        "Savolingizni yoki muammoingizni yozing.\n"
        "Admin imkon qadar javob beradi.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Bekor qilish", callback_data="main_menu")
        ]])
    )
    return WAIT_SUPPORT_MSG


async def msg_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi xabarini adminga yuborish."""
    user = update.effective_user
    user_id = user.id
    data = load_user(user_id)
    phone = data.get("phone") or "—"
    text = update.message.text

    # Adminga yuborish
    admin_text = (
        f"📩 *Yangi murojaat*\n\n"
        f"👤 [{user.first_name}](tg://user?id={user_id})\n"
        f"🆔 `{user_id}`\n"
        f"📱 {phone}\n\n"
        f"💬 {text}"
    )
    try:
        await context.bot.send_message(
            config.ADMIN_ID,
            admin_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"↩️ Javob berish", callback_data=f"reply_{user_id}")
            ]])
        )
    except Exception:
        pass

    await update.message.reply_text(
        "✅ Xabaringiz adminga yuborildi!\n\nJavob kutib turing.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Bosh menyu", callback_data="main_menu")
        ]])
    )
    return ConversationHandler.END


async def cb_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin javob berish tugmasini bosadi."""
    if update.effective_user.id != config.ADMIN_ID:
        return
    query = update.callback_query
    await query.answer()

    target_id = int(query.data.split("_")[1])
    context.user_data["reply_to"] = target_id

    await query.edit_message_text(
        query.message.text + "\n\n─────────────\n✍️ Javobingizni yozing:",
        parse_mode="Markdown",
    )
    return WAIT_SUPPORT_MSG


async def msg_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin yozgan javobni foydalanuvchiga yuborish."""
    if update.effective_user.id != config.ADMIN_ID:
        return ConversationHandler.END

    target_id = context.user_data.get("reply_to")
    if not target_id:
        return ConversationHandler.END

    text = update.message.text
    try:
        await context.bot.send_message(
            target_id,
            f"📬 *Admin javobi:*\n\n{text}",
            parse_mode="Markdown",
        )
        await update.message.reply_text("✅ Javob yuborildi!")
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {e}")

    context.user_data.pop("reply_to", None)
    return ConversationHandler.END
