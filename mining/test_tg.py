import requests
from dotenv import load_dotenv
import os 
load_dotenv()


# Telegram Bot credentials
BOT_TOKEN = os.environ.get('TG_BOT')
CHAT_ID =  os.environ.get('TG_CHATID')

def send_telegram_message(message):
    """
    Send a message to the specified Telegram chat using requests.
    
    Args:
        message (str): The message to send.
    """
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    payload = {'chat_id': CHAT_ID, 'text': message}
    requests.post(url, data=payload)


alert_message = {'test':'test'}
send_telegram_message(alert_message) 