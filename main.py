# 🤖 TELEGRAM BOT - Проверка оплаты контейнеров
# Версия: 2.0 (WEBHOOK MODE) - PRODUCTION READY

import os
import json
from datetime import datetime
from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
import httpx
import logging

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

# 🔐 Получаем токен из переменных окружения (НЕ жестко закодирован!)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("❌ ОШИБКА: TELEGRAM_TOKEN не установлен в переменных окружения!")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Webhook URL для регистрации бота
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not WEBHOOK_URL:
    raise ValueError("❌ ОШИБКА: WEBHOOK_URL не установлена в переменных окружения!")

WEBHOOK_PATH = "/telegram"

# Google Sheets конфигурация
CREDENTIALS_PATH = os.getenv("CREDENTIALS_PATH", "telegram-bot-pay-cont.json")
SHEET_ID = os.getenv("SHEET_ID", "1cTfkGG2HC8HQBgt8ePfpQ-diyoJStvvEx4EAOdYmcbk")
SHEET_NAME = "Контейнеры"


# ════════════════════════════════════════════════════════════════
# 📊 КЛАСС РАБОТЫ С GOOGLE SHEETS
# ════════════════════════════════════════════════════════════════

class SheetManager:
    """Управляет подключением и операциями с Google Sheets"""
    
    def __init__(self, credentials_path, sheet_id, sheet_name):
        self.sheet_id = sheet_id
        self.sheet_name = sheet_name
        self.sheet = None
        self.client = None
        
        try:
            # Поддержка JSON строки или пути к файлу
            if credentials_path.startswith('{'):
                creds_dict = json.loads(credentials_path)
                credentials = Credentials.from_service_account_info(
                    creds_dict,
                    scopes=['https://www.googleapis.com/auth/spreadsheets']
                )
            else:
                credentials = Credentials.from_service_account_file(
                    credentials_path,
                    scopes=['https://www.googleapis.com/auth/spreadsheets']
                )
            
            self.client = gspread.authorize(credentials)
            self.sheet = self.client.open_by_key(sheet_id).worksheet(sheet_name)
            logger.info("✅ Подключено к Google Sheets")
        except FileNotFoundError:
            logger.error(f"❌ Файл учетных данных не найден: {credentials_path}")
            self.sheet = None
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
        """Получает список неоплаченных контейнеров"""
        try:
            if not self.sheet:
                return {'ошибка': 'Нет подключения'}
            
            all_records = self.sheet.get_all_records()
            unpaid = []
            for record in all_records:
                status = record.get('Статус', '').lower().strip()
                if status in ['нет оплаты', 'задолженость', 'просрочено']:
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
            paid = sum(1 for r in all_records if r.get('Статус', '').lower().strip() == 'оплачено')
            unpaid = sum(1 for r in all_records if r.get('Статус', '').lower().strip() in ['нет оплаты', 'задолженость', 'просрочено'])
            postpay = sum(1 for r in all_records if r.get('Статус', '').lower().strip() == 'постоплата')
            
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
            self.send_message(chat_id, f"❌ Произошла ошибка: {str(e)}")
    
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
            status_emoji = {
                'оплачено': '✅',
                'постоплата': '🔄',
                'нет оплаты': '❌',
                'задолженость': '💸',
                'просрочено': '⚠️'
            }
            emoji = status_emoji.get(result['статус'].lower(), '❓')
            
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
💰 Неоплачено: <b>{stats['неоплачено']}</b>
🔄 Постоплата: <b>{stats['постоплата']}</b>

Процент оплаты: <b>{percentage}%</b>"""
        
        self.send_message(chat_id, message)


# ════════════════════════════════════════════════════════════════
# 🌐 FLASK ПРИЛОЖЕНИЕ
# ════════════════════════════════════════════════════════════════

app = Flask(__name__)

# Инициализация компонентов
try:
    sheet_manager = SheetManager(CREDENTIALS_PATH, SHEET_ID, SHEET_NAME)
    bot = TelegramBot(TELEGRAM_TOKEN, sheet_manager)
    logger.info("✅ Бот инициализирован успешно")
except Exception as e:
    logger.error(f"❌ Ошибка инициализации: {e}")
    raise


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint для мониторинга"""
    return {'status': 'ok', 'timestamp': datetime.now().isoformat()}, 200


@app.route(WEBHOOK_PATH, methods=['POST'])
def telegram_webhook():
    """Основной webhook для получения обновлений от Telegram"""
    try:
        data = request.get_json()
        
        if not data:
            logger.warning("Получен пустой webhook")
            return {'ok': True}, 200
        
        logger.info(f"📥 Webhook получен: update_id={data.get('update_id')}")
        
        # Обрабатываем сообщение
        if 'message' in data:
            bot.handle_message(data['message'])
        
        return {'ok': True}, 200
    except Exception as e:
        logger.error(f"Ошибка обработки webhook: {e}")
        return {'ok': False, 'error': str(e)}, 500


@app.route('/set-webhook', methods=['POST'])
def set_webhook():
    """Регистрирует webhook в Telegram API"""
    try:
        webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        logger.info(f"Регистрирую webhook: {webhook_url}")
        
        data = {"url": webhook_url}
        
        response = httpx.post(
            f"{TELEGRAM_API_URL}/setWebhook",
            json=data,
            timeout=10
        )
        
        result = response.json()
        logger.info(f"✅ Ответ setWebhook: {result}")
        return result, 200
    except Exception as e:
        logger.error(f"❌ Ошибка регистрации webhook: {e}")
        return {'ok': False, 'error': str(e)}, 500


@app.errorhandler(404)
def not_found(error):
    """Обработка 404 ошибок"""
    return {'error': 'Not found'}, 404


@app.errorhandler(500)
def internal_error(error):
    """Обработка 500 ошибок"""
    logger.error(f"Internal server error: {error}")
    return {'error': 'Internal server error'}, 500


if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    logger.info(f"🚀 Запуск бота на порту {port}")
    logger.info(f"📍 Webhook URL: {WEBHOOK_URL}{WEBHOOK_PATH}")
    app.run(host='0.0.0.0', port=port, debug=False)
