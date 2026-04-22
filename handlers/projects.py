from __future__ import annotations

import datetime as dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from handlers.common import get_db, month_start, require_role
from handlers.menu import send_main_menu


DONE_SELECT = 1


@require_role("member")
async def myprojects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = await get_db(context)
    me = context.user_data["me"]
    projects = [dict(r) for r in await db.list_active_projects_for_user(me.id)]
    if not projects:
        await update.effective_message.reply_text("Активных проектов нет. Добавь через /log → «Добавить другой проект».")
        await send_main_menu(update, context)
        return

    today = dt.date.today()
    mstart = month_start(today)
    lines = ["Твои активные проекты:"]
    total_all = 0.0
    total_month = 0.0
    for p in projects:
        h_all = await db.user_project_hours(me.id, int(p["id"]))
        h_month = await db.user_project_hours(me.id, int(p["id"]), start=mstart)
        total_all += h_all
        total_month += h_month
        lines.append(f"- {p['client_name']} / {p['name']}: всего {h_all:.2f} ч, за месяц {h_month:.2f} ч")
    lines.append(f"\nИтого: всего {total_all:.2f} ч, за месяц {total_month:.2f} ч")
    await update.effective_message.reply_text("\n".join(lines))
    await send_main_menu(update, context)


myprojects_handler = CommandHandler("myprojects", myprojects)


@require_role("member")
async def done_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db = await get_db(context)
    me = context.user_data["me"]
    projects = [dict(r) for r in await db.list_active_projects_for_user(me.id)]
    if not projects:
        await update.effective_message.reply_text("Активных проектов нет.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"{p['client_name']} / {p['name']}", callback_data=f"done:{p['id']}")] for p in projects]
        + [[InlineKeyboardButton("Отмена", callback_data="done:cancel")]]
    )
    await update.effective_message.reply_text("Какой проект закрыть?", reply_markup=kb)
    return DONE_SELECT


async def done_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "done:cancel":
        await q.edit_message_text("Ок.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    project_id = int(data.split(":")[-1])
    db = await get_db(context)
    await db.set_project_status(project_id, "done")
    await q.edit_message_text("Закрыл.")
    await send_main_menu(update, context)
    return ConversationHandler.END


done_conversation = ConversationHandler(
    entry_points=[CommandHandler("done", done_entry), CallbackQueryHandler(done_entry, pattern=r"^menu:done$")],
    states={DONE_SELECT: [CallbackQueryHandler(done_select, pattern=r"^done:")]},
    fallbacks=[],
    name="done",
    persistent=False,
)

