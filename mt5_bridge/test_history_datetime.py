import MetaTrader5 as mt5
from datetime import datetime, timedelta

if mt5.initialize():
    now_dt = datetime.now()
    today_start_dt = datetime(now_dt.year, now_dt.month, now_dt.day)
    min_date = today_start_dt - timedelta(days=7)
    
    deals = mt5.history_deals_get(min_date, now_dt)
    if deals is None:
        print("deals is None")
    else:
        print(f"Got {len(deals)} deals using datetime")
        
    deals_int = mt5.history_deals_get(0, 2147483647)
    if deals_int:
        print(f"Got {len(deals_int)} deals using int")
