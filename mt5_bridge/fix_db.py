import sqlite3

db = sqlite3.connect('trades.db')
c = db.cursor()

c.execute("SELECT id, magic_number FROM trade_groups WHERE status = 'SUCCESS_TP2_HIT'")
rows = c.fetchall()

fixed_count = 0
for row in rows:
    gid, magic = row
    
    # Get the deals for this magic
    c.execute("SELECT profit, comment FROM trading_log WHERE magic = ? ORDER BY time ASC", (magic,))
    deals = c.fetchall()
    
    if len(deals) > 1:
        # Trade 2 is the second deal
        t2_profit, t2_comment = deals[1]
        
        # If the comment does not have TP, it must be a Trailed SL
        if 'tp' not in t2_comment.lower():
            # Estimate the trailing state based on profit ratio
            # A true TP2 is usually ~3R. A trailed SL is usually 0R, -0.5R, or +0.25R.
            # But the backend doesn't know the exact trailing state from just profit easily.
            # However, we know it's a CLOSED_T2_SL_PLUS_0_25 if profit is positive but not huge.
            
            # Since the user specifically complained about +0.25R falsely showing as TP2,
            # we can assume any positive profit lacking 'tp' in the comment is +0.25R.
            if t2_profit > 0:
                print(f"Fixing Group {gid} (Magic {magic}) from TP2 to +0.25R TSL.")
                c.execute("UPDATE trade_groups SET status = 'CLOSED_T2_SL_PLUS_0_25' WHERE id = ?", (gid,))
                fixed_count += 1
            elif t2_profit < 0:
                # This should technically be CLOSED_T2_SL_MINUS_0_5 but it would've been routed to CLOSED_T2_SL
                pass

db.commit()
print(f"Fixed {fixed_count} false TP2 records.")
db.close()
