from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
import requests
import logging
import sys

import requests
import json

from vali_objects.enums.order_type_enum import OrderType
from vali_config import TradePair
from miner_config import MinerConfig
from vali_config import TradePair, ValiConfig
from vali_objects.enums.order_type_enum import OrderType
from vali_objects.utils.vali_bkp_utils import ValiBkpUtils
from vali_objects.vali_dataclasses.signal import Signal

secrets_json_path = ValiConfig.BASE_DIR + "/mining/miner_secrets.json"
# Define your API key
if os.path.exists(secrets_json_path):
    with open(secrets_json_path, "r") as file:
        data = file.read()
    MINER_API_KEY = json.loads(data)["api_key"]
else:
    raise Exception(f"{secrets_json_path} not found", 404)


pairs_dict= {
    'BTCUSD': TradePair.BTCUSD,
    'ETHUSD': TradePair.ETHUSD           
           }

pos_dict = { 
    'LONG': OrderType.LONG,
    'SHORT': OrderType.SHORT,
    'FLAT': OrderType.FLAT
            }

class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, TradePair) or isinstance(obj, OrderType):
            return obj.__json__()  # Use the to_dict method to serialize TradePair

        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)

if __name__ == "__main__":
    # Set the default URL endpoint
    default_base_url = 'http://127.0.0.1:80'

    # Check if the URL argument is provided
    if len(sys.argv) == 2:
        # Extract the URL from the command line argument
        base_url = sys.argv[1]
    else:
        # Use the default URL if no argument is provided
        base_url = default_base_url

    print("base URL endpoint:", base_url)

    url = f'{base_url}/api/receive-signal'


# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)



# Function to start the bot and show initial options
def start(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [InlineKeyboardButton("Start", callback_data='start')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Please choose:', reply_markup=reply_markup)

# Function to handle user's selection and ask further questions
def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()

    if query.data == 'start':
        keyboard = [
            [InlineKeyboardButton("BTCUSD", callback_data='BTCUSD'),
             InlineKeyboardButton("ETHUSD", callback_data='ETHUSD')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="Select trade pair:", reply_markup=reply_markup)
    elif query.data in ['BTCUSD', 'ETHUSD']:
        context.user_data['trade_pair'] = query.data
        keyboard = [
            [InlineKeyboardButton("Long", callback_data='LONG'),
             InlineKeyboardButton("Short", callback_data='SHORT'),
             InlineKeyboardButton("Flat", callback_data='FLAT')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text="Select position:", reply_markup=reply_markup)
    elif query.data in ['LONG', 'SHORT', 'FLAT']:
        context.user_data['position'] = query.data
        query.edit_message_text(text=f"Enter leverage for {context.user_data['trade_pair']}:")
        # Assuming leverage is entered via text message. Implement a message handler to process it.

def submit_leverage(update: Update, context: CallbackContext) -> None:
    leverage = update.message.text
    # Assuming user enters valid leverage as a message after selecting options.
    try:
        leverage_float = float(leverage)
        context.user_data['leverage'] = leverage_float
    except ValueError:
        update.message.reply_text("Please enter a valid float.")
        return

    data = {
        "leverage": context.user_data['leverage'],
        "trade_pair": pairs_dict[context.user_data['trade_pair']],
        "position": pos_dict[context.user_data['position']],
        "api_key": MINER_API_KEY
    }

    # Send data to Flask server
    json_data = json.dumps(data, cls=CustomEncoder)
    print(json_data)
    # Set the headers to specify that the content is in JSON format
    headers = {
        'Content-Type': 'application/json',
    }

    # Make the POST request with JSON data
    response = requests.post(url, data=json_data, headers=headers)
    
    if response.ok:
        update.message.reply_text("Options submitted successfully!")
    else:
        update.message.reply_text("Failed to submit options.")

def main() -> None:
    # Token from BotFather
    
    secrets_json_path = ValiConfig.BASE_DIR + "/bot/telegram_secrets.json"
    # Define your API key
    if os.path.exists(secrets_json_path):
        with open(secrets_json_path, "r") as file:
            data = file.read()
        TOKEN  = json.loads(data)["api_key"]
    else:
        raise Exception(f"{secrets_json_path} not found", 404)
    updater = Updater(token=TOKEN)

    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CallbackQueryHandler(button))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, submit_leverage))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
