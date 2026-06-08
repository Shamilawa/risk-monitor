import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone

if not mt5.initialize():
    print("MT5 init failed")
else:
    deals = mt5.history_deals_get(datetime(2020, 1, 1), datetime(2030, 1, 1))
    print(f"Deals found: {len(deals) if deals else 0}")
    
    if deals:
        d = deals[-1]
        print(f"Last deal ticket: {d.ticket}")
        print(f"Last deal time (int): {d.time}")
        print(f"Last deal time interpreted by datetime.fromtimestamp: {datetime.fromtimestamp(d.time)}")
        print(f"Last deal time interpreted by datetime.utcfromtimestamp: {datetime.utcfromtimestamp(d.time)}")
        
        # Test finding this exact deal
        dt = datetime.fromtimestamp(d.time)
        print(f"Finding deals using datetime.fromtimestamp(d.time):")
        deals2 = mt5.history_deals_get(dt - timedelta(seconds=1), dt + timedelta(seconds=1))
        print(f"Deals found: {len(deals2) if deals2 else 0}")
        
    mt5.shutdown()
