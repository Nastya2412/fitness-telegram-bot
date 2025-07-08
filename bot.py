# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import re
import json  # Добавлен для Render.com
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, BotCommand, MenuButtonCommands
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

print("📦 Импорты загружены успешно")

# Загружаем переменные из .env файла (для локальной разработки)
load_dotenv()
print("🔧 .env файл загружен")

# Настройки из переменных окружения (поддержка и локальной разработки, и Render)
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS")

# Настройки оплаты
PAYMENT_PHONE = "+996995311919"  # Замените на ваш номер телефона
QR_CODE_PATH = "qr_code.jpg"        # Путь к QR коду в репозитории

print(f"🔑 BOT_TOKEN: {'✅ Загружен' if BOT_TOKEN else '❌ Отсутствует'}")
print(f"👨‍💼 ADMIN_ID: {'✅ ' + str(ADMIN_ID) if ADMIN_ID else '❌ Отсутствует'}")
print(f"📊 GOOGLE_CREDENTIALS_FILE: {'✅ ' + str(GOOGLE_CREDENTIALS_FILE) if GOOGLE_CREDENTIALS_FILE else '❌ Отсутствует'}")
print(f"📊 GOOGLE_CREDENTIALS_JSON: {'✅ Переменная окружения' if GOOGLE_CREDENTIALS_JSON else '❌ Отсутствует'}")
print(f"📋 SPREADSHEET_ID: {'✅ Загружен' if SPREADSHEET_ID else '❌ Отсутствует'}")
print(f"💳 PAYMENT_PHONE: {PAYMENT_PHONE}")
print(f"📷 QR_CODE_PATH: {'✅ ' + QR_CODE_PATH if os.path.exists(QR_CODE_PATH) else '❌ Файл не найден'}")

# Проверяем обязательные переменные
if not BOT_TOKEN:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: BOT_TOKEN не найден в переменных окружения!")
    exit(1)

if not ADMIN_ID:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: ADMIN_ID не найден в переменных окружения!")
    exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния
class RegistrationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_schedule = State()

class PaymentStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_screenshot = State()

class AdminStates(StatesGroup):
    editing_payment_amount = State()
    editing_min_amount = State()
    editing_max_amount = State()
    editing_monthly_price = State()
    editing_sessions_count = State()
    editing_free_days = State()
    editing_sick_days = State()
    editing_schedule_text = State()
    editing_rules_text = State()

# Глобальные переменные для Google Sheets
sheets_client = None
drive_service = None
users_sheet = None
payments_sheet = None
attendance_sheet = None
settings_sheet = None

# Настройки по умолчанию
DEFAULT_SETTINGS = {
    'min_payment': 1000,
    'max_payment': 20000,
    'monthly_price': 8000,
    'sessions_per_month': 10,
    'free_days_limit': 7,
    'sick_days_limit': 3,
    'gym_schedule': 'Пн-Ср-Пт: 7:00-12:00 (группа)\nВт-Чт-Сб: по записи',
    'gym_rules': '''📋 ПРАВИЛА ФИТНЕС-ЗАЛА

💰 ОПЛАТА:
• Месячный абонемент: 8000 сом за 10 занятий
• Минимальная сумма: 1000 сом
• Максимальная сумма: 20000 сом
• Оплата: переводом (со скриншотом) или наличными

⏰ ГРАФИК РАБОТЫ:
Пн-Ср-Пт: 7:00-12:00 (группа)
Вт-Чт-Сб: по записи

❄️ ЗАМОРОЗКА АБОНЕМЕНТА:
• Без причины: до 7 занятий подряд
• По болезни: до 3 занятий подряд (с отметкой в боте)
• Заморозка не переносится на следующий период
• Обязательно уведомлять о болезни через бота

✅ ПОСЕЩЕНИЕ:
• Приходить строго по расписанию или по записи
• Отмечать болезнь в боте обязательно
• За 10 занятий бот присылает напоминание об оплате

❌ ОТМЕНА ЗАНЯТИЙ:
• Отмена менее чем за 2 часа = занятие сгорает
• При отсутствии без предупреждения = занятие засчитывается

📱 ИСПОЛЬЗОВАНИЕ БОТА:
• /payment - отправить оплату
• /sick - отметить болезнь  
• /profile - посмотреть статус
• Все действия требуют подтверждения администратора'''
}

def init_google_services():
    """Инициализация Google Services (адаптированная для Render.com)"""
    global sheets_client, drive_service, users_sheet, payments_sheet, attendance_sheet, settings_sheet
    
    # Инициализируем переменные как None
    sheets_client = None
    drive_service = None
    users_sheet = None
    payments_sheet = None
    attendance_sheet = None
    settings_sheet = None
    
    try:
        print("🔄 Инициализация Google Services...")
        
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/drive.file'
        ]
        
        # Получаем credentials - поддержка и Render, и локальной разработки
        creds = None
        
        if GOOGLE_CREDENTIALS_JSON:
            print("🔑 Используем credentials из переменной окружения (Render.com)...")
            try:
                creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
                creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
                print("✅ JSON credentials успешно загружены")
            except json.JSONDecodeError as e:
                print(f"❌ Ошибка парсинга JSON credentials: {e}")
                return False
            except Exception as e:
                print(f"❌ Ошибка создания credentials из JSON: {e}")
                return False
                
        elif GOOGLE_CREDENTIALS_FILE and os.path.exists(GOOGLE_CREDENTIALS_FILE):
            print("🔑 Используем credentials из файла (локальная разработка)...")
            try:
                creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=scope)
                print("✅ Файл credentials успешно загружен")
            except Exception as e:
                print(f"❌ Ошибка загрузки файла credentials: {e}")
                return False
        else:
            print("❌ Google credentials не найдены!")
            print("💡 Для Render.com: установите переменную GOOGLE_CREDENTIALS_JSON")
            print("💡 Для локальной разработки: установите GOOGLE_CREDENTIALS_FILE в .env")
            return False
        
        if not creds:
            print("❌ Не удалось создать credentials")
            return False
        
        # Инициализация Sheets
        print("📊 Подключение к Google Sheets...")
        sheets_client = gspread.authorize(creds)
        
        # Инициализация Drive
        print("☁️ Подключение к Google Drive...")
        drive_service = build('drive', 'v3', credentials=creds)
        
        if not SPREADSHEET_ID:
            print("❌ SPREADSHEET_ID не указан в переменных окружения!")
            return False
            
        print(f"📋 Открытие таблицы ID: {SPREADSHEET_ID}")
        spreadsheet = sheets_client.open_by_key(SPREADSHEET_ID)
        
        # Получаем или создаем листы
        try:
            users_sheet = spreadsheet.worksheet("Пользователи")
            print("✅ Лист 'Пользователи' найден")
        except gspread.WorksheetNotFound:
            users_sheet = spreadsheet.add_worksheet(title="Пользователи", rows="1000", cols="15")
            users_sheet.append_row([
                "telegram_id", "username", "name", "phone", "schedule", 
                "registration_date", "total_sessions", "current_sessions", 
                "last_payment_date", "last_payment_amount", "next_payment_due", 
                "status", "notes"
            ])
            print("✅ Лист 'Пользователи' создан")
        
        try:
            payments_sheet = spreadsheet.worksheet("История_платежей")
            print("✅ Лист 'История_платежей' найден")
        except gspread.WorksheetNotFound:
            payments_sheet = spreadsheet.add_worksheet(title="История_платежей", rows="1000", cols="12")
            payments_sheet.append_row([
                "timestamp", "name", "telegram_id", "amount", "payment_type", "status", 
                "photo_file_id", "drive_photo_link", "confirmed_by", 
                "confirmation_date", "sessions_period", "notes"
            ])
            print("✅ Лист 'История_платежей' создан")
        
        try:
            attendance_sheet = spreadsheet.worksheet("Посещения")
            print("✅ Лист 'Посещения' найден")
        except gspread.WorksheetNotFound:
            attendance_sheet = spreadsheet.add_worksheet(title="Посещения", rows="1000", cols="10")
            attendance_sheet.append_row([
                "date", "name", "telegram_id", "status", "reason", 
                "session_number", "payment_period"
            ])
            print("✅ Лист 'Посещения' создан")
        
        try:
            settings_sheet = spreadsheet.worksheet("Настройки")
            print("✅ Лист 'Настройки' найден")
        except gspread.WorksheetNotFound:
            settings_sheet = spreadsheet.add_worksheet(title="Настройки", rows="20", cols="3")
            settings_sheet.append_row(["parameter", "value", "description"])
            for key, value in DEFAULT_SETTINGS.items():
                settings_sheet.append_row([key, value, ""])
            print("✅ Лист 'Настройки' создан с значениями по умолчанию")
        
        # Тестируем доступ
        print("🧪 Тестирование доступа...")
        test_users = users_sheet.get_all_values()
        print(f"✅ Тест успешен! Найдено строк в таблице: {len(test_users)}")
        
        print("🎉 Google Services успешно инициализированы!")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка инициализации Google Services: {e}")
        print(f"🔍 Тип ошибки: {type(e).__name__}")
        
        if "PERMISSION_DENIED" in str(e):
            print("❌ Ошибка доступа! Проверьте:")
            print("   1. Правильность ID таблицы")
            print("   2. Что таблица расшарена для сервисного аккаунта")
            print("   3. Что включены Google Sheets и Drive API")
        elif "INVALID_ARGUMENT" in str(e):
            print("❌ Неверные аргументы! Проверьте:")
            print("   1. Корректность JSON credentials")
            print("   2. Что JSON не поврежден")
        
        return False

class SettingsManager:
    @staticmethod
    def get_setting(key, default_value=None):
        """Получить настройку"""
        try:
            if settings_sheet is None:
                print(f"❌ settings_sheet не инициализирован, возвращаем {key}={default_value}")
                return default_value
                
            settings = settings_sheet.get_all_records()
            for setting in settings:
                if setting.get('parameter') == key:
                    value = setting.get('value')
                    if key in ['min_payment', 'max_payment', 'monthly_price', 'sessions_per_month', 'free_days_limit', 'sick_days_limit']:
                        return int(value)
                    return str(value)
            return default_value
        except Exception as e:
            print(f"Ошибка получения настройки {key}: {e}, возвращаем default: {default_value}")
            return default_value
    
    @staticmethod
    def update_setting(key, value):
        """Обновить настройку"""
        try:
            if settings_sheet is None:
                print(f"❌ settings_sheet не инициализирован")
                return False
                
            settings = settings_sheet.get_all_values()
            for i, row in enumerate(settings[1:], start=2):
                if len(row) >= 2 and row[0] == key:
                    settings_sheet.update_cell(i, 2, value)
                    print(f"Настройка {key} обновлена на {value}")
                    return True
            
            settings_sheet.append_row([key, value, ""])
            print(f"Добавлена новая настройка {key}: {value}")
            return True
            
        except Exception as e:
            print(f"Ошибка обновления настройки {key}: {e}")
            return False

class UserManager:
    @staticmethod
    def get_user(telegram_id):
        """Получить пользователя из Google Sheets"""
        try:
            if users_sheet is None:
                print("❌ users_sheet не инициализирован")
                if str(telegram_id) == str(ADMIN_ID):
                    return {
                        'telegram_id': telegram_id,
                        'username': 'admin',
                        'name': 'Администратор',
                        'phone': '',
                        'schedule': '',
                        'status': 'active'
                    }
                return None
                
            users = users_sheet.get_all_records()
            for user in users:
                if str(user.get('telegram_id')) == str(telegram_id):
                    return user
            return None
        except Exception as e:
            print(f"Ошибка получения пользователя: {e}")
            if str(telegram_id) == str(ADMIN_ID):
                return {
                    'telegram_id': telegram_id,
                    'username': 'admin',
                    'name': 'Администратор',
                    'phone': '',
                    'schedule': '',
                    'status': 'active'
                }
            return None

    @staticmethod
    def add_user(telegram_id, username, name, phone, schedule):
        """Добавить пользователя в Google Sheets"""
        try:
            if users_sheet is None:
                print("❌ users_sheet не инициализирован")
                return False
                
            row = [
                telegram_id, username, name, phone, schedule, 
                datetime.now().strftime("%Y-%m-%d"),
                0, 0, "", "", "", "active", ""
            ]
            users_sheet.append_row(row)
            print(f"Пользователь добавлен в Google Sheets: {name}")
            return True
        except Exception as e:
            print(f"Ошибка добавления пользователя: {e}")
            return False
    
    @staticmethod
    def get_user_sessions_count(telegram_id):
        """Подсчитать занятия пользователя"""
        try:
            if attendance_sheet is None:
                return 0
                
            attendance_records = attendance_sheet.get_all_records()
            user = UserManager.get_user(telegram_id)
            
            if not user:
                return 0
                
            last_payment_date = user.get('last_payment_date', '')
            
            if not last_payment_date:
                count = sum(
                    1 for record in attendance_records
                    if str(record.get('telegram_id')) == str(telegram_id) and 
                       record.get('status') == 'attended'
                )
            else:
                count = sum(
                    1 for record in attendance_records
                    if str(record.get('telegram_id')) == str(telegram_id) and 
                       record.get('status') == 'attended' and
                       record.get('date', '') > last_payment_date
                )
            
            return count
        except Exception as e:
            print(f"Ошибка подсчета занятий: {e}")
            return 0

# Создаем главное меню с кнопками
def get_main_menu():
    """Главное меню с кнопками"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💳 Отправить платеж")],
            [KeyboardButton(text="📋 Мой профиль"), KeyboardButton(text="🤒 Отметить болезнь")],
            [KeyboardButton(text="❌ Покинуть программу"), KeyboardButton(text="ℹ️ Помощь")],
            [KeyboardButton(text="🏠 Главное меню")]
        ],
        resize_keyboard=True,
        persistent=True
    )
    return keyboard

# Админское меню
def get_admin_menu():
    """Админское меню с настройками"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚙️ Настройки бота")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📝 Правила")],
            [KeyboardButton(text="✏️ Изменить правила")],
            [KeyboardButton(text="🏠 Главное меню")]
        ],
        resize_keyboard=True,
        persistent=True
    )
    return keyboard

async def save_payment_to_sheets(telegram_id, amount, payment_type="transfer", status="pending", photo_file_id=None):
    """Сохранить платеж в Google Sheets"""
    try:
        if users_sheet is None or payments_sheet is None:
            print("❌ Google Sheets не инициализированы")
            return False
            
        user = UserManager.get_user(telegram_id)
        if not user:
            print(f"❌ Пользователь {telegram_id} не найден")
            return False
        
        current_sessions = UserManager.get_user_sessions_count(telegram_id)
        
        payment_row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user['name'],
            telegram_id,
            amount or "Не указано",
            payment_type,
            status,
            photo_file_id or "",
            f"drive_link_{datetime.now().strftime('%Y%m%d_%H%M%S')}" if photo_file_id else "",
            "",
            "",
            current_sessions,
            ""
        ]
        payments_sheet.append_row(payment_row)
        
        print(f"Платеж сохранен в Google Sheets для {user['name']}")
        return True
        
    except Exception as e:
        print(f"Ошибка сохранения платежа: {e}")
        return False

async def update_payment_status(user_id: int, amount: float, new_status: str, admin_id: int):
    """Обновить статус платежа в Google Sheets"""
    try:
        if payments_sheet is None:
            print("❌ payments_sheet не инициализирован")
            return False
        
        # Находим последний платеж пользователя с указанной суммой
        payments = payments_sheet.get_all_records()
        
        for i, payment in enumerate(reversed(payments), 1):
            if (str(payment.get('telegram_id')) == str(user_id) and 
                float(payment.get('amount', 0)) == amount and 
                payment.get('status') == 'pending'):
                
                row_index = len(payments) - i + 2  # +2 для заголовка и индексации с 1
                
                # Обновляем статус и данные подтверждения
                payments_sheet.update_cell(row_index, 6, new_status)  # Колонка status
                payments_sheet.update_cell(row_index, 9, admin_id)    # Колонка confirmed_by
                payments_sheet.update_cell(row_index, 10, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))  # confirmation_date
                
                print(f"Статус платежа обновлен: {new_status} для пользователя {user_id}")
                return True
        
        print(f"Платеж не найден для пользователя {user_id} на сумму {amount}")
        return False
        
    except Exception as e:
        print(f"Ошибка обновления статуса платежа: {e}")
        return False

async def send_payment_confirmation_to_admin(user_id: int, amount: float, photo_file_id: str = None):
    """Отправить админу уведомление о платеже с кнопками подтверждения"""
    try:
        user = UserManager.get_user(user_id)
        if not user:
            print(f"Пользователь {user_id} не найден")
            return
        
        payment_type = "💳 Перевод" if photo_file_id else "💵 Наличные"
        
        # Создаем кнопки для подтверждения/отклонения
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить", 
                    callback_data=f"confirm_payment_{user_id}_{amount}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", 
                    callback_data=f"reject_payment_{user_id}_{amount}"
                )
            ]
        ])
        
        message_text = (
            f"💳 **НОВЫЙ ПЛАТЕЖ**\n\n"
            f"👤 **Клиент:** {user['name']}\n"
            f"💰 **Сумма:** {amount} сом\n"
            f"💳 **Тип:** {payment_type}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"📅 **Время:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"❓ **Подтвердить платеж?**"
        )
        
        # Отправляем уведомление
        if photo_file_id:
            # Если есть скриншот - отправляем с фото
            await bot.send_photo(
                ADMIN_ID,
                photo=photo_file_id,
                caption=message_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            # Если наличные - просто текст
            await bot.send_message(
                ADMIN_ID,
                message_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        
    except Exception as e:
        print(f"Ошибка отправки уведомления админу: {e}")

async def save_and_notify_cash_payment(user_id: int, amount: float, state: FSMContext):
    """Сохранить наличную оплату и уведомить админа"""
    try:
        success = await save_payment_to_sheets(
            telegram_id=user_id,
            amount=amount,
            payment_type="cash",
            status="pending"
        )
        
        if success:
            await bot.send_message(
                user_id,
                f"✅ **Наличная оплата зарегистрирована!**\n\n"
                f"💰 Сумма: **{amount} сом**\n"
                f"💵 Тип: Наличные\n"
                f"⏳ Ожидайте подтверждения администратора",
                parse_mode="Markdown"
            )
            
            # Уведомление админу
            await send_payment_confirmation_to_admin(user_id, amount)
        else:
            await bot.send_message(user_id, "❌ Ошибка при сохранении платежа. Попробуйте еще раз.")
        
        await state.clear()
        
    except Exception as e:
        print(f"Ошибка сохранения наличной оплаты: {e}")

async def notify_admin_on_error(error_text: str):
    """Уведомить админа об ошибке"""
    try:
        clean_error = str(error_text).replace('*', '').replace('_', '').replace('`', '')[:1000]
        await bot.send_message(ADMIN_ID, f"⚠️ ОШИБКА В БОТЕ:\n\n{clean_error}")
    except Exception as e:
        print(f"Ошибка отправки уведомления админу: {e}")

# Настройка команд бота
async def set_bot_commands():
    """Устанавливаем команды бота"""
    commands = [
        BotCommand(command="start", description="🚀 Начать работу с ботом"),
        BotCommand(command="menu", description="🏠 Главное меню"),
        BotCommand(command="payment", description="💳 Отправить платеж"),
        BotCommand(command="profile", description="📋 Посмотреть профиль"),
        BotCommand(command="sick", description="🤒 Отметить болезнь"),
        BotCommand(command="quit", description="❌ Покинуть программу"),
        BotCommand(command="rules", description="📝 Правила зала"),
        BotCommand(command="help", description="ℹ️ Получить помощь"),
        BotCommand(command="edit_prices", description="💰 Изменить цены (админ)"),
        BotCommand(command="edit_limits", description="⏰ Изменить лимиты (админ)")
    ]
    await bot.set_my_commands(commands)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    
    print(f"🔍 Команда /start от пользователя {username} (ID: {user_id})")
    
    try:
        if users_sheet is None:
            print(f"⚠️ Google Sheets не инициализированы, работаем в упрощенном режиме")
            
            if user_id == ADMIN_ID:
                await message.answer(
                    f"👨‍💼 Добро пожаловать, Администратор!\n\n"
                    f"⚠️ Работаем в упрощенном режиме (без Google Sheets)\n"
                    f"🔧 Проверьте подключение к Google Sheets\n\n"
                    f"Доступные команды:\n"
                    f"/help - справка"
                )
            else:
                await message.answer(
                    f"👋 Привет! Бот временно работает в упрощенном режиме.\n\n"
                    f"Обратитесь к администратору."
                )
            return
            
        user = UserManager.get_user(user_id)
        print(f"🔍 Пользователь найден: {user is not None}")
        
        if user:
            if user_id == ADMIN_ID:
                print(f"🔍 Администратор входит в систему")
                await message.answer(
                    f"👨‍💼 Добро пожаловать, Администратор!\n\n"
                    "Выберите действие:",
                    reply_markup=get_admin_menu()
                )
            else:
                print(f"🔍 Обычный пользователь: {user.get('name', 'Без имени')}")
                await message.answer(
                    f"Привет, {user['name']}! 👋\n\n"
                    "Выберите действие из меню ниже:",
                    reply_markup=get_main_menu()
                )
        else:
            print(f"🔍 Новый пользователь, начинаем регистрацию")
            await message.answer(
                "🎉 Добро пожаловать в фитнес-бот! 🏋️‍♀️\n\n"
                "Для начала работы нужно пройти быструю регистрацию.\n\n"
                "👤 Как вас зовут? (ФИО)"
            )
            await state.set_state(RegistrationStates.waiting_for_name)
            
    except Exception as e:
        print(f"❌ Ошибка в cmd_start: {e}")
        
        if user_id == ADMIN_ID:
            await message.answer(
                f"❌ Ошибка в боте: {str(e)[:200]}\n\n"
                f"🔧 Проверьте Google Sheets подключение"
            )
        else:
            await message.answer("❌ Произошла ошибка. Обратитесь к администратору.")

@router.message(Command("help"))
async def cmd_help(message: Message):
    print(f"🔍 Команда /help от пользователя {message.from_user.id}")
    
    if message.from_user.id == ADMIN_ID:
        help_text = (
            "👨‍💼 АДМИН-СПРАВКА\n\n"
            "Управление ботом:\n"
            "⚙️ /edit_prices - изменить цены\n"
            "⏰ /edit_limits - изменить лимиты\n"
            "📊 Статистика - просмотр данных\n"
            "📝 Правила - текущие правила зала\n\n"
            "Подтверждение платежей:\n"
            "• Все платежи требуют вашего подтверждения\n"
            "• Уведомления приходят автоматически"
        )
    else:
        monthly_price = SettingsManager.get_setting('monthly_price', DEFAULT_SETTINGS['monthly_price'])
        sessions_count = SettingsManager.get_setting('sessions_per_month', DEFAULT_SETTINGS['sessions_per_month'])
        min_payment = SettingsManager.get_setting('min_payment', DEFAULT_SETTINGS['min_payment'])
        
        help_text = (
            "🤖 Справка по работе с ботом\n\n"
            "Удобное управление:\n"
            "• Используйте кнопки меню внизу экрана\n"
            "• Или вводите команды вручную (начинающиеся с /)\n\n"
            "Основные команды:\n"
            "💳 /payment - Отправить платеж\n"
            "🤒 /sick - Отметить болезнь\n"
            "❌ /quit - Покинуть программу\n"
            "📋 /profile - Мой профиль\n"
            "ℹ️ /help - Помощь\n\n"
            f"Важная информация:\n"
            f"• Месячный абонемент: {monthly_price} сом за {sessions_count} занятий\n"
            f"• Минимальная сумма оплаты: {min_payment} сом\n"
            "• Все платежи требуют подтверждения админа"
        )
    
    await message.answer(help_text)

@router.message(Command("payment"))
async def cmd_payment(message: Message, state: FSMContext):
    print(f"🔍 Команда /payment от пользователя {message.from_user.id}")
    
    user_id = message.from_user.id
    user = UserManager.get_user(user_id)
    
    if not user:
        await message.answer("❌ Сначала пройдите регистрацию командой /start")
        return
    
    monthly_price = SettingsManager.get_setting('monthly_price', DEFAULT_SETTINGS['monthly_price'])
    sessions_count = SettingsManager.get_setting('sessions_per_month', DEFAULT_SETTINGS['sessions_per_month'])
    
    message_text = f"💳 Оплата занятий\n\n"
    message_text += f"💡 Месячный абонемент: {monthly_price} сом за {sessions_count} занятий\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перевод по карте", callback_data="payment_transfer")],
        [InlineKeyboardButton(text="💵 Оплатил наличными", callback_data="payment_cash")]
    ])
    
    await message.answer(message_text, reply_markup=keyboard)

@router.message(Command("profile"))
async def cmd_profile(message: Message):
    """Команда /profile - показать профиль пользователя"""
    print(f"🔍 Команда /profile от пользователя {message.from_user.id}")
    
    user_id = message.from_user.id
    user = UserManager.get_user(user_id)
    
    if not user:
        await message.answer("❌ Сначала пройдите регистрацию командой /start")
        return
    
    sessions_count = UserManager.get_user_sessions_count(user_id)
    sessions_per_month = SettingsManager.get_setting('sessions_per_month', DEFAULT_SETTINGS['sessions_per_month'])
    sessions_left = max(0, sessions_per_month - sessions_count)
    monthly_price = SettingsManager.get_setting('monthly_price', DEFAULT_SETTINGS['monthly_price'])
    
    profile_text = (
        f"📋 Ваш профиль\n\n"
        f"👤 Имя: {user.get('name', 'Не указано')}\n"
        f"📱 Телефон: {user.get('phone', 'Не указан')}\n"
        f"📅 График: {user.get('schedule', 'Не указан')}\n\n"
        f"🏋️ Посещения:\n"
        f"• Посещено занятий: {sessions_count}\n"
        f"• Осталось занятий: {sessions_left}\n\n"
        f"💳 Последняя оплата:\n"
        f"• Сумма: {user.get('last_payment_amount', 'Нет данных')} сом\n"
        f"• Дата: {user.get('last_payment_date', 'Нет данных')}\n"
        f"• Статус: {user.get('status', 'active')}\n"
        f"\n💡 Текущая стоимость: {monthly_price} сом за {sessions_per_month} занятий"
    )
    
    await message.answer(profile_text)

@router.message(Command("sick"))
async def cmd_sick(message: Message):
    """Команда /sick - отметить болезнь"""
    print(f"🔍 Команда /sick от пользователя {message.from_user.id}")
    
    user_id = message.from_user.id
    user = UserManager.get_user(user_id)
    
    if not user:
        await message.answer("❌ Сначала пройдите регистрацию командой /start")
        return
    
    if attendance_sheet is None:
        await message.answer("❌ Функция временно недоступна (нет подключения к Google Sheets)")
        return
    
    # Записываем в лист посещений
    today = datetime.now().strftime("%Y-%m-%d")
    attendance_row = [
        today,
        user['name'],
        user_id,
        'sick',
        'Пользователь отметил болезнь',
        '',
        ''
    ]
    
    try:
        attendance_sheet.append_row(attendance_row)
        
        await message.answer(
            f"🤒 Болезнь отмечена на {today}.\n"
            f"Выздоравливайте! 💊\n\n"
            f"Администратор уведомлен."
        )
        
        # Уведомление админу
        await bot.send_message(
            ADMIN_ID,
            f"🤒 {user['name']} отметил болезнь\n"
            f"📅 Дата: {today}\n"
            f"👤 ID: {user_id}"
        )
        
    except Exception as e:
        print(f"Ошибка записи болезни: {e}")
        await message.answer("❌ Ошибка при записи. Попробуйте еще раз.")

@router.message(Command("quit"))
async def cmd_quit(message: Message):
    """Команда /quit - покинуть программу"""
    print(f"🔍 Команда /quit от пользователя {message.from_user.id}")
    
    user_id = message.from_user.id
    user = UserManager.get_user(user_id)
    
    if not user:
        await message.answer("❌ Сначала пройдите регистрацию командой /start")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, больше не буду ходить", callback_data="confirm_quit")],
        [InlineKeyboardButton(text="❌ Нет, остаюсь", callback_data="cancel_quit")]
    ])
    
    await message.answer(
        f"❓ Вы уверены, что больше не будете ходить на тренировки?\n\n"
        f"Ваш статус изменится на 'неактивный'.",
        reply_markup=keyboard
    )

@router.message(Command("rules"))
async def cmd_rules(message: Message):
    """Команда /rules - показать правила"""
    print(f"🔍 Команда /rules от пользователя {message.from_user.id}")
    
    # Получаем правила из настроек Google Sheets
    rules_text = SettingsManager.get_setting('gym_rules', DEFAULT_SETTINGS['gym_rules'])
    
    # Если правила из настроек пустые, используем шаблон с актуальными настройками
    if not rules_text or rules_text == DEFAULT_SETTINGS['gym_rules']:
        min_payment = SettingsManager.get_setting('min_payment', DEFAULT_SETTINGS['min_payment'])
        max_payment = SettingsManager.get_setting('max_payment', DEFAULT_SETTINGS['max_payment'])
        monthly_price = SettingsManager.get_setting('monthly_price', DEFAULT_SETTINGS['monthly_price'])
        sessions_count = SettingsManager.get_setting('sessions_per_month', DEFAULT_SETTINGS['sessions_per_month'])
        free_days = SettingsManager.get_setting('free_days_limit', DEFAULT_SETTINGS['free_days_limit'])
        sick_days = SettingsManager.get_setting('sick_days_limit', DEFAULT_SETTINGS['sick_days_limit'])
        gym_schedule = SettingsManager.get_setting('gym_schedule', DEFAULT_SETTINGS['gym_schedule'])
        
        rules_text = f"""📋 ПРАВИЛА ФИТНЕС-ЗАЛА

💰 ОПЛАТА:
• Месячный абонемент: {monthly_price} сом за {sessions_count} занятий
• Минимальная сумма: {min_payment} сом
• Максимальная сумма: {max_payment} сом
• Оплата: переводом (со скриншотом) или наличными

⏰ ГРАФИК РАБОТЫ:
{gym_schedule}

❄️ ЗАМОРОЗКА АБОНЕМЕНТА:
• Без причины: до {free_days} занятий подряд
• По болезни: до {sick_days} занятий подряд (с отметкой в боте)
• Заморозка не переносится на следующий период
• Обязательно уведомлять о болезни через бота

✅ ПОСЕЩЕНИЕ:
• Приходить строго по расписанию или по записи
• Отмечать болезнь в боте обязательно
• За {sessions_count} занятий бот присылает напоминание об оплате

❌ ОТМЕНА ЗАНЯТИЙ:
• Отмена менее чем за 2 часа = занятие сгорает
• При отсутствии без предупреждения = занятие засчитывается

📱 ИСПОЛЬЗОВАНИЕ БОТА:
• /payment - отправить оплату
• /sick - отметить болезнь  
• /profile - посмотреть статус
• Все действия требуют подтверждения администратора"""
    
    await message.answer(rules_text)

@router.message(Command("edit_prices"))
async def cmd_edit_prices(message: Message):
    """Команда /edit_prices - изменить цены (только админ)"""
    print(f"🔍 Команда /edit_prices от пользователя {message.from_user.id}")
    
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступно только администратору")
        return
    
    min_payment = SettingsManager.get_setting('min_payment', DEFAULT_SETTINGS['min_payment'])
    max_payment = SettingsManager.get_setting('max_payment', DEFAULT_SETTINGS['max_payment'])
    monthly_price = SettingsManager.get_setting('monthly_price', DEFAULT_SETTINGS['monthly_price'])
    sessions_count = SettingsManager.get_setting('sessions_per_month', DEFAULT_SETTINGS['sessions_per_month'])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💰 Цена абонемента: {monthly_price} сом", callback_data="edit_monthly_price")],
        [InlineKeyboardButton(text=f"📉 Минимум: {min_payment} сом", callback_data="edit_min_payment")],
        [InlineKeyboardButton(text=f"📈 Максимум: {max_payment} сом", callback_data="edit_max_payment")],
        [InlineKeyboardButton(text=f"🏋️ Занятий в абонементе: {sessions_count}", callback_data="edit_sessions_count")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_settings")]
    ])
    
    await message.answer(
        "💰 Настройки цен и платежей\n\n"
        "Выберите параметр для изменения:",
        reply_markup=keyboard
    )

@router.message(Command("edit_limits"))
async def cmd_edit_limits(message: Message):
    """Команда /edit_limits - изменить лимиты (только админ)"""
    print(f"🔍 Команда /edit_limits от пользователя {message.from_user.id}")
    
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступно только администратору")
        return
    
    free_days = SettingsManager.get_setting('free_days_limit', DEFAULT_SETTINGS['free_days_limit'])
    sick_days = SettingsManager.get_setting('sick_days_limit', DEFAULT_SETTINGS['sick_days_limit'])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❄️ Дней заморозки: {free_days}", callback_data="edit_free_days")],
        [InlineKeyboardButton(text=f"🤒 Дней по болезни: {sick_days}", callback_data="edit_sick_days")],
        [InlineKeyboardButton(text="📅 Изменить расписание", callback_data="edit_schedule")],
        [InlineKeyboardButton(text="✏️ Изменить правила", callback_data="edit_rules")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_settings")]
    ])
    
    await message.answer(
        "⏰ Настройки лимитов и контента\n\n"
        "Выберите параметр для изменения:",
        reply_markup=keyboard
    )

# Обработчики callback для настроек
@router.callback_query(F.data.startswith("edit_"))
async def handle_edit_settings(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования настроек"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступно только администратору")
        return
    
    setting_type = callback.data.replace("edit_", "")
    
    settings_map = {
        "monthly_price": ("💰 Введите новую цену абонемента (сом):", AdminStates.editing_monthly_price),
        "min_payment": ("📉 Введите новую минимальную сумму (сом):", AdminStates.editing_min_amount),
        "max_payment": ("📈 Введите новую максимальную сумму (сом):", AdminStates.editing_max_amount),
        "sessions_count": ("🏋️ Введите количество занятий в абонементе:", AdminStates.editing_sessions_count),
        "free_days": ("❄️ Введите количество дней заморозки:", AdminStates.editing_free_days),
        "sick_days": ("🤒 Введите количество дней по болезни:", AdminStates.editing_sick_days),
        "schedule": ("📅 Введите новое расписание зала:", AdminStates.editing_schedule_text),
        "rules": ("✏️ Введите новые правила зала:", AdminStates.editing_rules_text)
    }
    
    if setting_type in settings_map:
        message_text, state_to_set = settings_map[setting_type]
        await callback.message.answer(message_text)
        await state.update_data(editing_setting=setting_type)
        await state.set_state(state_to_set)
    
    await callback.answer()

# Обработчики состояний для редактирования настроек
@router.message(AdminStates.editing_monthly_price)
async def process_monthly_price(message: Message, state: FSMContext):
    """Обработка изменения цены абонемента"""
    try:
        new_price = int(message.text.strip())
        if new_price <= 0:
            await message.answer("❌ Цена должна быть больше 0")
            return
        
        if SettingsManager.update_setting('monthly_price', new_price):
            await message.answer(f"✅ Цена абонемента изменена на {new_price} сом")
        else:
            await message.answer("❌ Ошибка при сохранении настройки")
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число")

@router.message(AdminStates.editing_min_amount)
async def process_min_amount(message: Message, state: FSMContext):
    """Обработка изменения минимальной суммы"""
    try:
        new_amount = int(message.text.strip())
        if new_amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0")
            return
        
        if SettingsManager.update_setting('min_payment', new_amount):
            await message.answer(f"✅ Минимальная сумма изменена на {new_amount} сом")
        else:
            await message.answer("❌ Ошибка при сохранении настройки")
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число")

@router.message(AdminStates.editing_max_amount)
async def process_max_amount(message: Message, state: FSMContext):
    """Обработка изменения максимальной суммы"""
    try:
        new_amount = int(message.text.strip())
        if new_amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0")
            return
        
        if SettingsManager.update_setting('max_payment', new_amount):
            await message.answer(f"✅ Максимальная сумма изменена на {new_amount} сом")
        else:
            await message.answer("❌ Ошибка при сохранении настройки")
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число")

@router.message(AdminStates.editing_sessions_count)
async def process_sessions_count(message: Message, state: FSMContext):
    """Обработка изменения количества занятий"""
    try:
        new_count = int(message.text.strip())
        if new_count <= 0:
            await message.answer("❌ Количество занятий должно быть больше 0")
            return
        
        if SettingsManager.update_setting('sessions_per_month', new_count):
            await message.answer(f"✅ Количество занятий в абонементе изменено на {new_count}")
        else:
            await message.answer("❌ Ошибка при сохранении настройки")
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число")

@router.message(AdminStates.editing_free_days)
async def process_free_days(message: Message, state: FSMContext):
    """Обработка изменения дней заморозки"""
    try:
        new_days = int(message.text.strip())
        if new_days < 0:
            await message.answer("❌ Количество дней не может быть отрицательным")
            return
        
        if SettingsManager.update_setting('free_days_limit', new_days):
            await message.answer(f"✅ Дней заморозки изменено на {new_days}")
        else:
            await message.answer("❌ Ошибка при сохранении настройки")
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число")

@router.message(AdminStates.editing_sick_days)
async def process_sick_days(message: Message, state: FSMContext):
    """Обработка изменения дней по болезни"""
    try:
        new_days = int(message.text.strip())
        if new_days < 0:
            await message.answer("❌ Количество дней не может быть отрицательным")
            return
        
        if SettingsManager.update_setting('sick_days_limit', new_days):
            await message.answer(f"✅ Дней по болезни изменено на {new_days}")
        else:
            await message.answer("❌ Ошибка при сохранении настройки")
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число")

@router.message(AdminStates.editing_schedule_text)
async def process_schedule_text(message: Message, state: FSMContext):
    """Обработка изменения расписания"""
    new_schedule = message.text.strip()
    if not new_schedule:
        await message.answer("❌ Расписание не может быть пустым")
        return
    
    if SettingsManager.update_setting('gym_schedule', new_schedule):
        await message.answer(f"✅ Расписание зала изменено:\n\n{new_schedule}")
    else:
        await message.answer("❌ Ошибка при сохранении настройки")
    
    await state.clear()

@router.message(AdminStates.editing_rules_text)
async def process_rules_text(message: Message, state: FSMContext):
    """Обработка изменения правил зала"""
    new_rules = message.text.strip()
    if not new_rules:
        await message.answer("❌ Правила не могут быть пустыми")
        return
    
    if len(new_rules) > 4000:
        await message.answer("❌ Текст правил слишком длинный (максимум 4000 символов)")
        return
    
    if SettingsManager.update_setting('gym_rules', new_rules):
        await message.answer(
            f"✅ **Правила зала успешно обновлены!**\n\n"
            f"📝 Новые правила:\n\n{new_rules}",
            parse_mode="Markdown"
        )
        
        # Уведомляем, что правила обновлены
        print(f"✅ Правила зала обновлены администратором {message.from_user.id}")
    else:
        await message.answer("❌ Ошибка при сохранении правил")
    
    await state.clear()

# Обработчики кнопок меню
@router.message(F.text == "💳 Отправить платеж")
async def menu_payment(message: Message, state: FSMContext):
    await cmd_payment(message, state)

@router.message(F.text == "📋 Мой профиль")
async def menu_profile(message: Message):
    await cmd_profile(message)

@router.message(F.text == "🤒 Отметить болезнь")
async def menu_sick(message: Message):
    await cmd_sick(message)

@router.message(F.text == "❌ Покинуть программу")
async def menu_quit(message: Message):
    await cmd_quit(message)

@router.message(F.text == "ℹ️ Помощь")
async def menu_help(message: Message):
    await cmd_help(message)

# Админские обработчики кнопок
@router.message(F.text == "⚙️ Настройки бота")
async def admin_settings(message: Message):
    """Админские настройки"""
    if message.from_user.id != ADMIN_ID:
        return
    
    min_payment = SettingsManager.get_setting('min_payment', DEFAULT_SETTINGS['min_payment'])
    max_payment = SettingsManager.get_setting('max_payment', DEFAULT_SETTINGS['max_payment'])
    monthly_price = SettingsManager.get_setting('monthly_price', DEFAULT_SETTINGS['monthly_price'])
    sessions_count = SettingsManager.get_setting('sessions_per_month', DEFAULT_SETTINGS['sessions_per_month'])
    free_days = SettingsManager.get_setting('free_days_limit', DEFAULT_SETTINGS['free_days_limit'])
    sick_days = SettingsManager.get_setting('sick_days_limit', DEFAULT_SETTINGS['sick_days_limit'])
    
    settings_text = f"""⚙️ ТЕКУЩИЕ НАСТРОЙКИ

💰 Оплата:
• Минимум: {min_payment} сом
• Максимум: {max_payment} сом
• Цена абонемента: {monthly_price} сом
• Занятий в абонементе: {sessions_count}

❄️ Заморозка:
• Дней без причины: {free_days}
• Дней по болезни: {sick_days}

🔧 Для изменения настроек используйте команды:
/edit_prices - изменить цены
/edit_limits - изменить лимиты"""
    
    await message.answer(settings_text)

@router.message(F.text == "📝 Правила")
async def admin_rules(message: Message):
    """Показать правила"""
    await cmd_rules(message)

@router.message(F.text == "✏️ Изменить правила")
async def admin_edit_rules(message: Message, state: FSMContext):
    """Изменить правила зала (только админ)"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступно только администратору")
        return
    
    # Получаем текущие правила
    current_rules = SettingsManager.get_setting('gym_rules', DEFAULT_SETTINGS['gym_rules'])
    
    await message.answer(
        f"✏️ **РЕДАКТИРОВАНИЕ ПРАВИЛ ЗАЛА**\n\n"
        f"📝 Текущие правила:\n"
        f"```\n{current_rules[:500]}{'...' if len(current_rules) > 500 else ''}\n```\n\n"
        f"💬 Введите новый текст правил:\n"
        f"_(Можете использовать эмодзи, переносы строк и форматирование)_",
        parse_mode="Markdown"
    )
    
    await state.set_state(AdminStates.editing_rules_text)

@router.message(F.text == "📊 Статистика")
async def admin_stats(message: Message):
    """Показать статистику"""
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        if users_sheet is None or payments_sheet is None:
            await message.answer("❌ Статистика недоступна (нет подключения к Google Sheets)")
            return
            
        # Считаем статистику
        users = users_sheet.get_all_records()
        payments = payments_sheet.get_all_records()
        
        total_users = len(users)
        active_users = len([u for u in users if u.get('status') == 'active'])
        
        # Платежи за текущий месяц
        current_month = datetime.now().strftime("%Y-%m")
        monthly_payments = [p for p in payments if p.get('timestamp', '').startswith(current_month) and p.get('status') == 'confirmed']
        monthly_income = sum(float(p.get('amount', 0)) for p in monthly_payments if str(p.get('amount', '')).replace('.', '').isdigit())
        
        stats_text = f"""📊 СТАТИСТИКА

👥 Пользователи:
• Всего зарегистрировано: {total_users}
• Активных: {active_users}
• Неактивных: {total_users - active_users}

💰 Доходы за {current_month}:
• Подтвержденных платежей: {len(monthly_payments)}
• Общая сумма: {monthly_income:.0f} сом

📋 Ожидают подтверждения:
• Платежей: {len([p for p in payments if p.get('status') == 'pending'])}

🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
        await message.answer(stats_text)
        
    except Exception as e:
        print(f"Ошибка получения статистики: {e}")
        await message.answer("❌ Ошибка при получении статистики")

@router.message(F.text == "🏠 Главное меню")
async def menu_main(message: Message):
    user = UserManager.get_user(message.from_user.id)
    if user:
        if message.from_user.id == ADMIN_ID:
            await message.answer(
                f"👨‍💼 Админ-панель:",
                reply_markup=get_admin_menu()
            )
        else:
            await message.answer(
                f"🏠 Главное меню\n\nВыберите действие:",
                reply_markup=get_main_menu()
            )
    else:
        await message.answer("❌ Сначала пройдите регистрацию командой /start")

# НОВЫЕ ОБРАБОТЧИКИ ПЛАТЕЖЕЙ

@router.callback_query(F.data == "payment_transfer")
async def payment_transfer_selected(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора безналичной оплаты с QR кодом из репозитория"""
    try:
        # Отправляем QR код из файла репозитория
        if os.path.exists(QR_CODE_PATH):
            with open(QR_CODE_PATH, 'rb') as photo:
                await callback.message.answer_photo(
                    photo=photo,
                    caption=f"💳 **Безналичная оплата**\n\n"
                            f"📱 **По номеру телефона:**\n"
                            f"`{PAYMENT_PHONE}`\n\n"
                            f"📋 **Инструкция:**\n"
                            f"1️⃣ Отсканируйте QR код или переведите по номеру\n"
                            f"2️⃣ Укажите сумму перевода\n"
                            f"3️⃣ Пришлите скриншот чека\n\n"
                            f"💰 Введите сумму оплаты:",
                    parse_mode="Markdown"
                )
        else:
            # Если файл QR кода не найден
            await callback.message.answer(
                f"💳 **Безналичная оплата**\n\n"
                f"📱 **По номеру телефона:**\n"
                f"`{PAYMENT_PHONE}`\n\n"
                f"📋 **Инструкция:**\n"
                f"1️⃣ Переведите деньги по указанному номеру\n"
                f"2️⃣ Укажите сумму перевода\n"
                f"3️⃣ Пришлите скриншот чека\n\n"
                f"💰 Введите сумму оплаты:",
                parse_mode="Markdown"
            )
        
        await state.update_data(payment_type="transfer")
        await state.set_state(PaymentStates.waiting_for_amount)
        
    except Exception as e:
        print(f"Ошибка отправки QR кода: {e}")
        await callback.message.answer(
            f"💳 Безналичная оплата\n\n"
            f"📱 По номеру телефона: {PAYMENT_PHONE}\n\n"
            f"💰 Введите сумму оплаты:"
        )
        await state.update_data(payment_type="transfer")
        await state.set_state(PaymentStates.waiting_for_amount)
    
    await callback.answer()

@router.callback_query(F.data == "payment_cash")
async def payment_cash_selected(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("💰 Введите сумму, которую оплатили наличными (например: 8000):")
    await state.update_data(payment_type="cash")
    await state.set_state(PaymentStates.waiting_for_amount)
    await callback.answer()

@router.callback_query(F.data == "confirm_quit")
async def confirm_quit_callback(callback: CallbackQuery):
    """Подтверждение выхода из программы"""
    try:
        user_id = callback.from_user.id
        user = UserManager.get_user(user_id)
        
        if not user:
            await callback.message.answer("❌ Пользователь не найден")
            return
        
        # Здесь можно добавить логику изменения статуса пользователя
        await callback.message.answer(
            f"✅ Ваш статус изменен на 'неактивный'.\n\n"
            f"Если захотите вернуться, напишите /start\n"
            f"Спасибо, что были с нами! 👋"
        )
        
        # Уведомление админу
        await bot.send_message(
            ADMIN_ID,
            f"❌ {user['name']} покинул программу\n"
            f"👤 ID: {user_id}\n"
            f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
    except Exception as e:
        print(f"Ошибка подтверждения выхода: {e}")
        await callback.message.answer("❌ Ошибка. Попробуйте еще раз.")
    
    await callback.answer()

@router.callback_query(F.data == "cancel_quit")
async def cancel_quit_callback(callback: CallbackQuery):
    """Отмена выхода из программы"""
    await callback.message.answer(
        f"✅ Отлично! Остаемся в программе! 💪\n\n"
        f"Выберите действие:",
        reply_markup=get_main_menu()
    )
    await callback.answer()

@router.callback_query(F.data == "close_settings")
async def close_settings_callback(callback: CallbackQuery):
    """Закрыть настройки"""
    await callback.message.answer("⚙️ Настройки закрыты")
    await callback.answer()

# НОВЫЕ ОБРАБОТЧИКИ ПОДТВЕРЖДЕНИЯ ПЛАТЕЖЕЙ

@router.callback_query(F.data.startswith("confirm_payment_"))
async def confirm_payment_callback(callback: CallbackQuery):
    """Подтверждение платежа администратором"""
    try:
        # Парсим данные из callback_data
        parts = callback.data.split("_")
        user_id = int(parts[2])
        amount = float(parts[3])
        
        user = UserManager.get_user(user_id)
        if not user:
            await callback.answer("❌ Пользователь не найден")
            return
        
        # Обновляем статус платежа в Google Sheets
        success = await update_payment_status(user_id, amount, "confirmed", callback.from_user.id)
        
        if success:
            # Уведомляем клиента
            await bot.send_message(
                user_id,
                f"✅ **Ваш платеж подтвержден!**\n\n"
                f"💰 Сумма: **{amount} сом**\n"
                f"👨‍💼 Подтверждено администратором\n"
                f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"🎉 Спасибо за оплату!",
                parse_mode="Markdown"
            )
            
            # Обновляем сообщение админа
            await callback.message.edit_caption(
                caption=f"✅ **ПЛАТЕЖ ПОДТВЕРЖДЕН**\n\n"
                        f"👤 **Клиент:** {user['name']}\n"
                        f"💰 **Сумма:** {amount} сом\n"
                        f"🆔 **ID:** `{user_id}`\n"
                        f"📅 **Подтверждено:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="Markdown"
            )
            
            await callback.answer("✅ Платеж подтвержден!")
        else:
            await callback.answer("❌ Ошибка при обновлении статуса")
            
    except Exception as e:
        print(f"Ошибка подтверждения платежа: {e}")
        await callback.answer("❌ Ошибка при подтверждении")

@router.callback_query(F.data.startswith("reject_payment_"))
async def reject_payment_callback(callback: CallbackQuery):
    """Отклонение платежа администратором"""
    try:
        # Парсим данные из callback_data
        parts = callback.data.split("_")
        user_id = int(parts[2])
        amount = float(parts[3])
        
        user = UserManager.get_user(user_id)
        if not user:
            await callback.answer("❌ Пользователь не найден")
            return
        
        # Обновляем статус платежа в Google Sheets
        success = await update_payment_status(user_id, amount, "rejected", callback.from_user.id)
        
        if success:
            # Уведомляем клиента
            await bot.send_message(
                user_id,
                f"❌ **Ваш платеж отклонен**\n\n"
                f"💰 Сумма: **{amount} сом**\n"
                f"👨‍💼 Отклонено администратором\n"
                f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"📞 Свяжитесь с администратором для уточнения",
                parse_mode="Markdown"
            )
            
            # Обновляем сообщение админа
            await callback.message.edit_caption(
                caption=f"❌ **ПЛАТЕЖ ОТКЛОНЕН**\n\n"
                        f"👤 **Клиент:** {user['name']}\n"
                        f"💰 **Сумма:** {amount} сом\n"
                        f"🆔 **ID:** `{user_id}`\n"
                        f"📅 **Отклонено:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="Markdown"
            )
            
            await callback.answer("❌ Платеж отклонен!")
        else:
            await callback.answer("❌ Ошибка при обновлении статуса")
            
    except Exception as e:
        print(f"Ошибка отклонения платежа: {e}")
        await callback.answer("❌ Ошибка при отклонении")

# Обработчик состояний регистрации
@router.message(RegistrationStates.waiting_for_name)
async def process_registration_name(message: Message, state: FSMContext):
    """Обработка имени при регистрации"""
    name = message.text.strip()
    if not name or len(name) < 2:
        await message.answer("❌ Введите корректное имя (минимум 2 символа)")
        return
    
    await state.update_data(name=name)
    await message.answer(f"📱 Введите ваш номер телефона:")
    await state.set_state(RegistrationStates.waiting_for_phone)

@router.message(RegistrationStates.waiting_for_phone)
async def process_registration_phone(message: Message, state: FSMContext):
    """Обработка телефона при регистрации"""
    phone = message.text.strip()
    if not phone or len(phone) < 10:
        await message.answer("❌ Введите корректный номер телефона")
        return
    
    await state.update_data(phone=phone)
    await message.answer(f"📅 Какой график занятий вам подходит?\n(например: 'утром', 'вечером', 'понедельник-среда-пятница')")
    await state.set_state(RegistrationStates.waiting_for_schedule)

@router.message(RegistrationStates.waiting_for_schedule)
async def process_registration_schedule(message: Message, state: FSMContext):
    """Обработка графика при регистрации"""
    schedule = message.text.strip()
    if not schedule:
        await message.answer("❌ Введите предпочитаемый график")
        return
    
    data = await state.get_data()
    user_id = message.from_user.id
    username = message.from_user.username or ""
    
    # Добавляем пользователя
    success = UserManager.add_user(
        telegram_id=user_id,
        username=username,
        name=data['name'],
        phone=data['phone'],
        schedule=schedule
    )
    
    if success:
        await message.answer(
            f"🎉 Регистрация завершена!\n\n"
            f"👤 Имя: {data['name']}\n"
            f"📱 Телефон: {data['phone']}\n"
            f"📅 График: {schedule}\n\n"
            f"Теперь вы можете пользоваться ботом:",
            reply_markup=get_main_menu()
        )
        
        # Уведомление админу
        await bot.send_message(
            ADMIN_ID,
            f"👤 Новый пользователь зарегистрирован!\n\n"
            f"Имя: {data['name']}\n"
            f"Телефон: {data['phone']}\n"
            f"График: {schedule}\n"
            f"ID: {user_id}\n"
            f"Username: @{username}"
        )
    else:
        await message.answer("❌ Ошибка регистрации. Попробуйте позже.")
    
    await state.clear()

# НОВЫЕ ОБРАБОТЧИКИ СОСТОЯНИЙ ПЛАТЕЖА

@router.message(PaymentStates.waiting_for_amount)
async def process_payment_amount(message: Message, state: FSMContext):
    try:
        amount_text = message.text.replace(',', '.').replace(' ', '')
        amount = float(amount_text)
        
        min_payment = SettingsManager.get_setting('min_payment', DEFAULT_SETTINGS['min_payment'])
        max_payment = SettingsManager.get_setting('max_payment', DEFAULT_SETTINGS['max_payment'])
        
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0. Попробуйте еще раз:")
            return
        
        if amount < min_payment:
            await message.answer(f"❌ Минимальная сумма: {min_payment} сом. Попробуйте еще раз:")
            return
            
        if amount > max_payment:
            await message.answer(f"❌ Максимальная сумма: {max_payment} сом. Свяжитесь с администратором.")
            return
        
        await state.update_data(amount=amount)
        data = await state.get_data()
        payment_type = data.get('payment_type', 'transfer')
        
        if payment_type == 'transfer':
            await message.answer(
                f"📸 **Отлично!** Теперь пришлите скриншот перевода на сумму **{amount} сом**\n\n"
                f"💡 Прикрепите фото чека или скриншот из приложения банка\n"
                f"📱 После получения скриншота администратор подтвердит платеж",
                parse_mode="Markdown"
            )
            await state.set_state(PaymentStates.waiting_for_screenshot)
        else:
            # Для наличных сразу сохраняем
            await save_and_notify_cash_payment(message.from_user.id, amount, state)
        
    except ValueError:
        await message.answer("❌ Введите корректную сумму (только цифры). Например: 8000")
    except Exception as e:
        print(f"Ошибка обработки суммы: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте еще раз.")

@router.message(PaymentStates.waiting_for_screenshot, F.photo)
async def process_payment_screenshot(message: Message, state: FSMContext):
    """Обработка скриншота платежа"""
    try:
        data = await state.get_data()
        amount = data.get('amount')
        photo_file_id = message.photo[-1].file_id  # Берем фото в максимальном качестве
        
        # Сохраняем платеж со скриншотом
        success = await save_payment_to_sheets(
            telegram_id=message.from_user.id,
            amount=amount,
            payment_type="transfer",
            status="pending",
            photo_file_id=photo_file_id
        )
        
        if success:
            await message.answer(
                f"✅ **Платеж принят!**\n\n"
                f"💰 Сумма: **{amount} сом**\n"
                f"📸 Скриншот получен\n"
                f"⏳ Ожидайте подтверждения администратора\n\n"
                f"📝 Уведомление отправлено администратору",
                parse_mode="Markdown"
            )
            
            # Уведомление админу с кнопками подтверждения
            await send_payment_confirmation_to_admin(message.from_user.id, amount, photo_file_id)
        else:
            await message.answer("❌ Ошибка при сохранении платежа. Попробуйте еще раз.")
        
        await state.clear()
        
    except Exception as e:
        print(f"Ошибка обработки скриншота: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте еще раз.")

@router.message(PaymentStates.waiting_for_screenshot)
async def process_payment_no_photo(message: Message, state: FSMContext):
    await message.answer(
        "📸 **Пожалуйста, пришлите именно фото скриншота перевода**\n\n"
        "💡 Нажмите на скрепку (📎) и выберите 'Фото'",
        parse_mode="Markdown"
    )

# ВАЖНО: Обработчик неизвестных сообщений должен быть ПОСЛЕДНИМ!
@router.message(F.text)
async def handle_unknown_text(message: Message, state: FSMContext):
    """Обработка неизвестных текстовых сообщений - ПОСЛЕДНИЙ обработчик!"""
    current_state = await state.get_state()
    if current_state is not None:
        return
    
    if message.text and message.text.startswith('/'):
        return
    
    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "🤖 Команда не распознана.\n\n"
            "Используйте кнопки меню или команды:\n"
            "/start - главное меню\n"
            "/help - справка",
            reply_markup=get_admin_menu()
        )
    else:
        user = UserManager.get_user(message.from_user.id)
        if user:
            await message.answer(
                "🤖 Команда не распознана.\n\n"
                "Используйте кнопки меню внизу экрана:",
                reply_markup=get_main_menu()
            )
        else:
            await message.answer("👋 Привет! Для начала работы нажмите /start")

# Запуск бота (адаптированный для Render.com)
async def main():
    """Основная функция запуска бота"""
    try:
        print("🚀 Запуск фитнес-бота на Render.com...")
        print(f"🔑 Токен: {BOT_TOKEN[:10]}...")
        print(f"👨‍💼 Админ ID: {ADMIN_ID}")
        print(f"🌐 Платформа: {'Render.com' if GOOGLE_CREDENTIALS_JSON else 'Локальная разработка'}")
        
        # Инициализируем Google Services
        if not init_google_services():
            print("⚠️ Google Sheets недоступны, работаем в упрощенном режиме")
            await notify_admin_on_error("Google Sheets недоступны на Render.com")
        else:
            print("✅ Google Sheets подключены успешно")
        
        # Устанавливаем команды бота
        print("🔧 Настройка команд бота...")
        await set_bot_commands()
        print("✅ Команды бота установлены")
        
        print("🔧 Настройка обработчиков...")
        print(f"🔍 Зарегистрированных роутеров: {len(dp.sub_routers)}")
        print(f"🔍 Обработчиков в роутере: {len(router.message.handlers)}")
        
        # Уведомляем админа о запуске
        try:
            platform_info = "🌐 Render.com (бесплатно)" if GOOGLE_CREDENTIALS_JSON else "💻 Локальная разработка"
            await bot.send_message(
                ADMIN_ID,
                f"🚀 БОТ ЗАПУЩЕН!\n\n"
                f"📱 Все команды работают\n"
                f"⚙️ Google Sheets: {'✅ Подключены' if users_sheet else '❌ Недоступны'}\n"
                f"🏗️ Платформа: {platform_info}\n"
                f"💳 Платежи: ✅ QR код + подтверждения\n"
                f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        except Exception as e:
            print(f"Не удалось уведомить админа о запуске: {e}")
        
        print("\n🎉 Бот успешно запущен!")
        print("📱 Напишите боту /start для начала работы")
        print(f"👨‍💼 Админ-панель доступна по ID: {ADMIN_ID}")
        print("💳 Система оплаты с QR кодом и подтверждениями активна!")
        print("🔄 Бот автоматически перезапускается при ошибках")
        
        await dp.start_polling(bot)
        
    except Exception as e:
        error_msg = f"💥 Критическая ошибка запуска: {e}"
        print(error_msg)
        
        try:
            await notify_admin_on_error(error_msg)
        except:
            pass
            
        import traceback
        traceback.print_exc()
        
        # Для Render важно завершить с кодом ошибки
        exit(1)
    finally:
        try:
            await bot.session.close()
        except:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
    except Exception as e:
        print(f"💥 Фатальная ошибка: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
