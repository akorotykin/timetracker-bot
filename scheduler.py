from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot

from database import Database
from handlers.log import reminder_keyboard


async def send_daily_reminders(bot: Bot, db: Database, tz: ZoneInfo) -> None:
    # Reminder: only active members (role=member). Observers/admins are excluded.
    members = await db.fetchall(
        "SELECT id, tg_id, name FROM users WHERE role = 'member' ORDER BY name;"
    )
    today = dt.datetime.now(tz=tz).date()
    await db.mark_sleeping_projects(today=today)

    for m in members:
        user_id = int(m["id"])
        tg_id = int(m["tg_id"])
        projects = [dict(r) for r in await db.list_active_projects_for_user(user_id)]
        text = "Привет! Внеси время за вчера 👇"
        if projects:
            await bot.send_message(chat_id=tg_id, text=text, reply_markup=reminder_keyboard(projects))
        else:
            await bot.send_message(chat_id=tg_id, text=text + "\nУ тебя пока нет проектов. Нажми «Добавить проект».", reply_markup=reminder_keyboard([]))


def build_scheduler(bot: Bot, db: Database, tz: ZoneInfo) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=tz)
    trigger = CronTrigger(hour=10, minute=0)
    scheduler.add_job(send_daily_reminders, trigger=trigger, args=[bot, db, tz], id="daily_reminders", replace_existing=True)
    return scheduler

