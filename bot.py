import os
import sqlite3
import time
import json
import logging
import hashlib
from datetime import datetime, timedelta
from contextlib import closing
import requests
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
API_URL = "https://api-poweron.toe.com.ua/api/a_gpv_g"
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
GROUP = "3.2"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "X-debug-key": "MjEwMDUvMzI2ODMvMTY4"
}

# Кнопки
BTN_TODAY = "📅 Графік на сьогодні"
BTN_TOMORROW = "⏭️ Графік на завтра"
BTN_STATUS = "📊 Мій статус"
BTN_HELP = "❓ Допомога"
BTN_STOP = "🔕 Вимкнути сповіщення"
BTN_START = "🔔 Увімкнути сповіщення"


def main_menu_keyboard(is_active=True):
    sub_btn = BTN_STOP if is_active else BTN_START
    keyboard = [
        [KeyboardButton(BTN_TODAY), KeyboardButton(BTN_TOMORROW)],
        [KeyboardButton(BTN_STATUS), KeyboardButton(BTN_HELP)],
        [KeyboardButton(sub_btn)]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY, active INTEGER DEFAULT 1)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS sent_graphs (date_text TEXT PRIMARY KEY, content_hash TEXT, updated_at TEXT)")
        db.commit()


def get_user_status(chat_id):
    with closing(sqlite3.connect(DB_PATH)) as db:
        row = db.execute("SELECT active FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        return row[0] if row else 0


def has_graph_changed(date_text, current_content):
    content_str = json.dumps(current_content, sort_keys=True)
    content_hash = hashlib.md5(content_str.encode()).hexdigest()
    with closing(sqlite3.connect(DB_PATH)) as db:
        row = db.execute("SELECT content_hash FROM sent_graphs WHERE date_text = ?", (date_text,)).fetchone()
        if row is None or row[0] != content_hash:
            db.execute("INSERT OR REPLACE INTO sent_graphs (date_text, content_hash, updated_at) VALUES (?, ?, ?)",
                       (date_text, content_hash, datetime.now().isoformat()))
            db.commit()
            return True
    return False


def fetch_one_day(target_date):
    """Запит до API на конкретну дату з виправленим форматом порівняння"""
    date_str = target_date.strftime("%Y-%m-%d")

    # Формуємо параметри точно як хоче API
    params = {
        "after": f"{date_str}T00:00:00Z",
        "before": f"{date_str}T23:59:59Z",
        "group[]": [GROUP],
        "time": int(time.time() * 1000)
    }

    try:
        r = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        items = data.get("hydra:member", [])

        if not items:
            logger.info(f"API повернуло порожній список для {date_str}")
            return None

        # Шукаємо айтем, де дата ПОЧИНАЄТЬСЯ з нашого date_str
        for item in items:
            api_date = item.get("dateGraph", "")
            if api_date.startswith(date_str):
                return item

        return None
    except Exception as e:
        logger.error(f"Помилка API ({date_str}): {e}")
        return None


def format_graph_text(graph):
    if not graph:
        return "⚠️ Графік не знайдено."

    # Обробка дати: прибираємо зайвий час, якщо він є (T00:00:00Z)
    date_raw = graph.get("dateGraph", "---")
    date_str = date_raw.split('T')[0] if 'T' in date_raw else date_raw

    data_json = graph.get("dataJson", {})
    group_info = data_json.get(GROUP)

    if not group_info:
        for key in data_json.keys():
            if GROUP in key:
                group_info = data_json[key]
                break

    times = group_info.get("times", {}) if group_info else {}

    if not times:
        return f"📅 **Графік на {date_str}**\n\nДані для групи {GROUP} відсутні."

    # Формуємо заголовок
    msg = f"📅 **Графік ГПВ: {date_str}**\n"
    msg += f"👥 **Група: {GROUP}**\n"
    msg += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"

    # Сортуємо ключі (часи)
    sorted_times = sorted(times.keys())

    for t in sorted_times:
        val = str(times[t])  # Перетворюємо на рядок для надійності

        # Логіка згідно з вашим API:
        # "1" - немає світла (червоний)
        # "10" - можливі відключення (сірий/жовтий)
        # "0" - є світло (зелений)

        if val == "1":
            status_icon = "🔴"
            status_text = "Немає світла"
        elif val == "10":
            status_icon = "⚪"  # або 🟡
            status_text = "Можливе відключення"
        elif val == "0":
            status_icon = "🟢"
            status_text = "Світло є"
        else:
            status_icon = "❓"
            status_text = "Невідомо"

        msg += f"{status_icon} `{t}` — {status_text}\n"

    msg += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    msg += "**Умовні позначення:**\n"
    msg += "🔴 — Відключення\n"
    msg += "⚪ — Можливе відключення\n"
    msg += "🟢 — Світло є"

    return msg


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.execute("INSERT OR REPLACE INTO users (chat_id, active) VALUES (?, 1)", (chat_id,))
        db.commit()
    await update.message.reply_text("👋 Бот активний!", reply_markup=main_menu_keyboard(True))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == BTN_TODAY:
        graph = fetch_one_day(datetime.now())
        await update.message.reply_text(format_graph_text(graph), parse_mode="Markdown")

    elif text == BTN_TOMORROW:
        graph = fetch_one_day(datetime.now() + timedelta(days=1))
        if not graph:
            await update.message.reply_text("⚠️ Графік на завтра ще не опублікований.")
        else:
            await update.message.reply_text(format_graph_text(graph), parse_mode="Markdown")

    elif text == BTN_STATUS:
        is_active = get_user_status(chat_id)
        status = "✅ Активні" if is_active else "🔕 Вимкнені"
        await update.message.reply_text(f"📊 Сповіщення: {status}\n👥 Група: {GROUP}")

    elif text == BTN_STOP:
        with closing(sqlite3.connect(DB_PATH)) as db:
            db.execute("UPDATE users SET active = 0 WHERE chat_id = ?", (chat_id,))
            db.commit()
        await update.message.reply_text("🔕 Сповіщення вимкнено.", reply_markup=main_menu_keyboard(False))

    elif text == BTN_START:
        with closing(sqlite3.connect(DB_PATH)) as db:
            db.execute("UPDATE users SET active = 1 WHERE chat_id = ?", (chat_id,))
            db.commit()
        await update.message.reply_text("🔔 Сповіщення увімкнено!", reply_markup=main_menu_keyboard(True))


async def monitoring_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Фонова перевірка...")
    # Перевіряємо сьогодні і завтра
    for delta in [0, 1]:
        target_date = datetime.now() + timedelta(days=delta)
        graph = fetch_one_day(target_date)

        if graph:
            date_text = graph.get("dateGraph")
            times_data = graph.get("dataJson", {}).get(GROUP, {}).get("times", {})

            if times_data and has_graph_changed(date_text, times_data):
                msg = "🔄 **ОНОВЛЕННЯ ГРАФІКУ!**\n\n" + format_graph_text(graph)
                with closing(sqlite3.connect(DB_PATH)) as db:
                    users = [row[0] for row in db.execute("SELECT chat_id FROM users WHERE active = 1").fetchall()]

                for user_id in users:
                    try:
                        await context.bot.send_message(user_id, msg, parse_mode="Markdown")
                    except Exception as e:
                        logger.warning(f"Не надіслано {user_id}: {e}")


if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if app.job_queue:
        app.job_queue.run_repeating(monitoring_job, interval=120, first=5)

    logger.info("Бот запущений!")
    app.run_polling()
