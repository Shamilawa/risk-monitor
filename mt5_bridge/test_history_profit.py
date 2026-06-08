import MetaTrader5 as mt5
from datetime import datetime, timedelta

if mt5.initialize():
    now_dt = datetime.now()
    today_start_dt = datetime(now_dt.year, now_dt.month, now_dt.day)
    min_date = today_start_dt - timedelta(days=7)
    
    deals = mt5.history_deals_get(min_date, now_dt)
    print(f"deals: {deals}")
    if deals:
        for d in deals[-5:]:
            deal_time = datetime.fromtimestamp(d.time)
            profit = d.profit + d.commission + d.swap
            is_today = deal_time >= today_start_dt
            print(f"Deal {d.ticket} (Profit: {profit}): d.time={d.time}, deal_time={deal_time}, today_start={today_start_dt}, is_today={is_today}")
