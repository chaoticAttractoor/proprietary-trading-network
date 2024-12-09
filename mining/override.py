import sys
import requests
import json
import time
from vali_objects.enums.order_type_enum import OrderType
from vali_config import TradePair, ValiConfig
from generate_signals import TradeHandler  # Import the TradeHandler class
import mining_utils
from datetime import datetime

# Constants and API Key Setup
secrets_json_path = ValiConfig.BASE_DIR + "/mining/miner_secrets.json"

if os.path.exists(secrets_json_path):
    with open(secrets_json_path, "r") as file:
        data = file.read()
    API_KEY = json.loads(data)["api_key"]
else:
    raise Exception(f"{secrets_json_path} not found", 404)

str_to_ordertype = {
    'long': OrderType.LONG,
    'short': OrderType.SHORT,
    'flat': OrderType.FLAT
}

str_to_tradepair = {
    'btcusd': TradePair.BTCUSD,
}

def generate_signal_and_execute_trade(base_url='http://127.0.0.1:80'):
    url = f'{base_url}/api/receive-signal'
    order = 'flat'  # Example signal
    trade_pair = str_to_tradepair['btcusd']
    order_type = str_to_ordertype[order]
    
    data = {
        'trade_pair': trade_pair,
        'order_type': order_type,
        'leverage': 0.5,
        'api_key': API_KEY,
    }
    json_data = json.dumps(data)
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, data=json_data, headers=headers)

    if response.status_code == 200:
        print("Order successful:", response.json())
        handler = TradeHandler()
        handler.set_position(price=0.0, new_position=order)  # Replace `0.0` with real price data
    else:
        print("Order failed with status code:", response.status_code)

if __name__ == "__main__":
    generate_signal_and_execute_trade()
