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

    await db.mark_sleeping_projects(today=today)

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

    await db.mark_sleeping_projects(today=today)

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
    return scheduler

