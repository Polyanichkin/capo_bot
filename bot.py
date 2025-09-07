import os
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, MessageHandler, filters, \
    CallbackQueryHandler
from aiosqlite import connect as sqlite_connect
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
import datetime

# Загрузка переменных окружения
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_TELEGRAM_ID'))
DB_NAME = 'capoeira.db'

# Константы состояний разговора
SELECT_HALL, SELECT_TIME, CONFIRM_BOOKING = range(3)

# Зал и временные слоты
HALLS = ['Заставская', 'Комендантский']
TIMESLOTS = {
    'Заставская': ['18:00', '19:00'],
    'Комендантский': ['17:00', '18:30']
}


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
    await query.edit_message_text(
        f"Выбранное время: {context.user_data['time']} в зале {context.user_data['hall']}. Ваша запись принята!")
    await notify_admin(context)
    return ConversationHandler.END


# Оповещаем администратора о новой записи
async def notify_admin(context):
    admin_chat_id = ADMIN_ID

    # Простое текстовое сообщение без Markdown
    first_name = context.user_data['first_name'] or "Не указано"
    username = f"@{context.user_data['username']}" if context.user_data['username'] else "нет username"
    hall = context.user_data['hall']
    time = context.user_data['time']

    message = f"Новая запись!\nПользователь: {first_name} ({username})\nЗал: {hall}\nВремя: {time}"

    try:
        await context.bot.send_message(chat_id=admin_chat_id, text=message)
    except Exception as e:
        print(f"Ошибка отправки уведомления администратору: {e}")


# Главная функция запуска приложения
def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECT_HALL: [CallbackQueryHandler(select_hall, pattern='^hall_')],
            SELECT_TIME: [CallbackQueryHandler(select_time, pattern='^time_')],
        },
        fallbacks=[],
        per_message=False  # Оставляем False, но добавляем паттерны
    )

    application.add_handler(conv_handler)
    application.run_polling()


if __name__ == '__main__':
    main()