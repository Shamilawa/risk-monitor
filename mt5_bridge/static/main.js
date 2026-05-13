document.addEventListener('DOMContentLoaded', () => {
    // --- Theme Toggling ---
    const themeBtn = document.getElementById('theme-toggle');
    const currentTheme = localStorage.getItem('theme') || 'light';

    if (currentTheme === 'dark') {
        document.body.setAttribute('data-theme', 'dark');
        themeBtn.innerText = 'Switch to Light Mode';
    } else {
        themeBtn.innerText = 'Switch to Dark Mode';
    }

    themeBtn.addEventListener('click', () => {
        if (document.body.getAttribute('data-theme') === 'dark') {
            document.body.removeAttribute('data-theme');
            localStorage.setItem('theme', 'light');
            themeBtn.innerText = 'Switch to Dark Mode';
        } else {
            document.body.setAttribute('data-theme', 'dark');
            localStorage.setItem('theme', 'dark');
            themeBtn.innerText = 'Switch to Light Mode';
        }
    });

    // --- Tooltip Component ---
    const tooltip = document.createElement('div');
    tooltip.className = 'custom-tooltip';
    document.body.appendChild(tooltip);

    function showTooltip(e, content) {
        tooltip.innerHTML = content;
        tooltip.classList.add('visible');
        moveTooltip(e);
    }

    function hideTooltip() {
        tooltip.classList.remove('visible');
    }

    function moveTooltip(e) {
        tooltip.style.left = `${e.pageX + 15}px`;
        tooltip.style.top = `${e.pageY + 15}px`;
    }

    const logTable = document.getElementById('log-table');
    if (logTable) {
        logTable.addEventListener('mouseover', (e) => {
            const badge = e.target.closest('.profit-badge');
            if (badge) {
                const raw = parseFloat(badge.dataset.raw).toFixed(2);
                const comm = parseFloat(badge.dataset.comm).toFixed(2);
                const swap = parseFloat(badge.dataset.swap).toFixed(2);
                const total = parseFloat(badge.dataset.total).toFixed(2);

                const content = `
                    <div class="tooltip-row"><span>Raw P&L</span><span>${raw}</span></div>
                    <div class="tooltip-row"><span>Commission</span><span>${comm}</span></div>
                    <div class="tooltip-row"><span>Swap</span><span>${swap}</span></div>
                    <div class="tooltip-divider"></div>
                    <div class="tooltip-row tooltip-total"><span>Total</span><span>${total}</span></div>
                `;
                showTooltip(e, content);
            }
        });

        logTable.addEventListener('mousemove', (e) => {
            if (e.target.closest('.profit-badge')) {
                moveTooltip(e);
            }
        });

        logTable.addEventListener('mouseout', (e) => {
            if (e.target.closest('.profit-badge')) {
                hideTooltip();
            }
        });
    }

    // --- UI Elements ---
    const webhookInput = document.getElementById('webhook-url');
    const copyBtn = document.getElementById('copy-btn');
    const logBox = document.getElementById('log-box');
    const trackerTbody = document.getElementById('tracker-tbody');
    const mt5StatusIcon = document.getElementById('mt5-status-icon');
    const mt5StatusText = document.getElementById('mt5-status-text');

    const modalOverlay = document.getElementById('trade-modal');
    const modalActionSymbol = document.getElementById('modal-action-symbol');
    const modalInfoGrid = document.getElementById('modal-info-grid');
    const modalSplitInfo = document.getElementById('modal-split-info');
    const btnExecute = document.getElementById('btn-execute');
    const btnAbort = document.getElementById('btn-abort');

    // State map to remember which nodes are expanded
    const expandedState = {};
    let currentFilter = 'all'; // 'all', 'active', 'pending'
    let currentTab = 'active'; // 'active', 'history'

    let currentTradePayload = null;
    fetchTracker();
    fetchInstances();

    // Copy Button
    copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(webhookInput.value).then(() => {
            const originalText = copyBtn.innerText;
            copyBtn.innerText = 'Copied!';
            setTimeout(() => { copyBtn.innerText = originalText; }, 2000);
        });
    });

    // --- SSE Connection ---
    const eventSource = new EventSource('/api/stream');

    eventSource.addEventListener('log', (e) => { appendLog(e.data); });
    eventSource.addEventListener('ngrok_url', (e) => { webhookInput.value = e.data; });
    eventSource.addEventListener('tracker_update', (e) => { fetchTracker(); });

    eventSource.addEventListener('mt5_status', (e) => {
        try {
            const status = JSON.parse(e.data);
            if (status.online) {
                mt5StatusIcon.className = 'status-icon online';
            } else {
                mt5StatusIcon.className = 'status-icon offline';
            }
            mt5StatusText.innerText = status.text;
        } catch (err) {
            console.error("Failed to parse mt5_status:", err);
            // Fallback for old simple string if any
            const isOnline = e.data === 'true';
            mt5StatusIcon.className = isOnline ? 'status-icon online' : 'status-icon offline';
            mt5StatusText.innerText = isOnline ? 'MT5 Connected' : 'MT5 Offline';
        }
    });

    eventSource.addEventListener('trade_signal', (e) => {
        const data = JSON.parse(e.data);
        showTradeModal(data);
    });

    eventSource.onerror = (err) => { console.error("SSE Error:", err); };

    // --- Functions ---
    function appendLog(message) {
        const div = document.createElement('div');
        div.className = 'log-line';

        let levelClass = 'info';
        if (message.includes('[ERROR]')) levelClass = 'error';
        if (message.includes('[WARNING]')) levelClass = 'warning';

        div.classList.add(levelClass);
        div.innerText = message;

        logBox.appendChild(div);
        if (logBox.childElementCount > 200) {
            logBox.removeChild(logBox.firstChild);
        }
        logBox.scrollTop = logBox.scrollHeight;
    }



    function fetchTracker() {
        fetch(`/api/tracker?tab=${currentTab}`)
            .then(res => res.json())
            .then(data => { renderTrackerTable(data); })
            .catch(err => console.error("Error fetching tracker:", err));
    }

    function fetchPerformance() {
        const logFilter = document.getElementById('log-instance-filter');
        const instId = logFilter ? logFilter.value : 'all';
        fetch(`/api/performance?instance_id=${instId}`)
            .then(res => res.json())
            .then(data => {
                renderPerformance(data);
            })
            .catch(err => console.error("Error fetching performance:", err));
    }

    function renderPerformance(data) {
        try {
            console.log("Rendering performance data:", data);
            
            if (!data.metrics) {
                console.error("No metrics in data");
                return;
            }

            const totalProfitEl = document.getElementById('metric-total-profit');
            const winRateEl = document.getElementById('metric-win-rate');
            const totalTradesEl = document.getElementById('metric-total-trades');
            const rrRatioEl = document.getElementById('metric-rr-ratio');
            const rawProfitEl = document.getElementById('metric-raw-profit');

            if (totalProfitEl) totalProfitEl.innerText = `$${(data.metrics.total_profit || 0).toFixed(2)}`;
            if (winRateEl) winRateEl.innerText = `${(data.metrics.win_rate || 0).toFixed(1)}%`;
            if (totalTradesEl) totalTradesEl.innerText = data.metrics.total_trades || 0;

            // Calculate new metrics
            let totalRawProfit = 0;
            let winningProfits = 0;
            let losingProfits = 0;
            let winCount = 0;
            let lossCount = 0;

            if (data.trades) {
                data.trades.forEach(t => {
                    totalRawProfit += t.raw_profit || 0;
                    if (t.profit > 0) {
                        winningProfits += t.profit;
                        winCount++;
                    } else if (t.profit < 0) {
                        losingProfits += Math.abs(t.profit);
                        lossCount++;
                    }
                });
            }

            const avgWin = winCount > 0 ? winningProfits / winCount : 0;
            const avgLoss = lossCount > 0 ? losingProfits / lossCount : 0;
            const rrRatio = avgLoss > 0 ? (avgWin / avgLoss).toFixed(2) : "N/A";

            if (rrRatioEl) rrRatioEl.innerText = `1:${rrRatio}`;
            if (rawProfitEl) rawProfitEl.innerText = `$${totalRawProfit.toFixed(2)}`;

            if (totalProfitEl) {
                if (data.metrics.total_profit > 0) {
                    totalProfitEl.style.color = 'var(--color-buy)';
                } else if (data.metrics.total_profit < 0) {
                    totalProfitEl.style.color = 'var(--color-sell)';
                } else {
                    totalProfitEl.style.color = 'var(--text-main)';
                }
            }

            if (rawProfitEl) {
                if (totalRawProfit > 0) {
                    rawProfitEl.style.color = 'var(--color-buy)';
                } else if (totalRawProfit < 0) {
                    rawProfitEl.style.color = 'var(--color-sell)';
                } else {
                    rawProfitEl.style.color = 'var(--text-main)';
                }
            }

            const tbody = document.getElementById('log-tbody');
            if (!tbody) return;
            
            tbody.innerHTML = '';

            if (!data.trades || data.trades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No trades found. Click Sync to fetch.</td></tr>';
                return;
            }

            data.trades.forEach(t => {
                const tr = document.createElement('tr');
                const date = new Date(t.time * 1000);
                const timeStr = date.toLocaleString();
                const profitClass = t.profit > 0 ? 'bdg-buy' : t.profit < 0 ? 'bdg-sell' : 'bdg-cancel';

                tr.innerHTML = `
                    <td>${timeStr}</td>
                    <td>${t.instance_name}</td>
                    <td>${t.symbol}</td>
                    <td><span class="badge-dense ${t.type === 'BUY' ? 'bdg-buy' : 'bdg-sell'}">${t.type}</span></td>
                    <td>${t.volume}</td>
                    <td><span class="badge-dense ${profitClass} profit-badge" data-raw="${t.raw_profit || 0}" data-comm="${t.commission || 0}" data-swap="${t.swap || 0}" data-total="${t.profit}">${t.profit.toFixed(2)}</span></td>
                    <td>${t.magic}</td>
                `;
                tbody.appendChild(tr);
            });
            
            // Render Charts
            renderCharts(data.trades);
        } catch (error) {
            console.error("Error in renderPerformance:", error);
        }
    }

    function renderCharts(trades) {
        if (!trades || trades.length === 0) return;

        // Sort trades by time ascending for the curve
        const sortedTrades = [...trades].sort((a, b) => a.time - b.time);

        let cumulativeProfit = 0;
        const equityData = [];
        const labels = [];
        const drawdownData = [];
        let peak = 0;

        sortedTrades.forEach((t, index) => {
            cumulativeProfit += t.profit;
            equityData.push(cumulativeProfit);
            labels.push(new Date(t.time * 1000).toLocaleDateString());

            if (cumulativeProfit > peak) {
                peak = cumulativeProfit;
            }
            const dd = peak - cumulativeProfit;
            drawdownData.push(-dd); // Store as negative value for drop
        });

        // Render Equity Chart
        const equityCtx = document.getElementById('equity-chart');
        if (equityCtx) {
            const ctx = equityCtx.getContext('2d');
            if (window.equityChartInstance) window.equityChartInstance.destroy();
            
            window.equityChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Equity',
                        data: equityData,
                        borderColor: '#1976d2',
                        backgroundColor: 'rgba(25, 118, 210, 0.1)',
                        fill: true,
                        tension: 0.1,
                        pointRadius: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { display: false },
                        y: { grid: { color: 'rgba(255,255,255,0.05)' } }
                    },
                    plugins: {
                        legend: { display: false }
                    }
                }
            });
        }

        // Render Drawdown Chart
        const ddCtx = document.getElementById('drawdown-chart');
        if (ddCtx) {
            const ctx = ddCtx.getContext('2d');
            if (window.drawdownChartInstance) window.drawdownChartInstance.destroy();
            
            window.drawdownChartInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Drawdown',
                        data: drawdownData,
                        backgroundColor: 'rgba(211, 47, 47, 0.5)',
                        borderColor: '#d32f2f',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { display: false },
                        y: { grid: { color: 'rgba(255,255,255,0.05)' } }
                    },
                    plugins: {
                        legend: { display: false }
                    }
                }
            });
        }
    }

    function toggleNode(nodeId) {
        if (expandedState[nodeId] === undefined) {
            expandedState[nodeId] = true; // default is collapsed, so first click expands
        } else {
            expandedState[nodeId] = !expandedState[nodeId];
        }
        fetchTracker(); // re-render to apply state
    }

    // Attach click handler to table using event delegation
    trackerTbody.addEventListener('click', (e) => {
        if (e.target.classList.contains('btn-retry')) {
            const tradeId = e.target.getAttribute('data-id');
            e.target.innerText = "Retrying...";
            fetch('/api/retry_trade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: tradeId })
            }).then(res => res.json()).then(data => {
                if (data.status !== 'success') {
                    alert("Retry failed: " + (data.error || "Unknown"));
                }
                fetchTracker();
            }).catch(err => {
                alert("Retry error: " + err);
                fetchTracker();
            });
            return;
        }

        const toggleRow = e.target.closest('.tree-toggle');
        if (toggleRow) {
            const nodeId = toggleRow.getAttribute('data-node-id');
            if (nodeId) {
                toggleNode(nodeId);
            }
        }
    });

    // Filter Buttons
    const filterBtns = document.querySelectorAll('.btn-filter');
    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.getAttribute('data-filter');
            fetchTracker();
        });
    });

    // Log Sync Button
    const btnSyncLog = document.getElementById('btn-sync-log');
    if (btnSyncLog) {
        btnSyncLog.addEventListener('click', () => {
            btnSyncLog.innerText = "Syncing...";
            btnSyncLog.disabled = true;
            fetch('/api/sync_log', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    alert(`Sync complete! Synced ${data.synced} new deals.`);
                    btnSyncLog.innerText = "Sync Trades";
                    btnSyncLog.disabled = false;
                    fetchPerformance();
                })
                .catch(err => {
                    console.error("Sync error:", err);
                    btnSyncLog.innerText = "Sync Trades";
                    btnSyncLog.disabled = false;
                    alert("Sync failed: " + err);
                });
        });
    }

    // Log Instance Filter
    const logInstanceFilter = document.getElementById('log-instance-filter');
    if (logInstanceFilter) {
        logInstanceFilter.addEventListener('change', () => {
            fetchPerformance();
        });
    }

    const tabs = document.querySelectorAll('.grid-section .section-toolbar .tab');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentTab = tab.getAttribute('data-tab');

            const filterGroup = document.getElementById('tracker-filters');
            const mainTableContainer = document.querySelector('.grid-section > .table-container');
            const logContainer = document.getElementById('trading-log-container');

            if (currentTab === 'log') {
                if (filterGroup) filterGroup.style.display = 'none';
                if (mainTableContainer) mainTableContainer.style.display = 'none';
                if (logContainer) logContainer.style.display = 'flex';
                fetchPerformance();
            } else {
                if (filterGroup) {
                    if (currentTab === 'history') {
                        filterGroup.style.display = 'none';
                    } else {
                        filterGroup.style.display = 'flex';
                    }
                }
                if (mainTableContainer) mainTableContainer.style.display = 'block';
                if (logContainer) logContainer.style.display = 'none';
                fetchTracker();
            }
        });
    });

    function getFriendlyStatus(status, isGroup = false) {
        if (!status) return 'Unknown';

        if (isGroup) {
            if (status === 'PENDING_ORIGINAL') return 'Original Orders Pending';
            if (status === 'ACTIVE') return 'Original Trades Live';
            if (status === 'SUCCESS_TP1_HIT') return 'TP1 Hit (Complete)';
            if (status === 'RECOVERY_TRIGGERED') return 'Recovery Mode Active';
            if (status === 'RECOVERY_SUCCESS') return 'Recovery Successful';
            if (status === 'RECOVERY_FAILED') return 'Recovery Failed';
            if (status === 'CANCELLED') return 'Cancelled';
            return status;
        } else {
            if (status === 'PENDING_ORIGINAL' || status === 'PENDING (Placed)') return 'Pending';
            if (status === 'ACTIVE') return 'Live';
            if (status === 'SUCCESS_TP1_HIT') return 'TP Hit';
            if (status === 'RECOVERY_SUCCESS') return 'TP Hit';
            if (status === 'RECOVERY_FAILED') return 'SL Hit';
            if (status === 'SL_HIT') return 'SL Hit';
            if (status === 'CANCELLED') return 'Cancelled';
            if (status === 'FAILED_EXECUTION') return 'Failed to Execute';
            return status;
        }
    }

    function renderTrackerTable(rows) {
        const trackerThead = document.querySelector('#tracker-table thead');

        if (currentTab === 'history') {
            trackerThead.innerHTML = `
                <tr>
                    <th style="width: 15%;">Symbol</th>
                    <th style="width: 20%;">Instance</th>
                    <th style="width: 15%;">Ticket</th>
                    <th style="width: 20%;">Trade Type</th>
                    <th style="width: 30%;">Status</th>
                </tr>
            `;
        } else {
            trackerThead.innerHTML = `
                <tr>
                    <th style="width: 20%;">Symbol / Group</th>
                    <th style="width: 15%;">Instance</th>
                    <th style="width: 15%;">Ticket</th>
                    <th style="width: 15%;">Trade Type</th>
                    <th style="width: 35%;">Status</th>
                </tr>
            `;
        }

        trackerTbody.innerHTML = '';
        if (!rows || rows.length === 0) return;

        if (currentTab === 'active') {
            const symbols = {};
            rows.forEach(r => {
                const sym = r.symbol;
                if (!symbols[sym]) symbols[sym] = [];
                symbols[sym].push(r);
            });

            for (const [sym, groups] of Object.entries(symbols)) {
                const symNodeId = `sym_${sym}`;
                const symExpanded = expandedState[symNodeId] === true; // Default to false (collapsed)

                // Apply Filter to groups
                const filteredGroups = groups.filter(g => {
                    if (currentFilter === 'all') return true;
                    if (currentFilter === 'active') return g.status === 'ACTIVE' || g.status === 'RECOVERY_TRIGGERED';
                    if (currentFilter === 'pending') return g.status.startsWith('PENDING');
                    return true;
                });

                if (filteredGroups.length === 0) continue; // Skip symbol if no groups match

                // Group Header (Symbol)
                trackerTbody.innerHTML += `
                    <tr class="tree-header tree-toggle" data-node-id="${symNodeId}">
                        <td colspan="5">
                            <span class="toggle-icon ${symExpanded ? '' : 'collapsed'}">▼</span>
                            <strong>${sym}</strong> <span style="font-size: 10px; color: var(--text-muted);">(${filteredGroups.length} Groups)</span>
                        </td>
                    </tr>
                `;

                if (symExpanded) {
                    filteredGroups.forEach(g => {
                        const groupNodeId = `grp_${g.id}`;
                        const groupExpanded = expandedState[groupNodeId] === true; // Default to false

                        // Group Row
                        let retryBtn = '';
                        if (g.status === 'FAILED_EXECUTION') {
                            retryBtn = `<button class="btn-toolbar btn-retry" data-id="${g.id}" style="padding: 2px 6px; font-size: 10px; margin-left: 5px;">Retry</button>`;
                        }

                        trackerTbody.innerHTML += `
                            <tr class="tree-toggle" data-node-id="${groupNodeId}">
                                <td class="indent-1">
                                    <span class="toggle-icon ${groupExpanded ? '' : 'collapsed'}">▼</span>
                                    Magic: ${g.magic_number}
                                </td>
                                <td>${g.instance_name}</td>
                                <td></td>
                                <td>Trade Group</td>
                                <td><span class="badge-dense ${getBadgeClass(g.status)}">${getFriendlyStatus(g.status, true)}</span>${retryBtn}</td>
                            </tr>
                        `;

                        if (groupExpanded) {
                            // Compute status for original child trades
                            let childStatus = g.status;
                            if (g.status === 'RECOVERY_TRIGGERED' || g.status === 'RECOVERY_SUCCESS' || g.status === 'RECOVERY_FAILED') {
                                childStatus = 'SL_HIT';
                            }

                            // Orig 1
                            trackerTbody.innerHTML += `
                                <tr>
                                    <td class="indent-2">Orig 1 (TP1)</td>
                                    <td></td>
                                    <td>${g.trade_1_ticket || 'N/A'}</td>
                                    <td>Original</td>
                                    <td><span class="badge-dense ${getBadgeClass(childStatus)}">${getFriendlyStatus(childStatus, false)}</span></td>
                                </tr>
                            `;

                            // Orig 2
                            if (g.trade_2_ticket) {
                                trackerTbody.innerHTML += `
                                    <tr>
                                        <td class="indent-2">Orig 2 (TP2)</td>
                                        <td></td>
                                        <td>${g.trade_2_ticket}</td>
                                        <td>Original</td>
                                        <td><span class="badge-dense ${getBadgeClass(childStatus)}">${getFriendlyStatus(childStatus, false)}</span></td>
                                    </tr>
                                `;
                            }

                            // Recovery
                            let recStatus = g.status === 'PENDING_ORIGINAL' && !g.recovery_ticket ? 'PENDING_ORIGINAL' : g.status;
                            if (g.status === 'SUCCESS_TP1_HIT') recStatus = 'CANCELLED';
                            else if (g.status === 'RECOVERY_TRIGGERED') recStatus = 'ACTIVE';
                            else if (g.status === 'CANCELLED') recStatus = 'CANCELLED';
                            else if (g.recovery_ticket) recStatus = g.status === 'ACTIVE' ? 'PENDING (Placed)' : g.status;

                            trackerTbody.innerHTML += `
                                <tr>
                                    <td class="indent-2">Recovery</td>
                                    <td></td>
                                    <td>${g.recovery_ticket || 'N/A'}</td>
                                    <td>Recovery</td>
                                    <td><span class="badge-dense ${getBadgeClass(recStatus)}">${getFriendlyStatus(recStatus, false)}</span></td>
                                </tr>
                            `;
                        }
                    });
                }
            }
        } else {
            // History Tab: Flat list of groups with Symbol column
            rows.forEach(g => {
                const groupNodeId = `grp_hist_${g.magic_number}`;
                const groupExpanded = expandedState[groupNodeId] === true;

                // Group Row (5 columns)
                trackerTbody.innerHTML += `
                    <tr class="tree-toggle" data-node-id="${groupNodeId}">
                        <td>${g.symbol}</td>
                        <td class="indent-1">
                            <span class="toggle-icon ${groupExpanded ? '' : 'collapsed'}">▼</span>
                            Magic: ${g.magic_number} (${g.instance_name})
                        </td>
                        <td></td>
                        <td>Trade Group</td>
                        <td><span class="badge-dense ${getBadgeClass(g.status)}">${getFriendlyStatus(g.status, true)}</span></td>
                    </tr>
                `;

                if (groupExpanded) {
                    // Compute status for original child trades
                    let childStatus = g.status;
                    if (g.status === 'RECOVERY_TRIGGERED' || g.status === 'RECOVERY_SUCCESS' || g.status === 'RECOVERY_FAILED') {
                        childStatus = 'SL_HIT';
                    }

                    // Orig 1
                    trackerTbody.innerHTML += `
                        <tr>
                            <td></td>
                            <td class="indent-2">Orig 1 (TP1)</td>
                            <td>${g.trade_1_ticket || 'N/A'}</td>
                            <td>Original</td>
                            <td><span class="badge-dense ${getBadgeClass(childStatus)}">${getFriendlyStatus(childStatus, false)}</span></td>
                        </tr>
                    `;

                    // Orig 2
                    if (g.trade_2_ticket) {
                        trackerTbody.innerHTML += `
                            <tr>
                                <td></td>
                                <td class="indent-2">Orig 2 (TP2)</td>
                                <td>${g.trade_2_ticket}</td>
                                <td>Original</td>
                                <td><span class="badge-dense ${getBadgeClass(childStatus)}">${getFriendlyStatus(childStatus, false)}</span></td>
                            </tr>
                        `;
                    }

                    // Recovery
                    let recStatus = g.status === 'PENDING_ORIGINAL' && !g.recovery_ticket ? 'PENDING_ORIGINAL' : g.status;
                    if (g.status === 'SUCCESS_TP1_HIT') recStatus = 'CANCELLED';
                    else if (g.status === 'RECOVERY_TRIGGERED') recStatus = 'ACTIVE';
                    else if (g.status === 'CANCELLED') recStatus = 'CANCELLED';
                    else if (g.recovery_ticket) recStatus = g.status === 'ACTIVE' ? 'PENDING (Placed)' : g.status;

                    trackerTbody.innerHTML += `
                        <tr>
                            <td></td>
                            <td class="indent-2">Recovery</td>
                            <td>${g.recovery_ticket || 'N/A'}</td>
                            <td>Recovery</td>
                            <td><span class="badge-dense ${getBadgeClass(recStatus)}">${getFriendlyStatus(recStatus, false)}</span></td>
                        </tr>
                    `;
                }
            });
        }
    }

    function getBadgeClass(status) {
        if (!status) return 'bdg-cancel';
        if (status === 'ACTIVE') return 'bdg-active';
        if (status.startsWith('PENDING')) return 'bdg-pending';
        if (status === 'SUCCESS_TP1_HIT' || status === 'RECOVERY_SUCCESS') return 'bdg-buy';
        if (status === 'RECOVERY_TRIGGERED' || status === 'RECOVERY_FAILED' || status === 'SL_HIT') return 'bdg-sell';
        if (status === 'CANCELLED') return 'bdg-cancel';
        return 'bdg-cancel';
    }

    // --- Modal Logic ---
    function showTradeModal(data) {
        currentTradePayload = data;

        const action = (data.action || '').toUpperCase();
        const symbol = data.symbol || '';

        modalActionSymbol.innerText = `${action} ${symbol}`;
        modalActionSymbol.className = `action-banner ${action === 'BUY' ? 'buy' : 'sell'}`;

        modalInfoGrid.innerHTML = '';
        function addRow(label, value) {
            modalInfoGrid.innerHTML += `<tr><td>${label}</td><td>${value}</td></tr>`;
        }

        const entryStr = data.entry > 0 ? `${data.entry} (Limit/Stop)` : "Market";
        addRow("Entry Level", entryStr);
        addRow("Stop Loss", data.sl);
        addRow("Take Profit 1", data.tp1);
        if (data.tp2) addRow("Take Profit 2", data.tp2);

        modalSplitInfo.innerHTML = '';
        if (data.instance_executions && data.instance_executions.length > 0) {
            let html = '<div style="margin-top: 10px; font-weight: bold; color: var(--text-primary); border-bottom: 1px solid var(--border-color); padding-bottom: 4px; margin-bottom: 8px;">Executions per Instance:</div>';
            data.instance_executions.forEach(exec => {
                html += `<div style="margin-bottom: 8px;">`;
                html += `<strong>${exec.name}</strong> <span style="font-size: 11px; color: var(--text-muted);">($${exec.risk_usd} Risk)</span><br>`;
                if (exec.split_trade) {
                    html += `<span style="font-size: 12px; color: var(--text-secondary);">Total: ${exec.calculated_volume} Lots &nbsp;&rarr;&nbsp; [1] ${exec.vol1} (TP1) &nbsp; [2] ${exec.vol2} (TP2)</span>`;
                } else {
                    html += `<span style="font-size: 12px; color: var(--text-secondary);">Total: ${exec.calculated_volume} Lots (Single) - ${exec.split_reason}</span>`;
                }
                html += `</div>`;
            });
            modalSplitInfo.innerHTML = html;
        }

        modalOverlay.classList.add('active');
    }

    btnExecute.addEventListener('click', () => {
        if (!currentTradePayload) return;

        fetch('/api/execute_trade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentTradePayload)
        })
            .then(res => res.json())
            .then(data => {
                modalOverlay.classList.remove('active');
                currentTradePayload = null;
            })
            .catch(err => console.error("Execute error:", err));
    });

    btnAbort.addEventListener('click', () => {
        fetch('/api/abort_trade', { method: 'POST' })
            .then(() => {
                modalOverlay.classList.remove('active');
                currentTradePayload = null;
            })
            .catch(err => console.error("Abort error:", err));
    });

    // --- Settings Modal Logic ---
    const btnSettings = document.getElementById('btn-settings');
    const settingsModal = document.getElementById('settings-modal');
    const btnCloseSettings = document.getElementById('btn-close-settings');
    const instanceList = document.getElementById('instance-list');
    const btnAddInstance = document.getElementById('btn-add-instance');
    const newInstanceName = document.getElementById('new-instance-name');
    const newInstancePath = document.getElementById('new-instance-path');
    const btnBrowsePath = document.getElementById('btn-browse-path');
    const newInstanceRisk = document.getElementById('new-instance-risk');
    const newInstanceSuffix = document.getElementById('new-instance-suffix');

    if (btnSettings) {
        btnSettings.addEventListener('click', () => {
            settingsModal.classList.add('active');
            fetchInstances();
        });
    }

    if (btnCloseSettings) {
        btnCloseSettings.addEventListener('click', () => {
            settingsModal.classList.remove('active');
        });
    }

    function fetchInstances() {
        const instanceList = document.getElementById('instance-list');
        if (!instanceList) return;
        fetch('/api/instances')
            .then(res => res.json())
            .then(data => {
                instanceList.innerHTML = '';

                const logFilter = document.getElementById('log-instance-filter');
                if (logFilter) {
                    const currentVal = logFilter.value;
                    logFilter.innerHTML = '<option value="all">All Instances</option>';
                    data.forEach(inst => {
                        const opt = document.createElement('option');
                        opt.value = inst.id;
                        opt.innerText = inst.name;
                        logFilter.appendChild(opt);
                    });
                    logFilter.value = currentVal || 'all';
                }

                if (data.length === 0) {
                    instanceList.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; padding: 10px;">No instances configured. Executing on default MT5.</div>';
                    return;
                }
                data.forEach(inst => {
                    const div = document.createElement('div');
                    div.style = 'display: flex; justify-content: space-between; align-items: center; padding: 8px; background: var(--bg-secondary); border: 1px solid var(--border-color); margin-bottom: 5px;';
                    div.innerHTML = `
                        <div>
                            <strong>${inst.name}</strong> <span style="font-size: 11px; color: #10b981; margin-left: 5px;">$${inst.risk_usd || 100} Risk</span> ${inst.symbol_suffix ? `<span style="font-size: 11px; color: #64b5f6; margin-left: 5px;">(${inst.symbol_suffix} Suffix)</span>` : ''}<br>
                            <span style="font-size: 10px; color: var(--text-muted);">${inst.path}</span>
                        </div>
                        <button class="btn-toolbar btn-delete-inst" data-id="${inst.id}" style="color: #fca5a5; border-color: #7f1d1d;">Remove</button>
                    `;
                    instanceList.appendChild(div);
                });
            });
    }

    if (instanceList) {
        instanceList.addEventListener('click', (e) => {
            if (e.target.classList.contains('btn-delete-inst')) {
                const id = e.target.getAttribute('data-id');
                fetch('/api/instances', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: id })
                }).then(() => fetchInstances());
            }
        });
    }

    if (btnAddInstance) {
        btnAddInstance.addEventListener('click', () => {
            const name = newInstanceName.value;
            const path = newInstancePath.value;
            const risk_usd = parseFloat(newInstanceRisk.value || 100);
            const symbol_suffix = newInstanceSuffix ? newInstanceSuffix.value : '';
            if (!name || !path) { alert("Please enter name and path"); return; }
            fetch('/api/instances', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, path, risk_usd, symbol_suffix })
            }).then(() => {
                newInstanceName.value = '';
                newInstancePath.value = '';
                if (newInstanceRisk) newInstanceRisk.value = '100';
                if (newInstanceSuffix) newInstanceSuffix.value = '';
                fetchInstances();
            });
        });
    }

    if (btnBrowsePath) {
        btnBrowsePath.addEventListener('click', () => {
            fetch('/api/browse_file')
                .then(res => res.json())
                .then(data => {
                    if (data.path) {
                        newInstancePath.value = data.path;
                    }
                })
                .catch(err => console.error("Browse file error:", err));
        });
    }
});
