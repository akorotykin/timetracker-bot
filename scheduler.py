from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot

from database import Database
from handlers.log import reminder_keyboard


async def _is_satisfied(db: Database, user_id: int, date_: dt.date) -> bool:
    if await db.has_timelog(user_id, date_):
        return True
    if await db.has_absence(user_id, date_):
        return True
    if await db.has_ack(user_id, date_, kind="already"):
        return True
    # weekend "no" writes ack kind=weekend_rest
    if await db.has_ack(user_id, date_, kind="weekend_rest"):
        return True
    return False


async def _send_day_reminder(bot: Bot, db: Database, tz: ZoneInfo, tg_id: int, user_id: int, date_: dt.date) -> None:
    projects = [dict(r) for r in await db.list_active_projects_for_user(user_id)]
    text = f"Привет! Что делал за {date_.isoformat()}? Внеси время за {date_.isoformat()}."
    if projects:
        await bot.send_message(chat_id=tg_id, text=text, reply_markup=reminder_keyboard(projects, date_))
    else:
        await bot.send_message(
            chat_id=tg_id,
            text=text + "\nУ тебя пока нет проектов. Нажми «Добавить проект».",
            reply_markup=reminder_keyboard([], date_),
        )


async def _send_weekend_question(bot: Bot, tg_id: int, monday: dt.date) -> None:
    sat = monday - dt.timedelta(days=2)
    sun = monday - dt.timedelta(days=1)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Да, работал", callback_data=f"remW:{monday.isoformat()}:ans:yes"),
                InlineKeyboardButton("Нет, отдыхал", callback_data=f"remW:{monday.isoformat()}:ans:no"),
            ]
        ]
    )
    await bot.send_message(
        chat_id=tg_id,
        text=f"Работал в выходные (сб {sat.isoformat()} / вс {sun.isoformat()})?",
        reply_markup=kb,
    )


async def send_daily_kickoff(bot: Bot, db: Database, tz: ZoneInfo) -> None:
    # Active users for reminders: member + admin (exclude observer).
    users = await db.fetchall(
        "SELECT id, tg_id, name, role FROM users WHERE role IN ('member','admin') ORDER BY name;"
    )
    now = dt.datetime.now(tz=tz)
    today = now.date()

    # No reminders on weekends.
    if today.weekday() in {5, 6}:
        return

    # sleeping status removed; keep last_activity_at only

    # Monday: ask Friday first, then weekend question later.
    if today.weekday() == 0:
        friday = today - dt.timedelta(days=3)
        for u in users:
            user_id = int(u["id"])
            tg_id = int(u["tg_id"])
            if await _is_satisfied(db, user_id, friday):
                continue
            await bot.send_message(
                chat_id=tg_id,
                text=f"Что делал в пятницу {friday.isoformat()}?",
                reply_markup=reminder_keyboard([dict(r) for r in await db.list_active_projects_for_user(user_id)], friday),
            )
        return

    # Tue-Fri: ask yesterday.
    yesterday_ = today - dt.timedelta(days=1)
    for u in users:
        user_id = int(u["id"])
        tg_id = int(u["tg_id"])
        if await _is_satisfied(db, user_id, yesterday_):
            continue
        await _send_day_reminder(bot, db, tz, tg_id=tg_id, user_id=user_id, date_=yesterday_)


async def send_daily_repeats(bot: Bot, db: Database, tz: ZoneInfo) -> None:
    users = await db.fetchall(
        "SELECT id, tg_id, name, role FROM users WHERE role IN ('member','admin') ORDER BY name;"
    )
    now = dt.datetime.now(tz=tz)
    today = now.date()

    if today.weekday() in {5, 6}:
        return

    # Only repeat until 18:00 inclusive.
    if now.time() > dt.time(18, 0):
        return

    # sleeping status removed; keep last_activity_at only

    if today.weekday() == 0:
        monday = today
        friday = today - dt.timedelta(days=3)
        sat = today - dt.timedelta(days=2)
        sun = today - dt.timedelta(days=1)
        for u in users:
            user_id = int(u["id"])
            tg_id = int(u["tg_id"])

            # Step 1: Friday reminder until satisfied.
            if not await _is_satisfied(db, user_id, friday):
                await bot.send_message(
                    chat_id=tg_id,
                    text=f"Что делал в пятницу {friday.isoformat()}?",
                    reply_markup=reminder_keyboard([dict(r) for r in await db.list_active_projects_for_user(user_id)], friday),
                )
                continue

            # Step 2: weekend question until answered (yes/no).
            weekend_answer = await db.get_flag(user_id, monday, "weekend_answer")
            if weekend_answer is None:
                await _send_weekend_question(bot, tg_id=tg_id, monday=monday)
                continue

            # Step 3: if answered yes, repeat for chosen day(s) until satisfied.
            if weekend_answer == "yes":
                choice = await db.get_flag(user_id, monday, "weekend_days")
                if choice is None:
                    await _send_weekend_question(bot, tg_id=tg_id, monday=monday)
                    continue
                if choice in {"sat", "both"} and not await _is_satisfied(db, user_id, sat):
                    await _send_day_reminder(bot, db, tz, tg_id=tg_id, user_id=user_id, date_=sat)
                if choice in {"sun", "both"} and not await _is_satisfied(db, user_id, sun):
                    await _send_day_reminder(bot, db, tz, tg_id=tg_id, user_id=user_id, date_=sun)
        return

    # Tue-Fri repeats: yesterday.
    target = today - dt.timedelta(days=1)
    for u in users:
        user_id = int(u["id"])
        tg_id = int(u["tg_id"])
        if await _is_satisfied(db, user_id, target):
            continue
        await _send_day_reminder(bot, db, tz, tg_id=tg_id, user_id=user_id, date_=target)


def build_scheduler(bot: Bot, db: Database, tz: ZoneInfo) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=tz)
    kickoff = CronTrigger(day_of_week="mon-fri", hour=10, minute=30)
    repeats = CronTrigger(day_of_week="mon-fri", hour="11-18", minute=30)
    scheduler.add_job(
        send_daily_kickoff,
        trigger=kickoff,
        args=[bot, db, tz],
        id="daily_reminders_kickoff",
        replace_existing=True,
    )
    scheduler.add_job(
        send_daily_repeats,
        trigger=repeats,
        args=[bot, db, tz],
        id="daily_reminders_repeats",
        replace_existing=True,
    )

    # Traffic Manager notifications (daily).
    notify = CronTrigger(hour=10, minute=15)
    scheduler.add_job(
        send_planning_notifications,
        trigger=notify,
        args=[bot, db, tz],
        id="planning_notifications",
        replace_existing=True,
    )
    return scheduler


async def send_planning_notifications(bot: Bot, db: Database, tz: ZoneInfo) -> None:
    today = dt.datetime.now(tz=tz).date()
    tms = [dict(r) for r in await db.list_traffic_managers()]
    if not tms:
        return

    # 1) Exceed plan.
    rows = await db.fetchall(
        """
        SELECT pp.user_id, pp.project_id, pp.planned_hours,
               COALESCE(SUM(t.hours),0) AS actual_hours,
               u.name AS user_name,
               c.name AS client_name,
               p.name AS project_name,
               p.status AS project_status
        FROM project_plans pp
        JOIN users u ON u.id = pp.user_id
        JOIN projects p ON p.id = pp.project_id
        JOIN clients c ON c.id = p.client_id
        LEFT JOIN timelog t ON t.user_id = pp.user_id AND t.project_id = pp.project_id
        WHERE p.status = 'active'
        GROUP BY pp.user_id, pp.project_id;
        """
    )
    for r in rows:
        planned = float(r["planned_hours"] or 0)
        actual = float(r["actual_hours"] or 0)
        if planned > 0 and actual > planned:
            key = f"exceed:{int(r['user_id'])}:{int(r['project_id'])}:{today.isoformat()}"
            if await db.get_notify_last_sent(key):
                continue
            msg = (
                f"Превышение плана: {r['user_name']} → {r['client_name']} {r['project_name']}\n"
                f"Факт {actual:.1f} ч > План {planned:.1f} ч"
            )
            for tm in tms:
                await bot.send_message(chat_id=int(tm["tg_id"]), text=msg)
            await db.set_notify_last_sent(key, today.isoformat())

    # 2) Deadlines: 3 days left and overdue (active only).
    drows = await db.fetchall(
        """
        SELECT p.id AS project_id, p.name AS project_name, p.deadline_at, p.status,
               c.name AS client_name
        FROM projects p
        JOIN clients c ON c.id = p.client_id
        WHERE p.status = 'active' AND p.deadline_at IS NOT NULL;
        """
    )
    for r in drows:
        try:
            d = dt.date.fromisoformat(str(r["deadline_at"])[:10])
        except Exception:
            continue
        days = (d - today).days
        if days == 3:
            key = f"deadline3:{int(r['project_id'])}:{today.isoformat()}"
            if await db.get_notify_last_sent(key):
                continue
            msg = f"До дедлайна 3 дня: {r['client_name']} {r['project_name']} — {d.isoformat()}"
            for tm in tms:
                await bot.send_message(chat_id=int(tm["tg_id"]), text=msg)
            await db.set_notify_last_sent(key, today.isoformat())
        if days < 0:
            key = f"overdue:{int(r['project_id'])}:{today.isoformat()}"
            if await db.get_notify_last_sent(key):
                continue
            msg = f"Проект просрочен: {r['client_name']} {r['project_name']} — дедлайн был {d.isoformat()}"
            for tm in tms:
                await bot.send_message(chat_id=int(tm["tg_id"]), text=msg)
            await db.set_notify_last_sent(key, today.isoformat())

