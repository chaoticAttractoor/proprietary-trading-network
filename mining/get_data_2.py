import requests
import pandas as pd
from datetime import datetime

def fetch_binance_data(symbol="BTCUSDT", interval='5m', start=None, end=None, limit=1000, max_rows=2500):
    # Set default start and end times if none are provided
    if start is None:
        start = str(int(datetime.now().timestamp() * 1000) - 60000 * 60 * 24 * 7)  # One week ago
    if end is None:
        end = str(int(datetime.now().timestamp() * 1000))  # Current time
    
    # Convert start and end to integers
    start = int(start)
    end = int(end)

    # Empty list to hold data
    all_data = []

    while len(all_data) < max_rows:
        # Construct the URL with the provided parameters
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&startTime={start}&endTime={end}&limit={limit}'

        # Fetch the data
        response = requests.get(url)

        # Check if the request was successful
        if response.status_code == 200:
            # Parse the response data
            data = response.json()
            
            # Break if no more data is returned
            if not data:
                break

            # Append data to the list
            all_data.extend(data)

            # Update the start time to the last timestamp + 1 ms (to avoid duplicate data)
            start = data[-1][0] + 1

            # Stop if we've reached the max rows
            if len(all_data) >= max_rows:
                all_data = all_data[:max_rows]  # Trim to max_rows
                break
        else:
            print(f"Failed to fetch data: {response.status_code}")
            return None

    # Define column names
    columns = ['ds', 'open', 'high', 'low', 'close', 'volume', 'Close Time', 'Quote Asset Volume', 'Number of Trades', 'Taker Buy Base Asset Volume', 'Taker Buy Quote Asset Volume', 'Ignore']

    # Load the data into a pandas DataFrame
    df = pd.DataFrame(all_data, columns=columns)

    # Convert 'Open Time' (ds) to datetime format
    df['ds'] = pd.to_datetime(df['ds'], unit='ms')

    # Add additional column for unique identifier if needed
    df['unique_id'] = symbol

    return df

