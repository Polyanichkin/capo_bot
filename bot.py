import os
import logging
import asyncio
from io import BytesIO
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
from aiosqlite import connect as sqlite_connect
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile
import datetime
import re
from openpyxl import Workbook
from openpyxl.styles import Font

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_TELEGRAM_ID'))
DB_NAME = 'capoeira.db'

# Константы состояний разговора
SELECT_HALL, SELECT_TIME, INPUT_PHONE, CONFIRM_BOOKING = range(4)

# Зал и временные слоты
HALLS = ['Заставская', 'Комендантский']
TIMESLOTS = {
    'Заставская': ['18:00', '19:00'],
    'Комендантский': ['17:00', '18:30']
}

# Функция для проверки номера телефона
def is_valid_phone(phone):
    pattern = r'^\+?\d{10,15}$'
    cleaned_phone = re.sub(r'[^\d+]', '', phone)
    return bool(re.match(pattern, cleaned_phone))

# Инициализация базы данных
async def init_db():
    async with sqlite_connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                first_name TEXT NOT NULL,
                username TEXT,
                phone TEXT,
                hall TEXT NOT NULL,
                time TEXT NOT NULL,
                created_at DATETIME NOT NULL
            )
        """)
        await db.commit()

# Сохранение записи в базу данных
async def save_booking(user_id, context):
    first_name = context.user_data['first_name'] or "Не указано"
    username = context.user_data.get('username')
    phone = context.user_data.get('phone', 'не указан')
    hall = context.user_data['hall']
    time = context.user_data['time']
    created_at = datetime.datetime.now()

    async with sqlite_connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO bookings (user_id, first_name, username, phone, hall, time, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, first_name, username, phone, hall, time, created_at)
        )
        await db.commit()
    logger.info(f"Сохранена запись: user_id={user_id}, hall={hall}, time={time}")

# === НОВОЕ ПРИВЕТСТВИЕ ДЛЯ /start ===
async def start(update: Update, context):
    """Первое приветствие при /start."""
    first_name = update.effective_user.first_name
    username = update.effective_user.username
    context.user_data.update({
        'first_name': first_name,
        'username': username
    })

    welcome_text = (
        f"Привет, <b>{first_name}</b>! 🎉\n\n"
        "Добро пожаловать в <b>Capoeira Training Bot</b>!\n"
        "Я помогу тебе записаться на тренировку в один из наших залов.\n\n"
        "Выбери зал ниже и следуй инструкциям — запись займёт меньше минуты! 💪\n\n"
        "Доступные залы:"
    )

    buttons = [[InlineKeyboardButton(zal, callback_data=f'hall_{zal}')] for zal in HALLS]
    reply_markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    return SELECT_HALL

# === НОВАЯ КОМАНДА /book ===
async def book(update: Update, context):
    """Команда /book — начать запись в зал."""
    first_name = update.effective_user.first_name
    username = update.effective_user.username
    context.user_data.update({
        'first_name': first_name,
        'username': username
    })

    book_text = (
        f"Отлично, <b>{first_name}</b>! Записываем тебя на тренировку! 🥋\n\n"
        "Выбери зал, куда хочешь прийти:"
    )

    buttons = [[InlineKeyboardButton(zal, callback_data=f'hall_{zal}')] for zal in HALLS]
    reply_markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        book_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    return SELECT_HALL

# Выбор зала
async def select_hall(update: Update, context):
    query = update.callback_query
    await query.answer()
    selected_hall = query.data.split('_')[1]
    context.user_data['hall'] = selected_hall
    timeslots = TIMESLOTS.get(selected_hall)
    if not timeslots:
        await query.edit_message_text(f"В зале {selected_hall} нет свободных мест.")
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(timeslot, callback_data=f'time_{timeslot}')] for timeslot in timeslots]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(f"Вы выбрали зал '<b>{selected_hall}</b>'. Выберите время:", reply_markup=reply_markup, parse_mode='HTML')
    return SELECT_TIME

# Выбор времени
async def select_time(update: Update, context):
    query = update.callback_query
    await query.answer()
    selected_time = query.data.split('_')[1]
    context.user_data['time'] = selected_time
    logger.info(f"Выбрано время: {selected_time}, зал: {context.user_data['hall']}, username: {context.user_data.get('username')}")

    if not context.user_data.get('username'):
        await query.message.reply_text(
            f"Вы выбрали время: <b>{selected_time}</b> в зале <b>{context.user_data['hall']}</b>.\n\n"
            "У вас не указан username. Пожалуйста, введите номер телефона для связи:",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardRemove()
        )
        await query.message.delete()
        return INPUT_PHONE
    else:
        await query.edit_message_text(
            f"Готово! 🎯\n\n"
            f"Ты записан на <b>{context.user_data['time']}</b>\n"
            f"в зал <b>{context.user_data['hall']}</b>\n\n"
            f"До встречи на тренировке! 🔥",
            parse_mode='HTML'
        )
        await notify_admin(context)
        await save_booking(update.effective_user.id, context)
        return ConversationHandler.END

# Ввод номера телефона
async def input_phone(update: Update, context):
    phone = update.message.text.strip()

    if not is_valid_phone(phone):
        await update.message.reply_text(
            "Пожалуйста, введите корректный номер телефона (например: +79161234567 или 89161234567):"
        )
        return INPUT_PHONE

    context.user_data['phone'] = phone
    await update.message.reply_text(
        f"Спасибо! Запись подтверждена:\n\n"
        f"Зал: <b>{context.user_data['hall']}</b>\n"
        f"Время: <b>{context.user_data['time']}</b>\n"
        f"Телефон: <code>{phone}</code>\n\n"
        f"Ждём тебя на тренировке! 🏃‍♂️",
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove()
    )

    await notify_admin(context)
    await save_booking(update.effective_user.id, context)
    return ConversationHandler.END

# Оповещение админа
async def notify_admin(context):
    admin_chat_id = ADMIN_ID
    first_name = context.user_data['first_name'] or "Не указано"
    username = f"@{context.user_data['username']}" if context.user_data.get('username') else "нет username"
    hall = context.user_data['hall']
    time = context.user_data['time']
    phone = context.user_data.get('phone', 'не указан')

    message = (
        f"НОВАЯ ЗАПИСЬ!\n"
        f"Пользователь: {first_name} ({username})\n"
        f"Телефон: {phone}\n"
        f"Зал: {hall}\n"
        f"Время: {time}\n"
        f"Время: {datetime.datetime.now().strftime('%d.%m %H:%M')}"
    )

    try:
        await context.bot.send_message(chat_id=admin_chat_id, text=message)
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {e}")

# Отмена
async def cancel(update: Update, context):
    await update.message.reply_text(
        "Запись отменена. Чтобы записаться — используй /book или /start",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# Команда /bookings — только Excel-файл (для админа)
async def list_bookings(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Доступ запрещён. Команда только для администратора.")
        return

    async with sqlite_connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM bookings ORDER BY created_at DESC")
        rows = await cursor.fetchall()

    if not rows:
        await update.message.reply_text("Нет записей на тренировки.")
        return

    # Создаём Excel-файл
    wb = Workbook()
    ws = wb.active
    ws.title = "Записи на тренировки"

    # Заголовки
    headers = ['№', 'Зал', 'Время', 'Имя', 'Username', 'Телефон', 'Дата и время']
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    # Данные
    for idx, row in enumerate(rows, 1):
        username = f"@{row[3]}" if row[3] else "—"
        phone = row[4] if row[4] else "—"
        created_at = row[7]
        if hasattr(created_at, 'strftime'):
            created_at = created_at.strftime("%d.%m.%Y %H:%M")
        else:
            created_at = created_at

        ws.append([
            idx,
            row[5],  # зал
            row[6],  # время
            row[2],  # имя
            username,
            phone,
            created_at
        ])

    # Автоширина колонок
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column].width = adjusted_width

    # Сохраняем в память
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    # Отправляем
    await update.message.reply_document(
        document=InputFile(output, filename=f"капо_записи_{datetime.datetime.now().strftime('%d-%m-%Y')}.xlsx"),
        caption=(
            "Текущие записи на тренировки\n"
            f"Всего: {len(rows)} чел.\n"
            "Обновлено: сейчас"
        )
    )

# Обработчик ошибок
async def error_handler(update: Update, context):
    logger.error(f"Ошибка: {context.error}")
    if update and update.message:
        await update.message.reply_text("Ошибка. Попробуй /book или /start")

# === ОСНОВНОЙ ЗАПУСК ===
def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('book', book)  # НОВАЯ КОМАНДА
        ],
        states={
            SELECT_HALL: [CallbackQueryHandler(select_hall, pattern='^hall_')],
            SELECT_TIME: [CallbackQueryHandler(select_time, pattern='^time_')],
            INPUT_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, input_phone),
                CommandHandler('cancel', cancel)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('bookings', list_bookings))
    application.add_error_handler(error_handler)

    print("Бот запущен! Используй /start или /book")
    application.run_polling()

if __name__ == '__main__':
    main()