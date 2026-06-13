import sys

with open('d:/Coding/risk_monitor/mt5_bridge/static/main.js', 'r', encoding='utf-8') as f:
    content = f.read()

def exact_replace(old, new):
    global content
    if old not in content:
        print("COULD NOT FIND STRING!")
        print("String: ", repr(old[:100]))
    content = content.replace(old, new)

# 1. Remove Review Mode button from header (around line 170)
# Wait, Review Mode was in index.html, not main.js. In main.js it is btn-review-mode
s1 = """    const btnReviewMode = document.getElementById('btn-review-mode');
    if (btnReviewMode) {
        btnReviewMode.addEventListener('click', () => {
            alert('Review Mode: Switch to historical logs and annotations.');
        });
    }"""
exact_replace(s1, "")

# 2. Remove fetchPerformance and renderPerformance and renderCharts
# We can find them by looking for the blocks, or we can just comment them out if exact matching is hard.
# Actually I'll use index slicing for this because the blocks are huge.
def remove_between(start_str, end_str):
    global content
    idx1 = content.find(start_str)
    if idx1 == -1: return
    idx2 = content.find(end_str, idx1)
    if idx2 == -1: return
    content = content[:idx1] + content[idx2 + len(end_str):]

remove_between("    function fetchPerformance() {", "    fetchPerformance();\n")
remove_between("    function updateStoryNotes() {", "            });\n    }\n")

# 3. From fetchInstances, remove `newInstanceRisk`, `newInstanceProfitLimit`, etc.
r_risk_dec = """    const newInstanceRisk = document.getElementById('new-instance-risk');
    const newInstanceMapping = document.getElementById('new-instance-mapping');
    const newInstanceTimeframe = document.getElementById('new-instance-timeframe');"""
exact_replace(r_risk_dec, "    const newInstanceMapping = document.getElementById('new-instance-mapping');")

r_reset1 = """            if (newInstanceRisk) newInstanceRisk.value = '100';
            if (newInstanceMapping) newInstanceMapping.value = '';
            
            const newInstanceAuto = document.getElementById('new-instance-auto');
            if (newInstanceAuto) newInstanceAuto.checked = false;
            if (newInstanceTimeframe) newInstanceTimeframe.value = 'all';"""
exact_replace(r_reset1, "            if (newInstanceMapping) newInstanceMapping.value = '';")

r_autobadge = """                    const tfLabel = getFriendlyTimeframe(inst.accepted_timeframe);
                    const autoModeBadge = inst.auto_trade 
                        ? `<span class="badge-dense bdg-buy" style="margin-left: 5px; font-size: 9px; vertical-align: middle;">Auto (${tfLabel})</span>` 
                        : `<span class="badge-dense bdg-pending" style="margin-left: 5px; font-size: 9px; vertical-align: middle;">Manual Mode</span>`;"""
exact_replace(r_autobadge, "                    const autoModeBadge = '';")

r_profitlimit = """                    let profitLimitHtml = '';
                    if (inst.profit_limit > 0) {
                        const currentProfit = inst.current_profit || 0;
                        const pct = Math.min(100, Math.max(0, (currentProfit / inst.profit_limit) * 100));
                        const profitClass = currentProfit >= inst.profit_limit ? 'color: #fca5a5;' : 'color: #10b981;';
                        profitLimitHtml = `
                            <div style="margin-top: 8px; font-size: 11px;">
                                <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                                    <span style="color: var(--text-muted);">Profit Limit ($${inst.profit_limit})</span>
                                    <span style="${profitClass}">$${currentProfit.toFixed(2)}</span>
                                </div>
                                <div style="width: 100%; height: 4px; background: var(--bg-main); border-radius: 2px; overflow: hidden;">
                                    <div style="width: ${pct}%; height: 100%; background: ${currentProfit >= inst.profit_limit ? '#ef4444' : '#10b981'};"></div>
                                </div>
                                <button class="btn-toolbar btn-reset-profit" data-id="${inst.id}" style="margin-top: 5px; color: #fbbf24; border-color: #92400e; font-size: 9px; padding: 2px 6px;">Reset Session</button>
                            </div>
                        `;
                    }"""
exact_replace(r_profitlimit, "                    let profitLimitHtml = '';")

r_card1 = """<strong>${inst.name}</strong> ${roleBadge} ${autoModeBadge} <span style="font-size: 11px; color: #10b981; margin-left: 5px;">$${inst.risk_usd || 100} Risk</span> ${inst.symbol_suffix ? `<span style="font-size: 11px; color: #64b5f6; margin-left: 5px;">(${inst.symbol_suffix} Suffix)</span>` : ''}<br>"""
exact_replace(r_card1, """<strong>${inst.name}</strong> ${roleBadge} ${inst.symbol_suffix ? `<span style="font-size: 11px; color: #64b5f6; margin-left: 5px;">(${inst.symbol_suffix} Suffix)</span>` : ''}<br>""")

r_edit = """                            newInstanceRisk.value = inst.risk_usd || 100;
                            const newInstanceProfitLimit = document.getElementById('new-instance-profit-limit');
                            if (newInstanceProfitLimit) newInstanceProfitLimit.value = inst.profit_limit || 0;
                            
                            const newInstanceAuto = document.getElementById('new-instance-auto');
                            if (newInstanceAuto) newInstanceAuto.checked = inst.auto_trade === 1;
                            if (newInstanceTimeframe) newInstanceTimeframe.value = inst.accepted_timeframe || 'all';
                            
                            let mappingStr = '';"""
exact_replace(r_edit, """                            let mappingStr = '';""")

r_save1 = """            const risk_usd = parseFloat(newInstanceRisk.value || 100);
            const newInstanceProfitLimit = document.getElementById('new-instance-profit-limit');
            const profit_limit = newInstanceProfitLimit ? parseFloat(newInstanceProfitLimit.value || 0) : 0;
            const autoTradeVal = document.getElementById('new-instance-auto')?.checked ? 1 : 0;
            const acceptedTimeframeVal = newInstanceTimeframe ? newInstanceTimeframe.value : 'all';
            
            const mappingStr = newInstanceMapping ? newInstanceMapping.value : '';"""
exact_replace(r_save1, """            const mappingStr = newInstanceMapping ? newInstanceMapping.value : '';""")

r_payload = """            const payload = { name, path, risk_usd, symbol_mapping, auto_trade: autoTradeVal, accepted_timeframe: acceptedTimeframeVal, profit_limit: profit_limit };"""
exact_replace(r_payload, """            const payload = { name, path, symbol_mapping };""")

r_reset2 = """                if (newInstanceRisk) newInstanceRisk.value = '100';
                const newInstanceProfitLimit = document.getElementById('new-instance-profit-limit');
                if (newInstanceProfitLimit) newInstanceProfitLimit.value = '0';
                if (newInstanceMapping) newInstanceMapping.value = '';
                const newInstanceAuto = document.getElementById('new-instance-auto');
                if (newInstanceAuto) newInstanceAuto.checked = false;
                if (newInstanceTimeframe) newInstanceTimeframe.value = 'all';"""
exact_replace(r_reset2, """                if (newInstanceMapping) newInstanceMapping.value = '';""")

with open('d:/Coding/risk_monitor/mt5_bridge/static/main.js', 'w', encoding='utf-8') as f:
    f.write(content)
print("Fix script completed.")
