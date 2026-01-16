# 🤖 TELEGRAM BOT - Проверка оплаты контейнеров
# Версия: 2.0 (WEBHOOK MODE)

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
# ⚙️ КОНФИГУРАЦИЯ
# ════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN = "8138214238:AAGIb0H9jYvbVXg3Pv2d8QelOwfaDWh97hg"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://YOUR_APP.onrender.com")
WEBHOOK_PATH = "/telegram"

CREDENTIALS_PATH = os.getenv("CREDENTIALS_PATH", "telegram-bot-pay-cont.json")
SHEET_ID = os.getenv("SHEET_ID", "1cTfkGG2HC8HQBgt8ePfpQ-diyoJStvvEx4EAOdYmcbk")
SHEET_NAME = "Контейнеры"

# ════════════════════════════════════════════════════════════════
# 📊 КЛАСС РАБОТЫ С GOOGLE SHEETS
# ════════════════════════════════════════════════════════════════

class SheetManager:
    def __init__(self, credentials_path, sheet_id, sheet_name):
        self.sheet_id = sheet_id
        self.sheet_name = sheet_name
        self.sheet = None
        
        try:
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
        except Exception as e:
            logger.error(f"❌ Ошибка подключения: {e}")
            self.sheet = None
    
    def get_container_status(self, container_id):
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
            logger.error(f"Error: {e}")
            return {'ошибка': str(e)}
    
    def get_unpaid_containers(self):
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
            logger.error(f"Error: {e}")
            return {'ошибка': str(e)}
    
    def get_statistics(self):
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
            logger.error(f"Error: {e}")
            return {'ошибка': str(e)}

# ════════════════════════════════════════════════════════════════
# 🤖 TELEGRAM BOT ЛОГИКА
# ════════════════════════════════════════════════════════════════

class TelegramBot:
    def __init__(self, token, sheet_manager):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.sheet_manager = sheet_manager
    
    def send_message(self, chat_id, text, reply_markup=None):
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
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error: {e}")
            return False
    
    def handle_message(self, message):
        try:
            chat_id = message.get('chat', {}).get('id')
            text = message.get('text', '').strip()
            
            if not chat_id or not text:
                return
            
            logger.info(f"📨 Message from {chat_id}: {text}")
            
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
🔍 Команды:
/start - Главное меню
/check TCLU1234567 - Проверить контейнер
/unpaid - Неоплаченные
/stats - Статистика
/help - Эта справка
                """
                self.send_message(chat_id, help_text)
            elif len(text) >= 6:
                self.check_container(chat_id, text)
            else:
                self.send_message(chat_id, "⚠️ Не понял команду")
        
        except Exception as e:
            logger.error(f"Error: {e}")
    
    def send_start_menu(self, chat_id):
        welcome_text = """
🚢 Добро пожаловать в бот проверки оплаты контейнеров!

Я помогу тебе:
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
            "resize_keyboard": True
        }
        
        self.send_message(chat_id, welcome_text, keyboard)
    
    def check_container(self, chat_id, container_id):
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
            
            message = f"""{emoji} Контейнер: {result['контейнер']}
Статус: {result['статус']}"""
            self.send_message(chat_id, message)
        else:
            self.send_message(chat_id, f"❌ Контейнер {container_id} не найден")
    
    def show_unpaid(self, chat_id):
        self.send_message(chat_id, "⏳ Загружаю...")
        
        unpaid_list = self.sheet_manager.get_unpaid_containers()
        
        if isinstance(unpaid_list, dict) and 'ошибка' in unpaid_list:
            self.send_message(chat_id, f"❌ Ошибка: {unpaid_list['ошибка']}")
            return
        
        if not unpaid_list:
            self.send_message(chat_id, "✅ Все контейнеры оплачены!")
            return
        
        message = f"💰 Неоплаченные ({len(unpaid_list)}):\n\n"
        for i, container in enumerate(unpaid_list, 1):
            message += f"{i}. 📦 {container['контейнер']} - {container['статус']}\n"
        
        self.send_message(chat_id, message)
    
    def show_statistics(self, chat_id):
        self.send_message(chat_id, "⏳ Загружаю...")
        
        stats = self.sheet_manager.get_statistics()
        
        if isinstance(stats, dict) and 'ошибка' in stats:
            self.send_message(chat_id, f"❌ Ошибка: {stats['ошибка']}")
            return
        
        percentage = int((stats['оплачено']/stats['всего']*100) if stats['всего'] > 0 else 0)
        message = f"""📊 Статистика:

📦 Всего: {stats['всего']}
✅ Оплачено: {stats['оплачено']}
💰 Неоплачено: {stats['неоплачено']}
🔄 Постоплата: {stats['постоплата']}

Процент: {percentage}%"""
        
        self.send_message(chat_id, message)

# ════════════════════════════════════════════════════════════════
# 🌐 FLASK ПРИЛОЖЕНИЕ
# ════════════════════════════════════════════════════════════════

app = Flask(__name__)
sheet_manager = SheetManager(CREDENTIALS_PATH, SHEET_ID, SHEET_NAME)
bot = TelegramBot(TELEGRAM_TOKEN, sheet_manager)

@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok'}, 200

@app.route(WEBHOOK_PATH, methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json()
        logger.info(f"Webhook: {data}")
        
        if 'message' in data:
            bot.handle_message(data['message'])
        
        return {'ok': True}, 200
    except Exception as e:
        logger.error(f"Error: {e}")
        return {'ok': False}, 500

@app.route('/set-webhook', methods=['POST'])
def set_webhook():
    try:
        webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        data = {"url": webhook_url}
        
        response = httpx.post(
            f"{TELEGRAM_API_URL}/setWebhook",
            json=data,
            timeout=10
        )
        
        result = response.json()
        logger.info(f"Webhook: {result}")
        return result, 200
    except Exception as e:
        logger.error(f"Error: {e}")
        return {'ok': False}, 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    logger.info(f"🚀 Starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
