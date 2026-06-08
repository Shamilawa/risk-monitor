import MetaTrader5 as mt5
import time
from datetime import datetime, timezone

if not mt5.initialize():
    print("MT5 init failed")
else:
    # Let's get the latest deal
    deals = mt5.history_deals_get(datetime(2020, 1, 1), datetime(2030, 1, 1))
    if not deals:
        print("No deals found at all.")
    else:
        last_deal = deals[-1]
        print(f"Last deal ticket: {last_deal.ticket}, time: {last_deal.time}")
        
        # Test 1: Query using last_deal.time (integer)
        print("\nTest 1: Query with integers (last_deal.time)")
        d1 = mt5.history_deals_get(last_deal.time - 10, last_deal.time + 10)
        print(f"Result: {len(d1) if d1 else 0} deals found")
        
        # Test 2: Try to get current broker time using symbol_info_tick
        print("\nTest 2: Try getting broker time from a symbol")
        symbols = mt5.symbols_get()
        broker_time = None
        if symbols:
            # just pick the first visible symbol
            for s in symbols:
                if s.visible:
                    tick = mt5.symbol_info_tick(s.name)
                    if tick and tick.time > 0:
                        broker_time = tick.time
                        print(f"Broker time from {s.name}: {broker_time}")
                        break
                        
        if broker_time:
            d2 = mt5.history_deals_get(broker_time - 3600, broker_time + 3600)
            print(f"Result for last hour (using broker_time integers): {len(d2) if d2 else 0} deals found")
            
        # Test 3: Can we just use a massive time window?
        print("\nTest 3: Massive time window but filtering by deal.time manually")
        # If we use mt5.history_deals_get(0, 2000000000), it might be slow.
        d3 = mt5.history_deals_get(0, 2147483647)
        print(f"Total deals ever: {len(d3) if d3 else 0}")
        
    mt5.shutdown()
