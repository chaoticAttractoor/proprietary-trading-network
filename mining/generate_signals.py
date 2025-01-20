import sys

import requests
import json
import time

from vali_objects.enums.order_type_enum import OrderType
import mining_utils 
import pandas as pd
from vali_objects.enums.order_type_enum import OrderType
from vali_objects.vali_config import TradePair, TradePairCategory, ValiConfig
from get_data import fetch_data_polygon
from datetime import datetime 
import pickle
import os
from signals import process_data_for_predictions,LONG_ENTRY
import bittensor as bt
import duckdb
import numpy as np
from datetime import timedelta 
from dotenv import load_dotenv
import requests

load_dotenv()
model = mining_utils.load_model()
TP = 0.05 
SL = -0.01
TRAILING_STOP = 0.01 # 2% trailing stop (only active after reaching 2% profit)
TRAILING_THRESHOLD = 0.02

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




secrets_json_path = ValiConfig.BASE_DIR + "/mining/miner_secrets.json"
# Define your API key
if os.path.exists(secrets_json_path):
    with open(secrets_json_path, "r") as file:
        data = file.read()
    API_KEY = json.loads(data)["api_key"]
else:
    raise Exception(f"{secrets_json_path} not found", 404)

polygon_path= ValiConfig.BASE_DIR + "/mining/polygon_api_secrets.json"
# Define your API key
if os.path.exists(polygon_path):
    with open(polygon_path, "r") as file:
        data = file.read()
    POLYGON_API = json.loads(data)["api_key"]
else:
    raise Exception(f"{polygon_path} not found", 404)

def round_time_down_to_nearest_5_minutes(dt):
    discard = timedelta(minutes=dt.minute % 5,
                        seconds=dt.second,
                        microseconds=dt.microsecond)
    return dt - discard

# Function to check if the time is within 1 minute of a 5-minute boundary (rounding down only)
def is_within_1_minute_of_5_minute_mark(current_time):
    nearest_5_minute = round_time_down_to_nearest_5_minutes(current_time)
    difference = abs(current_time - nearest_5_minute)
    return difference <= timedelta(minutes=1)

def fetch_candle_on_nearest_five_minutes(dt):
    try:
        # Convert the datetime string to a datetime object
        dt = datetime.strptime(dt, '%Y-%m-%dT%H:%M:%S.%f')
        
        # Number of seconds in 5 minutes
        round_to = 5 * 60
        
        # Convert the datetime to seconds since epoch
        timestamp = dt.timestamp()
        
        # Perform rounding to the nearest 5-minute interval
        rounded_timestamp = round(timestamp / round_to) * round_to 
        
        # Convert the rounded timestamp back to a datetime object
        rounded_dt = datetime.fromtimestamp(rounded_timestamp)
        
        # Check if the time is exactly on a 5-minute interval
        if rounded_dt.minute % 5 == 0:
            return rounded_dt  # Return if it's on a 5-minute boundary
        else:
            return None  # Return None if it's not on a 5-minute interval
    
    except Exception as e:
        return None


str_to_ordertype= { 
             'LONG' : OrderType.LONG, 
             'SHORT': OrderType.SHORT ,
             'FLAT' : OrderType.FLAT      
                   }
     
str_to_tradepair= { 
             'btcusd' : TradePair.BTCUSD, 
             'ethusd' : TradePair.ETHUSD, 

                   }



class TradeHandler:
    def __init__(self,signal=None, last_update=None, pair=None, current_position=None, trade_opened=None, position_open=False, filename='trade_handler_state.pkl'):
        self.filename = filename
        if os.path.exists(self.filename):
            try:
                loaded_instance = self.load_from_file(self.filename)
                self.__dict__.update(loaded_instance.__dict__)
                self.init_table()
                print(f"State loaded from {self.filename}")
            except Exception as e:
                print(f"Error loading state: {e}")
                self.initialize_attributes(signal, last_update, pair, current_position, trade_opened, position_open)
                self.init_table()
        else:
            self.initialize_attributes(signal, last_update, pair, current_position, trade_opened, position_open)
            self.init_table()
            
    def initialize_attributes(self, signal: str, last_update: datetime, pair: str, current_position: str, trade_opened: datetime, position_open:str):
        self.pair = pair
        self.current_position = current_position
        self.trade_opened = trade_opened
        self.position_open = position_open
        self.last_update = last_update
        self.signal = signal

    def clear_trade(self):
        self.current_position = None
        self.trade_opened = None
        self.position_open = False
        self.last_update = None 
        self.signal = None
        self.save_to_file(self.filename)
        print('Trade cleared.')

    def check_position(self): 
        print(self.current_position)
        
    def log_update(self): 
        self.last_update =  datetime.now().isoformat()

    def set_position(self,price:float, new_position: str):
        if self.current_position == 'SHORT' and new_position == 'LONG':
            self.last_update = datetime.now().isoformat()
            self.close_trade_to_duckdb(close_price=price, trade_closed= self.last_update,signal=self.current_position, pair=self.pair)
            print('Position changed from short to long, closing current position.')
            self.clear_trade()
            self.current_position = 'FLAT'
            self.last_update = datetime.now().isoformat()

        elif self.current_position == 'LONG' and new_position == 'SHORT':
            self.last_update = datetime.now().isoformat()
            self.close_trade_to_duckdb(close_price=price, trade_closed= self.last_update,signal=self.current_position, pair=self.pair)
            print('Position changed from long to short, closing current position.')
            self.clear_trade()
            self.current_position = 'FLAT'
            self.last_update = datetime.now().isoformat()
  
        elif self.current_position in ['SHORT', 'LONG'] and new_position == 'FLAT':
            self.last_update = datetime.now().isoformat()
            self.close_trade_to_duckdb(close_price=price, trade_closed= self.last_update,signal=self.current_position, pair=self.pair)
            print('Trade closed.')
            self.clear_trade()
            self.current_position = 'FLAT'
            self.last_update = datetime.now().isoformat()
            
        else:
            if not self.position_open and new_position in ['LONG', 'SHORT']:
                self.trade_opened = datetime.now().isoformat()
                self.last_update = self.trade_opened 
                print(f'Trade opened at: {self.trade_opened}')
                self.position_open = True
                self.current_position = new_position
                self.open_trade_to_duckdb(price=price)
                self.price = None
            else:  
                self.last_update = datetime.now().isoformat()
        
        # Save state to file after updating the position
        self.save_to_file(self.filename)

    def save_to_file(self, filename: str):
        with open(filename, 'wb') as f:
            pickle.dump(self, f)
        print(f'State saved to {filename}')

    @classmethod
    def load_from_file(cls, filename: str):
        with open(filename, 'rb') as f:
            obj = pickle.load(f)
        print(f'State loaded from {filename}')
        return obj


    def init_table(self,db_filename: str = 'trades.duckdb', table_name: str = 'trades') -> None:
        conn = duckdb.connect(db_filename)
        try:
            # Create the table if it does not exist
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    signal VARCHAR,
                    pair VARCHAR,
                    trade_opened TIMESTAMP,
                    open_price FLOAT,
                    trade_closed TIMESTAMP,
                    close_price FLOAT
                )
            """)
            print(f"Table '{table_name}' initialized in database '{db_filename}'")
        finally:
            conn.close()

    def open_trade_to_duckdb(self,price:float, db_filename: str = 'trades.duckdb', table_name: str = 'trades') -> None:
            conn = duckdb.connect(db_filename)
            try:
                # Create the table if it does not exist
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        signal VARCHAR,
                        pair VARCHAR,
                        trade_opened TIMESTAMP,
                        open_price FLOAT,
                        trade_closed TIMESTAMP,
                        close_price FLOAT
                    )
                """)

                # Check if the last trade is closed
                result = conn.execute(f"""
                    SELECT trade_closed
                    FROM {table_name}
                    WHERE signal = ? AND pair = ?
                    ORDER BY trade_opened DESC
                    LIMIT 1
                """, (self.current_position, self.pair)).fetchone()
                
                if result is not None and result[0] is None:
                    print("Warning: The last trade is not closed yet.")

                # Insert the current trade data into the table
                conn.execute(f"""
                    INSERT INTO {table_name} (signal, pair, trade_opened, open_price)
                    VALUES (?, ?, ?, ?)
                """, (self.current_position, self.pair, self.trade_opened, price))
                
                print(f"Trade opened and saved to DuckDB table '{table_name}' in database '{db_filename}'")
            finally:
                conn.close()

    def close_trade_to_duckdb(self, signal: str, pair: str, close_price: float, trade_closed: datetime, db_filename: str = 'trades.duckdb', table_name: str = 'trades') -> None:
        conn = duckdb.connect(db_filename)
        try:
            # Check if there is an open trade that has not been closed yet
            result = conn.execute(f"""
                SELECT close_price, trade_closed
                FROM {table_name}
                WHERE signal = ? AND pair = ? AND trade_closed IS NULL
                ORDER BY trade_opened DESC
                LIMIT 1
            """, (signal, pair)).fetchone()

            # Check if no open trade is found
            if result is None:
                raise Exception("No open trade found to close.")

            # Check if the trade has already been closed
            if result[0] is not None or result[1] is not None:
                raise Exception("The trade has already been closed.")

            # Update the close price and trade closed time for the last open trade
            conn.execute(f"""
                      WITH cte AS (
                          SELECT trade_opened
                          FROM {table_name}
                          WHERE signal = ? AND pair = ? AND trade_closed IS NULL
                          ORDER BY trade_opened DESC
                          LIMIT 1
                      )
                      UPDATE {table_name}
                      SET close_price = ?, trade_closed = ?
                      WHERE trade_opened = (SELECT trade_opened FROM cte)
                  """, (signal, pair, close_price, trade_closed))

            print(f"Trade closed and updated in DuckDB table '{table_name}' in database '{db_filename}'")
        finally:
            conn.close()

    @staticmethod
    def check_last_trade(db_filename: str = 'trades.duckdb', table_name: str = 'trades') -> None:
        conn = duckdb.connect(db_filename)
        try:
            # Retrieve the last row of the table
            result = conn.execute(f"""
                SELECT *
                FROM {table_name}
                ORDER BY trade_opened DESC
                LIMIT 1
            """).df()

            if isinstance(result, pd.DataFrame):
                conn.close()    
                return result
               #print("Last row in the table:")
               # print(result)
            else:
                print("The table is empty.")
                conn.close()  
                return False

        except: 
                print("The table is empty.")
                conn.close()  
                return False


            
    
            

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
    
    last = None
    last_logged_time = None

    btc =  TradeHandler(pair='ethusd')
    bt.logging.info(f"Initialised trade handler.")
    bt.logging.info(f"Beginning loop.")
    order = None 
    triggered = False
    last_triggered_minute = None
    highest_prices = {}

    while True: 
        current_time = datetime.now()
        
  
        nearest_5_minute = round_time_down_to_nearest_5_minutes(current_time)
        
        
        if last_logged_time != nearest_5_minute and is_within_1_minute_of_5_minute_mark(current_time):
                    print(f'current time: {current_time} and nearest 5 munutes : { nearest_5_minute}')
                    
                    time.sleep(62)

                    last_logged_time = nearest_5_minute
                    print(f'last logged time is : {last_logged_time}')
                    # load live data
                    order = None 
                    input =   fetch_data_polygon('X:ETHUSD', API_KEY=POLYGON_API)
                    print(f'data shape if {input.shape}')
                    if input.shape[0] < 1999:
                        print(f'warning - polygon data has only returned {input.shape[0]} rows')

                    bt.logging.info(f"Latest candle: {input['ds'].tail(1).values[0]}")
                    print(f"Latest candle: {input['ds'].tail(1).values[0]}")

                    bt.logging.info(f"Last Trade: {btc.check_last_trade()}")
                    print(f"Last Trade: {btc.check_last_trade()}")

                    price = input['close'].tail(1).values[0]
                    bt.logging.info(f'{price}')
                    print(f'{price}')

                    input = process_data_for_predictions(input)
                    print(f'Last update: {btc.last_update}')
                    latest_data_time = pd.to_datetime(input['ds'].tail(1).values[0])  # Ensure this is a datetime object
                    #last_update_time = round_time_to_nearest_five_minutes(btc.last_update)  # Ensure this is a datetime object
 
                    # Perform the comparison if btc.last_update exists
                    if True:
                        # Proceed with the logic here
                        
                

                        lasttrade = btc.check_last_trade()
                        
                        if isinstance(lasttrade, pd.DataFrame) and not lasttrade.empty:

                            if pd.isna(lasttrade['trade_closed'].iloc[-1]):
                                print('Open trade detected. ')

                                trade_opened = lasttrade['trade_opened'].tail(1).values[0]

                                current_pnl = None
                                exit_long = False 
                                if trade_opened not in highest_prices:
                                   highest_prices[trade_opened] =  float(price)
                                
                                    
                                current_pnl = float(price) / lasttrade['open_price'].tail(1).values[0] - 1

                                print(f'Current PnL is : {current_pnl}')

                                if float(price) > highest_prices[trade_opened]:
                                     highest_prices[trade_opened] = float(price)

                                open_price = float(lasttrade['open_price'].tail(1).values[0])
                                highest_price = highest_prices[trade_opened]
                                print(f'Current highest price : {highest_price }')
                                max_profit_difference = float(highest_price) - open_price
                                trailing_stop_activated = current_pnl > TRAILING_THRESHOLD

                                # Trailing stop only activates after reaching 2% gain
                               # trailing_stop_activated = current_pnl >  TRAILING_THRESHOLD
                                    
                                if current_pnl > TP:
                                    exit_long = True
                                    print('Profit Target reached - exiting.')
                                elif current_pnl < SL:
                                    exit_long = True
                                    print('Stop Loss Triggered.')
                                elif trailing_stop_activated:
                                    trailing_stop_price = open_price + 0.5 * max_profit_difference 
                                    if float(price) < trailing_stop_price:
                                        exit_long = True
                                        print('Trailing Stop Loss Triggered at 50% of highest price.')           

                                if (current_pnl is not None)  and (exit_long is True) :
                                    
                                    order = 'FLAT'
                                    btc.log_update()

                            
                        if order != 'FLAT': 
                            print('No Open trade - running prediction ')

                            preds = mining_utils.single_predict(model,input.dropna())
                            print(f'prediction string is {preds.shape}')
                            modelname = str(model.models[0])
                            output = mining_utils.gen_signals_from_predictions(predictions= preds, hist = input ,modelname=modelname ) 
                        #  signals = mining_utils.assess_signals(output)
                            order= mining_utils.map_signals(output)
                            print(f'order is {order}')
                            btc.log_update()
                            
                                    
                        if order != 'PASS' : 
                            print('Trade signal detected. Assessing impact.')

                            old_position = btc.position_open
                                
                            btc.set_position(new_position=order,price=float(price) ) 
                            
                            new_position = btc.position_open 
                            
                            
                            if sum([old_position,new_position]) == 1 :  
                                
                                print('Order Triggered.')
                                bt.logging.info(f"Order Triggered.")
                                alert_message = {'position ':order,'output ': btc.pair , 'logs ': output }
                                send_telegram_message(alert_message) 


                                    
                                order_type = str_to_ordertype[btc.current_position]
                                
                                trade_pair = str_to_tradepair[btc.pair]       
                                
                                
                                # Define the JSON data to be sent in the request
                                        
                                data = {
                                    'trade_pair':trade_pair ,
                                    'order_type': order_type,
                                    'leverage': 0.5,
                                    'api_key':API_KEY,
                                    } 
                                
                                print(f"order type: {order_type}")
                                
                        
                                # Convert the Python dictionary to JSON format
                                json_data = json.dumps(data, cls=CustomEncoder)
                                print(json_data)
                                # Set the headers to specify that the content is in JSON format
                                headers = {
                                    'Content-Type': 'application/json',
                                }

                                # Make the POST request with JSON data
                                response = requests.post(url, data=json_data, headers=headers)
                                bt.logging.info(f"Order Posted")
                                bt.logging.info(f"Status: { response.status_code }")

                            

                                # Check if the request was successful (status code 200)
                                if response.status_code == 200:
                                    print("POST request was successful.")
                                    print("Response:")
                                    print(response.json())  # Print the response data
                                else:
                                    print(response.__dict__)
                                    print("POST request failed with status code:", response.status_code)
                                
                                order = None 
                            # time.sleep(5)
                            
                        else: 
                            print('No Change In Position')
                            bt.logging.info(f"No Change In Position")
                            order = None 

                            
                            #time.sleep(5)
                        

        
    time.sleep(5)