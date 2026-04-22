from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from handlers.common import ensure_user


def _main_menu_kb(role: str) -> InlineKeyboardMarkup:
    if role == "admin":
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📝 Внести время", callback_data="menu:log"),
                    InlineKeyboardButton("📁 Мои проекты", callback_data="menu:myprojects"),
                ],
                [InlineKeyboardButton("🙋 Профиль (/me)", callback_data="menu:me")],
                [InlineKeyboardButton("➕ Добавить клиента / проект", callback_data="menu:addcp")],
                [
                    InlineKeyboardButton("📊 Отчёт", callback_data="menu:report"),
                    InlineKeyboardButton("📤 Выгрузка", callback_data="menu:export"),
                ],
                [
                    InlineKeyboardButton("👥 Админ панель", callback_data="menu:admin"),
                    InlineKeyboardButton("✅ Закрыть проект", callback_data="menu:done"),
                ],
            ]
        )
    if role == "observer":
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🙋 Профиль (/me)", callback_data="menu:me")],
                [InlineKeyboardButton("📊 Отчёт", callback_data="menu:report")],
                [InlineKeyboardButton("📤 Выгрузка", callback_data="menu:export")],
            ]
        )
    # member (default)
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 Внести время", callback_data="menu:log")],
            [InlineKeyboardButton("📁 Мои проекты", callback_data="menu:myprojects")],
            [InlineKeyboardButton("🙋 Профиль (/me)", callback_data="menu:me")],
            [InlineKeyboardButton("➕ Добавить клиента / проект", callback_data="menu:addcp")],
            [InlineKeyboardButton("✅ Закрыть проект", callback_data="menu:done")],
        ]
    )


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await ensure_user(update, context)
    if user is None:
        await update.effective_message.reply_text("Для начала представься в /start.")
        return
    await update.effective_message.reply_text(
        "Главное меню:",
        reply_markup=_main_menu_kb(user.role),
    )


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_main_menu(update, context)


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    assert q is not None
    await q.answer()
    action = (q.data or "").split(":", 1)[-1]

    if action == "myprojects":
        from handlers.projects import myprojects

        await myprojects(update, context)
        return
    if action == "me":
        from handlers.me import me_cmd

        await me_cmd(update, context)
        return

    await q.edit_message_text("Неизвестное действие. Открой /menu ещё раз.")


menu_handler = CommandHandler("menu", menu_cmd)
menu_callback_handler = CallbackQueryHandler(menu_callback, pattern=r"^menu:(myprojects|me)$")

