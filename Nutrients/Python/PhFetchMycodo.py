import datetime, json, requests, urllib3
urllib3.disable_warnings()          # self-signed cert on the Pi
import serial
import time
import os


BT_PORT_DOWN = 'n'      
BT_PORT_UP = 'COM10'
BAUD_RATE = 9600   

PI_IP      = ""         # change to your Pi’s address
API_KEY    = os.environ["MYCODO_API_KEY"]
DEVICE_ID  = "0e004ed7-7557-4361-b3da-6b695b3b7360"   # PH sensor
UNIT       = "pH"
CHANNEL    = 0
WINDOW_SEC = 60                    # last 10 min
PH_UPPER_BOUND = 6.6
PH_LOWER_BOUND = 6.4
ADJUSTMENT = 2

url = (f"https://{PI_IP}/api/measurements/last/"
       f"{DEVICE_ID}/{UNIT}/{CHANNEL}/{WINDOW_SEC}")

headers = {
    "Accept": "application/vnd.mycodo.v1+json",
    "X-API-KEY": API_KEY
}

r = requests.get(url, headers=headers, verify=False)
r.raise_for_status()
data = r.json()

ts = datetime.datetime.fromtimestamp(data["time"])
pH = data['value']

if (pH < PH_LOWER_BOUND):

    print("adjust up: " + f"{ADJUSTMENT}")
    try:
        bt = serial.Serial(BT_PORT_UP, BAUD_RATE, timeout=1)
        time.sleep(2)  

        bt.write(b'd,2\n')

        bt.close()

    except serial.SerialException as e:
        print("Failed to connect or send:", e)
elif (pH > PH_UPPER_BOUND):

    print("adjust down: " + f"{ADJUSTMENT}")
    try:
        bt = serial.Serial(BT_PORT_DOWN, BAUD_RATE, timeout=1)
        time.sleep(2)  

        bt.write(b'd,2\n')

        bt.close()

    except serial.SerialException as e:
        print("Failed to connect or send:", e)

print(f"{UNIT} = {pH} (measured {ts})")
