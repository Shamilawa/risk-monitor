import MetaTrader5 as mt5
from datetime import datetime, timedelta

if not mt5.initialize():
    print("MT5 init failed")
else:
    now = datetime.now()
    deals = mt5.history_deals_get(datetime(2020, 1, 1), now)
    
    if deals:
        d = deals[-1]
        dt = datetime.fromtimestamp(d.time)
        print(f"Current datetime.now(): {now}")
        print(f"Deal time fromtimestamp: {dt}")
        print(f"Is deal dt > now? {dt > now}")
        
    mt5.shutdown()
