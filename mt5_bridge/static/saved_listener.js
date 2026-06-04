eventSource.addEventListener('risk_data', (e) => {
    try {
        const payload = JSON.parse(e.data);
        renderHealthCards(payload);
        renderActivePositions(payload);
    } catch (err) {
        console.error("Error parsing risk_data:", err);
    }
});