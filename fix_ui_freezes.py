import re

def patch_index():
    with open('mt5_bridge/templates/index.html', 'r', encoding='utf-8') as f:
        html = f.read()
        
    modal_html = """
    <!-- Trade/Story Modal -->
    <div id="trade-modal" class="modal-overlay">
        <div class="modal">
            <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
                <span>Trade Details</span>
                <button id="modal-close-btn" class="btn-close-modal">&times;</button>
            </div>
            <div class="modal-body" style="padding: 15px;">
                <h4 id="modal-action-symbol" style="margin-bottom: 15px;"></h4>
                <div class="input-field-group col-full">
                    <label>Story Notes</label>
                    <textarea id="modal-notes-input" rows="4" placeholder="Enter notes for this trade..." style="width: 100%; resize: vertical; padding: 8px; background: var(--bg-input); border: 1px solid var(--border-dark); color: var(--text-main); border-radius: 4px;"></textarea>
                </div>
                <button id="modal-save-btn" class="btn btn-primary-premium" style="width: 100%; margin-top: 10px;">Save Notes</button>
            </div>
        </div>
    </div>
    
    <!-- Settings Modal -->
"""
    html = html.replace('    <!-- Settings Modal -->', modal_html)
    
    with open('mt5_bridge/templates/index.html', 'w', encoding='utf-8') as f:
        f.write(html)

def patch_main():
    with open('mt5_bridge/static/main.js', 'r', encoding='utf-8') as f:
        js = f.read()

    # 1. Fix trackerTbody reference
    js = js.replace("const trackerTbody = document.getElementById('tracker-tbody');", "const trackerTbody = document.getElementById('log-tbody');")
    
    # 2. Fix the activePosExpanded toggler to immediately re-render
    toggler_code_old = """window.toggleActivePos = function(nodeId) {
    activePosExpanded[nodeId] = !activePosExpanded[nodeId];
    // Next risk_data SSE tick will re-render with new state
};"""
    
    toggler_code_new = """window.toggleActivePos = function(nodeId) {
    activePosExpanded[nodeId] = !activePosExpanded[nodeId];
    if (window.lastRiskData) {
        renderActivePositions(window.lastRiskData);
    }
};"""
    js = js.replace(toggler_code_old, toggler_code_new)
    
    # 3. Store lastRiskData and fix Close All button listener
    risk_data_listener_old = """    eventSource.addEventListener('risk_data', (e) => {
        try {
            const payload = JSON.parse(e.data);
            renderHealthCards(payload);
            renderActivePositions(payload);
        } catch (err) {
            console.error("Error parsing risk_data:", err);
        }
    });"""
    
    risk_data_listener_new = """    eventSource.addEventListener('risk_data', (e) => {
        try {
            const payload = JSON.parse(e.data);
            window.lastRiskData = payload;
            renderHealthCards(payload);
            renderActivePositions(payload);
        } catch (err) {
            console.error("Error parsing risk_data:", err);
        }
    });

    // Close All Buttons Delegation
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('btn-close-all')) {
            const instId = e.target.getAttribute('data-id');
            if (instId && confirm("Close all active positions for this instance?")) {
                e.target.innerText = "Closing...";
                fetch('/api/close_all', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ instance_id: instId })
                }).then(res => res.json()).then(data => {
                    e.target.innerText = "Close All";
                    if (data.status !== 'success') alert("Failed: " + data.error);
                }).catch(err => {
                    e.target.innerText = "Close All";
                    alert("Error: " + err);
                });
            }
        }
    });
"""
    js = js.replace(risk_data_listener_old, risk_data_listener_new)
    
    # 4. Add data-id to the btn-close-all button in renderHealthCards
    js = js.replace('<button class="btn-toolbar" style="color: var(--color-sell); border-color: var(--color-sell); padding: 2px 6px; font-size: 10px;">Close All</button>', 
                    '<button class="btn-toolbar btn-close-all" data-id="${inst.id}" style="color: var(--color-sell); border-color: var(--color-sell); padding: 2px 6px; font-size: 10px; cursor: pointer;">Close All</button>')
                    
    # 5. Add data-id to Trading Log rows so they can be clicked
    js = js.replace("tr.innerHTML = `", "tr.setAttribute('data-id', t.id || t.ticket);\n                tr.innerHTML = `")
    js = js.replace("tr.setAttribute('data-id', t.id || t.ticket);\\n                tr.setAttribute('data-id', t.id || t.ticket);\\n", "tr.setAttribute('data-id', t.id || t.ticket);\n") # Deduplicate just in case
    
    # 6. Change modal data extraction for the trade-modal in trackerTbody click handler
    old_modal_extract = """            modalActionSymbol.innerText = tr.querySelector('td:nth-child(2)').innerText;
            const notesCell = tr.querySelector('td:nth-child(8)');
            modalNotesInput.value = notesCell ? notesCell.innerText : "";"""
            
    new_modal_extract = """            modalActionSymbol.innerText = tr.querySelector('td:nth-child(3)').innerText + ' / ' + tr.querySelector('td:nth-child(2)').innerText;
            // Trading log doesn't have notes displayed in the row anymore, we will just clear it or fetch it if needed.
            // For now, clear it to let user write new notes.
            modalNotesInput.value = "";"""
    js = js.replace(old_modal_extract, new_modal_extract)
    
    with open('mt5_bridge/static/main.js', 'w', encoding='utf-8') as f:
        f.write(js)

patch_index()
patch_main()
print("Patched completely!")
