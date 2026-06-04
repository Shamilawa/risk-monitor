import re

def patch_main_tabs():
    with open('mt5_bridge/static/main.js', 'r', encoding='utf-8') as f:
        js = f.read()

    # Find the tabs click listener
    old_tabs_logic = """        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentTab = tab.getAttribute('data-tab');

            const filterGroup = document.getElementById('tracker-filters');
            const mainTableContainer = document.querySelector('.grid-section > .table-container');
            const logContainer = document.getElementById('trading-log-container');
            const storyContainer = document.getElementById('story-notes-container');
            if (filterGroup) filterGroup.style.display = 'none';
            if (mainTableContainer) mainTableContainer.style.display = 'none';
            if (logContainer) logContainer.style.display = 'none';
            if (storyContainer) storyContainer.style.display = 'none';

            if (currentTab === 'log') {
                if (logContainer) logContainer.style.display = 'flex';
                fetchPerformance();
            } else if (currentTab === 'story') {
                if (storyContainer) storyContainer.style.display = 'flex';
                fetchStoryDates();
            } else {
                if (filterGroup) filterGroup.style.display = 'flex';
                if (mainTableContainer) mainTableContainer.style.display = 'block';
                fetchTracker();
            }
        });"""
        
    new_tabs_logic = """        tab.addEventListener('click', () => {
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
        });"""
        
    js = js.replace(old_tabs_logic, new_tabs_logic)
    
    # Let's also hide the Close All button to prevent confusion since it's not implemented yet in the backend
    js = js.replace('<button class="btn-toolbar btn-close-all"', '<button class="btn-toolbar btn-close-all" style="display: none;"')
    
    with open('mt5_bridge/static/main.js', 'w', encoding='utf-8') as f:
        f.write(js)

patch_main_tabs()
print("Tabs patched!")
