function renderHealthCards(instances) {
    const grid = document.getElementById('health-cards-grid');
    if (!grid) return;
    
    instances.forEach(inst => {
        const mlColor = inst.margin_level < 100 ? 'var(--color-sell)' : (inst.margin_level < 300 ? 'orange' : 'var(--color-buy)');
        const bal = inst.balance.toFixed(2);
        const eq = inst.equity.toFixed(2);
        const ml = inst.margin_level > 0 ? inst.margin_level.toFixed(2) + '%' : 'N/A';
        const riskUsd = inst.total_risk_usd.toFixed(2);
        const riskPct = inst.balance > 0 ? ((inst.total_risk_usd / inst.balance) * 100).toFixed(2) : '0.00';
        
        let riskColor = 'var(--text-primary)';
        if (riskPct > 5) riskColor = 'var(--color-sell)';
        else if (riskPct > 2) riskColor = 'orange';

        let card = document.getElementById(`health-card-${inst.id}`);
        if (!card) {
            card = document.createElement('div');
            card.id = `health-card-${inst.id}`;
            card.className = "setting-card";
            card.style = "display: flex; flex-direction: column; padding: 12px;";
            
            card.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; margin-bottom: 8px;">
                    <strong style="font-size: 14px; color: var(--text-primary);">${inst.name}</strong>
                    <button class="btn-toolbar" style="color: var(--color-sell); border-color: var(--color-sell); padding: 2px 6px; font-size: 10px;">Close All</button>
                </div>
                
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="color: var(--text-secondary); font-size: 11px;">Balance / Equity</span>
                    <strong id="card-bal-eq-${inst.id}" style="font-size: 12px;">$${bal} / $${eq}</strong>
                </div>
                
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="color: var(--text-secondary); font-size: 11px;">Margin Level</span>
                    <strong id="card-ml-${inst.id}" style="font-size: 12px; color: ${mlColor};">${ml}</strong>
                </div>
                
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="color: var(--text-secondary); font-size: 11px;">Open Trades</span>
                    <strong id="card-trades-${inst.id}" style="font-size: 12px;">${inst.positions.length}</strong>
                </div>
                
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <span style="color: var(--text-secondary); font-size: 11px;">Total Risk</span>
                    <strong id="card-risk-${inst.id}" style="font-size: 12px; color: ${riskColor};">$${riskUsd} (${riskPct}%)</strong>
                </div>
                
                <div style="height: 120px; width: 100%; margin-top: auto; padding-top: 10px; border: 1px dashed rgba(255,255,255,0.2); position: relative;">
                    <canvas id="equity-chart-${inst.id}"></canvas>
                </div>
            `;
            grid.appendChild(card);
        } else {
            document.getElementById(`card-bal-eq-${inst.id}`).innerText = `$${bal} / $${eq}`;
            
            const mlEl = document.getElementById(`card-ml-${inst.id}`);
            mlEl.innerText = ml;
            mlEl.style.color = mlColor;
            
            document.getElementById(`card-trades-${inst.id}`).innerText = inst.positions.length;
            
            const riskEl = document.getElementById(`card-risk-${inst.id}`);
            riskEl.innerText = `$${riskUsd} (${riskPct}%)`;
            riskEl.style.color = riskColor;
            
            // Force inject canvas container if it's missing (e.g., from old cache)
            if (!document.getElementById(`equity-chart-${inst.id}`)) {
                const chartDiv = document.createElement('div');
                chartDiv.style = "height: 120px; width: 100%; margin-top: auto; padding-top: 10px; position: relative;";
                chartDiv.innerHTML = `<canvas id="equity-chart-${inst.id}"></canvas>`;
                card.appendChild(chartDiv);
            }
        }
        
        // Update charts with historical data
        const canvas = document.getElementById(`equity-chart-${inst.id}`);
        if (!canvas) return;
        
        const labels = inst.historical_equity ? inst.historical_equity.labels : [];
        const data = inst.historical_equity ? inst.historical_equity.data : [];
        
        if (!equityCharts[inst.id]) {
            if (typeof Chart !== 'undefined') {
                const ctx = canvas.getContext('2d');
                equityCharts[inst.id] = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Equity/Balance',
                            data: data,
                            borderColor: '#2196f3',
                            backgroundColor: 'rgba(33, 150, 243, 0.1)',
                            fill: true,
                            tension: 0.2,
                            pointRadius: 3, // Make points slightly visible for daily ticks
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        scales: {
                            x: { 
                                display: true, 
                                ticks: { font: {size: 9}, color: 'var(--text-muted)' },
                                grid: { display: false }
                            },
                            y: { 
                                display: true, ticks: { font: {size: 9}, color: 'var(--text-muted)' } 
                            }
                        },
                        plugins: { 
                            legend: { display: false }, 
                            tooltip: { 
                                enabled: true,
                                callbacks: {
                                    label: function(context) {
                                        let label = context.dataset.label || '';
                                        if (label) {
                                            label += ': ';
                                        }
                                        if (context.parsed.y !== null) {
                                            label += new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(context.parsed.y);
                                        }
                                        return label;
                                    }
                                }
                            } 
                        }
                    }
                });
            }
        } else {
            document.getElementById(`card-bal-eq-${inst.id}`).innerText = `$${bal} / $${eq}`;
            
            const mlEl = document.getElementById(`card-ml-${inst.id}`);
            mlEl.innerText = ml;
            mlEl.style.color = mlColor;
            
            document.getElementById(`card-trades-${inst.id}`).innerText = inst.positions.length;
            
            const riskEl = document.getElementById(`card-risk-${inst.id}`);
            riskEl.innerText = `$${riskUsd} (${riskPct}%)`;
            riskEl.style.color = riskColor;
            
            // Force inject canvas container if it's missing (e.g., from old cache)
            if (!document.getElementById(`equity-chart-${inst.id}`)) {
                const chartDiv = document.createElement('div');
                chartDiv.style = "height: 120px; width: 100%; margin-top: auto; padding-top: 10px; position: relative;";
                chartDiv.innerHTML = `<canvas id="equity-chart-${inst.id}"></canvas>`;
                card.appendChild(chartDiv);
            }
        }
    });
}
const activePosExpanded = {};

function renderActivePositions(instances) {
    const tbody = document.getElementById('active-positions-tbody');
    if (!tbody) return;
    
    let html = '';
    
    instances.forEach(inst => {
        if (inst.positions.length === 0) return;
        
        const nodeId = `inst_pos_${inst.id}`;
        if (activePosExpanded[nodeId] === undefined) {
            activePosExpanded[nodeId] = true; 
        }
        const isExpanded = activePosExpanded[nodeId];
        
        let instProfit = 0;
        inst.positions.forEach(p => instProfit += p.profit);
        const profColor = instProfit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)';
        
        html += `
            <tr class="tree-header tree-toggle" style="cursor: pointer;" onclick="toggleActivePos('${nodeId}')">
                <td colspan="8">
                    <span class="toggle-icon ${isExpanded ? '' : 'collapsed'}">▼</span>
                    <strong>${inst.name}</strong> 
                    <span style="font-size: 11px; color: var(--text-muted); margin-left: 10px;">${inst.positions.length} Trades</span>
                    <span style="float: right; color: ${profColor}; font-weight: bold;">$${instProfit.toFixed(2)}</span>
                </td>
            </tr>
        `;
        
        if (isExpanded) {
            inst.positions.forEach(p => {
                const pColor = p.profit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)';
                const tClass = p.type === 'BUY' ? 'bdg-buy' : 'bdg-sell';
                const distSlStr = p.dist_sl >= 0 ? p.dist_sl.toFixed(1) : 'No SL';
                
                html += `
                    <tr>
                        <td class="indent-1">
                            <strong>${p.symbol}</strong><br>
                            <span style="font-size: 9px; color: var(--text-muted);">${p.ticket}</span>
                        </td>
                        <td><span class="badge-dense ${tClass}">${p.type}</span></td>
                        <td>${p.volume}</td>
                        <td>${p.price_open}</td>
                        <td>${p.price_current}</td>
                        <td>${distSlStr}</td>
                        <td>$${p.risk_usd.toFixed(2)}</td>
                        <td style="color: ${pColor}; font-weight: bold;">$${p.profit.toFixed(2)}</td>
                    </tr>
                `;
            });
        }
    });
    
    tbody.innerHTML = html;
}

window.toggleActivePos = function(nodeId) {
    activePosExpanded[nodeId] = !activePosExpanded[nodeId];
    // Next risk_data SSE tick will re-render with new state
};