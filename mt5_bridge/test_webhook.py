import urllib.request
import json

url = 'http://127.0.0.1:5000/webhook'
data = {
    "action": "buy",
    "symbol": "EURUSD",
    "entry": 1.17349,
    "sl": 1.17182,
    "tp1": 1.17464,
    "tp2": 1.17564,
    "risk_usd": 100.0
}

req = urllib.request.Request(url)
req.add_header('Content-Type', 'application/json')
jsondata = json.dumps(data).encode('utf-8')

print(f"Sending test signal to {url}...")
try:
    response = urllib.request.urlopen(req, jsondata)
    print(f"Response: {response.read().decode('utf-8')}")
    print("Signal sent successfully! Check your other CMD window.")
except Exception as e:
    print(f"Failed to send signal: {e}")
    print("Make sure your run.bat server is running!")
    
input("Press Enter to exit...")
