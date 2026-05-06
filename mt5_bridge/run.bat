@echo off
echo ===================================================
echo Starting MT5 Python Bridge...
echo Make sure MT5 is open and Algo Trading is enabled!
echo ===================================================
echo Starting Ngrok in a separate window...
start "Ngrok Tunnel" ngrok http 5000
python app.py
pause
