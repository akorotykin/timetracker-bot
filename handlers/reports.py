from __future__ import annotations

import datetime as dt
from io import BytesIO

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from openpyxl import Workbook

from handlers.common import current_month, current_week, get_db, parse_date, require_role
from handlers.menu import send_main_menu


R_PERIOD, R_CUSTOM, R_DIM = 1, 2, 3


def _period_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Эта неделя", callback_data=f"{prefix}:week")],
            [InlineKeyboardButton("Этот месяц", callback_data=f"{prefix}:month")],
            [InlineKeyboardButton("Произвольный", callback_data=f"{prefix}:custom")],
            [InlineKeyboardButton("Отмена", callback_data=f"{prefix}:cancel")],
        ]
    )


def _dim_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("По проектам", callback_data=f"{prefix}:project")],
            [InlineKeyboardButton("По сотрудникам", callback_data=f"{prefix}:user")],
            [InlineKeyboardButton("По клиентам", callback_data=f"{prefix}:client")],
            [InlineKeyboardButton("Отмена", callback_data=f"{prefix}:cancel")],
        ]
    )


def _money_allowed(role: str) -> bool:
    return role in {"admin", "observer"}


@require_role("observer")
async def report_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("Выбери период:", reply_markup=_period_kb("repP"))
    return R_PERIOD


async def report_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "repP:cancel":
        await q.edit_message_text("Ок.")
        await send_main_menu(update, context)
        return ConversationHandler.END

    today = dt.date.today()
    if data == "repP:week":
        p = current_week(today)
        context.user_data["rep_period"] = (p.start, p.end)
        await q.edit_message_text(f"Период: {p.start.isoformat()} .. {p.end.isoformat()}\nВыбери разрез:", reply_markup=_dim_kb("repD"))
        return R_DIM
    if data == "repP:month":
        p = current_month(today)
        context.user_data["rep_period"] = (p.start, p.end)
        await q.edit_message_text(f"Период: {p.start.isoformat()} .. {p.end.isoformat()}\nВыбери разрез:", reply_markup=_dim_kb("repD"))
        return R_DIM
    if data == "repP:custom":
        await q.edit_message_text("Введи период в формате: YYYY-MM-DD YYYY-MM-DD")
        return R_CUSTOM
    return R_PERIOD


async def report_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    parts = (update.message.text or "").strip().split()
    if len(parts) != 2:
        await update.message.reply_text("Нужно 2 даты: YYYY-MM-DD YYYY-MM-DD")
        return R_CUSTOM
    start = parse_date(parts[0])
    end = parse_date(parts[1])
    if not start or not end or start > end:
        await update.message.reply_text("Некорректный период. Пример: 2026-04-01 2026-04-30")
        return R_CUSTOM
    context.user_data["rep_period"] = (start, end)
    await update.message.reply_text(f"Период: {start.isoformat()} .. {end.isoformat()}\nВыбери разрез:", reply_markup=_dim_kb("repD"))
    return R_DIM


async def report_dim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "repD:cancel":
        await q.edit_message_text("Ок.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    group_by = data.split(":")[-1]
    start, end = context.user_data["rep_period"]
    db = await get_db(context)
    me = context.user_data["me"]
    rows = await db.report_grouped(start=start, end=end, group_by=group_by, restrict_user_id=None)
    show_money = _money_allowed(me.role)
    lines = [f"Отчёт {start.isoformat()} .. {end.isoformat()} ({group_by})"]
    if not rows:
        lines.append("Данных нет.")
        await q.edit_message_text("\n".join(lines))
        await send_main_menu(update, context)
        return ConversationHandler.END

    for r in rows:
        h = float(r["hours"] or 0)
        if show_money:
            ic = float(r["internal_cost"] or 0)
            ec = float(r["external_cost"] or 0)
            lines.append(f"- {r['label']}: {h:.2f} ч | себест. {ic:.2f} | клиент. {ec:.2f}")
        else:
            lines.append(f"- {r['label']}: {h:.2f} ч")
    await q.edit_message_text("\n".join(lines))
    await send_main_menu(update, context)
    return ConversationHandler.END


report_conversation = ConversationHandler(
    entry_points=[CommandHandler("report", report_entry), CallbackQueryHandler(report_entry, pattern=r"^menu:report$")],
    states={
        R_PERIOD: [CallbackQueryHandler(report_period, pattern=r"^repP:")],
        R_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_custom)],
        R_DIM: [CallbackQueryHandler(report_dim, pattern=r"^repD:")],
    },
    fallbacks=[],
    name="report",
    persistent=False,
)


@require_role("observer")
async def workload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = dt.date.today()
    p = current_month(today)
    start, end = p.start, p.end
    db = await get_db(context)
    rows = await db.fetchall(
        """
        SELECT u.name AS user_name,
               SUM(t.hours) AS hours
        FROM timelog t
        JOIN users u ON u.id = t.user_id
        WHERE t.date BETWEEN ? AND ?
        GROUP BY u.id
        ORDER BY u.name;
        """,
        (start.isoformat(), end.isoformat()),
    )
    if not rows:
        await update.effective_message.reply_text("Данных нет.")
        return

    lines = [f"Загрузка за {start.isoformat()} .. {end.isoformat()}:"]
    for r in rows:
        user_name = r["user_name"]
        hours = float(r["hours"] or 0)
        lines.append(f"- {user_name}: {hours:.2f} ч")
        prows = await db.fetchall(
            """
            SELECT c.name AS client_name, p.name AS project_name, SUM(t.hours) AS hours
            FROM timelog t
            JOIN projects p ON p.id = t.project_id
            JOIN clients c ON c.id = p.client_id
            JOIN users u ON u.id = t.user_id
            WHERE u.name = ? AND t.date BETWEEN ? AND ?
            GROUP BY p.id
            ORDER BY c.name, p.name;
            """,
            (user_name, start.isoformat(), end.isoformat()),
        )
        for pr in prows:
            lines.append(f"  - {pr['client_name']} / {pr['project_name']}: {float(pr['hours'] or 0):.2f} ч")
    await update.effective_message.reply_text("\n".join(lines))


workload_handler = CommandHandler("workload", workload)


# ---------- admin export ----------


E_PERIOD, E_CUSTOM = 1, 2


@require_role("admin")
async def export_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("Выбери период для Excel:", reply_markup=_period_kb("expP"))
    return E_PERIOD


async def export_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "expP:cancel":
        await q.edit_message_text("Ок.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    today = dt.date.today()
    if data == "expP:week":
        p = current_week(today)
        context.user_data["exp_period"] = (p.start, p.end)
        await q.edit_message_text(f"Готовлю Excel за {p.start.isoformat()} .. {p.end.isoformat()}…")
        return await export_build_and_send(update, context)
    if data == "expP:month":
        p = current_month(today)
        context.user_data["exp_period"] = (p.start, p.end)
        await q.edit_message_text(f"Готовлю Excel за {p.start.isoformat()} .. {p.end.isoformat()}…")
        return await export_build_and_send(update, context)
    if data == "expP:custom":
        await q.edit_message_text("Введи период в формате: YYYY-MM-DD YYYY-MM-DD")
        return E_CUSTOM
    return E_PERIOD


async def export_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    assert update.message is not None
    parts = (update.message.text or "").strip().split()
    if len(parts) != 2:
        await update.message.reply_text("Нужно 2 даты: YYYY-MM-DD YYYY-MM-DD")
        return E_CUSTOM
    start = parse_date(parts[0])
    end = parse_date(parts[1])
    if not start or not end or start > end:
        await update.message.reply_text("Некорректный период.")
        return E_CUSTOM
    context.user_data["exp_period"] = (start, end)
    await update.message.reply_text("Готовлю Excel…")
    return await export_build_and_send(update, context)


async def export_build_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    start, end = context.user_data["exp_period"]
    db = await get_db(context)

    # Sheet 1: by projects
    by_projects = await db.fetchall(
        """
        SELECT c.name AS client_name,
               p.name AS project_name,
               GROUP_CONCAT(DISTINCT u.name) AS employees,
               SUM(t.hours) AS hours,
               SUM(t.hours * u.internal_rate) AS internal_cost,
               SUM(t.hours * u.external_rate) AS external_cost
        FROM timelog t
        JOIN users u ON u.id = t.user_id
        JOIN projects p ON p.id = t.project_id
        JOIN clients c ON c.id = p.client_id
        WHERE t.date BETWEEN ? AND ?
        GROUP BY p.id
        ORDER BY c.name, p.name;
        """,
        (start.isoformat(), end.isoformat()),
    )

    # Sheet 2: by employees
    by_users = await db.fetchall(
        """
        SELECT u.name AS user_name,
               GROUP_CONCAT(DISTINCT (c.name || ' / ' || p.name)) AS projects,
               SUM(t.hours) AS hours,
               SUM(t.hours * u.internal_rate) AS internal_cost,
               SUM(t.hours * u.external_rate) AS external_cost
        FROM timelog t
        JOIN users u ON u.id = t.user_id
        JOIN projects p ON p.id = t.project_id
        JOIN clients c ON c.id = p.client_id
        WHERE t.date BETWEEN ? AND ?
        GROUP BY u.id
        ORDER BY u.name;
        """,
        (start.isoformat(), end.isoformat()),
    )

    wb = Workbook()
    ws1 = wb.active
    ws1.title = "По проектам"
    ws1.append(["Проект", "Клиент", "Сотрудники", "Часы", "Себестоимость", "Клиентская стоимость"])
    for r in by_projects:
        ws1.append(
            [
                r["project_name"],
                r["client_name"],
                r["employees"] or "",
                float(r["hours"] or 0),
                float(r["internal_cost"] or 0),
                float(r["external_cost"] or 0),
            ]
        )

    ws2 = wb.create_sheet("По сотрудникам")
    ws2.append(["Сотрудник", "Проекты", "Часы", "Себестоимость", "Клиентская стоимость"])
    for r in by_users:
        ws2.append(
            [
                r["user_name"],
                r["projects"] or "",
                float(r["hours"] or 0),
                float(r["internal_cost"] or 0),
                float(r["external_cost"] or 0),
            ]
        )

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    filename = f"timetracker_{start.isoformat()}_{end.isoformat()}.xlsx"
    await update.effective_message.reply_document(document=bio, filename=filename)
    await send_main_menu(update, context)
    return ConversationHandler.END


export_conversation = ConversationHandler(
    entry_points=[CommandHandler("export", export_entry), CallbackQueryHandler(export_entry, pattern=r"^menu:export$")],
    states={
        E_PERIOD: [CallbackQueryHandler(export_period, pattern=r"^expP:")],
        E_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, export_custom)],
    },
    fallbacks=[],
    name="export",
    persistent=False,
)

