import MetaTrader5 as mt5
import time

if not mt5.initialize():
    print("MT5 init failed")
else:
    deals = mt5.history_deals_get(0, 2147483647)
    if deals:
        last_deal_time = deals[-1].time
        print(f"Initial last_deal_time: {last_deal_time}")
        
        # Now query using integer
        d1 = mt5.history_deals_get(last_deal_time, 2147483647)
        print(f"Subsequent query found: {len(d1) if d1 else 0} deals")
        if d1:
            print(f"Tickets: {[d.ticket for d in d1]}")
    mt5.shutdown()
