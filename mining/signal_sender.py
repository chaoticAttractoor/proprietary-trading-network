import sys

import requests
import json
import time

from vali_objects.enums.order_type_enum import OrderType
from vali_config import TradePair
import mining_utils 
import pandas as pd
from trade_handler import TradeHandler

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
    
    while True:  
            
        
        # load live data
        input = mining_utils.fetch_binance_data()
        if (last is not None) and (input.tail(1).ds > last.tail(1).ds):            
            # feed into model to predict 
            model = mining_utils.load_model()
            preds = model.predict(input)
            preds['close'] = preds[model.models[0]] 
            pred_df = pd.concat([input[['ds','close']], preds[['ds','close']]], axis=0)
            future_signals = mining_utils.future_signals(pred_df)
            present_signals = mining_utils.present_signals(input) 
            
            signals = mining_utils.assess_signals(future_signals, present_signals).tail(1) 
            last_trade=  mining_utils.last_trade( )
            
            ordertype = mining_utils.str_to_ordertype(signals['order_type'])
            
            if last_trade['order_type'] != signals['order_type'] : 
                
                if ordertype != OrderType.FLAT:
                    mining_utils.close_trade(input.tail(1)) 
                    mining_utils.open_trade(input.tail(1), signals['order_type'])
                elif ordertype == OrderType.FLAT: 
                     mining_utils.open_trade(input.tail(1), signals['order_type'])
                else: 
                    print('Wrong Order Type')
                    pass

                    
                data = {
                'trade_pair': mining_utils.str_to_tradepair(signals['trade_pair']),
                'order_type': ordertype,
                'leverage': signals['leverage'],
                'api_key': '1234567890',
                }        
            # log in trades database 

            # Define the JSON data to be sent in the request
            
 
            # Convert the Python dictionary to JSON format
            json_data = json.dumps(data, cls=CustomEncoder)
            print(json_data)
            # Set the headers to specify that the content is in JSON format
            headers = {
                'Content-Type': 'application/json',
            }

            # Make the POST request with JSON data
            response = requests.post(url, data=json_data, headers=headers)

            # Check if the request was successful (status code 200)
            if response.status_code == 200:
                print("POST request was successful.")
                print("Response:")
                print(response.json())  # Print the response data
            else:
                print(response.__dict__)
                print("POST request failed with status code:", response.status_code)
            
            time.sleep(60)