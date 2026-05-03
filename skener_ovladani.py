from threading import Lock, Thread, Event
from time import sleep
from requests import get

url = "http://localhost:5001/state"

class Skener:
    def __init__(self):
        self.pos = 0
        self.end = 0
        self.lock = Lock()
        self.pause_event = Event()
        self.pause_event.set()
        self.is_running = False

    def setup(self):
        with self.lock:
            self.pos = 0
            self.end = 100

    def start_inc(self):
        if not self.is_running:
            self.is_running = True
            Thread(target=self.__loop_inc, daemon=True).start()

    def __loop_inc(self):
        while self.is_running:
            self.pause_event.wait()

            if self.pos > self.end:
                self.is_running = False
                get(url=url)
                continue
            
            with self.lock:
                if self.pos <= self.end:
                    self.pos += 1

            sleep(2)

    def pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
        else:
            self.pause_event.set()


    def kill(self):
        with self.lock:
            self.is_running = False
            self.pos = 0
            self.end = 0
