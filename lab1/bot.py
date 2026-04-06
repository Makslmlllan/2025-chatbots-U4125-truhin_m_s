import json
import logging
import os
from datetime import datetime, time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -----------------------------
# Load environment variables
# -----------------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

# -----------------------------
# File paths
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data.json"

# -----------------------------
# Conversation states
# -----------------------------
ADD_SUBJECT, ADD_DESCRIPTION, ADD_DATE, ADD_TIME = range(4)
DELETE_ID = 10


# -----------------------------
# Data helpers
# -----------------------------
def load_data() -> list[dict[str, Any]]:
    """Load all deadlines from JSON file."""
    if not DATA_FILE.exists():
        return []

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        logger.warning("data.json is corrupted. Returning empty list.")
        return []
    except Exception as error:
        logger.exception("Unexpected error while loading data: %s", error)
        return []


def save_data(data: list[dict[str, Any]]) -> None:
    """Save all deadlines to JSON file."""
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def get_user_entries(user_id: int) -> list[dict[str, Any]]:
    """Return entries only for a specific user."""
    data = load_data()
    return [entry for entry in data if entry["user_id"] == user_id]


def get_next_entry_id(user_id: int) -> int:
    """Generate next local ID for user's entries."""
    entries = get_user_entries(user_id)
    if not entries:
        return 1
    return max(entry["id"] for entry in entries) + 1


def parse_deadline(entry: dict[str, Any]) -> datetime:
    """
    Convert entry date/time to datetime for sorting and expiration logic.
    If time is missing, use 23:59 for the same date.
    """
    entry_date = datetime.strptime(entry["deadline_date"], "%d.%m.%Y").date()

    if entry.get("deadline_time"):
        entry_time = datetime.strptime(entry["deadline_time"], "%H:%M").time()
    else:
        entry_time = time(23, 59)

    return datetime.combine(entry_date, entry_time)


def cleanup_expired_entries() -> None:
    """
    Remove expired entries from storage.
    This simulates auto-deletion without background jobs.
    """
    data = load_data()
    now = datetime.now()

    active_entries = []
    for entry in data:
        try:
            deadline_dt = parse_deadline(entry)
            if deadline_dt >= now:
                active_entries.append(entry)
        except Exception:
            # If one broken entry exists, skip it rather than crashing the bot
            logger.warning("Skipping broken entry during cleanup: %s", entry)

    if len(active_entries) != len(data):
        save_data(active_entries)


def format_entry(entry: dict[str, Any]) -> str:
    """Format one deadline entry for Telegram message."""
    deadline = entry["deadline_date"]
    if entry.get("deadline_time"):
        deadline += f" {entry['deadline_time']}"

    return (
        f"ID: {entry['id']}\n"
        f"📘 Предмет/событие: {entry['subject']}\n"
        f"📝 Описание: {entry['description']}\n"
        f"📅 Дедлайн: {deadline}"
    )


# -----------------------------
# Command handlers
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message."""
    text = (
        "Привет! Я <b>SmartDiary</b> — бот для учета учебных дедлайнов и событий.\n\n"
        "Доступные команды:\n"
        "/start — запуск бота\n"
        "/add_deadline — добавить дедлайн\n"
        "/list — показать все активные записи\n"
        "/nearest — показать ближайшие дедлайны\n"
        "/delete — удалить запись по ID\n"
        "/cancel — отменить текущую операцию"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def list_entries(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all active entries for the user."""
    cleanup_expired_entries()

    user_id = update.effective_user.id
    entries = get_user_entries(user_id)

    if not entries:
        await update.message.reply_text("У тебя пока нет активных дедлайнов.")
        return

    entries.sort(key=parse_deadline)

    response = "📚 Твои активные дедлайны:\n\n"
    response += "\n\n".join(format_entry(entry) for entry in entries)

    await update.message.reply_text(response)


async def nearest_entries(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show nearest upcoming deadlines."""
    cleanup_expired_entries()

    user_id = update.effective_user.id
    entries = get_user_entries(user_id)

    if not entries:
        await update.message.reply_text("У тебя пока нет активных дедлайнов.")
        return

    entries.sort(key=parse_deadline)
    nearest = entries[:5]

    response = "🔥 Ближайшие дедлайны:\n\n"
    response += "\n\n".join(format_entry(entry) for entry in nearest)

    await update.message.reply_text(response)


# -----------------------------
# Add deadline conversation
# -----------------------------
async def add_deadline_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Start add deadline conversation."""
    await update.message.reply_text("Введите предмет или событие:")
    return ADD_SUBJECT


async def add_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save subject and ask for description."""
    subject = update.message.text.strip()

    if not subject:
        await update.message.reply_text("❌ Поле не может быть пустым. Введите предмет или событие:")
        return ADD_SUBJECT

    context.user_data["subject"] = subject
    await update.message.reply_text("Введите описание:")
    return ADD_DESCRIPTION


async def add_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save description and ask for date."""
    description = update.message.text.strip()

    if not description:
        await update.message.reply_text("❌ Поле не может быть пустым. Введите описание:")
        return ADD_DESCRIPTION

    context.user_data["description"] = description
    await update.message.reply_text("Введите дату дедлайна в формате ДД.ММ.ГГГГ:")
    return ADD_DATE


async def add_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate date and ask for optional time."""
    date_text = update.message.text.strip()

    try:
        deadline_date = datetime.strptime(date_text, "%d.%m.%Y")
        if deadline_date.date() < datetime.now().date():
            await update.message.reply_text("❌ Нельзя указать дату в прошлом. Введите корректную дату:")
            return ADD_DATE
    except ValueError:
        await update.message.reply_text("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ:")
        return ADD_DATE

    context.user_data["deadline_date"] = date_text
    await update.message.reply_text(
        'Введите время в формате ЧЧ:ММ или напишите "нет", если время не нужно:'
    )
    return ADD_TIME


async def add_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate optional time and save entry."""
    time_text = update.message.text.strip().lower()

    deadline_time = None
    if time_text != "нет":
        try:
            datetime.strptime(time_text, "%H:%M")
            deadline_time = time_text
        except ValueError:
            await update.message.reply_text(
                '❌ Неверный формат времени. Используйте ЧЧ:ММ или напишите "нет":'
            )
            return ADD_TIME

    user_id = update.effective_user.id
    data = load_data()

    entry = {
        "id": get_next_entry_id(user_id),
        "user_id": user_id,
        "subject": context.user_data["subject"],
        "description": context.user_data["description"],
        "deadline_date": context.user_data["deadline_date"],
        "deadline_time": deadline_time,
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }

    data.append(entry)
    save_data(data)

    deadline_text = entry["deadline_date"]
    if entry["deadline_time"]:
        deadline_text += f" {entry['deadline_time']}"

    await update.message.reply_text(
        "✅ Запись успешно добавлена!\n\n"
        f"ID: {entry['id']}\n"
        f"📘 Предмет/событие: {entry['subject']}\n"
        f"📝 Описание: {entry['description']}\n"
        f"📅 Дедлайн: {deadline_text}"
    )

    context.user_data.clear()
    return ConversationHandler.END


# -----------------------------
# Delete conversation
# -----------------------------
async def delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start delete conversation."""
    cleanup_expired_entries()

    user_id = update.effective_user.id
    entries = get_user_entries(user_id)

    if not entries:
        await update.message.reply_text("Удалять нечего — активных записей пока нет.")
        return ConversationHandler.END

    entries.sort(key=parse_deadline)
    response = "Выбери ID записи для удаления:\n\n"
    response += "\n\n".join(format_entry(entry) for entry in entries)
    response += "\n\nВведите только ID числами:"

    await update.message.reply_text(response)
    return DELETE_ID


async def delete_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Delete entry by ID."""
    user_id = update.effective_user.id
    id_text = update.message.text.strip()

    if not id_text.isdigit():
        await update.message.reply_text("❌ ID должен быть числом. Введите корректный ID:")
        return DELETE_ID

    entry_id = int(id_text)
    data = load_data()

    entry_to_delete = None
    for entry in data:
        if entry["user_id"] == user_id and entry["id"] == entry_id:
            entry_to_delete = entry
            break

    if entry_to_delete is None:
        await update.message.reply_text("❌ Запись с таким ID не найдена. Введите другой ID:")
        return DELETE_ID

    data.remove(entry_to_delete)
    save_data(data)

    await update.message.reply_text(
        f"✅ Запись ID {entry_id} удалена:\n\n{format_entry(entry_to_delete)}"
    )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel current conversation."""
    context.user_data.clear()
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END


# -----------------------------
# Error handler
# -----------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and notify user."""
    logger.exception("Exception while handling update:", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Произошла непредвиденная ошибка. Попробуй ещё раз позже."
        )


# -----------------------------
# Bot commands menu
# -----------------------------
async def post_init(application: Application) -> None:
    """Set bot command menu after startup."""
    commands = [
        BotCommand("start", "Запуск бота"),
        BotCommand("add_deadline", "Добавить дедлайн"),
        BotCommand("list", "Список дедлайнов"),
        BotCommand("nearest", "Ближайшие дедлайны"),
        BotCommand("delete", "Удалить запись"),
        BotCommand("cancel", "Отменить текущую операцию"),
    ]
    await application.bot.set_my_commands(commands)


# -----------------------------
# Main function
# -----------------------------
def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not found. Create .env file with your token.")

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    add_deadline_handler = ConversationHandler(
        entry_points=[CommandHandler("add_deadline", add_deadline_start)],
        states={
            ADD_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_subject)],
            ADD_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_description)
            ],
            ADD_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_date)],
            ADD_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    delete_handler = ConversationHandler(
        entry_points=[CommandHandler("delete", delete_start)],
        states={
            DELETE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_by_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_entries))
    application.add_handler(CommandHandler("nearest", nearest_entries))
    application.add_handler(add_deadline_handler)
    application.add_handler(delete_handler)

    application.add_error_handler(error_handler)

    logger.info("SmartDiary bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
