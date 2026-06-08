import MetaTrader5 as mt5
from datetime import datetime, timezone

if mt5.initialize():
    deals = mt5.history_deals_get(0, 2147483647)
    if deals:
        last = deals[-1]
        print(f"Deal Broker Time Integer: {last.time}")
        print(f"fromtimestamp(d.time): {datetime.fromtimestamp(last.time)}")
        print(f"utcfromtimestamp(d.time): {datetime.utcfromtimestamp(last.time)}")
        print(f"Local now(): {datetime.now()}")
    mt5.shutdown()
