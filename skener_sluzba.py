from flask import Flask, jsonify
from waitress import serve
from threading import Thread
from time import sleep
from rpi_lcd import LCD
from skener_ovladani import Skener

states = ["neskenuje","skenuje","pozastaveno","hotovo","chyba"]

class State:
    def __init__(self):
        self.state = states[0]
        self.dir = "/var/www/html/scans"
        self.pos = 0
        self.end = 100

data = State()

try:
    lcd = LCD()
except:
    lcd = None

scan = Skener()

# ---

app_control = Flask(__name__)

@app_control.route("/start")
def start():
    global scan

    scan = Skener()

    scan.setup()
    scan.start_inc()

    data.state = states[1]

    return "scan started", 200

@app_control.route("/stop")
def stop():
    global scan

    if data.state == states[0]:
        return "not a state", 400

    scan.pause()
        
    if data.state == states[1]:
        data.state = states[2]
        return "scan stopped", 200

    elif data.state == states[2]:
        data.state = states[1]
        return "scan resumed", 200

@app_control.route("/kill")
def kill():
    global scan

    scan.kill()

    data.state = states[0]
    return "scan killed", 200

def run_control():
    serve(app_control, host="0.0.0.0", port=5000)

# ---

app_state = Flask(__name__)

@app_state.route('/state')
def get_state():
    global scan

    data.pos = scan.pos
    data.end = scan.end

    if data.pos > data.end:
        data.state = states[3]

    return jsonify({
        "name": "Skener",
        "scan_state": data.state,
        "scan_dir": data.dir,
        "scan_process": {
            "pos": data.pos, 
            "end": data.end
        }
    })

def run_state():
    serve(app_state, host="0.0.0.0", port=5001)

# ---

def lcd_worker():
    global scan

    if lcd is None:
        return

    last_text = ""
    while True:
        text1 = f"{data.state}"
        text2 = f"{data.pos}/{data.end}"

        current_text = text1 + text2

        if current_text != last_text:

            lcd.text(text1, 1)
            lcd.text(text2, 2)
            last_text = current_text

        sleep(0.5)
# ---

if __name__ == "__main__":

    t1 = Thread(target=run_control)
    t2 = Thread(target=run_state)
    t3 = Thread(target=lcd_worker, daemon=True)

    t1.start()
    t2.start()
    t3.start()

    t1.join()
    t2.join()
    t3.join()
