# SPDX-License-Identifier: MIT

# A wrapper to adafruit_logging that allows multiple class files to access and act on a single logger
# Objective is to simplify adding Handlers

import re
import time
import board
import sys
import busio
import json
import os
from digitalio import DigitalInOut
import storage
import adafruit_sdcard
import adafruit_logging as a_logger

from adafruit_logging import FileHandler, NOTSET, Handler, LogRecord
import one_mqtt
import time_lord

the_log = None
handlers = []
storage_initialized = False


# Create or return the logger this project uses
# If the local logger does not exist it will be created
# For this project the local logger is console
def getLocalLogger():
    _addLocalLogger()
    return the_log


try:
    from data import data
except ImportError:
    print("Logging information stored in data.py, please create file")
    raise


def _addLocalLogger():
    global the_log

    if the_log is None:
        the_log = LocalLogger()
        the_log.add_console_stream()
        message = "Created local logger at"
        the_log.log_message(message, "info")


# Take in a string and return the proper logging level
# Needed so that consumers of the class don't need to send in the proper log level format - string or int
def get_log_level(level: str = "notset"):
    if level is "debug":
        return a_logger.DEBUG
    elif level is "info":
        return a_logger.INFO
    elif level is "warning":
        return a_logger.WARNING
    elif level is "error":
        return a_logger.ERROR
    elif level is "critical":
        return a_logger.CRITICAL
    else:
        return a_logger.NOTSET


# For projects using SD card for logging or another purpose
# This project is using the Adafruit Featherwing Adalogger
def initialize_storage():
    global storage_initialized
    try:
        sd_cs = board.D33

        if storage_initialized is False:
            spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
            cs = DigitalInOut(sd_cs)
            sdcard = adafruit_sdcard.SDCard(spi, cs)
            vfs = storage.VfsFat(sdcard)
            storage.mount(vfs, "/sd")

            storage_initialized = True
    except OSError:
        message = "unable to initialize storage"
        print(message)


# The wrapper - this creates the singleton logging object
# Methods for adding, closing, and removing handlers provided
# A simple log_message method is provided
class LocalLogger:

    # Initialize the wrapper
    # This should never be called directly, use getLocalLogger() instead
    def __init__(self):
        self._the_log = a_logger.getLogger('console')
        self._the_log.setLevel(data["log_level"])
        self.file_handler = None
        self.mqtt_handler = None

    # Logging to an SD card
    def add_sd_stream(self):
        if self.file_handler not in handlers and storage_initialized is True:
            log_name = data["sd_logfile"]
            log_filepath = "/sd/" + log_name
            self.file_handler = FileHandler(log_filepath)
            self._the_log.addHandler(self.file_handler)
            handlers.append(self.file_handler)
        else:
            self._the_log.log(get_log_level("warning"), "unable to add sd stream")

    # Flush the file_handler stream to SD
    def flush_sd_stream(self):
        if self.file_handler in handlers:
            try:
                self.file_handler.stream.flush()
            except OSError as oe:
                message = "could not flush FileHandler to disk, SD card may be corrupted! " + str(oe)
                self._the_log.log(get_log_level("error"), message)
                pass

    # Close the sd card handler and remove it from the logger
    def close_sd_stream(self):
        self.file_handler.close()  # This performs: stream.flush and stream.close
        self._the_log.removeHandler(self.file_handler)
        handlers.remove(self.file_handler)

    # General console logging
    def add_console_stream(self):
        stream_handler = a_logger.StreamHandler()
        self._the_log.addHandler(stream_handler)

    # Logging to an MQTT broker
    def add_mqtt_stream(self, topic):
        if self.mqtt_handler not in handlers:
            my_mqtt = one_mqtt.getMqtt()
            self.mqtt_handler = MQTTHandler(my_mqtt.mqtt_client, topic)
            self._the_log.addHandler(self.mqtt_handler)
            handlers.append(self.mqtt_handler)

    # Remove the MQTT stream from the logger
    def remove_mqtt_stream(self):
        if self._the_log.hasHandlers():
            if self.mqtt_handler in handlers:
                self._the_log.removeHandler(self.mqtt_handler)
                handlers.remove(self.mqtt_handler)

    # Log a message to all relevant handlers
    # If using MQTT we need to handle if we're sending logging data or JSON data
    # Passing in True for the mqtt attribute will tell this method that it is JSON data
    # If notset is passed with mqtt then the level will be set to info; this is so things don't crash
    def log_message(self, message, level: str = "notset", mqtt: bool = False, sdcard_dump: bool = False):

        my_time = time_lord.get_time_lord()

        if mqtt is True:
            if level is "notset" or sdcard_dump is True:
                level = "info"
                io_message = message
            else:
                log_info = level.upper()
                io_message = log_info + " - " + my_time.get_logging_datetime() + ": " + message

            try:
                self._the_log.log(get_log_level(level), json.dumps(io_message))
            except OSError as oe:
                message = "MQTT logging failed, " + str(oe)
                self._the_log.log(get_log_level("error"),message)
                pass
        else:
            try:
                self._the_log.log(get_log_level(level), my_time.get_logging_datetime() + ": " + message)
            except OSError as oe:
                message = "Console/SD logging failed, " + str(oe)
                self._the_log.log(get_log_level("error"), message)
                pass

        # Remove MQTT handler
        if self.mqtt_handler in handlers:
            self._the_log.removeHandler(self.mqtt_handler)
            handlers.remove(self.mqtt_handler)

        # Write to the SD card file
        if self.file_handler in handlers:
            self.flush_sd_stream()


# Class to handle publishing to the MQTT broker
class MQTTHandler(Handler):
    def __init__(self, mqtt_client: MQTT.MQTT, topic: str) -> None:
        super().__init__()

        self._mqtt_client = mqtt_client
        self._topic = topic

        self.level = NOTSET

    def emit(self, record: LogRecord) -> None:
        try:
            if self._mqtt_client.is_connected():
                self._mqtt_client.publish(self._topic, record.msg)
        except RuntimeError:
            pass

    def handle(self, record: LogRecord) -> None:
        self.emit(record)


# --- Methods to interact with the SD card without having to remove it --- #
# Output specified number of lines of log file to disk
# If restart is True then exclude the most recent 13 lines (start up messages)
def dump_sd_log(restart: bool = False):
    the_log.close_sd_stream()  # remove the SD card stream for this

    list_of_log_levels = ["DEBUG", "INFO", "WARNING", "CRITICAL", "ERROR"]
    file = "/sd/" + data["sd_logfile"]
    num = data["sd_logfile_lines_to_output"]
    log_length = 0
    start_read = 0

    # Try to read the log file
    # If unable just log an error and move on
    try:
        with open(file, 'r') as logfile:
            log_output = logfile.readlines()
        logfile.close()
        log_length = len(log_output)
        start_read = log_length - num
    except OSError:
        the_log.log_message("unable to open and read syslog file", "warning")
        pass

    # Decide if we need to start reading the file prior to the initial 13 start up lines
    if log_length != 0:
        if restart is True:
            on_start_lines = 13
            if log_length > on_start_lines:
                end_read = log_length - on_start_lines
                start_read = end_read - num
                new_log_output = log_output[start_read:end_read]
            else:
                new_log_output = log_output[start_read:log_length]
        else:
            new_log_output = log_output[start_read:log_length]

        # Read the selected content and remove all " and carriage returns
        # If we don't the output will look hideous
        the_log.log_message("log file output is " + str(len(new_log_output)) + " long ", "debug")
        for line in range(len(new_log_output)):
            string = _get_split_string(new_log_output[line])
            the_log.log_message("string is " + str(len(string)) + " long and is " + str(string), "debug")

            # Assign new_string based on length of string
            if len(string) > 1:
                new_string = string[1]
            else:
                new_string = string

            # If any logging level is in the string, use this array to remove it
            strip_level = [sub for sub in list_of_log_levels if sub in new_string]
            if len(strip_level) > 0:
                remove_string = strip_level[0] + " - "
                the_log.log_message("remove string is " + str(remove_string), "debug")
                # Remove all log levels in string
                new_string = new_string.replace(remove_string, '')

            # Remove all double quotes in string
            new_string = new_string.replace('"', '')

            mqtt = one_mqtt.getMqtt()
            the_log.add_mqtt_stream(mqtt.gen_topic)
            the_log.log_message("LOG: " + new_string.strip('\r\n'), "info", mqtt=True, sdcard_dump=True)
            time.sleep(0.25)
            the_log.add_mqtt_stream(mqtt.gen_topic)

        the_log.add_sd_stream()  # Add the SD stream back
        the_log.log_message("End read sdcard log file", "info", mqtt=True)


# split string on log level and return result
def _get_split_string(log_line):
    if " DEBUG - " in log_line:
        return log_line.rsplit(" DEBUG - ")
    elif " INFO - " in log_line:
        return log_line.rsplit(" INFO - ")
    elif " WARNING - " in log_line:
        return log_line.rsplit(" WARNING - ")
    elif " ERROR - " in log_line:
        return log_line.rsplit(" ERROR - ")
    elif " CRITICAL - " in log_line:
        return log_line.rsplit(" CRITICAL - ")
    else:
        return log_line


# Read the contents of the alarm state file on SD card
# State is saved to SD card in case the system restarts after the system has been armed
def get_system_state():
    try:
        file = "/sd/" + data["alarm_state_file"]
        mqtt = one_mqtt.getMqtt()
        the_log.add_mqtt_stream(mqtt.gen_topic)
        with open(file, 'r') as alarm_file:
            alarm = alarm_file.read()
            message = "alarm state is " + str(alarm)
            the_log.log_message("alarm state: " + message, "info", mqtt=True, sdcard_dump=True)
        alarm_file.close()
    except OSError:
        the_log.log_message("unable to open and read alarm state file", "warning")
        pass


# Return the zones that are excluded from the alarm sounding if their state changes
# The state is saved to SD card in case the system restarts after the excluded list has been set
def get_exclusions_list():
    try:
        file = "/sd/" + data["excluded_zones_file"]
        exclusion_list = []
        with open(file, 'r') as exclusions_file:
            exclusion_list.append(exclusions_file.read())
        exclusions_file.close()
        mqtt = one_mqtt.getMqtt()
        the_log.add_mqtt_stream(mqtt.gen_topic)
        the_log.log_message("excluded zones are: " + str(exclusion_list), "info", mqtt=True, sdcard_dump=True)
    except OSError:
        the_log.log_message("unable to open and exclusions file", "warning")
        pass


# List the directories on the SD card where we store log and state files
# Just a sanity check in case something goes wonky
def list_sd_card():
    the_log.log_message("Request to list SD card contents", "info")
    syslog = data["sd_logfile"]
    system = data["alarm_state_file"]
    syslog_dir = syslog.split("/")
    dira = syslog_dir[0]
    system_dir = system.split("/")
    dirb = system_dir[0]
    if storage_initialized is True:
        mqtt = one_mqtt.getMqtt()
        the_log.add_mqtt_stream(mqtt.gen_topic)
        the_log.log_message(str(dira) + ": " + str(os.listdir("/sd/" + dira)), "info", mqtt=True, sdcard_dump=True)
        mqtt = one_mqtt.getMqtt()
        the_log.add_mqtt_stream(mqtt.gen_topic)
        the_log.log_message(str(dirb) + ": " + str(os.listdir("/sd/" + dirb)), "info", mqtt=True, sdcard_dump=True)
    else:
        the_log.log_message("Unable to list directory " + str(path), "warning")


# Maintenance, rotate the system log on a monthly basis
def rotate_sd_log():
    file = "/sd/" + data["sd_logfile"]
    rotate_file = file + "." + time_lord.get_date()
    os.rename(file, rotate_file)

