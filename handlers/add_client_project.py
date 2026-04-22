from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
try:
    from thefuzz import fuzz  # type: ignore
except Exception:  # pragma: no cover
    fuzz = None  # type: ignore[assignment]

from handlers.common import ensure_user, get_db, normalize_name, transliterate
from handlers.menu import send_main_menu


ASK_CLIENT, PICK_CLIENT, ASK_PROJECT, PICK_PROJECT = range(1, 5)


@dataclass(frozen=True)
class _Choice:
    id: int
    label: str
    score: int


def _best_similarity(a: str, b: str) -> int:
    a0 = normalize_name(a)
    b0 = normalize_name(b)
    if not a0 or not b0:
        return 0

    # Exact match
    if a0 == b0:
        return 100

    # Partial containment (both directions)
    if a0 in b0 or b0 in a0:
        return 90

    a_tr = normalize_name(transliterate(a0))
    b_tr = normalize_name(transliterate(b0))
    if fuzz is None:
        return 0
    candidates = [
        int(fuzz.token_set_ratio(a0, b0)),
        int(fuzz.token_set_ratio(a0, b_tr)),
        int(fuzz.token_set_ratio(a_tr, b0)),
        int(fuzz.token_set_ratio(a_tr, b_tr)),
    ]
    return int(max(candidates or [0]))


def _similar_choices(rows: list[dict], input_name: str, field: str, limit: int = 8) -> list[_Choice]:
    want = normalize_name(input_name)
    out: list[_Choice] = []
    for r in rows:
        label = str(r[field])
        score = _best_similarity(want, label)
        if score >= 70:
            out.append(_Choice(id=int(r["id"]), label=label, score=score))
    out.sort(key=lambda c: (-c.score, c.label.lower()))
    return out[:limit]


def _client_pick_kb(matches: list[_Choice], raw_name: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for m in matches:
        rows.append([InlineKeyboardButton(m.label, callback_data=f"acp:client:{m.id}")])
    rows.append([InlineKeyboardButton(f"Создать нового: {raw_name}", callback_data="acp:client:new")])
    rows.append([InlineKeyboardButton("Отмена", callback_data="acp:cancel")])
    return InlineKeyboardMarkup(rows)


def _project_pick_kb(matches: list[_Choice], raw_name: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for m in matches:
        rows.append([InlineKeyboardButton(m.label, callback_data=f"acp:proj:{m.id}")])
    rows.append([InlineKeyboardButton(f"Создать новый: {raw_name}", callback_data="acp:proj:new")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="acp:back:client")])
    rows.append([InlineKeyboardButton("Отмена", callback_data="acp:cancel")])
    return InlineKeyboardMarkup(rows)


async def _ensure_member_or_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = await ensure_user(update, context)
    if user is None:
        await update.effective_message.reply_text("Для начала представься в /start.")
        return False
    if user.role not in {"member", "admin"}:
        await update.effective_message.reply_text("Недостаточно прав.")
        return False
    context.user_data["me"] = user
    return True


async def entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ok = await _ensure_member_or_admin(update, context)
    if not ok:
        return ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Введи название клиента:")
    else:
        await update.effective_message.reply_text("Введи название клиента:")
    return ASK_CLIENT


async def client_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ok = await _ensure_member_or_admin(update, context)
    if not ok:
        return ConversationHandler.END
    assert update.message is not None
    raw = (update.message.text or "").strip()
    if len(raw) < 2:
        await update.message.reply_text("Слишком коротко. Введи название клиента ещё раз.")
        return ASK_CLIENT
    context.user_data["acp_client_name"] = raw

    db = await get_db(context)
    clients = [dict(r) for r in await db.list_clients()]

    # Fast exact match (case-insensitive) first.
    want = normalize_name(raw)
    for c in clients:
        if normalize_name(str(c["name"])) == want:
            context.user_data["acp_client_id"] = int(c["id"])
            await update.message.reply_text(f"Ок, клиент: {c['name']}\nВведи название проекта:")
            return ASK_PROJECT

    matches = _similar_choices(clients, raw, field="name")
    if matches:
        await update.message.reply_text(
            "Возможно, такой клиент уже есть. Выбери из списка или создай нового:",
            reply_markup=_client_pick_kb(matches, raw),
        )
        return PICK_CLIENT

    # No matches → create immediately.
    client_id = await db.create_client(raw)
    context.user_data["acp_client_id"] = int(client_id)
    await update.message.reply_text(f"Клиент создан: {raw}\nВведи название проекта:")
    return ASK_PROJECT


async def client_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ok = await _ensure_member_or_admin(update, context)
    if not ok:
        return ConversationHandler.END
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    if data == "acp:cancel":
        await q.edit_message_text("Ок.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    if data == "acp:client:new":
        db = await get_db(context)
        raw = str(context.user_data["acp_client_name"])
        client_id = await db.create_client(raw)
        context.user_data["acp_client_id"] = int(client_id)
        await q.edit_message_text(f"Клиент создан: {raw}\nВведи название проекта:")
        return ASK_PROJECT
    if data.startswith("acp:client:"):
        client_id = int(data.split(":")[-1])
        context.user_data["acp_client_id"] = client_id
        await q.edit_message_text("Введи название проекта:")
        return ASK_PROJECT
    await q.edit_message_text("Не понял выбор.")
    await send_main_menu(update, context)
    return ConversationHandler.END


async def project_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ok = await _ensure_member_or_admin(update, context)
    if not ok:
        return ConversationHandler.END
    assert update.message is not None
    raw = (update.message.text or "").strip()
    if len(raw) < 2:
        await update.message.reply_text("Слишком коротко. Введи название проекта ещё раз.")
        return ASK_PROJECT
    context.user_data["acp_project_name"] = raw
    db = await get_db(context)
    client_id = int(context.user_data["acp_client_id"])

    projects = [dict(r) for r in await db.list_projects_for_client_active(client_id)]
    want = normalize_name(raw)
    for p in projects:
        if normalize_name(str(p["name"])) == want:
            me = context.user_data["me"]
            await db.attach_user_to_project(me.id, int(p["id"]))
            await update.message.reply_text(f"Ок, привязал к проекту: {p['name']}")
            await send_main_menu(update, context)
            return ConversationHandler.END

    matches = _similar_choices(projects, raw, field="name")
    if matches:
        await update.message.reply_text(
            "Возможно, такой проект уже есть. Выбери из списка или создай новый:",
            reply_markup=_project_pick_kb(matches, raw),
        )
        return PICK_PROJECT

    # No matches → create + attach.
    project_id = await db.create_project(client_id=client_id, name=raw)
    me = context.user_data["me"]
    await db.attach_user_to_project(me.id, int(project_id))
    await update.message.reply_text(f"Проект создан и добавлен тебе: {raw}")
    await send_main_menu(update, context)
    return ConversationHandler.END


async def project_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ok = await _ensure_member_or_admin(update, context)
    if not ok:
        return ConversationHandler.END
    q = update.callback_query
    assert q is not None
    await q.answer()
    data = q.data or ""
    db = await get_db(context)
    if data == "acp:cancel":
        await q.edit_message_text("Ок.")
        await send_main_menu(update, context)
        return ConversationHandler.END
    if data == "acp:back:client":
        await q.edit_message_text("Введи название клиента:")
        return ASK_CLIENT
    if data == "acp:proj:new":
        client_id = int(context.user_data["acp_client_id"])
        raw = str(context.user_data["acp_project_name"])
        project_id = await db.create_project(client_id=client_id, name=raw)
        me = context.user_data["me"]
        await db.attach_user_to_project(me.id, int(project_id))
        await q.edit_message_text(f"Проект создан и добавлен тебе: {raw}")
        await send_main_menu(update, context)
        return ConversationHandler.END
    if data.startswith("acp:proj:"):
        project_id = int(data.split(":")[-1])
        me = context.user_data["me"]
        await db.attach_user_to_project(me.id, project_id)
        await q.edit_message_text("Готово, проект добавлен тебе.")
        await send_main_menu(update, context)
        return ConversationHandler.END

    await q.edit_message_text("Не понял выбор.")
    await send_main_menu(update, context)
    return ConversationHandler.END


add_client_project_conversation = ConversationHandler(
    entry_points=[
        CommandHandler("addproject", entry),
        CallbackQueryHandler(entry, pattern=r"^menu:addcp$"),
    ],
    states={
        ASK_CLIENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, client_name)],
        PICK_CLIENT: [CallbackQueryHandler(client_pick, pattern=r"^acp:")],
        ASK_PROJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, project_name)],
        PICK_PROJECT: [CallbackQueryHandler(project_pick, pattern=r"^acp:")],
    },
    fallbacks=[],
    name="add_client_project",
    persistent=False,
)

