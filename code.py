# SPDX-License-Identifier: MIT
import time
import board
import asyncio
import digitalio
import microcontroller
import watchdog
import neopixel
import wifi
import adafruit_connection_manager
from adafruit_pcf8523.pcf8523 import PCF8523
import time_lord
import local_logger as logger
import local_mqtt

# Replacement brains for circa 1987 home security system
# The system has 8 zones
# Each zone will be tied to an available GPIO
# First iteration will use Adafruit.io to display status

# All sensors in a zone closed = False
# Any sensor in a zone open = True


# --- import configurable items here --- #

try:
    from data import data
except ImportError:
    print("Configuration data stored in data.py, please create file")
    raise

try:
    from mqtt_data import mqtt_data
except ImportError:
    print("MQTT configuration stored in mqtt_data.py")
    raise

# --- Set up --- #

host = mqtt_data["server"]
cert_file = mqtt_data["cert_file"]
with open(cert_file, 'r') as file:
    cert_data = file.read()

radio = wifi.radio
pool = adafruit_connection_manager.get_radio_socketpool(radio)
ssl_context = adafruit_connection_manager.get_radio_ssl_context(radio)
ssl_context.load_verify_locations(cadata=cert_data)

# Set up I2C
i2c = board.I2C()
rtc = PCF8523(i2c)

# Timey wimey
my_time = time_lord.configure_time(pool, rtc)

# Logging
my_log = logger.getLocalLogger(use_time=False)
if my_log is not None:
    my_log.log_message("Created logging singleton", "info")
else:
    print("Did not create logging singleton!")

# MQTT
my_mqtt = local_mqtt.getMqtt(pool, ssl_context, use_logger=True)

# Watchdog
watchdog_timeout = data["watchdog_timeout"]
apollo = microcontroller.watchdog
apollo.timeout = watchdog_timeout
apollo.mode = watchdog.WatchDogMode.RAISE

# Colors for NeoPixel
RED = 0xF00000
GREEN = 0x0FF000
YELLOW = 0xF0F000
ORANGE = 0XF00F00
OFF = 0X000000

# On-board NeoPixel
pixel_pin = neopixel.NeoPixel(board.NEOPIXEL, 1)

# Power relay featherwing
relay_pin = digitalio.DigitalInOut(board.A5)
relay_pin.direction = digitalio.Direction.OUTPUT


# --- Helper Methods --- #

# connect to Wi-Fi
def connect_wifi():
    try:
        # wifi.radio.connect(os.getenv('CIRCUITPY_WIFI_SSID'), os.getenv('CIRCUITPY_WIFI_PASSWORD'))
        wifi.radio.connect(data["wifi_ssid"], data["wifi_password"])
        my_log.log_message("connected to Wi-Fi Network " + str(wifi.radio.ap_info.ssid), "info")
        my_mqtt.connect()
    except ConnectionError:
        my_log.log_message("Unable to connect to network", "critical")
        raise


# Signal the alarm system that motion has been detected
# Wait for 1 second then return the pin to False
def trip_zone(pin):
    if pin.value is False:
        pin.value = True
        time.sleep(4)
        pin.value = False


# --- MQTT Subscribe callback methods --- #
# Behavior when a message is published to a subscribed feed
def message(client, topic, message):
    # listen for messages from sensors being monitored
    if "pir1" in topic:
        log_message = "Motion detected by PIR sensor 1"
        my_mqtt.publish(my_mqtt.gen_topic, log_message, "info")
        trip_zone(relay_pin)


# Behavior when connected to the MQTT broker
# Subscribe to relevant topics
def connected(client, userdata, flags, rc):
    my_mqtt.subscribe(topics)  # subscribe to topics
    my_log.log_message("Connected to MQTT and subscribed to topics!", "info")


# Behavior when disconnected from MQTT broker
# Log a warning and try to reconnect
def disconnected(client, userdata, rc):
    log_message = "Disconnected from MQTT! Will try to reconnect"
    my_log.log_message(log_message, "warning")
    time.sleep(5)
    try:
        if not my_mqtt.mqtt_client.is_connected():
            my_mqtt.mqtt_client.connect()
    except RuntimeError as r:
        my_log.log_message("Error: " + str(r) + " Could not reconnect to MQTT, no longer listening", "warning")


# Asynchronous Methods --- #

# Class so all coroutines have the same wait time
class Controls:
    def __init__(self):
        self.reverse = False
        self.wait = 0.25


# Listener for all subscribed MQTT feeds
async def mqtt_listener(controls):
    while True:
        my_mqtt.mqtt_client.loop(timeout=1.25)  # Listen to the subscribed feeds
        await asyncio.sleep(controls.wait)


# Feed the watchdog
async def maintain_watchdog():
    watchdog_sleep = watchdog_timeout / 2
    while True:
        apollo.feed()
        await asyncio.sleep(watchdog_sleep)


# --- On Start Setup Tasks --- #

topics = []

# Set up MQTT for publish/subscribe
my_mqtt.mqtt_client.on_message = message
my_mqtt.mqtt_client.on_connect = connected
my_mqtt.mqtt_client.on_disconnect = disconnected

# Subscribe to sensor feeds in MQTT
# All feeds should be in the data.py file
sensor_feeds = data["sensor_feeds"]
for _ in range(len(sensor_feeds)):
    feed_name = sensor_feeds[_]
    topics.append(feed_name)

connect_wifi()

my_log.log_message("Ready")


# --- Main --- #
async def main():
    controls = Controls()
    task_array = []

    # Listen for MQTT messages
    mqtt_listener_task = asyncio.create_task(mqtt_listener(controls))
    task_array.append(mqtt_listener_task)
    # Feed the Watchdog
    maintain_watchdog_task = asyncio.create_task(maintain_watchdog())
    task_array.append(maintain_watchdog_task)

    for _ in range(len(task_array)):
        await asyncio.gather(task_array[_])


# Kick off all tasks
# This is in a try/except block so that we can handle it if the watchdog raises an exception
try:
    asyncio.run(main())
except watchdog.WatchDogTimeout as w:
    print("Error:", w)
    microcontroller.reset()
