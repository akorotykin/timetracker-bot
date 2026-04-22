from __future__ import annotations

import datetime as dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from handlers.common import get_db, month_start, require_role
from handlers.menu import send_main_menu
from handlers.positions import POSITIONS, position_label, positions_kb


def _me_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Изменить должность", callback_data="me:pos")]])


@require_role("member")
async def me_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = await get_db(context)
    me = context.user_data["me"]
    projects = await db.list_active_projects_for_user(me.id)

    today = dt.date.today()
    start = month_start(today)
    row = await db.fetchone(
        "SELECT COALESCE(SUM(hours),0) AS h FROM timelog WHERE user_id = ? AND date BETWEEN ? AND ?;",
        (me.id, start.isoformat(), today.isoformat()),
    )
    hours = float(row["h"] or 0) if row else 0.0

    await update.effective_message.reply_text(
        "\n".join(
            [
                f"Имя: {me.name}",
                f"Должность: {position_label(me.position)}",
                f"Активных проектов: {len(projects)}",
                f"Часов за этот месяц: {hours:.2f}",
            ]
        ),
        reply_markup=_me_kb(),
    )


@require_role("member")
async def me_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "me:pos":
        await q.edit_message_text("Выбери свою должность:", reply_markup=positions_kb("mepos"))
        return
    if data.startswith("mepos:"):
        pos = data.split(":")[-1]
        if pos not in POSITIONS:
            await q.edit_message_text("Не понял должность.")
            await send_main_menu(update, context)
            return
        db = await get_db(context)
        me = context.user_data["me"]
        await db.set_user_position(me.id, pos)
        await q.edit_message_text(f"Должность обновлена: {position_label(pos)}")
        await send_main_menu(update, context)
        return

    await q.edit_message_text("Не понял действие.")
    await send_main_menu(update, context)


me_handler = CommandHandler("me", me_cmd)
me_callback_handler = CallbackQueryHandler(me_callback, pattern=r"^(me:|mepos:)")

