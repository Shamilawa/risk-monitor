import MetaTrader5 as mt5
import time
from datetime import datetime

if not mt5.initialize():
    print("MT5 init failed")
else:
    tick = mt5.symbol_info_tick("EURUSD")
    if tick:
        mt5_time = tick.time
        local_utc = int(time.time())
        offset = local_utc - mt5_time
        print(f"MT5 Time (broker): {mt5_time} ({datetime.utcfromtimestamp(mt5_time)})")
        print(f"Local UTC Time: {local_utc} ({datetime.utcfromtimestamp(local_utc)})")
        print(f"Offset (Local - MT5) in seconds: {offset}")
        print(f"Offset in hours: {offset / 3600}")
    else:
        print("Failed to get tick")
    mt5.shutdown()
