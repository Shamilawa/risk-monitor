import sys

with open('d:/Coding/risk_monitor/mt5_bridge/static/main.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    # Skip fetchPerformance and renderPerf
    if 'function fetchPerformance()' in line:
        skip = True
    if 'function renderPerformance(data)' in line:
        skip = True
    if 'function renderCharts(trades)' in line:
        skip = True
    if 'function updateStoryNotes()' in line:
        skip = True
    if 'function renderActivePositions(payload)' in line:
        skip = False # These functions are over, resume appending. BUT wait, how do I know when the previous functions ended?

