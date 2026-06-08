import MetaTrader5 as mt5
from datetime import datetime, timezone

if mt5.initialize():
    deals = mt5.history_deals_get(0, 2147483647)
    if deals:
        print(f"Total deals: {len(deals)}")
        for deal in deals[-10:]:
            print(f"Ticket: {deal.ticket}, Time Integer: {deal.time}, UTC: {datetime.utcfromtimestamp(deal.time)}, Type: {deal.type}, Entry: {deal.entry}")
    mt5.shutdown()
