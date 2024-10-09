import requests
from datetime import datetime, timedelta
import pandas as pd
import concurrent.futures

# Function to fetch 5-minute candle data from Polygon.io with parallel pagination requests
def fetch_data_polygon(symbol, API_KEY):
    
    # Function to round a datetime object to the nearest 5-minute increment
    def round_time_to_nearest_5_minutes(dt):
        discard = timedelta(minutes=dt.minute % 5,
                            seconds=dt.second,
                            microseconds=dt.microsecond)
        dt -= discard
        if discard >= timedelta(minutes=2.5):
            dt += timedelta(minutes=5)
        return dt

    # Calculate the end date rounded to the nearest 5-minute increment
    now = datetime.now()
    end_date =  now #round_time_to_nearest_5_minutes(now)

    # Calculate the start date 7 days before the rounded end date
    start_date = end_date - timedelta(days=7)

    # Format the dates for the API request
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')

    # Define the initial API endpoint for 5-minute candles
    base_url = f'https://api.polygon.io/v2/aggs/ticker/{symbol}/range/5/minute/{start_date_str}/{end_date_str}?apiKey={API_KEY}'
    
    # Function to fetch each page of results
    def fetch_page(url):
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return data.get('results', [])
        else:
            print(f"Error: {response.status_code}, {response.text}")
            return []

    # Initialize all_data list to store all paginated data
    all_data = []
    
    # First request to get the initial page
    response = requests.get(base_url)
    
    if response.status_code == 200:
        data = response.json()

        # Append results from the first page
        all_data.extend(data.get('results', []))
        
        # Retrieve next_url if exists
        next_url = data.get('next_url')
        next_urls = []
        
        while next_url:
            next_urls.append(f"{next_url}&apiKey={API_KEY}")
            response = requests.get(next_url)
            next_url = response.json().get('next_url') if response.status_code == 200 else None

        # Fetch the paginated data using concurrent requests
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_url = {executor.submit(fetch_page, url): url for url in next_urls}
            for future in concurrent.futures.as_completed(future_to_url):
                data_chunk = future.result()
                all_data.extend(data_chunk)
    else:
        print(f"Error: {response.status_code}, {response.text}")
        return None

    # Convert the results into a pandas DataFrame
    df = pd.DataFrame(all_data)

    # Rename the columns to match the requested names: 'open', 'close', 'high', 'low'
    df.rename(columns={'o': 'open', 'c': 'close', 'h': 'high', 'l': 'low', 't': 'ds'}, inplace=True)
    
    # Convert 'ds' (timestamp in milliseconds) to a datetime object
    df['ds'] = pd.to_datetime(df['ds'], unit='ms')
    
    # Add a unique symbol identifier to the DataFrame
    df['unique_id'] = "BTCUSDT"
    
    return df

# Example usage:
# df = fetch_data_polygon('X:BTCUSD', 'your_api_key_here')
# print(df.head())
