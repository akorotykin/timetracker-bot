from __future__ import annotations

import datetime as dt

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
from handlers.positions import position_label


MENU, P_USER, P_PROJECT, P_HOURS, D_CLIENT, D_PROJECT, D_DATE = range(1, 8)


def _planning_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Назначить план", callback_data="plan:assign"),
                InlineKeyboardButton("Посмотреть загрузку команды", callback_data="plan:team"),
            ],
            [InlineKeyboardButton("Установить дедлайн", callback_data="plan:deadline")],
            [InlineKeyboardButton("Закрыть", callback_data="plan:close")],
        ]
    )


async def _ensure_tm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    db = await get_db(context)
    me = context.user_data.get("me")
    if me is None:
        # ensure require_role already ran
        return False
    # refresh position from DB (in case changed)
    row = await db.fetchone("SELECT position FROM users WHERE id = ?;", (me.id,))
    pos = (row["position"] if row else me.position) if row else me.position
    return pos == "traffic_manager"


@require_role("member")
async def planning_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _ensure_tm(update, context):
        await update.effective_message.reply_text("Недостаточно прав.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    await update.effective_message.reply_text("Планирование:", reply_markup=_planning_menu_kb())
    return MENU


async def planning_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "plan:close":
        await q.edit_message_text("Ок.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    if data == "plan:assign":
        db = await get_db(context)
        users = [dict(r) for r in await db.list_users_basic()]
        kb = [[InlineKeyboardButton(f"{u['name']} — {position_label(u.get('position'))}", callback_data=f"plan:u:{u['id']}")] for u in users]
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="plan:back")])
        await q.edit_message_text("Выбери сотрудника:", reply_markup=InlineKeyboardMarkup(kb))
        return P_USER
    if data == "plan:deadline":
        db = await get_db(context)
        clients = [dict(r) for r in await db.list_clients()]
        kb = [[InlineKeyboardButton(c["name"], callback_data=f"plan:c:{c['id']}")] for c in clients]
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="plan:back")])
        await q.edit_message_text("Выбери клиента:", reply_markup=InlineKeyboardMarkup(kb))
        return D_CLIENT
    if data == "plan:team":
        # Reuse existing /workload output for now (team view)
        db = await get_db(context)
        today = dt.date.today()
        start = dt.date(today.year, today.month, 1)
        end = today
        rows = await db.fetchall(
            """
            SELECT u.id AS user_id, u.name AS user_name, u.position AS position,
                   COALESCE(SUM(t.hours),0) AS hours
            FROM users u
            LEFT JOIN timelog t ON t.user_id = u.id AND t.date BETWEEN ? AND ?
            WHERE u.role IN ('member','admin')
            GROUP BY u.id
            ORDER BY u.name;
            """,
            (start.isoformat(), end.isoformat()),
        )
        lines = [f"Загрузка команды за {start.isoformat()} .. {end.isoformat()}:"]
        for r in rows:
            h = float(r["hours"] or 0)
            # Progress against planned total (sum of plans for active projects)
            prow = await db.fetchone(
                """
                SELECT COALESCE(SUM(pp.planned_hours),0) AS planned
                FROM project_plans pp
                JOIN projects p ON p.id = pp.project_id
                WHERE pp.user_id = ? AND p.status='active';
                """,
                (int(r["user_id"]),),
            )
            planned = float(prow["planned"] or 0) if prow else 0.0
            bar = _bar(h, planned)
            pos = position_label(r["position"])
            if planned > 0:
                lines.append(f"- {r['user_name']} — {pos}: {h:.1f}/{planned:.1f} ч {bar}")
            else:
                lines.append(f"- {r['user_name']} — {pos}: {h:.1f} ч {bar}")
        await q.edit_message_text("\n".join(lines))
        await send_main_menu(update, context)
        return ConversationHandler.END
    if data == "plan:back":
        await q.edit_message_text("Планирование:", reply_markup=_planning_menu_kb())
        return MENU
    return MENU


def _bar(actual: float, planned: float, width: int = 10) -> str:
    if planned <= 0:
        filled = min(width, int(actual // 10))
        return "[" + ("█" * filled) + ("·" * (width - filled)) + "]"
    ratio = min(1.0, actual / planned) if planned > 0 else 0.0
    filled = int(ratio * width)
    return "[" + ("█" * filled) + ("·" * (width - filled)) + "]"


async def plan_pick_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "plan:back":
        await q.edit_message_text("Планирование:", reply_markup=_planning_menu_kb())
        return MENU
    if data.startswith("plan:u:"):
        uid = int(data.split(":")[-1])
        context.user_data["plan_user_id"] = uid
        db = await get_db(context)
        projects = [dict(r) for r in await db.list_active_projects_for_user(uid)]
        kb = [[InlineKeyboardButton(f"{p['client_name']} / {p['name']}", callback_data=f"plan:p:{p['id']}")] for p in projects]
        kb.append([InlineKeyboardButton("Добавить на новый проект", callback_data="plan:p:new")])
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="plan:back")])
        await q.edit_message_text("Выбери проект сотрудника:", reply_markup=InlineKeyboardMarkup(kb))
        return P_PROJECT
    return P_USER


async def plan_pick_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "plan:back":
        await q.edit_message_text("Планирование:", reply_markup=_planning_menu_kb())
        return MENU
    if data == "plan:p:new":
        db = await get_db(context)
        clients = [dict(r) for r in await db.list_clients()]
        kb = [[InlineKeyboardButton(c["name"], callback_data=f"plan:nc:{c['id']}")] for c in clients]
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="plan:back")])
        await q.edit_message_text("Выбери клиента:", reply_markup=InlineKeyboardMarkup(kb))
        return P_PROJECT
    if data.startswith("plan:nc:"):
        client_id = int(data.split(":")[-1])
        context.user_data["plan_new_client_id"] = client_id
        db = await get_db(context)
        prows = [dict(r) for r in await db.list_projects_for_client(client_id, status="active")]
        kb = [[InlineKeyboardButton(p["name"], callback_data=f"plan:np:{p['id']}")] for p in prows]
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="plan:back")])
        await q.edit_message_text("Выбери проект:", reply_markup=InlineKeyboardMarkup(kb))
        return P_PROJECT
    if data.startswith("plan:np:"):
        project_id = int(data.split(":")[-1])
        db = await get_db(context)
        uid = int(context.user_data["plan_user_id"])
        await db.attach_user_to_project(uid, project_id)
        context.user_data["plan_project_id"] = project_id
        await q.edit_message_text("Введи плановые часы (число):")
        return P_HOURS
    if data.startswith("plan:p:"):
        project_id = int(data.split(":")[-1])
        context.user_data["plan_project_id"] = project_id
        await q.edit_message_text("Введи плановые часы (число):")
        return P_HOURS
    return P_PROJECT


async def plan_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    raw = (update.message.text or "").strip().replace(",", ".")
    try:
        hours = float(raw)
    except Exception:
        await update.message.reply_text("Не понял число. Пример: 40")
        return P_HOURS
    if hours <= 0 or hours > 1000:
        await update.message.reply_text("Некорректное число часов.")
        return P_HOURS
    db = await get_db(context)
    tm = context.user_data["me"]
    uid = int(context.user_data["plan_user_id"])
    pid = int(context.user_data["plan_project_id"])
    await db.upsert_project_plan(uid, pid, hours, set_by_user_id=tm.id)
    row = await db.fetchone(
        """
        SELECT u.name AS user_name, c.name AS client_name, p.name AS project_name
        FROM users u
        JOIN projects p ON p.id = ?
        JOIN clients c ON c.id = p.client_id
        WHERE u.id = ?;
        """,
        (pid, uid),
    )
    if row:
        await update.message.reply_text(
            f"Назначено: {row['user_name']} → {row['client_name']} {row['project_name']} → {hours:.0f} ч"
        )
    else:
        await update.message.reply_text(f"Назначено: {uid} → {pid} → {hours:.0f} ч")
    await send_main_menu(update, context)
    return ConversationHandler.END


async def deadline_pick_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "plan:back":
        await q.edit_message_text("Планирование:", reply_markup=_planning_menu_kb())
        return MENU
    if data.startswith("plan:c:"):
        client_id = int(data.split(":")[-1])
        context.user_data["dl_client_id"] = client_id
        db = await get_db(context)
        prows = [dict(r) for r in await db.list_projects_for_client(client_id, status="active")]
        kb = [[InlineKeyboardButton(p["name"], callback_data=f"plan:dp:{p['id']}")] for p in prows]
        kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="plan:back")])
        await q.edit_message_text("Выбери проект:", reply_markup=InlineKeyboardMarkup(kb))
        return D_PROJECT
    return D_CLIENT


async def deadline_pick_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "plan:back":
        await q.edit_message_text("Планирование:", reply_markup=_planning_menu_kb())
        return MENU
    if data.startswith("plan:dp:"):
        pid = int(data.split(":")[-1])
        context.user_data["dl_project_id"] = pid
        await q.edit_message_text("Введи дедлайн в формате ДД.ММ.ГГГГ:")
        return D_DATE
    return D_PROJECT


async def deadline_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    raw = (update.message.text or "").strip()
    try:
        d = dt.datetime.strptime(raw, "%d.%m.%Y").date()
    except Exception:
        await update.message.reply_text("Неверный формат. Пример: 30.04.2026")
        return D_DATE
    db = await get_db(context)
    pid = int(context.user_data["dl_project_id"])
    await db.set_project_deadline(pid, d.isoformat())
    row = await db.fetchone(
        """
        SELECT c.name AS client_name, p.name AS project_name
        FROM projects p JOIN clients c ON c.id = p.client_id
        WHERE p.id = ?;
        """,
        (pid,),
    )
    if row:
        await update.message.reply_text(f"Дедлайн {row['client_name']} {row['project_name']}: {raw}")
    else:
        await update.message.reply_text(f"Дедлайн установлен: {raw}")
    await send_main_menu(update, context)
    return ConversationHandler.END


planning_conversation = ConversationHandler(
    entry_points=[
        CommandHandler("planning", planning_entry),
        CallbackQueryHandler(planning_entry, pattern=r"^menu:planning$"),
    ],
    states={
        MENU: [CallbackQueryHandler(planning_menu, pattern=r"^plan:")],
        P_USER: [CallbackQueryHandler(plan_pick_user, pattern=r"^plan:")],
        P_PROJECT: [CallbackQueryHandler(plan_pick_project, pattern=r"^plan:")],
        P_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, plan_hours)],
        D_CLIENT: [CallbackQueryHandler(deadline_pick_client, pattern=r"^plan:")],
        D_PROJECT: [CallbackQueryHandler(deadline_pick_project, pattern=r"^plan:")],
        D_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, deadline_date)],
    },
    fallbacks=[],
    name="planning",
    persistent=False,
)

