// --- Backtester Logic ---
let btCurrentSessionId = null;

function btFetchSessions() {
    fetch('/api/backtest/sessions')
        .then(res => res.json())
        .then(data => {
            const select = document.getElementById('backtest-session-select');
            if (!select) return;
            select.innerHTML = '';
            
            if (data.length === 0) {
                select.innerHTML = '<option value="">No sessions</option>';
                btCurrentSessionId = null;
                btRenderTrades([]);
                document.getElementById('backtest-current-balance').innerText = '$0.00';
            } else {
                data.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.id;
                    opt.innerText = s.name;
                    select.appendChild(opt);
                });
                
                if (!btCurrentSessionId || !data.find(s => s.id == btCurrentSessionId)) {
                    btCurrentSessionId = data[0].id;
                }
                select.value = btCurrentSessionId;
                btFetchTrades(btCurrentSessionId);
            }
        });
}

function btFetchTrades(sessionId) {
    if (!sessionId) return;
    fetch(`/api/backtest/trades?session_id=${sessionId}`)
        .then(res => res.json())
        .then(data => {
            btRenderTrades(data);
            
            if (data.length > 0) {
                const last = data[data.length - 1];
                document.getElementById('backtest-current-balance').innerText = '$' + last.balance_after.toFixed(2);
                
                fetch('/api/backtest/sessions').then(r => r.json()).then(sessions => {
                    const s = sessions.find(x => x.id == sessionId);
                    if (s) {
                        btUpdateMetrics(data, s.starting_balance);
                    }
                });
            } else {
                fetch('/api/backtest/sessions')
                    .then(r => r.json())
                    .then(sessions => {
                        const s = sessions.find(x => x.id == sessionId);
                        if (s) {
                            document.getElementById('backtest-current-balance').innerText = '$' + s.starting_balance.toFixed(2);
                            btUpdateMetrics([], s.starting_balance);
                        }
                    });
            }
        });
}

function btUpdateMetrics(trades, startingBalance) {
    if (trades.length === 0) {
        document.getElementById('bt-metric-gains').innerHTML = '$0.00 <span style="font-size: 10px; color: var(--text-muted);">(0.00%)</span>';
        document.getElementById('bt-metric-winrate').innerHTML = '0% <span style="font-size: 10px; color: var(--text-muted);">(0W 0L)</span>';
        document.getElementById('bt-metric-profit-factor').innerText = '0.00';
        document.getElementById('bt-metric-drawdown').innerText = '0.00%';
        document.getElementById('bt-metric-rr').innerHTML = '0.00 <span style="font-size: 10px; color: var(--text-muted);">($0 / $0)</span>';
        return;
    }

    let grossProfit = 0;
    let grossLoss = 0;
    let wins = 0;
    let losses = 0;
    let totalWinAmount = 0;
    let totalLossAmount = 0;
    
    let peakBalance = startingBalance;
    let maxDrawdownPct = 0;
    
    let currentBalance = startingBalance;
    
    trades.forEach(t => {
        const pl = t.net_pl;
        if (pl > 0) {
            grossProfit += pl;
            wins++;
            totalWinAmount += pl;
        } else if (pl < 0) {
            grossLoss += Math.abs(pl);
            losses++;
            totalLossAmount += Math.abs(pl);
        }
        
        currentBalance += pl;
        
        if (currentBalance > peakBalance) {
            peakBalance = currentBalance;
        }
        
        const currentDrawdown = (peakBalance - currentBalance) / peakBalance * 100;
        if (currentDrawdown > maxDrawdownPct) {
            maxDrawdownPct = currentDrawdown;
        }
    });

    const totalGain = currentBalance - startingBalance;
    const gainPct = (totalGain / startingBalance) * 100;
    const gainClass = totalGain >= 0 ? 'var(--color-buy)' : 'var(--color-sell)';
    
    document.getElementById('bt-metric-gains').innerHTML = `<span style="color: ${gainClass}">$${totalGain.toFixed(2)}</span> <span style="font-size: 10px; color: ${gainClass};">(${gainPct >= 0 ? '+' : ''}${gainPct.toFixed(2)}%)</span>`;
    
    const winRate = trades.length > 0 ? (wins / trades.length * 100) : 0;
    document.getElementById('bt-metric-winrate').innerHTML = `${winRate.toFixed(1)}% <span style="font-size: 10px; color: var(--text-muted);">(${wins}W ${losses}L)</span>`;
    
    const profitFactor = grossLoss > 0 ? (grossProfit / grossLoss) : (grossProfit > 0 ? 99.99 : 0);
    document.getElementById('bt-metric-profit-factor').innerText = profitFactor.toFixed(2);
    
    document.getElementById('bt-metric-drawdown').innerText = maxDrawdownPct.toFixed(2) + '%';
    
    const avgWin = wins > 0 ? totalWinAmount / wins : 0;
    const avgLoss = losses > 0 ? totalLossAmount / losses : 0;
    const rr = avgLoss > 0 ? (avgWin / avgLoss) : (avgWin > 0 ? 99.99 : 0);
    
    document.getElementById('bt-metric-rr').innerHTML = `${rr.toFixed(2)} <span style="font-size: 10px; color: var(--text-muted);">($${avgWin.toFixed(0)} / $${avgLoss.toFixed(0)})</span>`;
}

function btRenderTrades(trades) {
    const tbody = document.getElementById('backtester-tbody');
    const btnClear = document.getElementById('btn-clear-bt-session');
    
    if (!tbody) return;
    tbody.innerHTML = '';
    
    if (trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color: var(--text-muted);">No trades yet. Add one above.</td></tr>';
        if (btnClear) btnClear.style.display = 'none';
        return;
    }
    
    if (btnClear) btnClear.style.display = 'inline-block';
    
    trades.forEach((t, i) => {
        const riskStr = t.risk_type === '$' ? `$${t.risk_value.toFixed(2)}` : `${t.risk_value.toFixed(2)}%`;
        const plClass = t.net_pl > 0 ? 'bdg-buy' : t.net_pl < 0 ? 'bdg-sell' : '';
        const recStr = t.recovery_sl_pips ? `[${t.recovery_tp_pips}]` : '-';
        
        // Main row
        tbody.innerHTML += `
            <tr class="bt-trade-row" style="cursor: pointer;" data-id="${t.id}">
                <td>${i + 1}</td>
                <td>${riskStr}</td>
                <td>${t.sl_pips}</td>
                <td>${t.tp1_pips} / ${t.tp2_pips}</td>
                <td>${recStr}</td>
                <td><span class="${plClass} badge-dense" style="background:transparent;">$${t.net_pl.toFixed(2)}</span></td>
                <td>$${t.balance_after.toFixed(2)}</td>
                <td><button class="btn-toolbar btn-bt-delete" data-id="${t.id}" style="color: var(--color-sell); border-color: var(--color-sell); padding: 2px 6px; font-size: 10px;">&times;</button></td>
            </tr>
        `;
        
        // Breakdown row (hidden by default)
        if (t.breakdown) {
            const b = t.breakdown;
            const origPlTotal = b.orig_pl1 + b.orig_pl2 - b.orig_comm;
            const origPlCls = origPlTotal > 0 ? 'color: var(--color-buy)' : origPlTotal < 0 ? 'color: var(--color-sell)' : '';
            
            let recHtml = '';
            if (b.rec_vol > 0) {
                const recPlTotal = b.rec_pl - b.rec_comm;
                const recPlCls = recPlTotal > 0 ? 'color: var(--color-buy)' : recPlTotal < 0 ? 'color: var(--color-sell)' : '';
                recHtml = `
                    <div style="margin-top: 5px; border-top: 1px solid var(--border-color); padding-top: 5px;">
                        <strong>Recovery Trade:</strong> Lot Size: ${b.rec_vol} | Gross: $${b.rec_pl.toFixed(2)} | Comm: $${b.rec_comm.toFixed(2)} | <span style="${recPlCls}">Net: $${recPlTotal.toFixed(2)}</span>
                    </div>
                `;
            }
            
            tbody.innerHTML += `
                <tr class="bt-breakdown-row" id="bt-breakdown-${t.id}" style="display: none; background: rgba(255,255,255,0.02);">
                    <td colspan="8" style="padding: 10px; text-align: left; font-size: 11px;">
                        <div>
                            <strong>Original Trade:</strong> 
                            Lot Size: ${b.vol1} / ${b.vol2} | 
                            Gross TP1: $${b.orig_pl1.toFixed(2)} | Gross TP2: $${b.orig_pl2.toFixed(2)} | 
                            Comm: $${b.orig_comm.toFixed(2)} | <span style="${origPlCls}">Net: $${origPlTotal.toFixed(2)}</span>
                        </div>
                        ${recHtml}
                    </td>
                </tr>
            `;
        }
    });
    
    const tableContainer = tbody.closest('.table-container');
    if (tableContainer) tableContainer.scrollTop = tableContainer.scrollHeight;
    
    // Add event listeners for expanding rows
    document.querySelectorAll('.bt-trade-row').forEach(row => {
        row.addEventListener('click', (e) => {
            // Don't expand if clicking the delete button
            if (e.target.classList.contains('btn-bt-delete')) return;
            
            const id = row.getAttribute('data-id');
            const breakdown = document.getElementById(`bt-breakdown-${id}`);
            if (breakdown) {
                breakdown.style.display = breakdown.style.display === 'none' ? 'table-row' : 'none';
            }
        });
    });
    
    // Add event listeners for delete buttons
    document.querySelectorAll('.btn-bt-delete').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const id = e.target.getAttribute('data-id');
            if (confirm('Delete this trade?')) {
                fetch('/api/backtest/trades', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ trade_id: id })
                }).then(r => r.json()).then(data => {
                    if (data.status === 'success') {
                        btFetchTrades(btCurrentSessionId);
                    }
                });
            }
        });
    });
}

document.addEventListener('DOMContentLoaded', () => {
    // Initial fetch since this is the only tab on this page now
    btFetchSessions();

    const btnNewSession = document.getElementById('btn-new-session');
    const modalSession = document.getElementById('bt-session-modal');
    const btnCloseSession = document.getElementById('btn-close-bt-session');
    const btnSaveSession = document.getElementById('btn-save-bt-session');
    
    if (btnNewSession) {
        btnNewSession.addEventListener('click', () => modalSession.style.display = 'flex');
        btnCloseSession.addEventListener('click', () => modalSession.style.display = 'none');
        
        btnSaveSession.addEventListener('click', () => {
            const name = document.getElementById('bt-new-session-name').value;
            const bal = document.getElementById('bt-new-session-balance').value;
            fetch('/api/backtest/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name || 'New Session', starting_balance: bal })
            }).then(r => r.json()).then(data => {
                modalSession.style.display = 'none';
                btCurrentSessionId = data.id;
                btFetchSessions();
            });
        });
    }
    
    const btnClearSession = document.getElementById('btn-clear-bt-session');
    if (btnClearSession) {
        btnClearSession.addEventListener('click', () => {
            if (!btCurrentSessionId) return;
            if (confirm('Are you sure you want to delete ALL trades in this session?')) {
                fetch('/api/backtest/trades', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ clear_session_id: btCurrentSessionId })
                }).then(r => r.json()).then(data => {
                    if (data.status === 'success') {
                        btFetchTrades(btCurrentSessionId);
                    }
                });
            }
        });
    }
    
    const sessionSelect = document.getElementById('backtest-session-select');
    if (sessionSelect) {
        sessionSelect.addEventListener('change', (e) => {
            btCurrentSessionId = e.target.value;
            btFetchTrades(btCurrentSessionId);
        });
    }
    
    const btnExecute = document.getElementById('btn-bt-execute');
    const modalRecovery = document.getElementById('bt-recovery-modal');
    const btnSubmitRecovery = document.getElementById('btn-submit-bt-recovery');
    
    let pendingTradePayload = null;
    
    if (btnExecute) {
        btnExecute.addEventListener('click', () => {
            if (!btCurrentSessionId) {
                alert("Please create or select a session first.");
                return;
            }
            
            const payload = {
                session_id: btCurrentSessionId,
                risk_type: document.getElementById('bt-risk-type').value,
                risk_value: document.getElementById('bt-risk-value').value,
                sl_pips: document.getElementById('bt-sl-pips').value,
                tp1_pips: document.getElementById('bt-tp1-pips').value,
                tp2_pips: document.getElementById('bt-tp2-pips').value
            };
            
            const t1 = parseFloat(payload.tp1_pips);
            const t2 = parseFloat(payload.tp2_pips);
            const sl = parseFloat(payload.sl_pips);
            
            if (t1 < 0 && t2 < 0) {
                pendingTradePayload = payload;
                modalRecovery.style.display = 'flex';
            } else {
                submitBtTrade(payload);
            }
        });
    }
    
    if (btnSubmitRecovery) {
        btnSubmitRecovery.addEventListener('click', () => {
            if (!pendingTradePayload) return;
            
            pendingTradePayload.recovery_sl_pips = document.getElementById('bt-rec-sl-pips').value;
            pendingTradePayload.recovery_tp_pips = document.getElementById('bt-rec-tp-pips').value;
            
            submitBtTrade(pendingTradePayload);
            modalRecovery.style.display = 'none';
            pendingTradePayload = null;
        });
    }
    
    function submitBtTrade(payload) {
        fetch('/api/backtest/trades', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(r => r.json()).then(data => {
            if (data.status === 'success') {
                btFetchTrades(btCurrentSessionId);
                document.getElementById('bt-tp1-pips').value = '';
                document.getElementById('bt-tp2-pips').value = '';
                document.getElementById('bt-tp1-pips').focus();
            } else {
                alert("Error: " + data.error);
            }
        });
    }
});
