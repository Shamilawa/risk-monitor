import MetaTrader5 as mt5

if not mt5.initialize():
    print("MT5 init failed")
else:
    deals = mt5.history_deals_get(0, 2147483647)
    if deals:
        for deal in deals[-5:]:
            print(f"Ticket: {deal.ticket}, Pos_ID: {deal.position_id}, Entry: {deal.entry}, Type: {deal.type}")
    mt5.shutdown()
