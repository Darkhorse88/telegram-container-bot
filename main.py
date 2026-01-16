import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
SHEET_ID = os.environ.get('SHEET_ID')
CREDENTIALS_JSON = os.environ.get('CREDENTIALS_JSON')

COLORS = {
    'оплачено': '🟢',
    'постоплата': '🟡',
    'нет оплаты': '🔴',
}

def get_sheet():
    try:
        creds_dict = json.loads(CREDENTIALS_JSON)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        return sheet
    except Exception as e:
        logger.error(f"Ошибка подключения: {e}")
        return None

def search_container(container_num):
    try:
        sheet = get_sheet()
        if not sheet:
            return None, "Ошибка подключения"
        
        cells = sheet.findall(container_num.upper())
        if cells:
            for cell in cells:
                row = cell.row
                status = sheet.cell(row, 2).value
                return status.lower().strip() if status else 'не найдено', None
        return None, "Не найдено"
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return None, f"Ошибка: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Проверяю статус контейнеров.\n\n"
        "Отправь номер: TCLU1234567\n\n"
        "🟢 Оплачено\n🟡 Постоплата\n🔴 Нет оплаты"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    container_num = update.message.text.strip().upper()
    
    if len(container_num) < 3:
        await update.message.reply_text("❌ Введи номер контейнера")
        return
    
    status, error = search_container(container_num)
    
    if error:
        await update.message.reply_text(f"❌ {error}")
        return
    
    color = COLORS.get(status, '⚪')
    response = f"{color} {container_num}: {status.upper()}"
    await update.message.reply_text(response)

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен!")
        return
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()
