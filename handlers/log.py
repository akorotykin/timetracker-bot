from __future__ import annotations

import datetime as dt
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from handlers.common import get_db, require_role, yesterday
from handlers.menu import send_main_menu


SELECT_PROJECT, ENTER_HOURS, MORE, SEL_CLIENT, NEW_CLIENT, SEL_CLIENT_PROJECT, NEW_PROJECT, SLEEPING = range(1, 9)


def _projects_kb(projects: list[dict], add_label: str, done_label: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in projects:
        rows.append(
            [InlineKeyboardButton(f"{p['client_name']} / {p['name']}", callback_data=f"log:proj:{p['id']}")]
        )
    rows.append([InlineKeyboardButton(add_label, callback_data="log:add")])
    rows.append([InlineKeyboardButton(done_label, callback_data="log:done")])
    return InlineKeyboardMarkup(rows)


def _clients_kb(rows: list[dict]) -> InlineKeyboardMarkup:
    kb: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(r["name"], callback_data=f"log:client:{r['id']}")] for r in rows
    ]
    kb.append([InlineKeyboardButton("Новый клиент", callback_data="log:client:new")])
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="log:back:projects")])
    return InlineKeyboardMarkup(kb)


def _client_projects_kb(rows: list[dict]) -> InlineKeyboardMarkup:
    kb: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(r["name"], callback_data=f"log:cproj:{r['id']}")] for r in rows
    ]
    kb.append([InlineKeyboardButton("Нет нужного, создать новый", callback_data="log:cproj:new")])
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="log:back:clients")])
    return InlineKeyboardMarkup(kb)


def _more_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Ещё проект", callback_data="log:more")],
            [InlineKeyboardButton("Готово", callback_data="log:done")],
        ]
    )


def _sleeping_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Да", callback_data="log:sleep:yes"),
                InlineKeyboardButton("Нет", callback_data="log:sleep:no"),
                InlineKeyboardButton("Позже", callback_data="log:sleep:later"),
            ]
        ]
    )


async def _load_user_projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    db = await get_db(context)
    me = context.user_data["me"]
    rows = await db.list_active_projects_for_user(me.id)
    return [dict(r) for r in rows]


@require_role("member")
async def log_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tz = context.bot_data.get("tz")
    context.user_data["log_date"] = yesterday(tz=tz)
    db = await get_db(context)
    await db.mark_sleeping_projects(today=dt.datetime.now(tz=tz).date())
    projects = await _load_user_projects(update, context)
    if not projects:
        await update.effective_message.reply_text(
            "У тебя пока нет активных проектов. Давай добавим.",
        )
        return await start_add_project(update, context)
    await update.effective_message.reply_text(
        f"Выбери проект для {context.user_data['log_date'].isoformat()}:",
        reply_markup=_projects_kb(projects, "Добавить другой проект", "Готово"),
    )
    return SELECT_PROJECT


async def select_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "log:add":
        return await start_add_project(update, context)
    if data == "log:done":
        return await maybe_sleeping_start(update, context)
    if data.startswith("log:proj:"):
        project_id = int(data.split(":")[-1])
        context.user_data["selected_project_id"] = project_id
        await q.edit_message_text("Сколько часов? (например 3.5)")
        return ENTER_HOURS
    return SELECT_PROJECT


async def enter_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    raw = (update.message.text or "").strip().replace(",", ".")
    try:
        hours = float(raw)
    except Exception:
        await update.message.reply_text("Не понял число. Введи, например 2 или 3.5")
        return ENTER_HOURS
    if hours <= 0 or hours > 24:
        await update.message.reply_text("Часы должны быть в диапазоне (0..24]. Попробуй ещё раз.")
        return ENTER_HOURS

    db = await get_db(context)
    me = context.user_data["me"]
    project_id = int(context.user_data["selected_project_id"])
    date_: dt.date = context.user_data["log_date"]
    await db.add_timelog(user_id=me.id, project_id=project_id, hours=hours, date_=date_)
    await db.touch_project_activity(project_id=project_id, activity_date=date_)

    await update.message.reply_text("Сохранено. Ещё проект?", reply_markup=_more_kb())
    return MORE


async def more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    if (q.data or "") == "log:more":
        projects = await _load_user_projects(update, context)
        await q.edit_message_text(
            "Выбери следующий проект:",
            reply_markup=_projects_kb(projects, "Добавить другой проект", "Готово"),
        )
        return SELECT_PROJECT
    if (q.data or "") == "log:done":
        return await maybe_sleeping_start(update, context)
    return MORE


async def maybe_sleeping_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db = await get_db(context)
    me = context.user_data["me"]
    sleeping = await db.list_sleeping_projects_for_user(me.id)
    sleeping_list = [dict(r) for r in sleeping]
    if update.callback_query:
        await update.callback_query.edit_message_text("Спасибо! Проверяю спящие проекты…")
    if not sleeping_list:
        await update.effective_message.reply_text("Готово.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    context.user_data["sleeping_projects"] = sleeping_list
    context.user_data["sleeping_idx"] = 0
    return await ask_sleeping(update, context)


async def ask_sleeping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    idx = int(context.user_data["sleeping_idx"])
    items: list[dict] = context.user_data["sleeping_projects"]
    if idx >= len(items):
        await update.effective_message.reply_text("Готово.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    p = items[idx]
    last = p.get("last_activity_at") or "—"
    await update.effective_message.reply_text(
        f"Проект спит 14+ дней: {p['client_name']} / {p['name']}\nПоследняя активность: {last}\nЗавершить?",
        reply_markup=_sleeping_kb(),
    )
    return SLEEPING


async def sleeping_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    action = (q.data or "").split(":")[-1]
    idx = int(context.user_data["sleeping_idx"])
    items: list[dict] = context.user_data["sleeping_projects"]
    p = items[idx]

    db = await get_db(context)
    if action == "yes":
        await db.set_project_status(int(p["id"]), "done")
        await q.edit_message_text(f"Закрыл: {p['client_name']} / {p['name']}")
    elif action == "no":
        await q.edit_message_text(f"Оставил спящим: {p['client_name']} / {p['name']}")
    elif action == "later":
        await q.edit_message_text("Ок, вернёмся позже.")
        await send_main_menu(update, context)
        return ConversationHandler.END

    context.user_data["sleeping_idx"] = idx + 1
    return await ask_sleeping(update, context)


async def start_add_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q:
        await q.answer()
    db = await get_db(context)
    clients = [dict(r) for r in await db.list_clients()]
    if not clients:
        await update.effective_message.reply_text("Клиентов пока нет. Введи название нового клиента:")
        return NEW_CLIENT
    await update.effective_message.reply_text("Выбери клиента:", reply_markup=_clients_kb(clients))
    return SEL_CLIENT


async def select_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "log:client:new":
        await q.edit_message_text("Введи название нового клиента:")
        return NEW_CLIENT
    if data == "log:back:projects":
        projects = await _load_user_projects(update, context)
        await q.edit_message_text(
            "Выбери проект:",
            reply_markup=_projects_kb(projects, "Добавить другой проект", "Готово"),
        )
        return SELECT_PROJECT
    if data.startswith("log:client:"):
        client_id = int(data.split(":")[-1])
        context.user_data["selected_client_id"] = client_id
        db = await get_db(context)
        prows = [dict(r) for r in await db.list_projects_for_client_active(client_id)]
        await q.edit_message_text("Проекты клиента:", reply_markup=_client_projects_kb(prows))
        return SEL_CLIENT_PROJECT
    return SEL_CLIENT


async def new_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("Название слишком короткое. Введи ещё раз.")
        return NEW_CLIENT
    db = await get_db(context)
    client_id = await db.create_client(name)
    context.user_data["selected_client_id"] = client_id
    await update.message.reply_text("Клиент создан. Теперь введи название проекта:")
    return NEW_PROJECT


async def select_client_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "log:cproj:new":
        await q.edit_message_text("Введи название нового проекта:")
        return NEW_PROJECT
    if data == "log:back:clients":
        clients = [dict(r) for r in await (await get_db(context)).list_clients()]
        await q.edit_message_text("Выбери клиента:", reply_markup=_clients_kb(clients))
        return SEL_CLIENT
    if data.startswith("log:cproj:"):
        project_id = int(data.split(":")[-1])
        db = await get_db(context)
        me = context.user_data["me"]
        await db.attach_user_to_project(me.id, project_id)
        projects = await _load_user_projects(update, context)
        await q.edit_message_text(
            "Готово! Выбери проект:",
            reply_markup=_projects_kb(projects, "Добавить другой проект", "Готово"),
        )
        return SELECT_PROJECT
    return SEL_CLIENT_PROJECT


async def new_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("Название слишком короткое. Введи ещё раз.")
        return NEW_PROJECT
    db = await get_db(context)
    me = context.user_data["me"]
    client_id = int(context.user_data["selected_client_id"])
    project_id = await db.create_project(client_id=client_id, name=name)
    await db.attach_user_to_project(me.id, project_id)
    projects = await _load_user_projects(update, context)
    await update.message.reply_text(
        "Проект создан и добавлен тебе. Выбери проект для логирования:",
        reply_markup=_projects_kb(projects, "Добавить другой проект", "Готово"),
    )
    return SELECT_PROJECT


# ---------- daily reminder callbacks ----------


@require_role("member")
async def reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    tz = context.bot_data.get("tz")
    context.user_data["log_date"] = yesterday(tz=tz)
    data = q.data or ""
    if data == "rem:skip":
        await q.edit_message_text("Ок, пропустили.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    if data == "rem:add":
        await q.edit_message_text("Добавим проект.")
        return await start_add_project(update, context)
    if data.startswith("rem:proj:"):
        project_id = int(data.split(":")[-1])
        context.user_data["selected_project_id"] = project_id
        await q.edit_message_text("Сколько часов за вчера? (например 3.5)")
        return ENTER_HOURS
    await send_main_menu(update, context)
    return ConversationHandler.END


def reminder_keyboard(projects: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in projects:
        rows.append(
            [InlineKeyboardButton(f"{p['client_name']} / {p['name']}", callback_data=f"rem:proj:{p['id']}")]
        )
    rows.append([InlineKeyboardButton("Добавить проект", callback_data="rem:add")])
    rows.append([InlineKeyboardButton("Пропустить", callback_data="rem:skip")])
    return InlineKeyboardMarkup(rows)


log_conversation = ConversationHandler(
    entry_points=[
        CommandHandler("log", log_entry),
        CallbackQueryHandler(log_entry, pattern=r"^menu:log$"),
        CallbackQueryHandler(reminder_callback, pattern=r"^rem:"),
    ],
    states={
        SELECT_PROJECT: [CallbackQueryHandler(select_project, pattern=r"^log:")],
        ENTER_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_hours)],
        MORE: [CallbackQueryHandler(more, pattern=r"^log:")],
        SEL_CLIENT: [CallbackQueryHandler(select_client, pattern=r"^log:")],
        NEW_CLIENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_client)],
        SEL_CLIENT_PROJECT: [CallbackQueryHandler(select_client_project, pattern=r"^log:")],
        NEW_PROJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_project)],
        SLEEPING: [CallbackQueryHandler(sleeping_answer, pattern=r"^log:sleep:")],
    },
    fallbacks=[],
    name="log",
    persistent=False,
)

