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


MENU, USER_SELECT, USER_RATES, USER_POSITION, CLIENTS, CLIENT_RENAME, PROJECTS, ROLES_LIST, ROLES_ACTION, POS_LIST, POS_ACTION, POS_RATES, POS_RENAME, POS_ADD, POS_APPLY = range(
    1, 16
)


def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Сотрудники (роль/ставки)", callback_data="adm:users")],
            [InlineKeyboardButton("Управление ролями", callback_data="adm:roles")],
            [InlineKeyboardButton("Должности и ставки", callback_data="adm:positions")],
            [InlineKeyboardButton("Управление проектами", callback_data="adm:projects")],
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
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Все", callback_data="adm:projf:all"),
                    InlineKeyboardButton("Active", callback_data="adm:projf:active"),
                    InlineKeyboardButton("Done", callback_data="adm:projf:done"),
                ],
                [InlineKeyboardButton("⬅️ Назад", callback_data="adm:back")],
            ]
        )
        await q.edit_message_text("Управление проектами — фильтр:", reply_markup=kb)
        return PROJECTS
    if data == "adm:clients":
        db = await get_db(context)
        clients = [dict(r) for r in await db.list_clients()]
        kb = [[InlineKeyboardButton(c["name"], callback_data=f"adm:client:{c['id']}")] for c in clients]
        kb.append([InlineKeyboardButton("➕ Добавить клиента", callback_data="adm:client:new")])
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm:back")])
        await q.edit_message_text("Клиенты:", reply_markup=InlineKeyboardMarkup(kb))
        return CLIENTS
    if data == "adm:positions":
        db = await get_db(context)
        items = [dict(r) for r in await db.list_positions()]
        kb = [
            [
                InlineKeyboardButton(
                    f"{position_label(p['name'])} — внутр: {int(p['default_internal_rate'])}₽ / внешн: {int(p['default_external_rate'])}₽",
                    callback_data=f"adm:pos:{p['id']}",
                )
            ]
            for p in items
        ]
        kb.append([InlineKeyboardButton("➕ Добавить новую должность", callback_data="adm:pos:add")])
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="adm:back")])
        await q.edit_message_text("Должности и ставки:", reply_markup=InlineKeyboardMarkup(kb))
        return POS_LIST
    if data == "adm:back":
        await q.edit_message_text("Админ-панель:", reply_markup=_menu_kb())
        return MENU
    return MENU


async def positions_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "adm:back":
        await q.edit_message_text("Админ-панель:", reply_markup=_menu_kb())
        return MENU
    if data == "adm:pos:add":
        await q.edit_message_text("Введи новую должность (ключ, например: motion_designer):")
        return POS_ADD
    if data.startswith("adm:pos:"):
        pos_id = int(data.split(":")[-1])
        context.user_data["adm_pos_id"] = pos_id
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Изменить ставки", callback_data="adm:posact:rates"),
                    InlineKeyboardButton("Переименовать", callback_data="adm:posact:rename"),
                ],
                [InlineKeyboardButton("Удалить", callback_data="adm:posact:delete")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="adm:positions")],
            ]
        )
        await q.edit_message_text("Действия с должностью:", reply_markup=kb)
        return POS_ACTION
    return POS_LIST


async def positions_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "adm:positions":
        # bounce to menu() handler via state routing
        await q.edit_message_text("Загружаю…")
        return MENU
    if data == "adm:posact:rates":
        await q.edit_message_text("Введи ставки через пробел: internal external (например: 5000 10000)")
        return POS_RATES
    if data == "adm:posact:rename":
        await q.edit_message_text("Введи новое имя должности (ключ):")
        return POS_RENAME
    if data == "adm:posact:delete":
        db = await get_db(context)
        await db.delete_position(int(context.user_data["adm_pos_id"]))
        await q.edit_message_text("Удалено.")
        await q.message.reply_text("Админ-панель:", reply_markup=_menu_kb())
        return MENU
    if data == "adm:back":
        await q.edit_message_text("Админ-панель:", reply_markup=_menu_kb())
        return MENU
    return POS_ACTION


async def positions_rates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    raw = (update.message.text or "").strip().replace(",", ".")
    parts = raw.split()
    if len(parts) != 2:
        await update.message.reply_text("Нужно 2 числа: internal external")
        return POS_RATES
    try:
        i = float(parts[0])
        e = float(parts[1])
    except Exception:
        await update.message.reply_text("Не понял числа. Пример: 5000 10000")
        return POS_RATES
    if i < 0 or e < 0:
        await update.message.reply_text("Ставки не могут быть отрицательными.")
        return POS_RATES
    context.user_data["adm_pos_new_rates"] = (i, e)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Да, обновить всех", callback_data="adm:posapply:yes"),
                InlineKeyboardButton("Нет, только для новых", callback_data="adm:posapply:no"),
            ]
        ]
    )
    await update.message.reply_text("Применить новые ставки ко всем сотрудникам с этой должностью?", reply_markup=kb)
    return POS_APPLY


async def positions_apply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data not in {"adm:posapply:yes", "adm:posapply:no"}:
        await q.edit_message_text("Не понял.")
        return POS_APPLY
    db = await get_db(context)
    pos_id = int(context.user_data["adm_pos_id"])
    row = await db.fetchone("SELECT name FROM positions WHERE id = ?;", (pos_id,))
    pos_name = str(row["name"]) if row else ""
    i, e = context.user_data["adm_pos_new_rates"]
    await db.update_position_rates(pos_id, i, e)
    if data.endswith(":yes") and pos_name:
        await db.apply_position_rates_to_users(pos_name, i, e)
    await q.edit_message_text("Ставки обновлены.")
    await q.message.reply_text("Админ-панель:", reply_markup=_menu_kb())
    return MENU


async def positions_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("Слишком коротко.")
        return POS_RENAME
    db = await get_db(context)
    await db.rename_position(int(context.user_data["adm_pos_id"]), name)
    await update.message.reply_text("Переименовано.", reply_markup=_menu_kb())
    return MENU


async def positions_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("Слишком коротко.")
        return POS_ADD
    db = await get_db(context)
    await db.create_position(name=name, default_internal_rate=0, default_external_rate=0)
    await update.message.reply_text("Должность добавлена.", reply_markup=_menu_kb())
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
        db = await get_db(context)
        urow = await db.fetchone(
            "SELECT name, role, position, internal_rate, external_rate FROM users WHERE id = ?;",
            (user_id,),
        )
        if not urow:
            await q.edit_message_text("Пользователь не найден.")
            return USER_SELECT
        header = "\n".join(
            [
                f"Имя: {urow['name']}",
                f"Должность: {position_label(urow['position'])}",
                f"Внутренняя ставка: {float(urow['internal_rate'] or 0):.0f}₽",
                f"Внешняя ставка: {float(urow['external_rate'] or 0):.0f}₽",
                f"Роль в системе: {urow['role']}",
            ]
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Изменить внутр. ставку", callback_data="adm:rate:internal"),
                    InlineKeyboardButton("Изменить внешн. ставку", callback_data="adm:rate:external"),
                ],
                [
                    InlineKeyboardButton("Роль: admin", callback_data="adm:role:admin"),
                    InlineKeyboardButton("observer", callback_data="adm:role:observer"),
                    InlineKeyboardButton("member", callback_data="adm:role:member"),
                ],
                [InlineKeyboardButton("Должность (выбрать)", callback_data="adm:position")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="adm:back-users")],
            ]
        )
        await q.edit_message_text(header, reply_markup=kb)
        return USER_SELECT
    if data.startswith("adm:role:"):
        role = data.split(":")[-1]
        db = await get_db(context)
        await db.set_user_role(int(context.user_data["adm_user_id"]), role)
        await q.edit_message_text(f"Роль обновлена: {role}", reply_markup=_menu_kb())
        return MENU
    if data.startswith("adm:rate:"):
        which = data.split(":")[-1]
        context.user_data["adm_rate_which"] = which
        await q.edit_message_text("Введи ставку в рублях (например: 7000)")
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
    try:
        val = float(((update.message.text or "").strip().replace(",", ".")))
    except Exception:
        await update.message.reply_text("Не понял число. Пример: 7000")
        return USER_RATES
    if val < 0:
        await update.message.reply_text("Ставки не могут быть отрицательными.")
        return USER_RATES
    db = await get_db(context)
    user_id = int(context.user_data["adm_user_id"])
    which = context.user_data.get("adm_rate_which")
    row = await db.fetchone("SELECT internal_rate, external_rate FROM users WHERE id = ?;", (user_id,))
    cur_i = float(row["internal_rate"] or 0) if row else 0.0
    cur_e = float(row["external_rate"] or 0) if row else 0.0
    if which == "internal":
        await db.set_user_rates(user_id, val, cur_e)
    else:
        await db.set_user_rates(user_id, cur_i, val)
    await update.message.reply_text("Ставка обновлена.", reply_markup=_menu_kb())
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
    if data.startswith("adm:projf:"):
        f = data.split(":")[-1]
        status = None if f == "all" else f
        db = await get_db(context)
        items = [dict(r) for r in await db.list_all_projects(status=status)]
        kb: list[list[InlineKeyboardButton]] = []
        for p in items:
            line = f"{p['status']} | {p['client_name']} / {p['name']}"
            if p["status"] == "done":
                who = p.get("closed_by_name") or "—"
                when = (p.get("closed_at") or "—")
                line += f" (закрыл: {who}, {when})"
                kb.append([InlineKeyboardButton(line, callback_data=f"adm:reopen:{p['id']}")])
            else:
                kb.append([InlineKeyboardButton(line, callback_data=f"adm:proj:{p['id']}")])
        kb.append(
            [
                InlineKeyboardButton("Фильтр", callback_data="adm:projects"),
                InlineKeyboardButton("⬅️ Назад", callback_data="adm:back"),
            ]
        )
        await q.edit_message_text("Проекты (active → закрыть, done → вернуть):", reply_markup=InlineKeyboardMarkup(kb))
        return PROJECTS
    if data.startswith("adm:proj:"):
        project_id = int(data.split(":")[-1])
        db = await get_db(context)
        me = context.user_data["me"]
        await db.close_project(project_id, closed_by_user_id=me.id)
        await q.edit_message_text("Проект закрыт.", reply_markup=_menu_kb())
        return MENU
    if data.startswith("adm:reopen:"):
        project_id = int(data.split(":")[-1])
        db = await get_db(context)
        await db.reopen_project(project_id)
        await q.edit_message_text("Вернул в работу.", reply_markup=_menu_kb())
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
        POS_LIST: [CallbackQueryHandler(positions_list, pattern=r"^adm:")],
        POS_ACTION: [CallbackQueryHandler(positions_action, pattern=r"^adm:")],
        POS_RATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, positions_rates)],
        POS_RENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, positions_rename)],
        POS_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, positions_add)],
        POS_APPLY: [CallbackQueryHandler(positions_apply, pattern=r"^adm:posapply:")],
    },
    fallbacks=[],
    name="admin",
    persistent=False,
)

