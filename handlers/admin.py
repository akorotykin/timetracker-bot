from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from handlers.common import get_db, require_role
from handlers.menu import send_main_menu
from handlers.positions import POSITIONS, position_label, positions_kb


MENU, USER_SELECT, USER_RATES, USER_POSITION, CLIENTS, CLIENT_RENAME, PROJECTS, ROLES_LIST, ROLES_ACTION = range(1, 10)


def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Сотрудники (роль/ставки)", callback_data="adm:users")],
            [InlineKeyboardButton("Управление ролями", callback_data="adm:roles")],
            [InlineKeyboardButton("Проекты (закрыть)", callback_data="adm:projects")],
            [InlineKeyboardButton("Клиенты (добавить/переименовать)", callback_data="adm:clients")],
            [InlineKeyboardButton("Закрыть", callback_data="adm:close")],
        ]
    )


@require_role("admin")
async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("Админ-панель:", reply_markup=_menu_kb())
    return MENU


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "adm:close":
        await q.edit_message_text("Ок.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    if data == "adm:users":
        db = await get_db(context)
        users = [dict(r) for r in await db.list_users()]
        kb = [
            [
                InlineKeyboardButton(
                    f"{u['name']} ({u['role']}) — {position_label(u.get('position'))}",
                    callback_data=f"adm:user:{u['id']}",
                )
            ]
            for u in users
        ]
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm:back")])
        await q.edit_message_text("Сотрудники:", reply_markup=InlineKeyboardMarkup(kb))
        return USER_SELECT
    if data == "adm:roles":
        db = await get_db(context)
        users = [dict(r) for r in await db.list_users()]
        kb = [
            [
                InlineKeyboardButton(
                    f"{u['name']} ({u['role']}) — {position_label(u.get('position'))}",
                    callback_data=f"adm:rolesel:{u['id']}",
                )
            ]
            for u in users
        ]
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm:back")])
        await q.edit_message_text("Управление ролями — выбери сотрудника:", reply_markup=InlineKeyboardMarkup(kb))
        return ROLES_LIST
    if data == "adm:projects":
        db = await get_db(context)
        projects = [dict(r) for r in await db.list_all_open_projects()]
        kb = [
            [
                InlineKeyboardButton(
                    f"{p['status']} | {p['client_name']} / {p['name']}",
                    callback_data=f"adm:proj:{p['id']}",
                )
            ]
            for p in projects
        ]
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm:back")])
        await q.edit_message_text("Открытые проекты (нажми чтобы закрыть):", reply_markup=InlineKeyboardMarkup(kb))
        return PROJECTS
    if data == "adm:clients":
        db = await get_db(context)
        clients = [dict(r) for r in await db.list_clients()]
        kb = [[InlineKeyboardButton(c["name"], callback_data=f"adm:client:{c['id']}")] for c in clients]
        kb.append([InlineKeyboardButton("➕ Добавить клиента", callback_data="adm:client:new")])
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm:back")])
        await q.edit_message_text("Клиенты:", reply_markup=InlineKeyboardMarkup(kb))
        return CLIENTS
    if data == "adm:back":
        await q.edit_message_text("Админ-панель:", reply_markup=_menu_kb())
        return MENU
    return MENU


async def roles_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "adm:back":
        await q.edit_message_text("Админ-панель:", reply_markup=_menu_kb())
        return MENU
    if data.startswith("adm:rolesel:"):
        user_id = int(data.split(":")[-1])
        context.user_data["adm_role_user_id"] = user_id
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Сделать admin", callback_data="adm:roleset:admin"),
                    InlineKeyboardButton("Сделать observer", callback_data="adm:roleset:observer"),
                    InlineKeyboardButton("Сделать member", callback_data="adm:roleset:member"),
                ],
                [InlineKeyboardButton("⬅️ К списку", callback_data="adm:rolesback")],
            ]
        )
        await q.edit_message_text("Выбери роль:", reply_markup=kb)
        return ROLES_ACTION
    return ROLES_LIST


async def roles_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "adm:rolesback":
        db = await get_db(context)
        users = [dict(r) for r in await db.list_users()]
        kb = [
            [
                InlineKeyboardButton(
                    f"{u['name']} ({u['role']}) — {position_label(u.get('position'))}",
                    callback_data=f"adm:rolesel:{u['id']}",
                )
            ]
            for u in users
        ]
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm:back")])
        await q.edit_message_text("Управление ролями — выбери сотрудника:", reply_markup=InlineKeyboardMarkup(kb))
        return ROLES_LIST
    if data.startswith("adm:roleset:"):
        role = data.split(":")[-1]
        user_id = int(context.user_data["adm_role_user_id"])
        db = await get_db(context)
        await db.set_user_role(user_id, role)
        user_row = await db.fetchone("SELECT name FROM users WHERE id = ?;", (user_id,))
        name = user_row["name"] if user_row else str(user_id)
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⬅️ К списку", callback_data="adm:rolesback")],
                [InlineKeyboardButton("В меню админки", callback_data="adm:back")],
            ]
        )
        await q.edit_message_text(f"Роль обновлена: {name} → {role}", reply_markup=kb)
        return ROLES_ACTION
    if data == "adm:back":
        await q.edit_message_text("Админ-панель:", reply_markup=_menu_kb())
        return MENU
    return ROLES_ACTION


async def user_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "adm:back":
        await q.edit_message_text("Админ-панель:", reply_markup=_menu_kb())
        return MENU
    if data.startswith("adm:user:"):
        user_id = int(data.split(":")[-1])
        context.user_data["adm_user_id"] = user_id
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Роль: admin", callback_data="adm:role:admin"),
                    InlineKeyboardButton("observer", callback_data="adm:role:observer"),
                    InlineKeyboardButton("member", callback_data="adm:role:member"),
                ],
                [InlineKeyboardButton("Должность (выбрать)", callback_data="adm:position")],
                [InlineKeyboardButton("Ставки (ввести)", callback_data="adm:rates")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="adm:back-users")],
            ]
        )
        await q.edit_message_text("Действия:", reply_markup=kb)
        return USER_SELECT
    if data.startswith("adm:role:"):
        role = data.split(":")[-1]
        db = await get_db(context)
        await db.set_user_role(int(context.user_data["adm_user_id"]), role)
        await q.edit_message_text(f"Роль обновлена: {role}", reply_markup=_menu_kb())
        return MENU
    if data == "adm:rates":
        await q.edit_message_text("Введи ставки через пробел: internal_rate external_rate (например: 25 60)")
        return USER_RATES
    if data == "adm:position":
        await q.edit_message_text("Выбери должность:", reply_markup=positions_kb("admpos"))
        return USER_POSITION
    if data == "adm:back-users":
        db = await get_db(context)
        users = [dict(r) for r in await db.list_users()]
        kb = [
            [
                InlineKeyboardButton(
                    f"{u['name']} ({u['role']}) — {position_label(u.get('position'))}",
                    callback_data=f"adm:user:{u['id']}",
                )
            ]
            for u in users
        ]
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm:back")])
        await q.edit_message_text("Сотрудники:", reply_markup=InlineKeyboardMarkup(kb))
        return USER_SELECT
    return USER_SELECT


async def user_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if not data.startswith("admpos:"):
        await q.edit_message_text("Не понял выбор.")
        return USER_POSITION
    pos = data.split(":")[-1]
    if pos not in POSITIONS:
        await q.edit_message_text("Не понял должность.")
        return USER_POSITION
    db = await get_db(context)
    await db.set_user_position(int(context.user_data["adm_user_id"]), pos)
    await q.edit_message_text(f"Должность обновлена: {position_label(pos)}")
    await q.message.reply_text("Админ-панель:", reply_markup=_menu_kb())
    return MENU


async def user_rates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    raw = (update.message.text or "").strip().replace(",", ".")
    parts = raw.split()
    if len(parts) != 2:
        await update.message.reply_text("Нужно 2 числа: internal external")
        return USER_RATES
    try:
        i = float(parts[0])
        e = float(parts[1])
    except Exception:
        await update.message.reply_text("Не понял числа. Пример: 25 60")
        return USER_RATES
    if i < 0 or e < 0:
        await update.message.reply_text("Ставки не могут быть отрицательными.")
        return USER_RATES
    db = await get_db(context)
    await db.set_user_rates(int(context.user_data["adm_user_id"]), i, e)
    await update.message.reply_text("Ставки обновлены.", reply_markup=_menu_kb())
    return MENU


async def clients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "adm:back":
        await q.edit_message_text("Админ-панель:", reply_markup=_menu_kb())
        return MENU
    if data == "adm:client:new":
        await q.edit_message_text("Введи название нового клиента:")
        context.user_data["adm_client_id"] = None
        return CLIENT_RENAME
    if data.startswith("adm:client:"):
        client_id = int(data.split(":")[-1])
        context.user_data["adm_client_id"] = client_id
        await q.edit_message_text("Введи новое название клиента:")
        return CLIENT_RENAME
    return CLIENTS


async def client_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("Слишком коротко. Введи ещё раз.")
        return CLIENT_RENAME
    db = await get_db(context)
    client_id = context.user_data.get("adm_client_id")
    if client_id is None:
        await db.create_client(name)
        await update.message.reply_text("Клиент добавлен.", reply_markup=_menu_kb())
        return MENU
    await db.rename_client(int(client_id), name)
    await update.message.reply_text("Клиент переименован.", reply_markup=_menu_kb())
    return MENU


async def projects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "adm:back":
        await q.edit_message_text("Админ-панель:", reply_markup=_menu_kb())
        return MENU
    if data.startswith("adm:proj:"):
        project_id = int(data.split(":")[-1])
        db = await get_db(context)
        await db.set_project_status(project_id, "done")
        await q.edit_message_text("Проект закрыт.", reply_markup=_menu_kb())
        return MENU
    return PROJECTS


admin_conversation = ConversationHandler(
    entry_points=[CommandHandler("admin", admin_entry), CallbackQueryHandler(admin_entry, pattern=r"^menu:admin$")],
    states={
        MENU: [CallbackQueryHandler(menu, pattern=r"^adm:")],
        USER_SELECT: [CallbackQueryHandler(user_select, pattern=r"^adm:")],
        USER_RATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_rates)],
        USER_POSITION: [CallbackQueryHandler(user_position, pattern=r"^admpos:")],
        CLIENTS: [CallbackQueryHandler(clients, pattern=r"^adm:")],
        CLIENT_RENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_rename)],
        PROJECTS: [CallbackQueryHandler(projects, pattern=r"^adm:")],
        ROLES_LIST: [CallbackQueryHandler(roles_list, pattern=r"^adm:")],
        ROLES_ACTION: [CallbackQueryHandler(roles_action, pattern=r"^adm:")],
    },
    fallbacks=[],
    name="admin",
    persistent=False,
)

