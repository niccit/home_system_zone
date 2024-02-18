# SPDX-License-Identifier: MIT
import os
import random
import sys
import time
import board
import asyncio
import ipaddress
import digitalio
import keypad
import microcontroller
import watchdog
import neopixel
import wifi
import socketpool
import adafruit_sdcard
import storage
from adafruit_debouncer import Debouncer
from adafruit_io.adafruit_io_errors import AdafruitIO_MQTTError
from adafruit_pcf8523.pcf8523 import PCF8523
from digitalio import DigitalInOut
import time_lord
import local_logger as logger
import local_mqtt
import alarm_handler
import siren
import zone

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

# Set up I2C
i2c = board.I2C()
rtc = PCF8523(i2c)

# Timey wimey
my_time = time_lord.configure_time(pool, rtc)

# Logging
my_log = logger.getLocalLogger(use_time=True)
if my_log is not None:
    my_log.log_message("Created logging singleton", "info")
else:
    print("Did not create logging singleton!")

# Initialize SD storage
try:
    sd_cs = board.D33
    spi = board.SPI()
    cs = DigitalInOut(sd_cs)
    sdcard = adafruit_sdcard.SDCard(spi, cs)
    vfs = storage.VfsFat(sdcard)
    storage.mount(vfs, "/sd")

except OSError as oe:
    message = "unable to initialize storage " + str(oe)
    print(message)

# If necessary, create files
log_file = "/sd/" + data["sd_logfile"]
try:
    file = open(log_file, "r")
    file.close()
except OSError:
    file = open(log_file, "w")
    file.close()
    pass

alarm_file = "/sd/" + data["alarm_state_file"]
try:
    file = open(alarm_file, "r")
    file.close()
except OSError:
    file = open(alarm_file, "w")
    file.close()
    pass

exclude_file = "/sd/" + data["excluded_zones_file"]
try:
    file = open(exclude_file, "r")
    file.close()
except OSError:
    file = open(exclude_file, "w")
    file.close()
    pass

# Add the SD stream
# my_log.add_sd_stream()

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


# NeoKeys --- FOR TESTING ONLY
# panic_button_in = digitalio.DigitalInOut(board.D32)
# panic_button_in.pull = digitalio.Pull.UP
# panic_button = Debouncer(panic_button_in)
# silence_button_in = digitalio.DigitalInOut(board.D14)
# silence_button_in.pull = digitalio.Pull.UP
# silence_button = Debouncer(silence_button_in)


# --- Helper Methods --- #
# Connect to local Wi-Fi
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
                log_message = "Error: - " + str(ae) + " giving up"
                my_log.log_message(log_message, "critical")
                break


# Return the zone object based on pin number
def get_zone_info(z_pin):
    for p in range(len(patrol)):
        tmp_array = patrol[p]
        if tmp_array.pinID is z_pin:
            return tmp_array


# --- MQTT Subscribe callback methods --- #
# Behavior when a message is published to a subscribed feed
def message(client, topic, message):
    # Handle requests regarding zone changes
    # Handle triggering the alarm if the system is armed
    if "zone" in topic:
        if message is "1" and alarm_handler.get_alarm_state() is True:
            if alarm_handler.get_zone_exclusion_state(topic) is False:
                if my_siren.state is True:
                    my_siren.steady()
                else:
                    msg = "sirens is already active"
                    my_mqtt.publish(my_mqtt.gen_topic, msg, "info")
            else:
                msg = "This " + str(topic) + " is in the exclude list"
                my_mqtt.publish(my_mqtt.gen_topic, msg, "info")

    # Handle requests to enable/disable the alarm
    if "alarm" in topic:
        topic_name = local_mqtt.get_formatted_topic(data["alarm_management_feed_name"])
        if message is not "0":
            msg = "Request to arm/disarm system"
            my_mqtt.publish(my_mqtt.gen_topic, msg, "info")
            alarm_msg = my_alarm.manage_alarm(message)
            my_mqtt.publish(my_mqtt.gen_topic, str(alarm_msg[0]), str(alarm_msg[1]))
            time.sleep(1)
            # For security log a value of 0 to the alarm management feed
            # The feed is configured to only keep one line of data
            #            my_log.close_sd_stream()
            my_mqtt.publish(topic_name, 0)

    # Handle requests to get data from the system and state files on SD
    if "output" in topic:
        if "check" in message:
            my_log.log_message("Request to read sdcard log file", "info")
            log_output = my_log.dump_sd_log(data["sd_logfile"], data["sd_logfile_lines_to_output"])
        elif "restart" in message:
            my_log.log_message("Request to read sdcard log file after restart", "info")
            log_output = my_log.dump_sd_log(data["sd_logfile"], data["sd_logfile_lines_to_output"], restart=True)
        elif "alarm" in message:
            my_log.log_message("Request to get system state from disk", "info")
            log_output = my_log.read_file(data["alarm_state_file"])
        elif "exclu" in message:
            my_log.log_message("Request to get excluded zones from disk", "info")
            log_output = my_log.read_file(data["excluded_zones_file"])
        else:
            my_log.log_message("Request to view contents of directory " + str(message), "info")
            log_output = my_log.list_sd_card(message)

        for _ in range(len(log_output)):
            my_mqtt.publish(my_mqtt.gen_topic, str(log_output[_]), "info")
            time.sleep(0.25)


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
    while True:
        apollo.feed()
        await asyncio.sleep(watchdog_sleep)


# --- FOR TESTING ---#

# Automate key presses
# async def press_keys(siren_controls):
#     siren_timeout = data["siren_timeout"]
#     while True:
#         button_sleep = random.randrange(10, 30)
#         button_sleep = button_sleep
#         buttons = [panic_button, silence_button]
#         button_choice = random.randrange(0, 2)
#         button_to_press = buttons[button_choice]
#         button_to_press.state = 4
#         if button_to_press.fell:
#             if button_choice == 0:
#                 if my_siren.state is True:
#                     my_siren.steady()
#         else:
#             if my_siren.state is False:
#                 if siren_controls.timer >= siren_timeout:
#                     my_siren.disable()
#                     siren_controls.timer = 0
#                 else:
#                     siren_controls.timer += 1
#
#         await asyncio.sleep(button_sleep)

# Automate change of testing zone, close to open
# async def change_zone_state():
#     while True:
#         for _ in range(len(patrol)):
#             tmp = patrol[_]
#             tmp.pin.direction = digitalio.Direction.OUTPUT
#             tmp.pin.value = True
#         sleep_time = random.randrange(0, 10)
#         await asyncio.sleep(sleep_time)


# Automate closing of testing zone
# async def reset_pin_direction():
#     while True:
#         for _ in range(len(patrol)):
#             tmp = patrol[_]
#             tmp.pin.direction = digitalio.Direction.INPUT
#         sleep_time = random.randrange(5, 15)
#         await asyncio.sleep(sleep_time)


# --- On Start Setup Tasks --- #

# Set up MQTT for publish/subscribe
my_mqtt = local_mqtt.getMqtt(use_logger=True)
my_mqtt.configure_publish(pool)
my_mqtt.mqtt_client.on_message = message
my_mqtt.mqtt_client.on_connect = connected
my_mqtt.mqtt_client.on_disconnect = disconnected

# Build Zone objects and append them to the patrol array
patrol = zone.buildZones()  # use mqtt=True if using mqtt services
topics = []
for z in range(len(patrol)):
    topic_zone = patrol[z]
    topics.append(topic_zone.feed_name)

# Build Siren objects and append them to the siren array
my_siren = siren.getSiren()

# Set up alarm state and exclusions lists
# Source of truth is retained on the system
my_alarm = alarm_handler.get_alarm_prime()
alarm_handler.set_alarm_state()
alarm_handler.set_zone_exclusions()

# Any additional topics for subscribing
topics.append(data["sd_logfile_feed_name"])
topics.append(data["alarm_management_feed_name"])

# Connect to network and MQTT broker
connect_wifi()

# If the MCU reset while the alarm was set we want to know about it
if alarm_handler.get_alarm_state() is True:
    if len(alarm_handler.get_exclusions()) > 0:
        message = "System is armed with these zones excluded: " + str(alarm_handler.get_exclusions())
    else:
        message = "System is armed with no zones excluded"

#    my_mqtt.publish(my_mqtt.gen_topic, message, "warning")

my_log.log_message("Ready to monitor", "info")


# --- Main --- #
async def main():
    controls = Controls()
    siren_controls = SirenControls()
    task_array = []

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
    # Feed the Watchdog
    maintain_watchdog_task = asyncio.create_task(maintain_watchdog())
    task_array.append(maintain_watchdog_task)
    # TEST STUFF
    # state_change_task = asyncio.create_task(change_zone_state())
    # task_array.append(state_change_task)
    # reset_pin_task = asyncio.create_task(reset_pin_direction())
    # task_array.append(reset_pin_task)
    # press_keys_task = asyncio.create_task(press_keys(siren_controls))
    # task_array.append(press_keys_task)

    for _ in range(len(task_array)):
        await asyncio.gather(task_array[_])


try:
    asyncio.run(main())
except watchdog.WatchDogTimeout as w:
    print("Error:", w)
    microcontroller.reset()
