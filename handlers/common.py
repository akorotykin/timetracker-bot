from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable, Coroutine, Optional, TypeVar

from telegram import Update
from telegram.ext import ContextTypes

from database import Database, User


T = TypeVar("T")


def yesterday(tz: dt.tzinfo | None = None) -> dt.date:
    now = dt.datetime.now(tz=tz)
    return (now.date() - dt.timedelta(days=1))


def month_start(date_: dt.date) -> dt.date:
    return dt.date(date_.year, date_.month, 1)


async def get_db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    db: Database = context.bot_data["db"]
    return db


async def get_me(update: Update) -> int:
    assert update.effective_user is not None
    return int(update.effective_user.id)


async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> User | None:
    db = await get_db(context)
    tg_id = await get_me(update)
    return await db.get_user_by_tg(tg_id)


def role_allows(role: str, required: str) -> bool:
    if required == "member":
        return role in {"member", "observer", "admin"}
    if required == "observer":
        return role in {"observer", "admin"}
    if required == "admin":
        return role == "admin"
    return False


def require_role(required: str):
    def deco(
        fn: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[None, None, T]]
    ) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[None, None, Optional[T]]]:
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[T]:
            user = await ensure_user(update, context)
            if user is None:
                await update.effective_message.reply_text("Для начала представься в /start.")
                return None
            if not role_allows(user.role, required):
                await update.effective_message.reply_text("Недостаточно прав.")
                return None
            context.user_data["me"] = user
            return await fn(update, context)

        return wrapped

    return deco


@dataclass(frozen=True)
class Period:
    start: dt.date
    end: dt.date


def current_week(today: dt.date) -> Period:
    # Monday..Sunday
    start = today - dt.timedelta(days=today.weekday())
    end = start + dt.timedelta(days=6)
    return Period(start=start, end=end)


def current_month(today: dt.date) -> Period:
    start = dt.date(today.year, today.month, 1)
    if today.month == 12:
        next_month = dt.date(today.year + 1, 1, 1)
    else:
        next_month = dt.date(today.year, today.month + 1, 1)
    end = next_month - dt.timedelta(days=1)
    return Period(start=start, end=end)


def parse_date(s: str) -> dt.date | None:
    s = s.strip()
    try:
        return dt.date.fromisoformat(s)
    except Exception:
        return None


_RU_LAT_MAP: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def transliterate(text: str) -> str:
    out: list[str] = []
    for ch in text:
        low = ch.lower()
        if low in _RU_LAT_MAP:
            tr = _RU_LAT_MAP[low]
            out.append(tr if ch.islower() else tr.capitalize())
        else:
            out.append(ch)
    return "".join(out)


def normalize_name(s: str) -> str:
    s = (s or "").strip().lower()
    return " ".join(s.split())


