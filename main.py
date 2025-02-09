import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import StateFilter
import sqlite3
import config
import re
from datetime import datetime, timedelta
import logging
import threading
from webhook_server import app  # Импортируем Flask-приложени
import json

# Инициализация бота, диспетчера и хранилища состояний
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Подключение к SQLite базе данных
db = sqlite3.connect("users.db")
cursor = db.cursor()

# Создаем таблицу, если она не существует
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    phone TEXT,
    is_paid_channel_1 INTEGER DEFAULT 0,  -- Подписка на канал 1 
    is_paid_channel_2 INTEGER DEFAULT 0,  -- Подписка на канал 2 
    payment_date_channel_1 TEXT,  -- Дата оплаты для канала 1
    payment_date_channel_2 TEXT,  -- Дата оплаты для канала 2
    subscription_end_date_channel_1 TEXT,  -- Дата окончания подписки для канала 1
    subscription_end_date_channel_2 TEXT  -- Дата окончания подписки для канала 2
)
""")
db.commit()

logger = logging.getLogger(__name__)  # Создаем объект logger

# Команда /get_users_db
@dp.message(Command("get_users_db"))
async def send_users_db(message: Message):
    # Проверяем, есть ли пользователь в списке администраторов
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("У вас нет прав для выполнения этой команды.")
        return

    # Получаем данные из базы данных
    cursor.execute("SELECT id, username, full_name, phone, is_paid_channel_1, is_paid_channel_2, payment_date_channel_1, payment_date_channel_2, subscription_end_date_channel_1, subscription_end_date_channel_2 FROM users")
    users = cursor.fetchall()

    if not users:
        await message.answer("В базе данных нет пользователей.")
        return

    # Формируем сообщение с данными пользователей
    users_info = []
    for user in users:
        user_id, username, full_name, phone, is_paid_channel_1, is_paid_channel_2, payment_date_channel_1, payment_date_channel_2, subscription_end_date_channel_1, subscription_end_date_channel_2 = user
        paid_status_channel_1 = "Оплачено ✅" if is_paid_channel_1 else "Не оплачено ❌"
        paid_status_channel_2 = "Оплачено ✅" if is_paid_channel_2 else "Не оплачено ❌"
        user_info = (
            f"ID: {user_id}\n"
            f"Имя: {full_name}\n"
            f"Username: @{username if username else 'N/A'}\n"
            f"Телефон: {phone if phone else 'N/A'}\n"
            f"Статус оплаты канал 1 (Тренировки с Сэнсэем): {paid_status_channel_1}\n"
            f"Дата оплаты канал 1: {payment_date_channel_1 if payment_date_channel_1 else 'N/A'}\n"
            f"Дата окончания подписки канал 1: {subscription_end_date_channel_1 if subscription_end_date_channel_1 else 'N/A'}\n"
            f"Статус оплаты канал 2 (Метод ОСС | обучение по исправлению осанки): {paid_status_channel_2}\n"
            f"Дата оплаты канал 2: {payment_date_channel_2 if payment_date_channel_2 else 'N/A'}\n"
            f"Дата окончания подписки канал 2: {subscription_end_date_channel_2 if subscription_end_date_channel_2 else 'N/A'}\n"
            "-----------------------------"
        )
        users_info.append(user_info)

    # Разбиваем сообщение на части, если оно слишком длинное
    message_text = "\n".join(users_info)
    for part in [message_text[i:i + 4096] for i in range(0, len(message_text), 4096)]:
        await message.answer(part)

# Определяем состояния
class UserState(StatesGroup):
    waiting_for_name = State()
    waiting_for_contact = State()
    waiting_for_donation_amount = State()

# Кнопки для ввода номера телефона
contact_button = KeyboardButton(text="Поделиться номером телефона", request_contact=True)
contact_keyboard = ReplyKeyboardMarkup(keyboard=[[contact_button]], resize_keyboard=True)

# Команда /start
@dp.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await message.answer("Привет! Давай начнем. Как тебя зовут?")
    await state.set_state(UserState.waiting_for_name)

# Обработка имени пользователя
@dp.message(UserState.waiting_for_name)
async def name_handler(message: Message, state: FSMContext):
    full_name = message.text
    user_id = message.from_user.id
    username = message.from_user.username

    # Сохраняем имя в базу
    cursor.execute("INSERT OR IGNORE INTO users (id, username, full_name) VALUES (?, ?, ?)", 
                   (user_id, username, full_name))
    db.commit()

    await message.answer(
        "Спасибо! Теперь поделись своим номером телефона с помощью кнопки ниже или в формате +79991234567.",
        reply_markup=contact_keyboard
    )
    await state.set_state(UserState.waiting_for_contact)

# Обработка номера телефона через кнопку "Поделиться номером телефона"
@dp.message(UserState.waiting_for_contact, F.contact)
async def contact_handler(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    user_id = message.from_user.id

    # Сохраняем номер телефона в базу
    cursor.execute("UPDATE users SET phone = ? WHERE id = ?", (phone, user_id))
    db.commit()

    await send_payment_prompt(message, state)

# Обработка номера телефона, введенного вручную
@dp.message(UserState.waiting_for_contact)
async def manual_phone_handler(message: Message, state: FSMContext):
    phone = message.text.strip()

    # Проверяем, является ли текст корректным номером телефона
    if not re.fullmatch(r"^\+?\d{10,15}$", phone):  # Номер телефона должен содержать от 10 до 15 цифр
        await message.answer(
            "Пожалуйста, введите корректный номер телефона в международном формате (например, +79991234567)."
        )
        return

    user_id = message.from_user.id

    # Сохраняем номер телефона в базу
    cursor.execute("UPDATE users SET phone = ? WHERE id = ?", (phone, user_id))
    db.commit()

    await send_payment_prompt(message, state)

# Функция отправки сообщения с предложением оплатить подписку
async def send_payment_prompt(message: Message, state: FSMContext):
    # Кнопки для выбора типа платежа
    pay_button_1 = InlineKeyboardButton(text="Оплатить канал 1 [300 руб]", callback_data="pay_channel_1")   
    pay_button_2 = InlineKeyboardButton(text="Оплатить канал 2 [3000 руб]", callback_data="pay_channel_2")
    donate_button = InlineKeyboardButton(text="Сделать пожертвование", callback_data="donate")
    pay_keyboard = InlineKeyboardMarkup(inline_keyboard=[[pay_button_1], [pay_button_2], [donate_button]])
    
    await message.answer(
        "Спасибо! Выберите тип платежа:",
        reply_markup=pay_keyboard
    )
    await state.clear()  # Сбрасываем состояние

# Обработка выбора типа платежа
@dp.callback_query(lambda c: c.data.startswith("pay_"))
async def payment_handler(callback: CallbackQuery):
    if callback.data == "pay_channel_1":
        prices = [types.LabeledPrice(label="Подписка на канал 1", amount=30000)]  # 300 рублей
        payload = "subscription_channel_1"
    elif callback.data == "pay_channel_2":
        prices = [types.LabeledPrice(label="Подписка на канал 2)", amount=300000)]  # 3000 рублей
        payload = "subscription_channel_2"
    
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Подписка на канал",
        description="Оплата доступа к закрытому каналу",
        provider_token=config.PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=prices,
        payload=payload,
    )
    await callback.answer()  # Закрываем всплывающее уведомление

# Обработка пожертвования
@dp.callback_query(lambda c: c.data == "donate")
async def donate_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите сумму пожертвования в рублях:")
    await state.set_state(UserState.waiting_for_donation_amount)
    await callback.answer()

# Обработка ввода суммы пожертвования
@dp.message(F.text, StateFilter(UserState.waiting_for_donation_amount))
async def process_donation_amount(message: Message, state: FSMContext):
    try:
        amount_rub = float(message.text)  # Преобразуем ввод в число
        if amount_rub < 60:  # Минимальная сумма — 60 рублей
            await message.answer("Минимальная сумма пожертвования — 60 рублей.")
            return
        amount = int(amount_rub * 100)  # Переводим рубли в копейки

        prices = [types.LabeledPrice(label="Пожертвование", amount=amount)]
        
        await bot.send_invoice(
            chat_id=message.from_user.id,
            title="Пожертвование",
            description="Спасибо за вашу поддержку!",
            provider_token=config.PAYMENT_PROVIDER_TOKEN,
            currency="RUB",
            prices=prices,
            payload="donation"
        )
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите корректную сумму.")

@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# Обработка успешной оплаты
@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    logger.info("Успешный платеж получен!")
    user_id = message.from_user.id
    payload = message.successful_payment.invoice_payload

    # Логируем информацию о платеже
    logger.info(f"Пользователь {user_id} оплатил: {payload}")

    # Получаем текущую дату
    payment_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if payload == "subscription_channel_1":
        # Получаем текущую дату окончания подписки для канала 1
        cursor.execute("SELECT subscription_end_date_channel_1 FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        current_subscription_end = result[0] if result else None

        # Если у пользователя есть активная подписка, продлеваем её
        if current_subscription_end and datetime.strptime(current_subscription_end, "%Y-%m-%d %H:%M:%S") > datetime.now():
            new_subscription_end = (datetime.strptime(current_subscription_end, "%Y-%m-%d %H:%M:%S") + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            new_subscription_end = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")

        # Обновляем статус оплаты, даты и информацию о подписке для канала 1
        cursor.execute(
            "UPDATE users SET is_paid_channel_1 = 1, payment_date_channel_1 = ?, subscription_end_date_channel_1 = ? WHERE id = ?",
            (payment_date, new_subscription_end, user_id)
        )
        db.commit()
        logger.info(f"Пользователь {user_id} подписан на Канал 1 (Тренировки с Сэнсэем)")
        await message.answer(f"Ваша подписка на канал 1 продлена до {new_subscription_end}.")
        invite_link = 'https://t.me/...'  # Замените на реальную ссылку
        await message.answer(
            "Оплата прошла успешно! Добро пожаловать в канал 1. Перейди по ссылке, чтобы присоединиться:",   
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text="Присоединиться к канал 1", url=invite_link)]
                ]
            )
        )
    elif payload == "subscription_channel_2":
        # Получаем текущую дату окончания подписки для канала 2
        cursor.execute("SELECT subscription_end_date_channel_2 FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        current_subscription_end = result[0] if result else None

        # Если у пользователя есть активная подписка, продлеваем её
        if current_subscription_end and datetime.strptime(current_subscription_end, "%Y-%m-%d %H:%M:%S") > datetime.now():
            new_subscription_end = (datetime.strptime(current_subscription_end, "%Y-%m-%d %H:%M:%S") + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            new_subscription_end = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")

        # Обновляем статус оплаты, даты и информацию о подписке для канала 2
        cursor.execute(
            "UPDATE users SET is_paid_channel_2 = 1, payment_date_channel_2 = ?, subscription_end_date_channel_2 = ? WHERE id = ?",
            (payment_date, new_subscription_end, user_id)
        )
        db.commit()
        logger.info(f"Пользователь {user_id} подписан на Канал 2")
        await message.answer(f"Ваша подписка на канал 2) продлена до {new_subscription_end}.")
        invite_link = 'https://t.me/...'  # Замените на реальную ссылку
        await message.answer(
            "Оплата прошла успешно! Добро пожаловать в канал 2). Перейди по ссылке, чтобы присоединиться:",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text="Присоединиться к канал 2", url=invite_link)]
                ]
            )
        )
    elif payload == "donation":
        logger.info(f"Пользователь {user_id} сделал пожертвование")
        await message.answer("Спасибо за ваше пожертвование! Ваша поддержка очень важна для нас.")

    # Отправляем уведомление администратору
    await notify_admin(user_id, payload, payment_date)

# Функция для отправки уведомления администратору
async def notify_admin(user_id: int, payload: str, payment_date: str):
    # Получаем данные о пользователе
    cursor.execute("SELECT id, username, full_name, phone, is_paid_channel_1, is_paid_channel_2, subscription_end_date_channel_1, subscription_end_date_channel_2 FROM users WHERE id = ?", (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        user_id, username, full_name, phone, is_paid_channel_1, is_paid_channel_2, subscription_end_date_channel_1, subscription_end_date_channel_2 = user_data
        paid_status_channel_1 = "Оплачено ✅" if is_paid_channel_1 else "Не оплачено ❌"
        paid_status_channel_2 = "Оплачено ✅" if is_paid_channel_2 else "Не оплачено ❌"
        payment_type = "Подписка на канал 1" if payload == "subscription_channel_1" else "Подписка на канал 2" if payload == "subscription_channel_2" else "Пожертвование"

        # Формируем сообщение для администратора
        admin_message = (
            f"Новая оплата!\n"
            f"Тип оплаты: {payment_type}\n"
            f"ID пользователя: {user_id}\n"
            f"Имя: {full_name}\n"
            f"Username: @{username if username else 'N/A'}\n"
            f"Телефон: {phone if phone else 'N/A'}\n"
            f"Статус оплаты канал 1: {paid_status_channel_1}\n"
            f"Дата оплаты канал 1: {payment_date if payload == 'subscription_channel_1' else 'N/A'}\n"
            f"Дата окончания подписки канал 1: {subscription_end_date_channel_1 if subscription_end_date_channel_1 else 'N/A'}\n"
            f"Статус оплаты канал 2: {paid_status_channel_2}\n"
            f"Дата оплаты канал 2: {payment_date if payload == 'subscription_channel_2' else 'N/A'}\n"
            f"Дата окончания подписки канал 2: {subscription_end_date_channel_2 if subscription_end_date_channel_2 else 'N/A'}\n"
        )

        # Отправляем сообщение всем администраторам
        for admin_id in config.ADMIN_IDS:
            await bot.send_message(admin_id, admin_message)

async def manage_subscriptions():
    while True:
        now = datetime.now()
        
        # Проверяем подписки на канал 1
        cursor.execute("SELECT id, subscription_end_date_channel_1, full_name, username FROM users WHERE is_paid_channel_1 = 1")
        users_channel_1 = cursor.fetchall()

        # Проверяем подписки на канал 2
        cursor.execute("SELECT id, subscription_end_date_channel_2, full_name, username FROM users WHERE is_paid_channel_2 = 1")
        users_channel_2 = cursor.fetchall()

        # Обработка подписок на канал 1
        for user in users_channel_1:
            user_id, subscription_end_date_str, full_name, username = user
            subscription_end_date = datetime.strptime(subscription_end_date_str, "%Y-%m-%d %H:%M:%S")
            delta = subscription_end_date - now

            try:
                # Если осталось 3 дня
                if timedelta(days=3) >= delta > timedelta(days=2):
                    await bot.send_message(
                        user_id,
                        "Ваша подписка на канал 1 заканчивается через 3 дня. Пожалуйста, продлите подписку, чтобы продолжить пользоваться услугами."
                    )

                # Если остался 1 день
                elif timedelta(days=1) >= delta > timedelta(hours=0):
                    await bot.send_message(
                        user_id,
                        "Ваша подписка на канал 1 заканчивается завтра. Пожалуйста, продлите подписку, чтобы продолжить пользоваться услугами."
                    )

                # Если подписка истекла
                elif delta <= timedelta(hours=0):
                    # Обновляем статус подписки на канал 1
                    cursor.execute("UPDATE users SET is_paid_channel_1 = 0 WHERE id = ?", (user_id,))
                    db.commit()
                    await bot.send_message(
                        user_id,
                        "Ваша подписка на канал 1 истекла. Пожалуйста, продлите подписку, чтобы снова получить доступ."
                    )

                    # Уведомляем администратора
                    for admin_id in config.ADMIN_IDS:
                        await bot.send_message(
                            admin_id,
                            f"Подписка пользователя {full_name} (@{username if username else 'N/A'}) на канал 1 истекла. Необходимо удалить пользователя из канала."
                        )

            except Exception as e:
                logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")

        # Обработка подписок на канал 2
        for user in users_channel_2:
            user_id, subscription_end_date_str, full_name, username = user
            subscription_end_date = datetime.strptime(subscription_end_date_str, "%Y-%m-%d %H:%M:%S")
            delta = subscription_end_date - now

            try:
                # Если осталось 3 дня
                if timedelta(days=3) >= delta > timedelta(days=2):
                    await bot.send_message(
                        user_id,
                        "Ваша подписка на канал 2 заканчивается через 3 дня. Пожалуйста, продлите подписку, чтобы продолжить пользоваться услугами."
                    )

                # Если остался 1 день
                elif timedelta(days=1) >= delta > timedelta(hours=0):
                    await bot.send_message(
                        user_id,
                        "Ваша подписка на канал 2 заканчивается завтра. Пожалуйста, продлите подписку, чтобы продолжить пользоваться услугами."
                    )

                # Если подписка истекла
                elif delta <= timedelta(hours=0):
                    # Обновляем статус подписки на канал 2
                    cursor.execute("UPDATE users SET is_paid_channel_2 = 0 WHERE id = ?", (user_id,))
                    db.commit()
                    await bot.send_message(
                        user_id,
                        "Ваша подписка на канал 2 истекла. Пожалуйста, продлите подписку, чтобы снова получить доступ."
                    )

                    # Уведомляем администратора
                    for admin_id in config.ADMIN_IDS:
                        await bot.send_message(
                            admin_id,
                            f"Подписка пользователя {full_name} (@{username if username else 'N/A'}) на канал 2 истекла. Необходимо удалить пользователя из канала."
                        )

            except Exception as e:
                logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")

        # Ждем до полуночи следующего дня
        now = datetime.now()
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_midnight - now).total_seconds())

# Запуск веб-сервера в отдельном потоке
def run_webhook_server():
    app.run(port=5000, ssl_context='adhoc')

# Запуск бота
async def main():
    # Запускаем веб-сервер в отдельном потоке
    webhook_thread = threading.Thread(target=run_webhook_server)
    webhook_thread.daemon = True  # Поток завершится при завершении основного потока
    webhook_thread.start()

    # Запускаем проверку подписок в фоновом режиме
    asyncio.create_task(manage_subscriptions())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())