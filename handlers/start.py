from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from handlers.common import get_db, get_me


ASK_NAME = 1


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db = await get_db(context)
    tg_id = await get_me(update)
    user = await db.get_user_by_tg(tg_id)
    admin_tg_id = context.bot_data.get("admin_tg_id")
    if user:
        if admin_tg_id and tg_id == admin_tg_id and user.role != "admin":
            await db.maybe_seed_first_admin(tg_id)
        await update.message.reply_text(
            f"Привет, {user.name}! Доступные команды: /log, /myprojects, /done."
        )
        return ConversationHandler.END
    await update.message.reply_text("Привет! Как тебя зовут? (введи имя текстом)")
    return ASK_NAME


async def save_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("Имя слишком короткое. Попробуй ещё раз.")
        return ASK_NAME
    db = await get_db(context)
    tg_id = await get_me(update)
    admin_tg_id = context.bot_data.get("admin_tg_id")
    role = "admin" if (admin_tg_id and tg_id == admin_tg_id) else "member"
    await db.create_user(tg_id=tg_id, name=name, role=role)
    await update.message.reply_text(f"Готово, {name}! Теперь можно логировать: /log")
    return ConversationHandler.END


start_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name)],
    },
    fallbacks=[],
    name="start",
    persistent=False,
)
