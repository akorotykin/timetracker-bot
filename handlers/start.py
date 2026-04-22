from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from handlers.common import get_db, get_me
from handlers.menu import send_main_menu
from handlers.positions import POSITIONS, positions_kb


ASK_NAME, ASK_POSITION = 1, 2


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db = await get_db(context)
    tg_id = await get_me(update)
    user = await db.get_user_by_tg(tg_id)
    admin_tg_id = context.bot_data.get("admin_tg_id")
    if user:
        if admin_tg_id and tg_id == admin_tg_id and user.role != "admin":
            await db.maybe_seed_first_admin(tg_id)
        await update.message.reply_text(f"Привет, {user.name}!")
        await send_main_menu(update, context)
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
    context.user_data["reg_name"] = name
    context.user_data["reg_role"] = role
    await update.message.reply_text("Выбери свою должность:", reply_markup=positions_kb("regpos"))
    return ASK_POSITION


async def save_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    pos = data.split(":")[-1]
    if pos not in POSITIONS:
        await q.edit_message_text("Не понял должность. Попробуй ещё раз.")
        return ASK_POSITION
    name = str(context.user_data["reg_name"])
    role = str(context.user_data["reg_role"])
    db = await get_db(context)
    tg_id = await get_me(update)
    prow = await db.get_position_by_name(pos)
    i = float(prow["default_internal_rate"] or 0) if prow else 0.0
    e = float(prow["default_external_rate"] or 0) if prow else 0.0
    await db.create_user(tg_id=tg_id, name=name, role=role, position=pos, internal_rate=i, external_rate=e)
    await q.edit_message_text(
        f"Твоя должность: {pos}\nСтавки установлены автоматически.\nЕсли что-то не так — обратись к админу."
    )
    await send_main_menu(update, context)
    return ConversationHandler.END


start_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name)],
        ASK_POSITION: [CallbackQueryHandler(save_position, pattern=r"^regpos:")],
    },
    fallbacks=[],
    name="start",
    persistent=False,
)
