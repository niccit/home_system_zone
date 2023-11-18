# SPDX-License-Identifier: MIT

import time

import adafruit_logging
import board
import busio
import adafruit_ntp
import local_logger as logger
from adafruit_pcf8523.pcf8523 import PCF8523

try:
    from data import data
except ImportError:
    print("Timezone data is stored in data.py. Please create the file")
    raise

# Set up I2C
# Used for RTC
i2c = busio.I2C(board.SCL, board.SDA)
rtc = PCF8523(i2c)

# Set up NTP client so we can set the board time
ntp_client = adafruit_ntp.NTP
rtc_set = False

# Logging
my_log = adafruit_logging.Logger


# Run this on startup only! Once the RTC is set use it
def set_up_system_time(socket_pool):
    global ntp_client, my_log

    my_log = logger.getLocalLogger()

    if rtc_set is False:
        ntp_client = adafruit_ntp.NTP(socket_pool, tz_offset=float(data["tz_offset"]))
        _set_rtc()


# Get time from NTP and set the RTC on the board
# This should only be called from set_up_system_time()
def _set_rtc():
    global rtc_set

    attempt = 0
    connect_success = False

    while connect_success is False:
        try:
            rtc.datetime = ntp_client.datetime
            rtc_set = True
            connect_success = True
        except OSError as oe:
            if attempt <= 5:
                message = "failed to connect to NTP, retrying ..."
                my_log.log_message(message, "warning")
                attempt += 1
                time.sleep(2)
                pass
            else:
                message = "Tried " + str(attempt) + "times, could not connect to NTP: " + str(oe)
                my_log.log_message(message, "critical")
                raise


# Return the current date/time for logging
# Formatted: Y.D.M HH:MM:SS
def get_logging_datetime():
    now = rtc.datetime
    t = "{:02d}.{:02d}.{:02d} {:02d}:{:02d}:{:02d}".format(now.tm_year, now.tm_mday, now.tm_mon, now.tm_hour,
                                                           now.tm_min, now.tm_sec)
    return t


# Return the current date
# Formatted: YDM
def get_date(separator=None):
    now = rtc.datetime
    if separator is not None:
        d = "{:02d}" + separator + "{:02d}" + separator + "{:02d}".format(now.tm_year, now.tm_mday, now.tm_mon)
    else:
        d = "{:02d}{:02d}{:02d}".format(now.tm_year, now.tm_mday, now.tm_mon)

    return d


# Return the current time with seconds
# Formatted: HH:MM:SS
def get_time_seconds():
    now = rtc.datetime
    t = "{:02d}:{:02d}:{:02d}".format(now.tm_hour, now.tm_min, now.tm_sec)
    return t


# Return the current time without seconds
# Formatted: HH:MM
def get_time():
    now = rtc.datetime
    t = "{:02d}:{:02d}".format(now.tm_hour, now.tm_min)
    return t


# Returns current datetime from the RTC
# This method returns as a time.struct_time
# Format (tm_year, tm_mon, tm_mday, tm_hour, tm_min, tm_sec, tm_wday, tm_yday, tm_isdst)
def get_current_time():
    return rtc.datetime
