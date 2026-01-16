# 🤖 TELEGRAM BOT - Проверка оплаты контейнеров
# Версия: 2.2 (WEBHOOK MODE) - PRODUCTION READY
# ✅ СТАТУСЫ: Оплачено | Оплаты нет | Постоплата (С БОЛЬШОЙ БУКВЫ)

import os
import json
from datetime import datetime
from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
import httpx
import logging
import time

# ════════════════════════════════════════════════════════════════
# 📋 ЛОГИРОВАНИЕ
# ════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════
# ⚙️ КОНФИГУРАЦИЯ (БЕЗОПАСНАЯ)
# ════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("❌ ОШИБКА: TELEGRAM_TOKEN не установлен в переменных окружения!")
    raise ValueError("TELEGRAM_TOKEN not set")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not WEBHOOK_URL:
    logger.error("❌ ОШИБКА: WEBHOOK_URL не установлена в переменных окружения!")
    raise ValueError("WEBHOOK_URL not set")

WEBHOOK_PATH = "/telegram"

SHEET_ID = os.getenv("SHEET_ID", "1cTfkGG2HC8HQBgt8ePfpQ-diyoJStvvEx4EAOdYmcbk")
SHEET_NAME = os.getenv("SHEET_NAME", "Контейнеры")

CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS")
if not CREDENTIALS_JSON:
    logger.warning("⚠️ GOOGLE_CREDENTIALS не установлены. Попытка загрузить из файла...")
    CREDENTIALS_PATH = "telegram-bot-pay-cont.json"
else:
    CREDENTIALS_PATH = None


# ════════════════════════════════════════════════════════════════
# 📊 КЛАСС РАБОТЫ С GOOGLE SHEETS
# ════════════════════════════════════════════════════════════════

class SheetManager:
    """Управляет подключением и операциями с Google Sheets"""
    
    def __init__(self, credentials_json=None, credentials_path=None, sheet_id=None, sheet_name=None):
        self.sheet_id = sheet_id
        self.sheet_name = sheet_name
        self.sheet = None
        self.client = None
        
        try:
            if credentials_json:
                logger.info("📌 Используем credentials из переменной окружения")
                try:
                    creds_dict = json.loads(credentials_json)
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Ошибка парсинга JSON credentials: {e}")
                    return
                
                credentials = Credentials.from_service_account_info(
                    creds_dict,
                    scopes=['https://www.googleapis.com/auth/spreadsheets']
                )
            elif credentials_path and os.path.exists(credentials_path):
                logger.info(f"📌 Используем credentials из файла: {credentials_path}")
                credentials = Credentials.from_service_account_file(
                    credentials_path,
                    scopes=['https://www.googleapis.com/auth/spreadsheets']
                )
            else:
                logger.error("❌ Не найдены Google credentials!")
                return
            
            self.client = gspread.authorize(credentials)
            self.sheet = self.client.open_by_key(sheet_id).worksheet(sheet_name)
            logger.info("✅ Подключено к Google Sheets успешно!")
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Google Sheets: {e}")
            self.sheet = None
    
    def get_container_status(self, container_id):
        """Получает статус конкретного контейнера"""
        try:
            if not self.sheet:
                return {'ошибка': 'Нет подключения к Google Sheets'}
            
            all_records = self.sheet.get_all_records()
            for record in all_records:
                if record.get('Контейнер', '').strip().upper() == container_id.strip().upper():
                    return {
                        'контейнер': record.get('Контейнер'),
                        'статус': record.get('Статус'),
                        'найден': True
                    }
            return {'найден': False, 'контейнер': container_id}
        except Exception as e:
            logger.error(f"Ошибка при получении статуса контейнера: {e}")
            return {'ошибка': str(e)}
    
    def get_unpaid_containers(self):
        """Получает список контейнеров со статусом 'Оплаты нет'"""
        try:
            if not self.sheet:
                return {'ошибка': 'Нет подключения'}
            
            all_records = self.sheet.get_all_records()
            unpaid = []
            for record in all_records:
                status = record.get('Статус', '').strip()
                # ✅ ТОЧНОЕ СОВПАДЕНИЕ: "Оплаты нет" (с большой буквы)
                if status == 'Оплаты нет':
                    unpaid.append({
                        'контейнер': record.get('Контейнер'),
                        'статус': record.get('Статус')
                    })
            return unpaid
        except Exception as e:
            logger.error(f"Ошибка при получении неоплаченных: {e}")
            return {'ошибка': str(e)}
    
    def get_statistics(self):
        """Получает общую статистику контейнеров"""
        try:
            if not self.sheet:
                return {'ошибка': 'Нет подключения'}
            
            all_records = self.sheet.get_all_records()
            total = len(all_records)
            
            # ✅ ТОЧНЫЕ СТАТУСЫ С БОЛЬШОЙ БУКВЫ
            paid = sum(1 for r in all_records if r.get('Статус', '').strip() == 'Оплачено')
            unpaid = sum(1 for r in all_records if r.get('Статус', '').strip() == 'Оплаты нет')
            postpay = sum(1 for r in all_records if r.get('Статус', '').strip() == 'Постоплата')
            
            return {
                'всего': total,
                'оплачено': paid,
                'неоплачено': unpaid,
                'постоплата': postpay
            }
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {e}")
            return {'ошибка': str(e)}


# ════════════════════════════════════════════════════════════════
# 🤖 TELEGRAM BOT ЛОГИКА
# ════════════════════════════════════════════════════════════════

class TelegramBot:
    """Основная логика Telegram бота"""
    
    def __init__(self, token, sheet_manager):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.sheet_manager = sheet_manager
    
    def send_message(self, chat_id, text, reply_markup=None):
        """Отправляет сообщение пользователю"""
        try:
            data = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            if reply_markup:
                data["reply_markup"] = reply_markup
            
            response = httpx.post(
                f"{self.api_url}/sendMessage",
                json=data,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.warning(f"Ошибка отправки сообщения: {response.status_code}")
            
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения: {e}")
            return False
    
    def handle_message(self, message):
        """Обрабатывает входящее сообщение от пользователя"""
        try:
            chat_id = message.get('chat', {}).get('id')
            text = message.get('text', '').strip()
            
            if not chat_id or not text:
                logger.warning("Получено пустое сообщение")
                return
            
            logger.info(f"📨 Сообщение от {chat_id}: {text}")
            
            # Обработка команд и кнопок
            if text == '/start':
                self.send_start_menu(chat_id)
            elif text == '🔍 Проверить контейнер':
                self.send_message(chat_id, "📦 Введи номер контейнера (например: TCLU1234567)")
            elif text == '💰 Неоплаченные':
                self.show_unpaid(chat_id)
            elif text == '📊 Статистика':
                self.show_statistics(chat_id)
            elif text == '❓ Справка':
                help_text = """
🔍 <b>Доступные команды:</b>
/start - Главное меню
/check TCLU1234567 - Проверить контейнер
/unpaid - Неоплаченные
/stats - Статистика
/help - Эта справка
                """
                self.send_message(chat_id, help_text)
            elif len(text) >= 6:
                # Если текст длинный - это номер контейнера
                self.check_container(chat_id, text)
            else:
                self.send_message(chat_id, "⚠️ Не понял команду. Нажми /start")
        
        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}")
            try:
                self.send_message(chat_id, f"❌ Произошла ошибка: {str(e)}")
            except:
                pass
    
    def send_start_menu(self, chat_id):
        """Отправляет стартовое меню с кнопками"""
        welcome_text = """
🚢 <b>Добро пожаловать!</b>

Я помогу тебе проверять статус оплаты контейнеров:
✅ Проверить статус оплаты контейнера
✅ Посмотреть список неоплаченных контейнеров
✅ Получить статистику
        """
        
        keyboard = {
            "keyboard": [
                [{"text": "🔍 Проверить контейнер"}],
                [{"text": "💰 Неоплаченные"}],
                [{"text": "📊 Статистика"}],
                [{"text": "❓ Справка"}]
            ],
            "resize_keyboard": True,
            "one_time_keyboard": False
        }
        
        self.send_message(chat_id, welcome_text, keyboard)
    
    def check_container(self, chat_id, container_id):
        """Проверяет статус конкретного контейнера"""
        result = self.sheet_manager.get_container_status(container_id)
        
        if result.get('найден'):
            # ✅ ТОЧНЫЕ СТАТУСЫ С БОЛЬШОЙ БУКВЫ
            status_emoji = {
                'Оплачено': '✅',
                'Постоплата': '🔄',
                'Оплаты нет': '❌'
            }
            emoji = status_emoji.get(result['статус'], '❓')
            
            message = f"""{emoji} <b>Контейнер:</b> {result['контейнер']}
<b>Статус:</b> {result['статус']}"""
            self.send_message(chat_id, message)
        else:
            self.send_message(chat_id, f"❌ Контейнер <b>{container_id}</b> не найден в базе")
    
    def show_unpaid(self, chat_id):
        """Показывает список неоплаченных контейнеров"""
        self.send_message(chat_id, "⏳ Загружаю список неоплаченных...")
        
        unpaid_list = self.sheet_manager.get_unpaid_containers()
        
        if isinstance(unpaid_list, dict) and 'ошибка' in unpaid_list:
            self.send_message(chat_id, f"❌ Ошибка: {unpaid_list['ошибка']}")
            return
        
        if not unpaid_list:
            self.send_message(chat_id, "✅ <b>Отлично!</b> Все контейнеры оплачены!")
            return
        
        message = f"💰 <b>Неоплаченные контейнеры ({len(unpaid_list)}):</b>\n\n"
        for i, container in enumerate(unpaid_list, 1):
            message += f"{i}. 📦 {container['контейнер']} - {container['статус']}\n"
        
        self.send_message(chat_id, message)
    
    def show_statistics(self, chat_id):
        """Показывает статистику по контейнерам"""
        self.send_message(chat_id, "⏳ Загружаю статистику...")
        
        stats = self.sheet_manager.get_statistics()
        
        if isinstance(stats, dict) and 'ошибка' in stats:
            self.send_message(chat_id, f"❌ Ошибка: {stats['ошибка']}")
            return
        
        percentage = int((stats['оплачено']/stats['всего']*100) if stats['всего'] > 0 else 0)
        message = f"""📊 <b>Статистика:</b>

📦 Всего: <b>{stats['всего']}</b>
✅ Оплачено: <b>{stats['оплачено']}</b>
❌ Неоплачено: <b>{stats['неоплачено']}</b>
🔄 Постоплата: <b>{stats['постоплата']}</b>

Процент оплаты: <b>{percentage}%</b>"""
        
        self.send_message(chat_id, message)


# ════════════════════════════════════════════════════════════════
# 🌐 FLASK ПРИЛОЖЕНИЕ
# ════════════════════════════════════════════════════════════════

def create_app():
    """Создает Flask приложение"""
    app = Flask(__name__)
    
    # Инициализация компонентов
    try:
        sheet_manager = SheetManager(
            credentials_json=CREDENTIALS_JSON,
            credentials_path=CREDENTIALS_PATH if not CREDENTIALS_JSON else None,
            sheet_id=SHEET_ID,
            sheet_name=SHEET_NAME
        )
        bot = TelegramBot(TELEGRAM_TOKEN, sheet_manager)
        logger.info("✅ Бот инициализирован успешно")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации: {e}")
        raise

    @app.route('/health', methods=['GET'])
    def health():
        """Health check endpoint для мониторинга"""
        return {'status': 'ok', 'timestamp': datetime.now().isoformat()}, 200

    @app.route('/init-webhook', methods=['GET'])
    def init_webhook():
        """Инициализирует webhook Telegram бота"""
        try:
            webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
            logger.info(f"📍 Webhook URL: {webhook_url}")
            
            response = httpx.post(
                f"{TELEGRAM_API_URL}/setWebhook",
                json={"url": webhook_url},
                timeout=10
            )
            
            result = response.json()
            logger.info(f"🔗 Webhook response: {result}")
            
            return result, 200
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации webhook: {e}")
            return {'error': str(e)}, 500

    @app.route(WEBHOOK_PATH, methods=['POST'])
    def telegram_webhook():
        """Получает обновления от Telegram"""
        try:
            update = request.json
            
            if 'message' in update:
                message = update['message']
                bot.handle_message(message)
            
            return {'ok': True}, 200
        except Exception as e:
            logger.error(f"❌ Ошибка обработки webhook: {e}")
            return {'ok': False, 'error': str(e)}, 500

    return app


# ════════════════════════════════════════════════════════════════
# 🚀 ЗАПУСК ПРИЛОЖЕНИЯ
# ════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
