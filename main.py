from __future__ import annotations

import asyncio
import logging
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ContextTypes

from database import Database
from handlers import (
    admin_conversation,
    done_conversation,
    export_conversation,
    log_conversation,
    myprojects_handler,
    report_conversation,
    start_handler,
    workload_handler,
)
from scheduler import build_scheduler


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("timetracker-bot")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error: %s", context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Упс, произошла ошибка. Попробуй ещё раз.")


async def main() -> None:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is missing. Copy .env.example to .env and set BOT_TOKEN.")

    tz_name = os.getenv("TZ", "Europe/Moscow")
    tz = ZoneInfo(tz_name)

    db_path = os.getenv("DB_PATH", "./timetracker.sqlite3")
    db = Database(db_path)
    await db.init()

    admin_tg_id = os.getenv("ADMIN_TG_ID")
    if admin_tg_id and admin_tg_id.isdigit():
        await db.maybe_seed_first_admin(int(admin_tg_id))

    app = Application.builder().token(token).build()
    app.bot_data["db"] = db
    app.bot_data["tz"] = tz

    app.add_handler(start_handler)
    app.add_handler(log_conversation)
    app.add_handler(myprojects_handler)
    app.add_handler(done_conversation)
    app.add_handler(report_conversation)
    app.add_handler(workload_handler)
    app.add_handler(export_conversation)
    app.add_handler(admin_conversation)
    app.add_error_handler(on_error)

    scheduler = build_scheduler(app.bot, db, tz)
    scheduler.start()

    logger.info("Bot started. TZ=%s DB=%s", tz_name, db_path)
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        # Run forever until SIGINT/SIGTERM
        await asyncio.Event().wait()
    finally:
        logger.info("Shutting down...")
        scheduler.shutdown(wait=False)
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

