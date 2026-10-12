# main.py - identical on all 4 boards (MicroPython, no external libraries needed)
#
# Wiring: LD2410 VCC->5V, GND->GND, OUT->MOTION_PIN (HIGH = presence, moving
# or still, in the module's default settings). Buzzer on BUZZER_PIN via a
# transistor.
#
# GET  http://<board-ip>/          -> {"name": "...", "motion": 0 or 1}
# GET  http://<board-ip>/buzz?on=1 -> turns the buzzer on (blinking); on=0 off

import network
import socket
import time
import machine
from machine import Pin
import config

wlan = network.WLAN(network.STA_IF)
motion = Pin(config.MOTION_PIN, Pin.IN)
buzzer = Pin(config.BUZZER_PIN, Pin.OUT, value=0)
buzzer_on = False


def wifi_connect():
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(config.WIFI_SSID, config.WIFI_PASS)
        for _ in range(30):
            if wlan.isconnected():
                break
            time.sleep(1)
    if not wlan.isconnected():
        raise OSError("Wi-Fi connection failed")
    print("Board '{}' ready at http://{}/".format(config.BOARD_NAME, wlan.ifconfig()[0]))


def handle(conn):
    global buzzer_on
    try:
        conn.settimeout(1)
        request = conn.recv(512)
        path = request.split(b" ", 2)[1]
        if path.startswith(b"/buzz"):
            buzzer_on = b"on=1" in path
            body = b'{"ok":true}'
        else:
            body = '{{"name":"{}","motion":{}}}'.format(
                config.BOARD_NAME, 1 if motion.value() else 0
            ).encode()
        conn.send(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n")
        conn.send(body)
    except Exception:
        pass
    finally:
        conn.close()


def main():
    wifi_connect()
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", 80))
    server.listen(2)
    server.settimeout(0.05)          # so the loop below still runs the buzzer

    wdt = machine.WDT(timeout=60000)  # reboots the board if it ever hangs
    last_toggle = time.ticks_ms()

    while True:
        try:
            conn, _ = server.accept()
            handle(conn)
        except OSError:
            pass  # just means "no request waiting right now"

        if buzzer_on:
            now = time.ticks_ms()
            if time.ticks_diff(now, last_toggle) > 400:
                buzzer.value(not buzzer.value())
                last_toggle = now
        else:
            buzzer.value(0)

        if not wlan.isconnected():
            machine.reset()          # clean restart if Wi-Fi drops
        wdt.feed()


main()
