from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from handlers.common import get_db, require_role
from handlers.menu import send_main_menu
from handlers.positions import position_label


def _bar(actual: float, planned: float, width: int = 12) -> str:
    if planned <= 0:
        filled = min(width, int(actual // 10))
        return "[" + ("█" * filled) + ("·" * (width - filled)) + "]"
    ratio = min(1.0, actual / planned) if planned > 0 else 0.0
    filled = int(ratio * width)
    return "[" + ("█" * filled) + ("·" * (width - filled)) + "]"


@require_role("member")
async def team_workload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = await get_db(context)
    me = context.user_data["me"]
    if me.position != "traffic_manager":
        await update.effective_message.reply_text("Недостаточно прав.")
        await send_main_menu(update, context)
        return

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
    if not rows:
        await update.effective_message.reply_text("Данных нет.")
        await send_main_menu(update, context)
        return

    lines = [f"Загрузка команды за {start.isoformat()} .. {end.isoformat()}:"]
    for r in rows:
        h = float(r["hours"] or 0)
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

    await update.effective_message.reply_text("\n".join(lines))
    await send_main_menu(update, context)


team_workload_handler = CommandHandler("team_workload", team_workload)

