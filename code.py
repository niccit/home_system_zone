# SPDX-License-Identifier: MIT
import json
import os
import time
import board
import busio
import countio
import digitalio
import asyncio
import ipaddress
import keypad
import microcontroller
import neopixel
import wifi
import watchdog
import socketpool
import displayio
import local_logger as logger
import time_lord as my_time
import alarm_handler as my_alarm
import one_mqtt
import siren
import zone
from adafruit_debouncer import Debouncer
from adafruit_io.adafruit_io_errors import AdafruitIO_MQTTError
from watchdog import WatchDogMode
from microcontroller import watchdog as apollo

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


# --- Set up --- #

# Network
pool = socketpool.SocketPool(wifi.radio)

# Watchdog
watchdog_timeout = data["watchdog_timeout"]
apollo.timeout = watchdog_timeout


# Logging
logger.initialize_storage()
my_log = logger.getLocalLogger()
my_log.add_sd_stream()

# Timey wimey stuff
# Gets current date from ntp and sets the RTC
my_time.set_up_system_time(pool)

# Colors for NeoPixel
RED = 0xF00000
GREEN = 0x0FF000
YELLOW = 0xF0F000
ORANGE = 0XF00F00
OFF = 0X000000

# On-board NeoPixel
pixel_pin = neopixel.NeoPixel(board.NEOPIXEL, 1)


# --- Helper Methods --- #
# Connect to local WiFi
def connect_wifi():
    log_message = "Attempting to connect to network"
    my_log.log_message(log_message, "info")
    wifi.radio.connect(os.getenv('CIRCUITPY_WIFI_SSID'), os.getenv('CIRCUITPY_WIFI_PASSWORD'))

    ping_ip = ipaddress.IPv4Address('8.8.8.8')
    ping = wifi.radio.ping(ping_ip)
    if ping is not None:
        ssid = wifi.radio.ap_info.ssid
        log_message = "Connected to " + ssid
        my_log.log_message(log_message, "debug")
        connect_mqtt()
        my_mqtt.publish(my_mqtt.gen_topic, log_message, "info")
    else:
        log_message = "Could not connect to network!"
        my_log.log_message(log_message, "critical")
        raise OSError


# Connect to MQTT broker
def connect_mqtt():
    wifi_connect_timeout = time.monotonic()
    mqtt_retry_limit = 20
    mqtt_connect_loop = True
    while mqtt_connect_loop is True:
        try:
            my_mqtt.connect()
            my_log.log_message("MQTT Connected!", "debug")
            mqtt_connect_loop = False
        except AdafruitIO_MQTTError as ae:
            log_message = "Couldn't connect to MQTT"
            my_log.log_message(log_message, "warning")
            if time.monotonic() >= wifi_connect_timeout + mqtt_retry_limit:
                log_message = "Error: - " + str(ae) + " resetting microcontroller"
                my_log.log_message(log_message, "critical")
                microcontroller.reset()
                mqtt_connect_loop = False
                pass


# Return the zone object based on pin number
def get_zone_info(pin):
    for p in range(len(patrol)):
        tmp_array = patrol[p]
        if tmp_array.pinID is pin:
            return tmp_array


# --- MQTT Subscribe callback methods --- #
# Behavior when a message is published to a subscribed feed
def message(client, topic, message):
    # Handle requests regarding zone changes
    # Handle triggering the alarm if the system is armed
    if "zone" in topic:
        my_log.log_message("alarm state is " + str(my_alarm.get_alarm_state()), "debug")
        my_log.log_message("siren state is " + str(my_siren.state), "debug")
        if message is "1" and my_alarm.get_alarm_state() is True:
            if my_alarm.get_zone_exclusion_state(topic) is False:
                if my_siren.state is True:
                    my_siren.steady()
                else:
                    my_log.log_message("sirens is already active", "info")
            else:
                my_log.log_message("This " + str(topic) + " is in the exclude list", "info")

    # Handle requests to enable/disable the alarm
    if "alarm" in topic:
        if message is not "0":
            my_log.log_message("Request to arm/disarm system", "info")
            my_alarm.manage_alarm(message)
            # For security log a value of 0 to the alarm management feed
            # The feed is configured to only keep one line of data
            my_log.close_sd_stream()
            my_log.add_mqtt_stream(one_mqtt.get_formatted_topic(data["alarm_management_feed_name"]))
            my_log.log_message(0000, mqtt=True)
            my_log.add_sd_stream()

    # Handle requests to get data from the system and state files on SD
    if "output" in topic:
        if "sys" in message:
            my_log.log_message("Request to read sdcard log file", "info")
            logger.dump_sd_log()
        elif "restart" in message:
            my_log.log_message("Request to read sdcard log file after restart", "info")
            logger.dump_sd_log(True)
        elif "alarm" in message:
            my_log.log_message("Request to get system state from disk", "info")
            logger.get_system_state()
        elif "exclusion" in message:
            my_log.log_message("Request to get excluded zones from disk", "info")
            logger.get_exclusions_list()
        elif "dir" in message:
            logger.list_sd_card()


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
    connect_mqtt()


# Asynchronous Methods --- #

# Class so all coroutines have the same wait time
class Controls:
    def __init__(self):
        self.reverse = False
        self.wait = 0.25


# Class so all coroutines use the same timer for dismissing an active alarm
class SirenControls:
    def __init__(self):
        self.timer = 0


# Listen for button presses on the NeoKey FeatherWing
# Disable Siren and Panic
async def catch_key_transition(pin, controls, siren_controls):
    with keypad.Keys((pin,), value_when_pressed=False) as keys:
        while True:
            event = keys.events.get()
            if event:
                if event.pressed:
                    if pin is board.D14:
                        if my_siren.state is False:
                            my_siren.disable()
                            if siren_controls.timer > 0:
                                siren_controls.timer = 0
                    if pin is board.D32:
                        if my_siren.state is True:
                            my_siren.steady()
            await asyncio.sleep(controls.wait)


# Continually check for changes in the security system zones
async def catch_zone_changes(pin, controls):
    while True:
        zcheck = get_zone_info(pin)
        zcheck.check_zone()
        zcheck.report()
        await asyncio.sleep(controls.wait)


# Listener for all subscribed MQTT feeds
async def mqtt_listener(controls):
    while True:
        my_mqtt.mqtt_client.loop()  # Listen to the subscribed feeds
        await asyncio.sleep(controls.wait)


# If the alarm is sounding and no one is home
# Disable it after a certain period of time
async def dismiss_siren(controls, siren_controls):
    siren_timeout = data["siren_timeout"]
    while True:
        if my_siren.state is False:
            if siren_controls.timer >= siren_timeout:
                my_siren.disable()
                siren_controls.timer = 0
            else:
                siren_controls.timer += 1

        await asyncio.sleep(controls.wait)


async def maintain_watchdog():
    watchdog_sleep = watchdog_timeout / 2
    my_log.log_message("will sleep for " + str(watchdog_sleep), "info")
    while True:
        apollo.mode = WatchDogMode.RAISE
        while True:
            try:
                apollo.feed()
            except watchdog.WatchDogTimeout:
                microcontroller.reset()
            await asyncio.sleep(watchdog_sleep)


# --- On Start Setup Tasks --- #

# Build Zone objects and append them to the patrol array
patrol = zone.buildZones()
topics = []
for z in range(len(patrol)):
    topic_zone = patrol[z]
    topics.append(topic_zone.feed_name)

# Build Siren objects and append them to the siren array
my_siren = siren.getSiren()

# Set up alarm state and exclusions lists
# Source of truth is retained on the system
my_alarm.set_alarm_state()
my_alarm.set_zone_exclusions()

# Set up MQTT for publish/subscribe
my_mqtt = one_mqtt.getMqtt()
my_mqtt.configure_publish(pool)
my_mqtt.mqtt_client.on_message = message
my_mqtt.mqtt_client.on_connect = connected
my_mqtt.mqtt_client.on_disconnect = disconnected

# Any additional topics for subscribing
topics.append(data["sd_logfile_feed_name"])
topics.append(data["alarm_management_feed_name"])

# Connect to network and MQTT broker
connect_wifi()

# If the MCU reset while the alarm was set we want to know about it
if my_alarm.get_alarm_state() is True:
    if len(my_alarm.get_exclusions()) > 0:
        message = "System is armed with these zones excluded: " + str(my_alarm.get_exclusions())
    else:
        message = "System is armed with no zones excluded"

    my_log.add_mqtt_stream(my_mqtt.gen_topic)
    my_log.log_message(message, "warning", mqtt=True)

my_log.log_message("Ready to monitor", "info")


# --- Main --- #
async def main():
    controls = Controls()
    siren_controls = SirenControls()
    task_array = []

    # Handle button presses from NeoKey FeatherWing
    # Green = Silence siren
    # Red = Panic button, enable siren
    interrupt_task_silence = asyncio.create_task(catch_key_transition(board.D14, controls, siren_controls))
    task_array.append(interrupt_task_silence)
    interrupt_task_panic = asyncio.create_task(catch_key_transition(board.D32, controls, siren_controls))
    task_array.append(interrupt_task_panic)
    # Handle changes for the security system zones
    # Build the tasks from the patrol array
    for _ in range(len(patrol)):
        tmp = patrol[_]
        tmp.task = asyncio.create_task(catch_zone_changes(tmp.pinID, controls))
        task_array.append(tmp.task)
    # Listen for MQTT messages
    mqtt_listener_task = asyncio.create_task(mqtt_listener(controls))
    task_array.append(mqtt_listener_task)
    # If the siren is sounding turn it off after pre-defined period of time
    disable_siren_task = asyncio.create_task(dismiss_siren(controls, siren_controls))
    task_array.append(disable_siren_task)
    # Enable the watchdog
    watchdog_task = asyncio.create_task(maintain_watchdog())
    task_array.append(watchdog_task)

    for _ in range(len(task_array)):
        await asyncio.gather(task_array[_])


asyncio.run(main())
