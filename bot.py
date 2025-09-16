import os
import logging
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
from aiosqlite import connect as sqlite_connect
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
import datetime
import re

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
    """Проверяет, является ли строка валидным номером телефона."""
    pattern = r'^\+?\d{10,15}$'
    cleaned_phone = re.sub(r'[^\d+]', '', phone)
    return bool(re.match(pattern, cleaned_phone))

# Начальное приветствие и предложение выбора зала
async def start(update: Update, context):
    """Начало взаимодействия с ботом."""
    first_name = update.effective_user.first_name
    username = update.effective_user.username
    context.user_data.update({
        'first_name': first_name,
        'username': username
    })

    buttons = [[InlineKeyboardButton(zal, callback_data=f'hall_{zal}')] for zal in HALLS]
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Добро пожаловать в Capoeira Bot!\nВыберите зал:", reply_markup=reply_markup)
    return SELECT_HALL

# Выбор зала
async def select_hall(update: Update, context):
    """Выбор зала для тренировок."""
    query = update.callback_query
    await query.answer()
    selected_hall = query.data.split('_')[1]
    context.user_data['hall'] = selected_hall
    timeslots = TIMESLOTS.get(selected_hall)
    if not timeslots:
        await query.edit_message_text(f"В зале {selected_hall} нет свободных мест.")
        return ConversationHandler.END

    # Кнопки для выбора времени
    buttons = [[InlineKeyboardButton(timeslot, callback_data=f'time_{timeslot}')] for timeslot in timeslots]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(f"Вы выбрали зал '{selected_hall}'. Выберите время:", reply_markup=reply_markup)
    return SELECT_TIME

# Выбор времени
async def select_time(update: Update, context):
    """Выбор времени тренировки."""
    query = update.callback_query
    await query.answer()
    selected_time = query.data.split('_')[1]
    context.user_data['time'] = selected_time
    logger.info(f"Выбрано время: {selected_time}, зал: {context.user_data['hall']}, username: {context.user_data.get('username')}")

    # Проверяем, есть ли username у пользователя
    if not context.user_data.get('username'):
        logger.info("Переход в состояние INPUT_PHONE")
        await query.message.reply_text(
            f"Вы выбрали время: {selected_time} в зале {context.user_data['hall']}.\n\n"
            "У вас не указан username в Telegram. Пожалуйста, введите ваш номер телефона для связи:",
            reply_markup=ReplyKeyboardRemove()
        )
        await query.message.delete()  # Удаляем старое сообщение с inline-клавиатурой
        return INPUT_PHONE
    else:
        logger.info("Завершение записи для пользователя с username")
        await query.edit_message_text(
            f"Выбранное время: {context.user_data['time']} в зале {context.user_data['hall']}. Ваша запись принята!",
            reply_markup=None  # Явно убираем inline-клавиатуру
        )
        await notify_admin(context)
        return ConversationHandler.END

# Ввод номера телефона
async def input_phone(update: Update, context):
    """Обработка ввода номера телефона."""
    phone = update.message.text.strip()

    if not is_valid_phone(phone):
        await update.message.reply_text(
            "Пожалуйста, введите корректный номер телефона (например: +79161234567 или 89161234567):"
        )
        return INPUT_PHONE

    context.user_data['phone'] = phone
    await update.message.reply_text(
        f"Спасибо! Ваша запись принята:\n"
        f"Зал: {context.user_data['hall']}\n"
        f"Время: {context.user_data['time']}\n",
        reply_markup=ReplyKeyboardRemove()
    )

    await notify_admin(context)
    return ConversationHandler.END

# Оповещаем администратора о новой записи
async def notify_admin(context):
    admin_chat_id = ADMIN_ID

    first_name = context.user_data['first_name'] or "Не указано"
    username = f"@{context.user_data['username']}" if context.user_data.get('username') else "нет username"
    hall = context.user_data['hall']
    time = context.user_data['time']
    phone = context.user_data.get('phone', 'не указан')

    message = (
        f"Новая запись!\n"
        f"Пользователь: {first_name} ({username})\n"
        f"Телефон: {phone}\n"
        f"Зал: {hall}\n"
        f"Время: {time}"
    )

    try:
        await context.bot.send_message(chat_id=admin_chat_id, text=message)
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления администратору: {e}")

# Отмена ввода телефона
async def cancel(update: Update, context):
    """Отмена ввода телефона."""
    await update.message.reply_text(
        "Запись отменена. Если хотите записаться снова, используйте /start",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# Обработчик ошибок
async def error_handler(update: Update, context):
    """Обработка ошибок."""
    logger.error(f"Ошибка: {context.error}")
    if update and update.message:
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте снова с помощью /start.")

# Главная функция запуска приложения
def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
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
    application.add_error_handler(error_handler)  # Добавляем обработчик ошибок
    application.run_polling()

if __name__ == '__main__':
    main()