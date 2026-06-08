document.addEventListener('DOMContentLoaded', () => {
    // Force dark mode
    document.body.setAttribute('data-theme', 'dark');
    localStorage.setItem('theme', 'dark');

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
    const trackerTbody = document.getElementById('log-tbody');
        if (!trackerTbody) return;
    const mt5StatusIcon = document.getElementById('mt5-status-icon');
    const mt5StatusText = document.getElementById('mt5-status-text');

    const modalOverlay = document.getElementById('trade-modal');
    const modalActionSymbol = document.getElementById('modal-action-symbol');
    const modalInfoGrid = document.getElementById('modal-info-grid');
    const modalSplitInfo = document.getElementById('modal-split-info');
    const btnExecute = document.getElementById('btn-execute');
    const btnAbort = document.getElementById('btn-abort');
    const btnDismiss = document.getElementById('btn-dismiss');

    // State map to remember which nodes are expanded
    const expandedState = {};
    let currentFilter = 'all'; // 'all', 'active', 'pending'
    let currentTab = 'active'; // 'active', 'history'

    let currentTradePayload = null;
    let signalQueue = [];
    let modalIsOpen = false;
    const alertAudio = new Audio('/signal_alert.wav');
    fetchTracker();
    fetchInstances();
    fetchGlobalSettings();

    // Copy Button
    if (copyBtn) copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(webhookInput.value).then(() => {
            const originalText = copyBtn.innerText;
            copyBtn.innerText = 'Copied!';
            setTimeout(() => { copyBtn.innerText = originalText; }, 2000);
        });
    });

    // Panic Button
    const btnPanicAll = document.getElementById('btn-panic-all');
    let panicConfirmState = false;
    let panicTimeout;
    
    if (btnPanicAll) {
        btnPanicAll.addEventListener('click', () => {
            if (!panicConfirmState) {
                panicConfirmState = true;
                btnPanicAll.innerText = 'CONFIRM CLOSE ALL';
                btnPanicAll.style.background = '#f23645';
                btnPanicAll.style.color = '#fff';
                
                panicTimeout = setTimeout(() => {
                    panicConfirmState = false;
                    btnPanicAll.innerText = 'CLOSE ALL (2-Click)';
                    btnPanicAll.style.background = 'rgba(242, 54, 69, 0.2)';
                    btnPanicAll.style.color = '#f23645';
                }, 3000);
            } else {
                clearTimeout(panicTimeout);
                panicConfirmState = false;
                btnPanicAll.innerText = 'CLOSING...';
                
                fetch('/api/close_all', { method: 'POST' })
                    .then(res => res.json())
                    .then(data => {
                        console.log(data.message);
                        setTimeout(() => {
                            btnPanicAll.innerText = 'CLOSE ALL (2-Click)';
                            btnPanicAll.style.background = 'rgba(242, 54, 69, 0.2)';
                            btnPanicAll.style.color = '#f23645';
                        }, 1000);
                    });
            }
        });
    }

    // --- SSE Connection ---
    const eventSource = new EventSource('/api/stream');

    eventSource.addEventListener('log', (e) => { appendLog(e.data); });
    eventSource.addEventListener('ngrok_url', (e) => { webhookInput.value = e.data; });
    eventSource.addEventListener('tracker_update', (e) => { fetchTracker(); });
    
    eventSource.addEventListener('trade_sound', (e) => {
        alertAudio.currentTime = 0;
        alertAudio.play().catch(e => console.error("Error playing sound:", e));
    });

    eventSource.addEventListener('mt5_status', (e) => {
        try {
            const status = JSON.parse(e.data);
            if (status.online) {
                if(mt5StatusIcon) mt5StatusIcon.className = 'status-icon online';
            } else {
                if(mt5StatusIcon) mt5StatusIcon.className = 'status-icon offline';
            }
            if(mt5StatusText) mt5StatusText.innerText = status.text;
        } catch (err) {
            console.error("Failed to parse mt5_status:", err);
            // Fallback for old simple string if any
            const isOnline = e.data === 'true';
            if(mt5StatusIcon) mt5StatusIcon.className = isOnline ? 'status-icon online' : 'status-icon offline';
            if(mt5StatusText) mt5StatusText.innerText = isOnline ? 'MT5 Connected' : 'MT5 Offline';
        }
    });

    eventSource.addEventListener('trade_signal', (e) => {
        const data = JSON.parse(e.data);
        signalQueue.push(data);
        
        if (modalIsOpen) {
            // Play sound for concurrent signal since modal won't "open" again
            alertAudio.currentTime = 0;
            alertAudio.play().catch(e => console.error("Error playing sound:", e));
        }
        
        const badge = document.getElementById('modal-signal-count');
        if (badge && modalIsOpen) {
            if (signalQueue.length > 1) {
                badge.innerText = `${signalQueue.length} Signals`;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }
        
        if (!modalIsOpen) {
            showNextSignal();
        }
    });

    eventSource.onerror = (err) => { console.error("SSE Error:", err); };

    // --- Functions ---
    function appendLog(message) {
        if (!logBox) return; // Guard for removed UI
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
        let url = `/api/performance?instance_id=${instId}`;
        
        const timeFilterEl = document.getElementById('log-time-filter');
        if (timeFilterEl) {
            const timeFilter = timeFilterEl.value;
            let startTime = null;
            let endTime = null;
            const now = new Date();
            
            if (timeFilter === 'today') {
                const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                startTime = Math.floor(d.getTime() / 1000);
            } else if (timeFilter === 'week') {
                const day = now.getDay() || 7;
                const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - day + 1);
                startTime = Math.floor(d.getTime() / 1000);
            } else if (timeFilter === 'month') {
                const d = new Date(now.getFullYear(), now.getMonth(), 1);
                startTime = Math.floor(d.getTime() / 1000);
            } else if (timeFilter === 'last_month') {
                const startD = new Date(now.getFullYear(), now.getMonth() - 1, 1);
                const endD = new Date(now.getFullYear(), now.getMonth(), 0, 23, 59, 59, 999);
                startTime = Math.floor(startD.getTime() / 1000);
                endTime = Math.floor(endD.getTime() / 1000);
            } else if (timeFilter === 'custom') {
                const startInput = document.getElementById('log-start-date').value;
                const endInput = document.getElementById('log-end-date').value;
                if (startInput) startTime = Math.floor(new Date(startInput + 'T00:00:00').getTime() / 1000);
                if (endInput) endTime = Math.floor(new Date(endInput + 'T23:59:59').getTime() / 1000);
            }
            
            if (startTime !== null) url += `&start_time=${startTime}`;
            if (endTime !== null) url += `&end_time=${endTime}`;
        }

        fetch(url)
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
                let timeDisplay = "";
                if (t.local_start_time && t.local_time) {
                    const startDate = new Date(t.local_start_time * 1000);
                    const endDate = new Date(t.local_time * 1000);
                    
                    const formatTime = (d) => {
                        let hours = d.getHours();
                        const ampm = hours >= 12 ? 'PM' : 'AM';
                        hours = hours % 12;
                        hours = hours ? hours : 12; 
                        const mins = d.getMinutes().toString().padStart(2, '0');
                        return `${hours}:${mins} ${ampm}`;
                    };
                    
                    const diffMs = endDate - startDate;
                    const diffMins = Math.floor(diffMs / 60000);
                    const diffHrs = Math.floor(diffMins / 60);
                    const remainingMins = diffMins % 60;
                    
                    let durStr = "";
                    if (diffHrs > 0) durStr += `${diffHrs}h `;
                    durStr += `${remainingMins}m`;
                    
                    const dateStr = endDate.toLocaleDateString();
                    
                    timeDisplay = `
                        <div style="font-size: 11px;">${dateStr}</div>
                        <div style="font-size: 10px; color: var(--text-muted);">${formatTime(startDate)} to ${formatTime(endDate)} <br>(${durStr})</div>
                    `;
                } else {
                    const fallbackDate = new Date((t.local_time || t.time) * 1000);
                    timeDisplay = fallbackDate.toLocaleString();
                }

                const profitClass = t.profit > 0 ? 'bdg-buy' : t.profit < 0 ? 'bdg-sell' : 'bdg-cancel';

                tr.setAttribute('data-id', t.id || t.ticket);
                tr.innerHTML = `
                    <td>${timeDisplay}</td>
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
    if (trackerTbody) trackerTbody.addEventListener('click', (e) => {
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

        if (e.target.classList.contains('btn-place-recovery')) {
            const tradeId = e.target.getAttribute('data-id');
            e.target.innerText = "Placing...";
            fetch('/api/place_recovery_trade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: tradeId })
            }).then(res => res.json()).then(data => {
                if (data.status !== 'success') {
                    alert("Failed to place recovery trade: " + (data.error || "Unknown"));
                }
                fetchTracker();
            }).catch(err => {
                alert("Error placing recovery trade: " + err);
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
        logInstanceFilter.addEventListener('change', () => fetchPerformance());
    }

    // Log Time Filter
    const logTimeFilter = document.getElementById('log-time-filter');
    const logCustomDates = document.getElementById('log-custom-dates');
    const logStartDate = document.getElementById('log-start-date');
    const logEndDate = document.getElementById('log-end-date');
    
    if (logTimeFilter) {
        logTimeFilter.addEventListener('change', () => {
            if (logTimeFilter.value === 'custom') {
                logCustomDates.style.display = 'flex';
                // Automatically fetch if dates are already filled in
                if (logStartDate.value || logEndDate.value) {
                    fetchPerformance();
                }
            } else {
                logCustomDates.style.display = 'none';
                fetchPerformance();
            }
        });
    }
    
    if (logStartDate) logStartDate.addEventListener('change', () => fetchPerformance());
    if (logEndDate) logEndDate.addEventListener('change', () => fetchPerformance());

    const tabs = document.querySelectorAll('.grid-section .section-toolbar .tab');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentTab = tab.getAttribute('data-tab');

            const overviewContainer = document.getElementById('overview-container');
            const logContainer = document.getElementById('trading-log-container');
            const storyContainer = document.getElementById('story-notes-container');
            
            if (overviewContainer) overviewContainer.style.display = 'none';
            if (logContainer) logContainer.style.display = 'none';
            if (storyContainer) storyContainer.style.display = 'none';

            if (currentTab === 'log') {
                if (logContainer) logContainer.style.display = 'flex';
                fetchPerformance();
            } else if (currentTab === 'story') {
                if (storyContainer) storyContainer.style.display = 'flex';
                fetchStoryDates();
            } else if (currentTab === 'overview') {
                if (overviewContainer) overviewContainer.style.display = 'flex';
            }
        });
    });

    const toggleDashBtn = document.getElementById('btn-toggle-dashboard');
    const mainWorkspace = document.getElementById('main-workspace');
    let currentDashboard = 'monitoring';
    
    if (toggleDashBtn) {
        toggleDashBtn.addEventListener('click', () => {
            if (currentDashboard === 'monitoring') {
                currentDashboard = 'review';
                toggleDashBtn.innerText = '◀ Monitoring';
                toggleDashBtn.style.color = 'var(--text-main)';
                toggleDashBtn.style.borderColor = 'var(--border-color)';
                
                mainWorkspace.className = 'workspace workspace-review';
                document.querySelector('.pane-overview').style.display = 'none';
                document.querySelector('.pane-positions').style.display = 'none';
                document.querySelector('.pane-trading').style.display = 'flex';
                document.querySelector('.pane-notes').style.display = 'flex';
                
                fetchPerformance();
                fetchStoryDates();
            } else {
                currentDashboard = 'monitoring';
                toggleDashBtn.innerText = 'Review Panel ➔';
                toggleDashBtn.style.color = 'var(--color-active)';
                toggleDashBtn.style.borderColor = 'var(--color-active)';
                
                mainWorkspace.className = 'workspace workspace-monitoring';
                document.querySelector('.pane-overview').style.display = 'flex';
                document.querySelector('.pane-positions').style.display = 'flex';
                document.querySelector('.pane-trading').style.display = 'none';
                document.querySelector('.pane-notes').style.display = 'none';
            }
        });
    }
    
    // Initial State
    if (mainWorkspace) {
        document.querySelector('.pane-trading').style.display = 'none';
        document.querySelector('.pane-notes').style.display = 'none';
    }

    function getFriendlyStatus(status, isGroup = false, isTP1 = false) {
        if (!status) return 'Unknown';

        if (isGroup) {
            if (status === 'PENDING_ORIGINAL') return 'Orders Pending';
            if (status === 'ACTIVE') return 'Live (Both Active)';
            if (status.startsWith('ACTIVE_T2')) return 'Live (T2 Running)';
            if (status === 'SUCCESS_TP2_HIT') return 'TP2 Hit (Closed)';
            if (status === 'CLOSED_T2_SL') return 'T2 Stopped (Closed)';
            if (status === 'SL_HIT') return 'SL Hit (Closed)';
            if (status === 'CANCELLED') return 'Cancelled';
            if (status === 'FAILED_EXECUTION') return 'Failed Execution';
            return status;
        } else {
            if (status === 'PENDING_ORIGINAL') return 'Pending';
            if (status === 'ACTIVE') return 'Live';
            
            if (status.startsWith('ACTIVE_T2')) {
                return isTP1 ? 'TP1 Hit (Closed)' : 'Live';
            }
            if (status === 'SUCCESS_TP2_HIT') {
                return isTP1 ? 'TP1 Hit (Closed)' : 'TP2 Hit (Closed)';
            }
            if (status === 'CLOSED_T2_SL') {
                return isTP1 ? 'TP1 Hit (Closed)' : 'Stopped Out (Closed)';
            }
            if (status === 'SL_HIT') return 'SL Hit';
            if (status === 'CANCELLED') return 'Cancelled';
            if (status === 'FAILED_EXECUTION') return 'Failed';
            
            return status;
        }
    }

    function renderTrackerTable(rows) {
        const trackerThead = document.querySelector('#tracker-table thead');
        if (!trackerThead) return;

        trackerThead.innerHTML = `
            <tr>
                <th style="width: 20%;">Symbol / Group</th>
                <th style="width: 15%;">Instance</th>
                <th style="width: 15%;">Ticket</th>
                <th style="width: 15%;">Trade Type</th>
                <th style="width: 35%;">Status</th>
            </tr>
        `;

        if(trackerTbody) trackerTbody.innerHTML = '';
        if (!rows || rows.length === 0) return;

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
                            <tr class="tree-toggle magic-row" data-node-id="${groupNodeId}">
                                <td class="indent-1">
                                    <span class="toggle-icon ${groupExpanded ? '' : 'collapsed'}">▼</span>
                                    Magic: ${g.magic_number}
                                </td>
                                <td>${g.instance_name}</td>
                                <td></td>
                                <td>Trade Group</td>
                                <td><span class="badge-dense ${getBadgeClass(g.status, true)}">${getFriendlyStatus(g.status, true)}</span>${retryBtn}</td>
                            </tr>
                        `;

                        if (groupExpanded) {
                            // Compute status for original child trades
                            let childStatus = g.status;

                            // Orig 1
                            trackerTbody.innerHTML += `
                                <tr>
                                    <td class="indent-2">Orig 1 (TP1)</td>
                                    <td></td>
                                    <td>${g.trade_1_ticket || 'N/A'}</td>
                                    <td>Original</td>
                                    <td><span class="badge-dense ${getBadgeClass(childStatus, false, true)}">${getFriendlyStatus(childStatus, false, true)}</span></td>
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
                                        <td><span class="badge-dense ${getBadgeClass(childStatus, false, false)}">${getFriendlyStatus(childStatus, false, false)}</span></td>
                                    </tr>
                                `;
                            }
                        }
                    });
                }
        }
    }
    function getBadgeClass(status, isGroup = false, isTP1 = false) {
        if (!status) return 'bdg-cancel';
        if (isGroup) {
            if (status === 'ACTIVE' || status.startsWith('ACTIVE_T2')) return 'bdg-active';
            if (status.startsWith('PENDING')) return 'bdg-pending';
            if (status === 'SUCCESS_TP2_HIT') return 'bdg-buy';
            if (status === 'CLOSED_T2_SL' || status === 'SL_HIT' || status === 'FAILED_EXECUTION') return 'bdg-sell';
            return 'bdg-cancel';
        } else {
            if (status === 'ACTIVE') return 'bdg-active';
            if (status.startsWith('ACTIVE_T2')) return isTP1 ? 'bdg-buy' : 'bdg-active';
            if (status === 'SUCCESS_TP2_HIT') return 'bdg-buy';
            if (status === 'CLOSED_T2_SL') return isTP1 ? 'bdg-buy' : 'bdg-sell';
            if (status === 'SL_HIT') return 'bdg-sell';
            if (status.startsWith('PENDING')) return 'bdg-pending';
            return 'bdg-cancel';
        }
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
        let html = '';

        // Display Auto-Executed Results
        if (data.auto_results && data.auto_results.length > 0) {
            html += '<div style="margin-top: 10px; font-weight: bold; color: var(--text-primary); border-bottom: 1px solid var(--border-color); padding-bottom: 4px; margin-bottom: 8px;">🤖 Auto-Executed Instances:</div>';
            data.auto_results.forEach(res => {
                let badgeClass = 'bdg-cancel';
                let statusText = 'Unknown';
                let details = '';

                if (res.status === 'executed') {
                    badgeClass = 'bdg-buy';
                    statusText = 'Executed';
                    details = `Ticket: ${res.ticket1}` + (res.ticket2 ? ` / ${res.ticket2}` : '');
                } else if (res.status === 'ignored') {
                    badgeClass = 'bdg-pending';
                    statusText = 'Ignored';
                    details = res.reason;
                } else if (res.status === 'failed') {
                    badgeClass = 'bdg-sell';
                    statusText = 'Failed';
                    details = res.reason;
                }

                html += `<div style="margin-bottom: 6px; padding: 4px 8px; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 3px;">`;
                html += `<strong>${res.name}</strong> &nbsp;<span class="badge-dense ${badgeClass}">${statusText}</span><br>`;
                if (details) {
                    html += `<span style="font-size: 10px; color: var(--text-secondary);">${details}</span>`;
                }
                html += `</div>`;
            });
        }

        // Display Manual Confirmations
        if (data.manual_executions && data.manual_executions.length > 0) {
            html += '<div style="margin-top: 10px; font-weight: bold; color: var(--text-primary); border-bottom: 1px solid var(--border-color); padding-bottom: 4px; margin-bottom: 8px;">✍️ Pending Manual Confirmation:</div>';
            data.manual_executions.forEach(exec => {
                html += `<div style="margin-bottom: 8px;">`;
                html += `<strong>${exec.name}</strong> <span style="font-size: 11px; color: var(--text-muted);">($${exec.risk_usd} Risk)</span><br>`;
                if (exec.split_trade) {
                    html += `<span style="font-size: 12px; color: var(--text-secondary);">Total: ${exec.calculated_volume} Lots &nbsp;&rarr;&nbsp; [1] ${exec.vol1} (TP1) &nbsp; [2] ${exec.vol2} (TP2)</span>`;
                } else {
                    html += `<span style="font-size: 12px; color: var(--text-secondary);">Total: ${exec.calculated_volume} Lots (Single) - ${exec.split_reason}</span>`;
                }
                html += `</div>`;
            });
        }

        modalSplitInfo.innerHTML = html;

        // Show/Hide footer actions based on presence of manual executions
        const manualFooter = document.getElementById('modal-footer-manual');
        const autoFooter = document.getElementById('modal-footer-auto');

        if (data.manual_executions && data.manual_executions.length > 0) {
            if (manualFooter) manualFooter.style.display = 'flex';
            if (autoFooter) autoFooter.style.display = 'none';
        } else {
            if (manualFooter) manualFooter.style.display = 'none';
            if (autoFooter) autoFooter.style.display = 'flex';
        }

        modalOverlay.classList.add('active');
    }

    function showNextSignal() {
        if (signalQueue.length === 0) {
            modalIsOpen = false;
            const badge = document.getElementById('modal-signal-count');
            if (badge) badge.style.display = 'none';
            modalOverlay.classList.remove('active');
            return;
        }

        modalIsOpen = true;
        const data = signalQueue[0];
        showTradeModal(data);
        
        const badge = document.getElementById('modal-signal-count');
        if (badge) {
            if (signalQueue.length > 1) {
                badge.innerText = `${signalQueue.length} Signals`;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }

        alertAudio.currentTime = 0;
        alertAudio.play().catch(e => console.error("Error playing sound:", e));
    }

    if(btnExecute) btnExecute.addEventListener('click', () => {
        if (!currentTradePayload) return;

        btnExecute.disabled = true;
        btnExecute.innerText = "Executing...";

        const payload = {
            symbol: currentTradePayload.symbol,
            action: currentTradePayload.action,
            sl: currentTradePayload.sl,
            tp1: currentTradePayload.tp1,
            tp2: currentTradePayload.tp2,
            entry: currentTradePayload.entry,
            instance_executions: currentTradePayload.manual_executions
        };

        fetch('/api/execute_trade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(res => res.json())
            .then(data => {
                currentTradePayload = null;
                btnExecute.disabled = false;
                btnExecute.innerText = "Execute";
                
                signalQueue.shift();
                showNextSignal();
            })
            .catch(err => {
                console.error("Execute error:", err);
                alert("Execution failed: " + err);
                btnExecute.disabled = false;
                btnExecute.innerText = "Execute";
            });
    });

    if(btnAbort) btnAbort.addEventListener('click', () => {
        fetch('/api/abort_trade', { method: 'POST' })
            .then(() => {
                currentTradePayload = null;
                signalQueue.shift();
                showNextSignal();
            })
            .catch(err => console.error("Abort error:", err));
    });

    if (btnDismiss) {
        if(btnDismiss) btnDismiss.addEventListener('click', () => {
            currentTradePayload = null;
            signalQueue.shift();
            showNextSignal();
        });
    }

    function getFriendlyTimeframe(tf) {
        if (!tf || tf === 'all') return 'All';
        if (tf === '60') return '1h';
        if (tf === '240') return '4h';
        if (tf === 'D') return 'Daily';
        return `${tf}m`;
    }

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
    const newInstanceMapping = document.getElementById('new-instance-mapping');
    const newInstanceTimeframe = document.getElementById('new-instance-timeframe');

    // Tab Switching Logic inside settings modal
    const settingsTabBtns = document.querySelectorAll('.settings-tab-btn');
    settingsTabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-settings-tab');
            
            // Toggle active button
            settingsTabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Toggle active panel
            const panels = document.querySelectorAll('.settings-panel');
            panels.forEach(panel => {
                if (panel.id === `settings-panel-${targetTab}`) {
                    panel.classList.add('active');
                } else {
                    panel.classList.remove('active');
                }
            });
        });
    });

    if (btnSettings) {
        btnSettings.addEventListener('click', () => {
            settingsModal.classList.add('active');
            
            // Reset to first tab (Global Settings)
            const firstTab = document.querySelector('.settings-tab-btn[data-settings-tab="global"]');
            if (firstTab) firstTab.click();
            
            fetchInstances();
        });
    }

    if (btnCloseSettings) {
        btnCloseSettings.addEventListener('click', () => {
            settingsModal.classList.remove('active');
            
            // Clear fields
            if (newInstanceName) newInstanceName.value = '';
            if (newInstancePath) newInstancePath.value = '';
            if (newInstanceRisk) newInstanceRisk.value = '100';
            if (newInstanceMapping) newInstanceMapping.value = '';
            
            const newInstanceAuto = document.getElementById('new-instance-auto');
            if (newInstanceAuto) newInstanceAuto.checked = false;
            if (newInstanceTimeframe) newInstanceTimeframe.value = 'all';
            
            // Reset button and heading in case it was in edit mode
            if (btnAddInstance) {
                btnAddInstance.innerText = "Add Instance";
                btnAddInstance.removeAttribute('data-edit-id');
            }
            const heading = document.getElementById('heading-add-instance');
            if (heading) heading.innerText = "Add New Instance";
        });
    }

    function fetchGlobalSettings() {
        fetch('/api/global_settings')
            .then(res => res.json())
            .then(data => {
                const check = document.getElementById('global-trade-disable');
                const start = document.getElementById('global-disable-start');
                const end = document.getElementById('global-disable-end');
                if(check) check.checked = data.trade_disable;
                if(start) start.value = data.disable_time_start || '';
                if(end) end.value = data.disable_time_end || '';
            })
            .catch(err => console.error("Error fetching global settings:", err));
    }

    const btnSaveGlobalSettings = document.getElementById('btn-save-global-settings');
    if (btnSaveGlobalSettings) {
        btnSaveGlobalSettings.addEventListener('click', () => {
            const check = document.getElementById('global-trade-disable').checked;
            const start = document.getElementById('global-disable-start').value;
            const end = document.getElementById('global-disable-end').value;
            
            btnSaveGlobalSettings.innerText = "Saving...";
            fetch('/api/global_settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    trade_disable: check ? 1 : 0,
                    disable_time_start: start,
                    disable_time_end: end
                })
            })
            .then(res => res.json())
            .then(data => {
                btnSaveGlobalSettings.innerText = "Save Global Settings";
                if(data.status === 'success') {
                    alert('Global settings saved!');
                } else {
                    alert('Error saving global settings: ' + data.error);
                }
            })
            .catch(err => {
                btnSaveGlobalSettings.innerText = "Save Global Settings";
                alert('Request failed: ' + err);
            });
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
                const storyFilter = document.getElementById('story-instance-filter');
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
                
                if (storyFilter) {
                    const currentVal = storyFilter.value;
                    storyFilter.innerHTML = '<option value="all">All Instances</option>';
                    data.forEach(inst => {
                        const opt = document.createElement('option');
                        opt.value = inst.id;
                        opt.innerText = inst.name;
                        storyFilter.appendChild(opt);
                    });
                    storyFilter.value = currentVal || 'all';
                }

                if (data.length === 0) {
                    instanceList.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; padding: 10px;">No instances configured. Executing on default MT5.</div>';
                    return;
                }
                data.forEach(inst => {
                    const tfLabel = getFriendlyTimeframe(inst.accepted_timeframe);
                    const autoModeBadge = inst.auto_trade 
                        ? `<span class="badge-dense bdg-buy" style="margin-left: 5px; font-size: 9px; vertical-align: middle;">Auto (${tfLabel})</span>` 
                        : `<span class="badge-dense bdg-pending" style="margin-left: 5px; font-size: 9px; vertical-align: middle;">Manual Mode</span>`;

                    let profitLimitHtml = '';
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
                    }

                    let roleBadge = '';
                    let cardStyle = 'display: flex; justify-content: space-between; align-items: center; padding: 8px; background: var(--bg-secondary); border: 1px solid var(--border-color); margin-bottom: 5px;';
                    
                    if (inst.copier_role === 'PROVIDER') {
                        roleBadge = `<span class="badge-dense" style="background: rgba(243, 156, 18, 0.15); color: #f39c12; margin-left: 5px; font-size: 9px; vertical-align: middle;">👑 MASTER</span><span class="badge-dense" style="background: rgba(46, 204, 113, 0.15); color: #2ecc71; margin-left: 5px; font-size: 8px; vertical-align: middle;"><span style="display:inline-block; width:6px; height:6px; background:#2ecc71; border-radius:50%; margin-right:3px;"></span>ZMQ: Broadcasting</span>`;
                        cardStyle = 'display: flex; justify-content: space-between; align-items: center; padding: 8px; background: var(--bg-secondary); border: 1px solid #f39c12; box-shadow: 0 0 10px rgba(243, 156, 18, 0.1); margin-bottom: 5px;';
                    } else if (inst.copier_role === 'CONSUMER') {
                        roleBadge = `<span class="badge-dense" style="background: rgba(52, 152, 219, 0.15); color: #3498db; margin-left: 5px; font-size: 9px; vertical-align: middle;">👥 SUB</span>`;
                    }

                    let copierInfoHtml = '';
                    if (inst.copier_role === 'CONSUMER') {
                        let riskStr = '';
                        if (inst.copier_risk_type === 'FIXED') riskStr = `Fixed ${inst.copier_fixed_lot} Lots`;
                        else if (inst.copier_risk_type === 'MULTIPLIER') riskStr = `${inst.copier_risk_multiplier}x Multiplier`;
                        else if (inst.copier_risk_type === 'USD') riskStr = `$${inst.copier_risk_usd} USD`;
                        copierInfoHtml = `<div style="margin-top: 4px; font-size: 10px; color: var(--text-muted);"><span style="color: #3498db; font-weight: bold;">Copier Risk:</span> ${riskStr}</div>`;
                    }

                    const div = document.createElement('div');
                    div.style = cardStyle;
                    div.innerHTML = `
                        <div style="flex: 1;">
                            <strong>${inst.name}</strong> ${roleBadge} ${autoModeBadge} <span style="font-size: 11px; color: #10b981; margin-left: 5px;">$${inst.risk_usd || 100} Risk</span> ${inst.symbol_suffix ? `<span style="font-size: 11px; color: #64b5f6; margin-left: 5px;">(${inst.symbol_suffix} Suffix)</span>` : ''}<br>
                            <span style="font-size: 10px; color: var(--text-muted);">${inst.path}</span>
                            ${copierInfoHtml}
                            ${profitLimitHtml}
                        </div>
                        <div style="display: flex; gap: 5px;">
                            <button class="btn-toolbar btn-edit-inst" data-id="${inst.id}" style="color: #64b5f6; border-color: #1e3a8a;">Edit</button>
                            <button class="btn-toolbar btn-delete-inst" data-id="${inst.id}" style="color: #fca5a5; border-color: #7f1d1d;">Remove</button>
                        </div>
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
            } else if (e.target.classList.contains('btn-reset-profit')) {
                const id = e.target.getAttribute('data-id');
                if (confirm("Are you sure you want to reset the profit tracking session for this instance? It will start tracking from $0 right now.")) {
                    fetch('/api/instances/reset_profit', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ id: id })
                    }).then(() => fetchInstances());
                }
            } else if (e.target.classList.contains('btn-edit-inst')) {
                const id = e.target.getAttribute('data-id');
                fetch('/api/instances')
                    .then(res => res.json())
                    .then(data => {
                        const inst = data.find(i => i.id == id);
                        if (inst) {
                            newInstanceName.value = inst.name;
                            newInstancePath.value = inst.path;
                            newInstanceRisk.value = inst.risk_usd || 100;
                            const newInstanceProfitLimit = document.getElementById('new-instance-profit-limit');
                            if (newInstanceProfitLimit) newInstanceProfitLimit.value = inst.profit_limit || 0;
                            
                            const newInstanceAuto = document.getElementById('new-instance-auto');
                            if (newInstanceAuto) newInstanceAuto.checked = inst.auto_trade === 1;
                            if (newInstanceTimeframe) newInstanceTimeframe.value = inst.accepted_timeframe || 'all';
                            
                            let mappingStr = '';
                            if (inst.symbol_mapping) {
                                try {
                                    const mapping = JSON.parse(inst.symbol_mapping);
                                    mappingStr = Object.entries(mapping).map(([k, v]) => `${k}:${v}`).join(',');
                                } catch(e) {}
                            }
                            newInstanceMapping.value = mappingStr;
                            
                            btnAddInstance.innerText = "Save Changes";
                            btnAddInstance.setAttribute('data-edit-id', id);
                            const heading = document.getElementById('heading-add-instance');
                            if (heading) heading.innerText = "Edit Instance";
                        }
                    });
            }
        });
    }

    if (btnAddInstance) {
        btnAddInstance.addEventListener('click', () => {
            const name = newInstanceName.value;
            const path = newInstancePath.value;
            const risk_usd = parseFloat(newInstanceRisk.value || 100);
            const newInstanceProfitLimit = document.getElementById('new-instance-profit-limit');
            const profit_limit = newInstanceProfitLimit ? parseFloat(newInstanceProfitLimit.value || 0) : 0;
            const autoTradeVal = document.getElementById('new-instance-auto')?.checked ? 1 : 0;
            const acceptedTimeframeVal = newInstanceTimeframe ? newInstanceTimeframe.value : 'all';
            
            const mappingStr = newInstanceMapping ? newInstanceMapping.value : '';
            const mapping = {};
            if (mappingStr) {
                mappingStr.split(',').forEach(pair => {
                    const [key, value] = pair.split(':');
                    if (key && value) {
                        mapping[key.trim()] = value.trim();
                    }
                });
            }
            const symbol_mapping = JSON.stringify(mapping);

            if (!name || !path) { alert("Please enter name and path"); return; }
            
            const editId = btnAddInstance.getAttribute('data-edit-id');
            const method = editId ? 'PUT' : 'POST';
            const payload = { name, path, risk_usd, symbol_mapping, auto_trade: autoTradeVal, accepted_timeframe: acceptedTimeframeVal, profit_limit: profit_limit };
            if (editId) payload.id = editId;

            fetch('/api/instances', {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(() => {
                newInstanceName.value = '';
                newInstancePath.value = '';
                if (newInstanceRisk) newInstanceRisk.value = '100';
                const newInstanceProfitLimit = document.getElementById('new-instance-profit-limit');
                if (newInstanceProfitLimit) newInstanceProfitLimit.value = '0';
                if (newInstanceMapping) newInstanceMapping.value = '';
                const newInstanceAuto = document.getElementById('new-instance-auto');
                if (newInstanceAuto) newInstanceAuto.checked = false;
                if (newInstanceTimeframe) newInstanceTimeframe.value = 'all';
                
                btnAddInstance.innerText = "Add Instance";
                btnAddInstance.removeAttribute('data-edit-id');
                const heading = document.getElementById('heading-add-instance');
                if (heading) heading.innerText = "Add New Instance";
                
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

    // --- Story Notes Logic ---
    const storyDateFilter = document.getElementById('story-date-filter');
    const storyInstanceFilter = document.getElementById('story-instance-filter');
    const btnSyncStories = document.getElementById('btn-sync-stories');

    if (btnSyncStories) {
        btnSyncStories.addEventListener('click', () => {
            if (storyDateFilter && storyDateFilter.value) {
                fetchStoryNotes(storyDateFilter.value);
            }
        });
    }

    if (storyDateFilter) {
        storyDateFilter.addEventListener('change', (e) => {
            if (e.target.value) {
                fetchStoryNotes(e.target.value);
            }
        });
    }
    
    if (storyInstanceFilter) {
        storyInstanceFilter.addEventListener('change', () => {
            if (storyDateFilter && storyDateFilter.value) {
                fetchStoryNotes(storyDateFilter.value);
            }
        });
    }

    function fetchStoryDates() {
        if (!storyDateFilter) return;
        
        fetch('/api/story_dates')
            .then(res => res.json())
            .then(data => {
                const dates = data.dates || [];
                const currentVal = storyDateFilter.value;
                storyDateFilter.innerHTML = '';
                
                if (dates.length === 0) {
                    storyDateFilter.innerHTML = '<option value="">No dates available</option>';
                    return;
                }
                
                dates.forEach(d => {
                    const opt = document.createElement('option');
                    opt.value = d;
                    // Format date nicely (e.g. "Jan 25 2024")
                    const dateObj = new Date(d);
                    const formatted = dateObj.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', weekday: 'long' });
                    opt.innerText = formatted;
                    storyDateFilter.appendChild(opt);
                });
                
                if (currentVal && dates.includes(currentVal)) {
                    storyDateFilter.value = currentVal;
                }
                
                if (storyDateFilter.value) {
                    fetchStoryNotes(storyDateFilter.value);
                }
            })
            .catch(err => console.error("Error fetching story dates:", err));
    }

    function fetchStoryNotes(dateStr) {
        if (!dateStr) return;
        
        const instanceId = storyInstanceFilter ? storyInstanceFilter.value : 'all';
        
        fetch(`/api/story_notes?date=${dateStr}&instance_id=${instanceId}`)
            .then(res => res.json())
            .then(data => {
                // Update report metadata fields
                const reportDate = document.getElementById('report-date');
                if (reportDate) reportDate.innerText = dateStr;
                
                const reportInst = document.getElementById('report-instance');
                if (reportInst) {
                    const currentInstText = storyInstanceFilter ? storyInstanceFilter.options[storyInstanceFilter.selectedIndex].text : "All Instances";
                    reportInst.innerText = currentInstText;
                }
                
                const reportTime = document.getElementById('report-time');
                if (reportTime) {
                    const now = new Date();
                    reportTime.innerText = now.toLocaleTimeString();
                }
                
                const reportRef = document.getElementById('report-ref-id');
                if (reportRef) {
                    const refInst = storyInstanceFilter ? storyInstanceFilter.value : "ALL";
                    reportRef.innerText = `VTC-${dateStr.replace(/-/g, '')}-${refInst}`;
                }

                // Pre-calculate Win Rate
                let winRateStr = "0.0%";
                let rateVal = 0;
                if (data.summary && data.summary.total_trades > 0) {
                    rateVal = (data.summary.win_trades / data.summary.total_trades) * 100;
                    winRateStr = `${rateVal.toFixed(1)}%`;
                }
                
                // Update metrics
                if (data.summary) {
                    const tp = document.getElementById('story-total-profit');
                    const tt = document.getElementById('story-total-trades');
                    const wt = document.getElementById('story-win-trades');
                    const lt = document.getElementById('story-loss-trades');
                    const wr = document.getElementById('story-win-rate');
                    
                    if (tp) {
                        tp.innerText = `$${data.summary.total_profit.toFixed(2)}`;
                        tp.style.color = data.summary.total_profit > 0 ? 'var(--color-buy)' : (data.summary.total_profit < 0 ? 'var(--color-sell)' : 'var(--text-main)');
                    }
                    if (tt) tt.innerText = data.summary.total_trades;
                    if (wt) wt.innerText = data.summary.win_trades;
                    if (lt) lt.innerText = data.summary.loss_trades;
                    if (wr) wr.innerText = winRateStr;
                }

                // Update Performance Grade Rating
                const ratingGrade = document.getElementById('report-grade');
                const ratingDesc = document.getElementById('report-grade-desc');
                if (ratingGrade && ratingDesc) {
                    const total = data.summary ? data.summary.total_trades : 0;
                    if (total === 0) {
                        ratingGrade.innerText = "N/A";
                        ratingGrade.style.color = "var(--text-muted)";
                        ratingDesc.innerText = "No trades logged today.";
                    } else {
                        const net = data.summary.total_profit;
                        if (net > 0 && rateVal >= 70) {
                            ratingGrade.innerText = "A+";
                            ratingGrade.style.color = "var(--color-buy)";
                            ratingDesc.innerText = "Excellent trading day with solid profits and high strike rate.";
                        } else if (net > 0 && rateVal >= 50) {
                            ratingGrade.innerText = "B";
                            ratingGrade.style.color = "var(--color-active)";
                            ratingDesc.innerText = "Profitable trading day with average strike rate.";
                        } else if (net === 0) {
                            ratingGrade.innerText = "B/E";
                            ratingGrade.style.color = "var(--text-muted)";
                            ratingDesc.innerText = "Perfect break-even trading session.";
                        } else {
                            ratingGrade.innerText = "D / draw";
                            ratingGrade.style.color = "var(--color-sell)";
                            ratingDesc.innerText = "Trading session in negative drawdown. Monitor risk settings.";
                        }
                    }
                }
                
                // Render timeline
                const feed = document.getElementById('story-feed');
                if (!feed) return;
                feed.innerHTML = '';
                
                const stories = data.stories || [];
                if (stories.length === 0) {
                    feed.innerHTML = '<div style="color: var(--text-muted); font-size: 11px; padding: 20px 0; text-align: center; font-style: italic;">No signals or executions logged for the selected date.</div>';
                    return;
                }
                
                stories.forEach(s => {
                    // Derive dynamic progression based on new trade management rules (and legacy fallback support)
                    let progressionHTML = '';
                    
                    // 1. Placement
                    progressionHTML += `<li class="report-timeline-item pending">${s.mode === 'Auto' ? '🤖 Auto mode' : '✍️ Manual mode'} placed pending orders for Trade 1 & Trade 2 at <strong>${s.symbol}</strong> on <strong>${s.timeframe}</strong></li>`;
                    
                    // 2. Status Updates
                    if (s.status === 'PENDING_ORIGINAL') {
                        progressionHTML += `<li class="report-timeline-item pending">⏳ Pending orders active. Waiting for entry price to fill.</li>`;
                    } else if (s.status === 'ACTIVE') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Entry price filled! Both Trade 1 and Trade 2 are currently active.</li>`;
                        progressionHTML += `<li class="report-timeline-item pending">📈 Tracking price towards Take Profit 1 (0.7R).</li>`;
                    } else if (s.status === 'ACTIVE_T2_SL_ORIGINAL') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Entry price filled! Both Trade 1 and Trade 2 active.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">✅ Take Profit 1 (0.7R) hit! Trade 1 closed, securing 50% profit.</li>`;
                        progressionHTML += `<li class="report-timeline-item pending">📈 Trade 2 is running with original Stop Loss. Tracking towards 1.3R.</li>`;
                    } else if (s.status === 'ACTIVE_T2_SL_MINUS_0_5') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Entry price filled! Both Trade 1 and Trade 2 active.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">✅ Take Profit 1 (0.7R) hit! Trade 1 closed, securing 50% profit.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">🛡️ Price reached 1.3R! Trade 2 Stop Loss trailed to -0.5R.</li>`;
                        progressionHTML += `<li class="report-timeline-item pending">📈 Tracking towards 2.5R.</li>`;
                    } else if (s.status === 'ACTIVE_T2_SL_PLUS_0_25') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Entry price filled! Both Trade 1 and Trade 2 active.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">✅ Take Profit 1 (0.7R) hit! Trade 1 closed, securing 50% profit.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">🛡️ Price reached 1.3R! Trade 2 Stop Loss trailed to -0.5R.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">🛡️ Price reached 2.5R! Trade 2 Stop Loss trailed to +0.25R.</li>`;
                        progressionHTML += `<li class="report-timeline-item pending">📈 Tracking towards Take Profit 2 (3.0R).</li>`;
                    } else if (s.status === 'SUCCESS_TP2_HIT') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Entry price filled! Both Trade 1 and Trade 2 active.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">✅ Take Profit 1 (0.7R) hit! Trade 1 closed, securing 50% profit.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">Price reached 1.3R! Trade 2 Stop Loss trailed to -0.5R.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">Price reached 2.5R! Trade 2 Stop Loss trailed to +0.25R.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">🎯 Take Profit 2 (3.0R) hit! Trade 2 closed, securing remaining 50% profit.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">🎉 Trade group completed successfully with full profit targets!</li>`;
                    } else if (s.status === 'CLOSED_T2_SL_PLUS_0_25') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Entry price filled! Both Trade 1 and Trade 2 active.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">✅ Take Profit 1 (0.7R) hit! Trade 1 closed, securing 50% profit.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">🛡️ Price reached 1.3R! Trade 2 Stop Loss trailed to -0.5R.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">🛡️ Price reached 2.5R! Trade 2 Stop Loss trailed to +0.25R.</li>`;
                        progressionHTML += `<li class="report-timeline-item stopped">🛑 Trade 2 stopped out at trailed Stop Loss (+0.25R).</li>`;
                    } else if (s.status === 'CLOSED_T2_SL_MINUS_0_5') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Entry price filled! Both Trade 1 and Trade 2 active.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">✅ Take Profit 1 (0.7R) hit! Trade 1 closed, securing 50% profit.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">🛡️ Price reached 1.3R! Trade 2 Stop Loss trailed to -0.5R.</li>`;
                        progressionHTML += `<li class="report-timeline-item stopped">🛑 Trade 2 stopped out at trailed Stop Loss (-0.5R).</li>`;
                    } else if (s.status === 'CLOSED_T2_SL') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Entry price filled! Both Trade 1 and Trade 2 active.</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">✅ Take Profit 1 (0.7R) hit! Trade 1 closed, securing 50% profit.</li>`;
                        progressionHTML += `<li class="report-timeline-item stopped">🛑 Trade 2 stopped out at trailed Stop Loss (Break Even).</li>`;
                    } else if (s.status === 'CLOSED_SL') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Entry price filled! Both Trade 1 and Trade 2 active.</li>`;
                        progressionHTML += `<li class="report-timeline-item stopped">🛑 Original Stop Loss hit! Both Trade 1 and Trade 2 stopped out.</li>`;
                    } else if (s.status === 'CANCELLED') {
                        progressionHTML += `<li class="report-timeline-item stopped">❌ Trade pending orders cancelled or invalidated before filling.</li>`;
                    } 
                    // Legacy status support
                    else if (s.status === 'SUCCESS_TP1_HIT') {
                        progressionHTML += `<li class="report-timeline-item hit">✅ Original trade hit TP1 successfully!</li>`;
                    } else if (s.status === 'RECOVERY_TRIGGERED') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Original trade filled and placed the recovery trade</li>`;
                        progressionHTML += `<li class="report-timeline-item pending">⏳ Recovery Trade is currently active</li>`;
                    } else if (s.status === 'RECOVERY_SUCCESS') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Original trade filled and placed the recovery trade</li>`;
                        progressionHTML += `<li class="report-timeline-item hit">✅ Recovery Trade Hit TP!</li>`;
                    } else if (s.status === 'RECOVERY_FAILED') {
                        progressionHTML += `<li class="report-timeline-item hit">🔄 Original trade filled and placed the recovery trade</li>`;
                        progressionHTML += `<li class="report-timeline-item stopped">🛑 Recovery Trade Hit SL!</li>`;
                    } else {
                        progressionHTML += `<li>Status: ${s.status}</li>`;
                    }
                    
                    // 3. P&L Footer
                    const plColor = s.pl > 0 ? 'var(--color-buy)' : (s.pl < 0 ? 'var(--color-sell)' : 'var(--text-muted)');
                    const plSign = s.pl > 0 ? '+' : '';
                    progressionHTML += `<li style="margin-top: 6px; list-style: none;">💰 <strong>[P&L: <span style="color: ${plColor};">${plSign}$${s.pl.toFixed(2)}</span>]</strong></li>`;
                    
                    // 4. Trade Path Diagram
                    let diagramHTML = '';
                    if (s.entry && s.sl && s.tp1 && s.tp2) {
                        const isBuy = (s.action || 'BUY').toUpperCase() === 'BUY';
                        const range = Math.abs(s.tp2 - s.sl) || 1;
                        const getPct = (p) => isBuy ? ((p - s.sl) / range) * 100 : ((s.sl - p) / range) * 100;
                        
                        const bSL = 0;
                        const bEntry = getPct(s.entry);
                        const bTP1 = getPct(s.tp1);
                        const bTP2 = 100;
                        
                        const rSize = Math.abs(bEntry - bSL); // Size of 1R in %
                        
                        let a1Class = 'active';
                        let a1Target = bEntry + 5;
                        let a2Class = 'active';
                        let a2Target = bEntry + 5;
                        
                        let a1Dir = 'right';
                        let a2Dir = 'right';
                        
                        let dist1 = 0;
                        let dist2 = 0;
                        
                        if (s.status === 'SUCCESS_TP2_HIT') {
                            a1Class = 'win'; a1Target = bTP1;
                            a2Class = 'win'; a2Target = bTP2;
                            dist1 = Math.abs(s.tp1 - s.entry);
                            dist2 = Math.abs(s.tp2 - s.entry);
                        } else if (s.status === 'SUCCESS_TP1_HIT' || s.status === 'RECOVERY_SUCCESS') {
                            a1Class = 'win'; a1Target = bTP1;
                            a2Class = 'win'; a2Target = bTP1;
                            dist1 = Math.abs(s.tp1 - s.entry);
                        } else if (s.status.startsWith('CLOSED_T2_SL')) {
                            a1Class = 'win'; a1Target = bTP1;
                            a2Class = 'loss'; a2Dir = 'left';
                            
                            if (s.status === 'CLOSED_T2_SL_PLUS_0_25') {
                                a2Class = 'win'; a2Dir = 'right';
                                a2Target = bEntry + (rSize * 0.25);
                                dist2 = Math.abs(s.entry - s.sl) * 0.25;
                            } else if (s.status === 'CLOSED_T2_SL_MINUS_0_5') {
                                a2Target = bEntry - (rSize * 0.5);
                                dist2 = Math.abs(s.entry - s.sl) * -0.5;
                            } else {
                                a2Target = bEntry - (rSize * 0.1);
                                dist2 = Math.abs(s.entry - s.sl) * -0.1;
                            }
                            dist1 = Math.abs(s.tp1 - s.entry);
                        } else if (s.status.startsWith('ACTIVE_T2')) {
                            a1Class = 'win'; a1Target = bTP1;
                            a2Class = 'active'; a2Target = bTP1 + 5;
                            dist1 = Math.abs(s.tp1 - s.entry);
                        } else if (s.status === 'ACTIVE') {
                            a1Class = 'active'; a1Target = bEntry + 5;
                            a2Class = 'active'; a2Target = bEntry + 5;
                        } else if (s.status === 'CLOSED_SL' || s.status === 'SL_HIT' || s.status === 'RECOVERY_FAILED') {
                            a1Class = 'loss'; a1Target = bSL; a1Dir = 'left';
                            a2Class = 'loss'; a2Target = bSL; a2Dir = 'left';
                            dist1 = -Math.abs(s.entry - s.sl);
                            dist2 = -Math.abs(s.entry - s.sl);
                        } else if (s.status === 'PENDING_ORIGINAL' || s.status === 'CANCELLED') {
                            a1Class = 'neutral'; a1Target = bEntry;
                            a2Class = 'neutral'; a2Target = bEntry;
                        }
                        
                        let t1_pl = (s.t1_pl !== undefined && s.t1_pl !== null) ? s.t1_pl : undefined;
                        let t2_pl = (s.t2_pl !== undefined && s.t2_pl !== null) ? s.t2_pl : undefined;
                        
                        // Fallback to calculation if DB values are missing but we have a total s.pl
                        if (t1_pl === undefined && t2_pl === undefined && s.pl) {
                            const totalDist = dist1 + dist2;
                            if (totalDist !== 0) {
                                t1_pl = s.pl * (dist1 / totalDist);
                                t2_pl = s.pl * (dist2 / totalDist);
                            } else {
                                t1_pl = s.pl / 2;
                                t2_pl = s.pl / 2;
                            }
                        }
                        
                        const rDist = Math.abs(s.entry - s.sl) || 1;
                        const rGain1 = dist1 / rDist;
                        const rGain2 = dist2 / rDist;
                        
                        const renderArrow = (cls, dir, target, isA2, plAmt, rGain) => {
                            if (target === bEntry) return '';
                            const left = Math.min(bEntry, target);
                            const width = Math.abs(bEntry - target);
                            const topPos = isA2 ? '70%' : '30%';
                            
                            let tooltipHTML = '';
                            if (cls !== 'active' && cls !== 'neutral' && plAmt !== undefined && plAmt !== null && rGain !== undefined) {
                                const sign = plAmt > 0 ? '+' : '';
                                const rSign = rGain > 0 ? '+' : '';
                                const color = plAmt > 0 ? 'var(--color-buy)' : (plAmt < 0 ? 'var(--color-sell)' : 'var(--text-main)');
                                tooltipHTML = `
                                    <div class="h-tooltip">
                                        <div style="font-size: 10px; color: var(--text-muted); margin-bottom: 2px;">Trade ${isA2 ? '2' : '1'}</div>
                                        <div style="font-size: 11px; font-weight: bold; color: ${color};">
                                            ${sign}$${Math.abs(plAmt).toFixed(2)} <span style="font-size: 9px; opacity: 0.8;">(${rSign}${rGain.toFixed(2)}R)</span>
                                        </div>
                                    </div>
                                `;
                            }
                            
                            return `<div class="h-arrow ${cls} ${dir}" style="top: ${topPos}; left: ${left}%; width: ${width}%;">${tooltipHTML}</div>`;
                        };
                        
                        let tslHTML = '';
                        if (s.status.startsWith('CLOSED_T2_SL')) {
                            let tslPct = bEntry;
                            if (s.status === 'CLOSED_T2_SL_PLUS_0_25') {
                                tslPct = bEntry + (rSize * 0.25);
                            } else if (s.status === 'CLOSED_T2_SL_MINUS_0_5') {
                                tslPct = bEntry - (rSize * 0.5);
                            } else {
                                tslPct = bEntry - (rSize * 0.1);
                            }
                            
                            const color = s.status === 'CLOSED_T2_SL_PLUS_0_25' ? 'var(--color-buy)' : 'var(--color-sell)';
                            tslHTML = `
                                <div class="h-level" style="left: ${tslPct}%; border-left-color: ${color};">
                                    <div class="h-label" style="color: ${color};">TSL</div>
                                </div>
                            `;
                        }
                        
                        diagramHTML = `
                            <div class="h-chart">
                                <div class="h-canvas">
                                    <div class="h-level" style="left: ${bSL}%;">
                                        <div class="h-label">SL</div>
                                    </div>
                                    <div class="h-level solid" style="left: ${bEntry}%;">
                                        <div class="h-label">Entry</div>
                                    </div>
                                    <div class="h-level" style="left: ${bTP1}%;">
                                        <div class="h-label">TP1</div>
                                    </div>
                                    <div class="h-level" style="left: ${bTP2}%;">
                                        <div class="h-label">TP2</div>
                                    </div>
                                    ${tslHTML}
                                    
                                    ${renderArrow(a1Class, a1Dir, a1Target, false, t1_pl, rGain1)}
                                    ${renderArrow(a2Class, a2Dir, a2Target, true, t2_pl, rGain2)}
                                </div>
                            </div>
                        `;
                    }
                    
                    const cardHTML = `
                        <div style="margin-bottom: 20px; page-break-inside: avoid;">
                            <div style="font-size: 11px; color: var(--text-main); font-weight: bold; padding-bottom: 4px; border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between;">
                                <span>SIGNAL GROUP #${s.id}: ${s.symbol} (${s.timeframe})</span>
                                <span style="font-family: monospace; color: var(--text-muted);">${s.time} LOCAL</span>
                            </div>
                            <div style="font-size: 10px; color: var(--text-muted); margin-top: 4px; margin-bottom: 6px; display: flex; gap: 12px;">
                                <span>Mode: ${s.mode === 'Auto' ? 'Automated Execution' : 'Manual Execution'}</span>
                                <span>Magic: <span style="font-family: monospace; color: var(--text-main);">${s.magic || 'N/A'}</span></span>
                            </div>
                            <ul class="report-timeline">
                                ${progressionHTML}
                            </ul>
                            ${diagramHTML}
                        </div>
                    `;
                    feed.innerHTML += cardHTML;
                });
            })
            .catch(err => console.error("Error fetching story notes:", err));
    }

    // --- PDF Export Button listener ---
    const btnPrintStories = document.getElementById('btn-print-stories');
    if (btnPrintStories) {
        btnPrintStories.addEventListener('click', () => {
            window.print();
        });
    }

    // --- Collapsible Event Log Section ---
    const logsSection = document.getElementById('logs-section');
    const btnToggleLogs = document.getElementById('btn-toggle-logs');
    const logsTabTitle = document.getElementById('logs-tab-title');
    const logsToggleIcon = document.getElementById('logs-toggle-icon');
    const logsToggleText = document.getElementById('logs-toggle-text');

    function setLogsCollapsedState(collapsed) {
        if (!logsSection) return;
        if (collapsed) {
            logsSection.classList.add('collapsed');
            if (logsToggleIcon) logsToggleIcon.innerText = '▲';
            if (logsToggleText) logsToggleText.innerText = 'Expand';
        } else {
            logsSection.classList.remove('collapsed');
            if (logsToggleIcon) logsToggleIcon.innerText = '▼';
            if (logsToggleText) logsToggleText.innerText = 'Collapse';
            // Scroll to bottom when expanded
            if (logBox) {
                setTimeout(() => {
                    if(logBox) logBox.scrollTop = logBox.scrollHeight;
                }, 200); // match transition duration
            }
        }
    }

    // Load initial state
    const isLogsCollapsed = localStorage.getItem('logsCollapsed') === 'true';
    setLogsCollapsedState(isLogsCollapsed);

    function toggleLogs() {
        if (!logsSection) return;
        const currentlyCollapsed = logsSection.classList.contains('collapsed');
        const nextState = !currentlyCollapsed;
        setLogsCollapsedState(nextState);
        localStorage.setItem('logsCollapsed', nextState ? 'true' : 'false');
    }

    if (btnToggleLogs) {
        btnToggleLogs.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleLogs();
        });
    }

    if (logsTabTitle) {
        logsTabTitle.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleLogs();
        });
    }


eventSource.addEventListener('risk_data', (e) => {
    try {
        const payload = JSON.parse(e.data);
        renderHealthCards(payload);
        renderActivePositions(payload);
    } catch (err) {
        console.error("Error parsing risk_data:", err);
    }
});

});

const equityCharts = {};
const prevCardPnls = {};
const cardTimeframes = {};

function formatGain(val) {
    if (val === undefined || val === null) val = 0;
    const sign = val > 0 ? '+' : (val < 0 ? '-' : '');
    const absVal = Math.abs(val).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    const color = val > 0 ? 'var(--color-buy)' : (val < 0 ? 'var(--color-sell)' : 'var(--text-secondary)');
    return { text: `${sign}$${absVal}`, color: color };
}

function renderHealthCards(instances) {
    const grid = document.getElementById('health-cards-grid');
    if (!grid) return;
    
    let totalBal = 0;
    let totalEq = 0;
    let totalTrades = 0;
    
    instances.forEach(inst => {
        totalBal += inst.balance;
        totalEq += inst.equity;
        totalTrades += inst.positions.length;
        
        const mlColor = inst.margin_level < 100 ? 'var(--color-sell)' : (inst.margin_level < 300 ? 'orange' : 'var(--color-buy)');
        const bal = inst.balance.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        const eq = inst.equity.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        const ml = inst.margin_level > 0 ? inst.margin_level.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '%' : 'N/A';
        const floatingPnl = inst.equity - inst.balance;
        const pnlAbs = Math.abs(floatingPnl);
        let pnlPctValStr = '0.00';
        if (inst.balance > 0 && pnlAbs > 0) {
            const pct = (pnlAbs / inst.balance) * 100;
            pnlPctValStr = pct < 0.01 ? '<0.01' : pct.toFixed(2);
        }
        const sign = floatingPnl > 0 ? '+' : (floatingPnl < 0 ? '-' : '');
        const pnlStr = `${sign}$${pnlAbs.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} (${pnlPctValStr}%)`;
        const pnlColor = floatingPnl > 0 ? 'var(--color-buy)' : (floatingPnl < 0 ? 'var(--color-sell)' : 'var(--text-primary)');

        let cardClass = "setting-card";
        if (floatingPnl > 0) {
            cardClass += " in-profit";
        } else if (floatingPnl < 0) {
            cardClass += " in-drawdown";
        }

        let roleBadge = '';
        let headerStyle = '';
        let targetContainer = grid;
        let flexStyle = ''; // For cards in flex containers
        
        if (inst.copier_role === 'PROVIDER') {
            roleBadge = `<span class="badge-dense" style="background: rgba(243, 156, 18, 0.15); color: #f39c12; margin-left: 5px; font-size: 9px; vertical-align: middle;">👑 MASTER</span><span class="badge-dense" style="background: rgba(46, 204, 113, 0.15); color: #2ecc71; margin-left: 5px; font-size: 8px; vertical-align: middle;"><span style="display:inline-block; width:6px; height:6px; background:#2ecc71; border-radius:50%; margin-right:3px;"></span>ZMQ</span>`;
            const masterContainer = document.getElementById('master-cards-container');
            if (masterContainer) targetContainer = masterContainer;
            flexStyle = 'width: 260px; flex-shrink: 0;';
        } else if (inst.copier_role === 'CONSUMER') {
            roleBadge = `<span class="badge-dense" style="background: rgba(52, 152, 219, 0.15); color: #3498db; margin-left: 5px; font-size: 9px; vertical-align: middle;">👥 SUB</span>`;
            const subContainer = document.getElementById('sub-cards-container');
            if (subContainer) targetContainer = subContainer;
            flexStyle = 'width: 220px; flex-shrink: 0;';
        }

        let copierInfoHtml = '';
        if (inst.copier_role === 'CONSUMER') {
            let riskStr = '';
            if (inst.copier_risk_type === 'FIXED') riskStr = `Fixed ${inst.copier_fixed_lot} Lots`;
            else if (inst.copier_risk_type === 'MULTIPLIER') riskStr = `${inst.copier_risk_multiplier}x Multi`;
            else if (inst.copier_risk_type === 'USD') riskStr = `$${inst.copier_risk_usd} USD`;
            copierInfoHtml = `<div style="display: flex; justify-content: space-between; align-items: center; margin-top: 2px;"><span style="color: #3498db; font-size: 10px; font-weight: bold;">Copier Risk</span><strong style="font-size: 10px; color: var(--text-secondary);">${riskStr}</strong></div>`;
        }
        
        let selectedPeriod = cardTimeframes[inst.id] || 'today';
        let realizedGainVal = (inst.realized_gains && inst.realized_gains[selectedPeriod]) ? inst.realized_gains[selectedPeriod] : 0.0;
        let gainFmt = formatGain(realizedGainVal);
        let realizedGainHtml = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px; padding-top: 4px; border-top: 1px solid var(--border-color);">
                <select id="card-rg-sel-${inst.id}" class="rg-select" data-id="${inst.id}" style="font-size: 9px; padding: 2px; background: var(--bg-panel); color: var(--text-main); border: 1px solid var(--border-color); border-radius: 3px; outline: none; cursor: pointer;">
                    <option value="today" ${selectedPeriod === 'today' ? 'selected' : ''}>Realized (Today)</option>
                    <option value="yesterday" ${selectedPeriod === 'yesterday' ? 'selected' : ''}>Realized (Yest.)</option>
                    <option value="week" ${selectedPeriod === 'week' ? 'selected' : ''}>Realized (Week)</option>
                    <option value="last_week" ${selectedPeriod === 'last_week' ? 'selected' : ''}>Realized (L.Week)</option>
                    <option value="month" ${selectedPeriod === 'month' ? 'selected' : ''}>Realized (Month)</option>
                </select>
                <strong id="card-rg-val-${inst.id}" style="font-size: 10.5px; color: ${gainFmt.color};">${gainFmt.text}</strong>
            </div>
        `;

        let card = document.getElementById(`health-card-${inst.id}`);
        if (!card) {
            card = document.createElement('div');
            card.id = `health-card-${inst.id}`;
            card.className = cardClass;
            card.style = `padding: 0; margin-bottom: 0; ${flexStyle}`;
            
            card.innerHTML = `
                <div class="card-header" style="${headerStyle}">
                    <div style="display:flex; align-items:center;"><strong>${inst.name}</strong> ${roleBadge}</div>
                    <button class="btn-toolbar btn-close-all" style="display: none;" data-id="${inst.id}">Close All</button>
                </div>
                
                <div style="padding: 4px 6px; display: flex; flex-direction: column; gap: 4px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="color: var(--text-secondary); font-size: 10px;">Balance</span>
                        <strong id="card-bal-${inst.id}" style="font-size: 10.5px;">$${bal}</strong>
                    </div>
                    
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="color: var(--text-secondary); font-size: 10px;">Equity</span>
                        <strong id="card-eq-${inst.id}" style="font-size: 10.5px;">$${eq}</strong>
                    </div>
                    
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="color: var(--text-secondary); font-size: 10px;">Trades</span>
                        <strong id="card-trades-${inst.id}" style="font-size: 10.5px;">${inst.positions.length}</strong>
                    </div>
                    
                    <div id="card-dd-row-${inst.id}" style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="color: var(--text-secondary); font-size: 10px;">P&L</span>
                        <strong id="card-dd-${inst.id}" style="font-size: 10.5px; color: ${pnlColor}; white-space: nowrap;">${pnlStr}</strong>
                    </div>
                    
                    ${copierInfoHtml}
                    ${realizedGainHtml}
                </div>
            `;
            targetContainer.appendChild(card);
            
            const selEl = document.getElementById(`card-rg-sel-${inst.id}`);
            if (selEl) {
                selEl.addEventListener('change', function(e) {
                    cardTimeframes[e.target.dataset.id] = e.target.value;
                });
            }
            
            prevCardPnls[inst.id] = floatingPnl;
        } else {
            // Re-assign to target container in case the role was changed dynamically
            if (card.parentNode !== targetContainer && targetContainer) {
                targetContainer.appendChild(card);
            }
            
            if (floatingPnl > 0) {
                card.classList.add('in-profit');
                card.classList.remove('in-drawdown');
            } else if (floatingPnl < 0) {
                card.classList.add('in-drawdown');
                card.classList.remove('in-profit');
            } else {
                card.classList.remove('in-drawdown', 'in-profit');
            }

            const balEl = document.getElementById(`card-bal-${inst.id}`);
            if (balEl) balEl.innerText = `$${bal}`;
            
            const eqEl = document.getElementById(`card-eq-${inst.id}`);
            if (eqEl) eqEl.innerText = `$${eq}`;
            
            const tradesEl = document.getElementById(`card-trades-${inst.id}`);
            if (tradesEl) tradesEl.innerText = inst.positions.length;
            
            const ddEl = document.getElementById(`card-dd-${inst.id}`);
            if (ddEl) {
                const prevVal = prevCardPnls[inst.id] !== undefined ? prevCardPnls[inst.id] : floatingPnl;
                const newVal = floatingPnl;
                prevCardPnls[inst.id] = newVal;
                
                ddEl.innerText = pnlStr;
                ddEl.style.color = pnlColor;
                
                if (newVal > prevVal) {
                    ddEl.classList.remove('flash-up', 'flash-down');
                    void ddEl.offsetWidth; // trigger reflow
                    ddEl.classList.add('flash-up');
                } else if (newVal < prevVal) {
                    ddEl.classList.remove('flash-up', 'flash-down');
                    void ddEl.offsetWidth; // trigger reflow
                    ddEl.classList.add('flash-down');
                }
            }
            
            const rgValEl = document.getElementById(`card-rg-val-${inst.id}`);
            if (rgValEl) {
                let selectedPeriod = cardTimeframes[inst.id] || 'today';
                let realizedGainVal = (inst.realized_gains && inst.realized_gains[selectedPeriod]) ? inst.realized_gains[selectedPeriod] : 0.0;
                let gainFmt = formatGain(realizedGainVal);
                rgValEl.innerText = gainFmt.text;
                rgValEl.style.color = gainFmt.color;
            }
        }
    });

    // Compute and update aggregated header statistics
    const totalPnl = totalEq - totalBal;
    const aggPnlAbs = Math.abs(totalPnl);
    let aggPnlPctStr = '0.00';
    if (totalBal > 0 && aggPnlAbs > 0) {
        const pct = (aggPnlAbs / totalBal) * 100;
        aggPnlPctStr = pct < 0.01 ? '<0.01' : pct.toFixed(2);
    }
    const aggSign = totalPnl > 0 ? '+' : (totalPnl < 0 ? '-' : '');
    const aggPnlStr = `${aggSign}$${aggPnlAbs.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} (${aggPnlPctStr}%)`;
    const aggPnlColor = totalPnl > 0 ? 'var(--color-buy)' : (totalPnl < 0 ? 'var(--color-sell)' : 'var(--text-main)');
    
    const aggBalEl = document.getElementById('agg-bal');
    if (aggBalEl) aggBalEl.innerText = `$${totalBal.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    
    const aggEqEl = document.getElementById('agg-eq');
    if (aggEqEl) aggEqEl.innerText = `$${totalEq.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    
    const aggPnlEl = document.getElementById('agg-pnl');
    if (aggPnlEl) {
        aggPnlEl.innerText = aggPnlStr;
        aggPnlEl.style.color = aggPnlColor;
    }
    
    const aggTradesEl = document.getElementById('agg-trades');
    if (aggTradesEl) aggTradesEl.innerText = totalTrades;

    const dateEl = document.getElementById('toolbar-date');
    if (dateEl) {
        const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
        dateEl.innerText = new Date().toLocaleDateString('en-US', options).toUpperCase();
    }
    
    updateFlowLines(instances);
}

let flowLines = {};
function updateFlowLines(instances) {
    if (typeof LeaderLine === 'undefined') return;

    const masters = instances.filter(i => i.copier_role === 'PROVIDER');
    const subs = instances.filter(i => i.copier_role === 'CONSUMER');

    const validKeys = new Set();

    if (masters.length > 0 && subs.length > 0) {
        const masterCard = document.getElementById(`health-card-${masters[0].id}`);
        
        if (masterCard) {
            subs.forEach(sub => {
                const subCard = document.getElementById(`health-card-${sub.id}`);
                if (subCard) {
                    const lineKey = `${masters[0].id}-${sub.id}`;
                    validKeys.add(lineKey);

                    if (!flowLines[lineKey]) {
                        flowLines[lineKey] = new LeaderLine(
                            masterCard,
                            subCard,
                            {
                                color: 'rgba(52, 152, 219, 0.4)',
                                size: 2,
                                path: 'fluid',
                                startSocket: 'bottom',
                                endSocket: 'top',
                                dropShadow: true,
                                dash: {animation: true}
                            }
                        );
                    } else {
                        try { flowLines[lineKey].position(); } catch(e) {}
                    }
                }
            });
        }
    }

    for (const key in flowLines) {
        if (!validKeys.has(key)) {
            try { flowLines[key].remove(); } catch(e) {}
            delete flowLines[key];
        }
    }
}

window.addEventListener('resize', () => {
    for (const key in flowLines) {
        try { flowLines[key].position(); } catch(e) {}
    }
});

const activePosExpanded = {};
const prevProfits = {};
const prevInstProfits = {};
const prevPrices = {};

function renderActivePositions(instances) {
    const tbody = document.getElementById('active-positions-tbody');
    if (!tbody) return;
    
    // Generate unique rendering keys representing the structure
    const currentKeys = instances.map(inst => {
        if (inst.positions.length === 0) return '';
        const nodeId = `inst_pos_${inst.id}`;
        const isExpanded = activePosExpanded[nodeId] !== false; // default true
        const posKeys = isExpanded ? inst.positions.map(p => p.ticket).join(',') : '';
        return `inst-${inst.id}-${isExpanded}:${posKeys}`;
    }).filter(Boolean).join('|');

    if (tbody.dataset.renderKeys !== currentKeys) {
        tbody.dataset.renderKeys = currentKeys;
        
        let html = '';
        instances.forEach(inst => {
            if (inst.positions.length === 0) return;
            
            const nodeId = `inst_pos_${inst.id}`;
            if (activePosExpanded[nodeId] === undefined) {
                activePosExpanded[nodeId] = true; 
            }
            const isExpanded = activePosExpanded[nodeId];
            
            let instProfit = 0;
            inst.positions.forEach(p => {
                instProfit += p.profit;
                prevProfits[p.ticket] = p.profit;
                prevPrices[p.ticket] = p.price_current;
            });
            prevInstProfits[inst.id] = instProfit;
            const profColor = instProfit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)';
            const instProfitStr = instProfit.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            let roleBadge = '';
            if (inst.copier_role === 'PROVIDER') {
                roleBadge = `<span class="badge-dense" style="background: rgba(243, 156, 18, 0.15); color: #f39c12; margin-left: 5px; font-size: 9px; vertical-align: middle;">👑 MASTER</span>`;
            } else if (inst.copier_role === 'CONSUMER') {
                roleBadge = `<span class="badge-dense" style="background: rgba(52, 152, 219, 0.15); color: #3498db; margin-left: 5px; font-size: 9px; vertical-align: middle;">👥 SUB</span>`;
            }
            
            html += `
                <tr class="tree-header tree-toggle" style="cursor: pointer;" onclick="toggleActivePos('${nodeId}')">
                    <td colspan="8" style="padding: 4px 8px;">
                        <span class="toggle-icon ${isExpanded ? '' : 'collapsed'}">▼</span>
                        <strong>${inst.name}</strong>${roleBadge}
                        <span style="font-size: 9px; color: var(--text-muted); margin-left: 10px;" id="inst-count-${inst.id}">${inst.positions.length} Trades</span>
                        <span style="float: right; color: ${profColor}; font-weight: bold;" id="inst-profit-${inst.id}">$${instProfitStr}</span>
                    </td>
                </tr>
            `;
            
            if (isExpanded) {
                inst.positions.forEach(p => {
                    const pColor = p.profit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)';
                    const tClass = p.type === 'BUY' ? 'bdg-buy' : 'bdg-sell';
                    const distSlStr = p.dist_sl >= 0 ? p.dist_sl.toFixed(1) : 'No SL';
                    const riskStr = p.risk_usd.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    const profStr = p.profit.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    
                    html += `
                        <tr id="pos-row-${p.ticket}">
                            <td class="indent-1" style="padding: 4px 8px;">
                                <strong>${p.symbol}</strong>
                            </td>
                            <td style="padding: 4px 8px;"><span class="badge-dense ${tClass}">${p.type}</span></td>
                            <td style="padding: 4px 8px;">${p.volume}</td>
                            <td style="padding: 4px 8px;">${p.price_open}</td>
                            <td style="padding: 4px 8px;" id="pos-price-${p.ticket}">${p.price_current}</td>
                            <td style="padding: 4px 8px;" id="pos-sl-${p.ticket}">${distSlStr}</td>
                            <td style="padding: 4px 8px;" id="pos-risk-${p.ticket}">$${riskStr}</td>
                            <td style="padding: 4px 8px; color: ${pColor}; font-weight: bold;" id="pos-profit-${p.ticket}">$${profStr}</td>
                        </tr>
                    `;
                });
            }
        });
        tbody.innerHTML = html;
    } else {
        // Update changed values in place
        instances.forEach(inst => {
            if (inst.positions.length === 0) return;
            
            let instProfit = 0;
            inst.positions.forEach(p => instProfit += p.profit);
            const profColor = instProfit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)';
            const instProfitStr = instProfit.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            
            const countEl = document.getElementById(`inst-count-${inst.id}`);
            if (countEl) countEl.innerText = `${inst.positions.length} Trades`;
            
            const profitEl = document.getElementById(`inst-profit-${inst.id}`);
            if (profitEl) {
                const prevVal = prevInstProfits[inst.id] !== undefined ? prevInstProfits[inst.id] : instProfit;
                const newVal = instProfit;
                prevInstProfits[inst.id] = newVal;
                
                profitEl.innerText = `$${instProfitStr}`;
                profitEl.style.color = profColor;
                
                if (newVal > prevVal) {
                    profitEl.classList.remove('flash-up', 'flash-down');
                    void profitEl.offsetWidth; // trigger reflow
                    profitEl.classList.add('flash-up');
                } else if (newVal < prevVal) {
                    profitEl.classList.remove('flash-up', 'flash-down');
                    void profitEl.offsetWidth; // trigger reflow
                    profitEl.classList.add('flash-down');
                }
            }
            
            inst.positions.forEach(p => {
                const pColor = p.profit >= 0 ? 'var(--color-buy)' : 'var(--color-sell)';
                const distSlStr = p.dist_sl >= 0 ? p.dist_sl.toFixed(1) : 'No SL';
                const riskStr = p.risk_usd.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                const profStr = p.profit.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                
                const priceEl = document.getElementById(`pos-price-${p.ticket}`);
                if (priceEl) {
                    const prevVal = prevPrices[p.ticket] !== undefined ? prevPrices[p.ticket] : p.price_current;
                    const newVal = p.price_current;
                    prevPrices[p.ticket] = newVal;
                    
                    priceEl.innerText = p.price_current;
                    
                    if (newVal > prevVal) {
                        priceEl.classList.remove('flash-up', 'flash-down');
                        void priceEl.offsetWidth; // trigger reflow
                        priceEl.classList.add('flash-up');
                    } else if (newVal < prevVal) {
                        priceEl.classList.remove('flash-up', 'flash-down');
                        void priceEl.offsetWidth; // trigger reflow
                        priceEl.classList.add('flash-down');
                    }
                }
                
                const slEl = document.getElementById(`pos-sl-${p.ticket}`);
                if (slEl) slEl.innerText = distSlStr;
                
                const riskEl = document.getElementById(`pos-risk-${p.ticket}`);
                if (riskEl) riskEl.innerText = `$${riskStr}`;
                
                const profEl = document.getElementById(`pos-profit-${p.ticket}`);
                if (profEl) {
                    const prevVal = prevProfits[p.ticket] !== undefined ? prevProfits[p.ticket] : p.profit;
                    const newVal = p.profit;
                    prevProfits[p.ticket] = newVal;
                    
                    profEl.innerText = `$${profStr}`;
                    profEl.style.color = pColor;
                    
                    if (newVal > prevVal) {
                        profEl.classList.remove('flash-up', 'flash-down');
                        void profEl.offsetWidth; // trigger reflow
                        profEl.classList.add('flash-up');
                    } else if (newVal < prevVal) {
                        profEl.classList.remove('flash-up', 'flash-down');
                        void profEl.offsetWidth; // trigger reflow
                        profEl.classList.add('flash-down');
                    }
                }
            });
        });
    }
}

window.toggleActivePos = function(nodeId) {
    activePosExpanded[nodeId] = !activePosExpanded[nodeId];
    if (window.lastRiskData) {
        renderActivePositions(window.lastRiskData);
    }
};

window.toggleActivePositions = function() {
    const pane = document.getElementById('pane-active-positions');
    const icon = document.getElementById('active-positions-toggle-icon');
    if (pane && icon) {
        if (pane.classList.contains('collapsed')) {
            pane.classList.remove('collapsed');
            icon.innerText = '▼';
        } else {
            pane.classList.add('collapsed');
            icon.innerText = '▶';
        }
    }
};

// Workspace Splitter Logic
document.addEventListener('DOMContentLoaded', () => {
    let isDraggingSplitter = false;
    const splitter = document.getElementById('main-splitter');
    const workspace = document.getElementById('main-workspace');

    if (splitter && workspace) {
        // Restore saved position
        const savedTopHeight = localStorage.getItem('workspaceTopHeight');
        if (savedTopHeight) {
            workspace.style.gridTemplateRows = `${savedTopHeight}px 4px 1fr`;
        }

        splitter.addEventListener('mousedown', (e) => {
            isDraggingSplitter = true;
            splitter.classList.add('active');
            document.body.style.cursor = 'row-resize';
            e.preventDefault();
        });

        window.addEventListener('mousemove', (e) => {
            if (!isDraggingSplitter) return;
            
            const workspaceRect = workspace.getBoundingClientRect();
            const relativeY = e.clientY - workspaceRect.top;
            
            // Limit the top pane to a minimum of 150px and bottom pane minimum of 150px
            const topHeight = Math.max(150, Math.min(relativeY, workspaceRect.height - 150));
            
            workspace.style.gridTemplateRows = `${topHeight}px 4px 1fr`;
            localStorage.setItem('workspaceTopHeight', topHeight);
            
            // Redraw LeaderLines on resize
            if (typeof flowLines !== 'undefined') {
                for (const key in flowLines) {
                    try { flowLines[key].position(); } catch(err) {}
                }
            }
        });

        window.addEventListener('mouseup', () => {
            if (isDraggingSplitter) {
                isDraggingSplitter = false;
                splitter.classList.remove('active');
                document.body.style.cursor = '';
            }
        });
    }
});