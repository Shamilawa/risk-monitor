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

    let currentTradePayload = null;
    fetchTracker();

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
        const isOnline = e.data === 'true';
        if (isOnline) {
            mt5StatusIcon.className = 'status-icon online';
            mt5StatusText.innerText = 'MT5 Connected';
        } else {
            mt5StatusIcon.className = 'status-icon offline';
            mt5StatusText.innerText = 'MT5 Offline';
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

    // State map to remember which nodes are expanded
    // Default is false (collapsed). We store true for expanded nodes.
    const expandedState = {};
    let currentFilter = 'all'; // 'all', 'active', 'pending'

    function fetchTracker() {
        fetch('/api/tracker')
            .then(res => res.json())
            .then(data => { renderTrackerTable(data); })
            .catch(err => console.error("Error fetching tracker:", err));
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

    function getFriendlyStatus(status) {
        if (!status) return 'Unknown';
        if (status === 'PENDING_ORIGINAL') return 'Waiting for Fill';
        if (status === 'ACTIVE') return 'Live';
        if (status === 'SUCCESS_TP1_HIT') return 'Target Hit';
        if (status === 'RECOVERY_TRIGGERED') return 'In Recovery';
        if (status === 'CANCELLED') return 'Cancelled';
        if (status === 'PENDING (Placed)') return 'Recovery Placed';
        return status; // fallback
    }

    function renderTrackerTable(rows) {
        trackerTbody.innerHTML = '';
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
                    <td colspan="4">
                        <span class="toggle-icon ${symExpanded ? '' : 'collapsed'}">▼</span>
                        <strong>${sym}</strong> <span style="font-size: 10px; color: var(--text-muted);">(${filteredGroups.length} Groups)</span>
                    </td>
                </tr>
            `;

            if (symExpanded) {
                filteredGroups.forEach(g => {
                    const groupNodeId = `grp_${sym}_${g.magic_number}`;
                    const groupExpanded = expandedState[groupNodeId] === true; // Default to false
                    
                    // Group Row
                    trackerTbody.innerHTML += `
                        <tr class="tree-toggle" data-node-id="${groupNodeId}">
                            <td class="indent-1">
                                <span class="toggle-icon ${groupExpanded ? '' : 'collapsed'}">▼</span>
                                Magic: ${g.magic_number}
                            </td>
                            <td></td>
                            <td>Trade Group</td>
                            <td><span class="badge-dense ${getBadgeClass(g.status)}">${getFriendlyStatus(g.status)}</span></td>
                        </tr>
                    `;

                    if (groupExpanded) {
                        // Orig 1
                        trackerTbody.innerHTML += `
                            <tr>
                                <td class="indent-2">Orig 1 (TP1)</td>
                                <td>${g.trade_1_ticket || 'N/A'}</td>
                                <td>Original</td>
                                <td><span class="badge-dense ${getBadgeClass(g.status)}">${getFriendlyStatus(g.status)}</span></td>
                            </tr>
                        `;

                        // Orig 2
                        if (g.trade_2_ticket) {
                            trackerTbody.innerHTML += `
                                <tr>
                                    <td class="indent-2">Orig 2 (TP2)</td>
                                    <td>${g.trade_2_ticket}</td>
                                    <td>Original</td>
                                    <td><span class="badge-dense ${getBadgeClass(g.status)}">${getFriendlyStatus(g.status)}</span></td>
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
                                <td>${g.recovery_ticket || 'N/A'}</td>
                                <td>Recovery</td>
                                <td><span class="badge-dense ${getBadgeClass(recStatus)}">${getFriendlyStatus(recStatus)}</span></td>
                            </tr>
                        `;
                    }
                });
            }
        }
    }

    function getBadgeClass(status) {
        if (!status) return 'bdg-cancel';
        if (status === 'ACTIVE') return 'bdg-active';
        if (status.startsWith('PENDING')) return 'bdg-pending';
        if (status === 'SUCCESS_TP1_HIT') return 'bdg-buy';
        if (status === 'RECOVERY_TRIGGERED') return 'bdg-sell';
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
        addRow("Risk Amount", `$${data.risk_usd}`);
        addRow("Total Lot Size", `${data.calculated_volume} Lots`);
        addRow("Recovery Trade", `${data.rec_action} @ ${data.rec_entry} (Vol: ${data.rec_volume})`);

        if (data.split_trade) {
            modalSplitInfo.innerHTML = `Split Execution: [1] ${data.vol1} Lots (TP1) &nbsp; [2] ${data.vol2} Lots (TP2)`;
        } else {
            modalSplitInfo.innerHTML = `Single Execution (TP1 only).<br><span style="font-size: 9px; font-weight: normal;">Reason: ${data.split_reason}</span>`;
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
});
