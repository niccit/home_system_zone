# SPDX-License-Identifier: MIT

# Wrapper class to handle alarm setting
# Will set a variable based on if it matches the code provided to the topic
# Will disable the siren if we are in an alarm state and the proper code is entered
# Can handle excluded zones

import re
import os
import local_logger as logger
import siren
import zone

alarm_set = None
excludes = []
alarm_prime = None

try:
    from data import data
except ImportError:
    print("Alarm information stored in data.py, please create file")
    raise


# Called to set the logger
def set_alarm_prime():
    global alarm_prime

    if alarm_prime is None:
        alarm_prime = Alarm()


# Get the alarm singleton
def get_alarm_prime():
    if alarm_prime is None:
        set_alarm_prime()
    return alarm_prime


# --- Setters --- #


# Done on system start up
# alarm armed/disarmed state is stored on the system in the alarm_state.txt file
# We need to read this in on startup to see if the system is armed
def set_alarm_state():
    global alarm_set

    a_file = "/sd/" + data["alarm_state_file"]
    try:
        with open(a_file, 'r') as alarm:
            current_state = alarm.read()
        alarm.close()
    except OSError:
        current_state = "False"
        pass

    if current_state is "False":
        current_state = False
    else:
        current_state = True

    alarm_set = current_state


# Done on system start up
# if the system is armed then we need to ensure we have the excluded zones
# the excluded zone list is stored on the system in the excludes.txt file
def set_zone_exclusions():
    global excludes

    e_file = "/sd/" + data["excluded_zones_file"]
    try:
        if os.stat(e_file)[6] > 0:
            with open(e_file, 'r') as ex:
                excludes.append(ex.read())
            ex.close()
    except OSError:
        print("No excluded zones")
        pass


# --- Getters --- #
# Will read the alarm_state.txt file and return the value in the file
# Will return the current state
def get_alarm_state():
    return alarm_set


# Return excluded zones list
# Gets this information from the exclusions.txt file
def get_exclusions():
    return excludes


# If a code is sent with more numeral that the base code, the additional numeral identify zones to be excluded
# when determining if the siren should sound
def get_zone_exclusion_state(feed):
    regex = re.compile("monitoring.")
    feed_array = regex.split(feed)
    topic = feed_array[1]
    if topic in excludes:
        return True
    else:
        return False


# --- General Helpers --- #

# Alternate way to add an exclusion.
def add_exclusion(name):
    excludes.append(name)
    _write_excludes(name)


# --- Private Methods --- #


# Private method
# Will write the updated alarm state value to the alarm_state.txt file
def _write_alarm_state(value):
    try:
        a_file = "/sd/" + data["alarm_state_file"]
        file = open(a_file, 'w')
        file.write(value)
        file.close()
    except OSError:
        print("unable to create/write to file", data["alarm_state_file"])
        pass


# Private method
# Adds excluded zones to the excludes.txt file
def _write_excludes(name):
    e_file = "/sd/" + data["excluded_zones_file"]
    try:
        file = open(e_file, 'a')
    except OSError:
        file = open(e_file, 'w')
        pass

    file.write(name)
    file.close()


# Private method
# Clears the excluded.txt file when the system is disarmed
# Clears the excludes array
def _clear_excludes():
    e_file = "/sd/" + data["excluded_zones_file"]
    file = open(e_file, 'w')
    file.close()
    excludes.clear()


def _check_for_open_zone():
    open_zones = []
    zone_list = zone.getZones()
    for z in range(len(zone_list)):
        tmp_zone = zone_list[z]
        is_excluded = get_zone_exclusion_state(tmp_zone.feed_name)
        if tmp_zone.state_value == 1 and is_excluded is False:
            open_zones.append(tmp_zone.name)

    if len(open_zones) != 0:
        return True, open_zones
    else:
        return False, ""


# Create an alarm and get the logging singleton for it
class Alarm:
    def __init__(self):
        self.my_log = logger.getLocalLogger()

    # Called when the proper code is sent to the alarm IO feed
    # Depending on the alarm_set value will enable or disable the alarm state
    def manage_alarm(self, num):
        global alarm_set, excludes

        my_siren = siren.getSiren()

        ac = data["alarm_code"]

        if len(num) <= 3:
            num = int(num)
        else:
            orig_num = num
            code = num[0] + num[1] + num[2] + num[3]
            num = int(code)
            for value in range(len(orig_num)):
                if value > 3:
                    zone_name = "zone-" + orig_num[value]
                    excludes.append(zone_name)
                    _write_excludes(zone_name)

        if alarm_set is None:
            set_alarm_state()
            current_state = alarm_set
        else:
            current_state = alarm_set

        self.my_log.log_message("current state is " + str(current_state), "debug")
        if num == ac:
            if current_state is False:
                open_zone = _check_for_open_zone()
                if open_zone[0] is True:
                    message = "Cannot arm system; the following zone(s) are open: " + str(open_zone[1])
                    level = "info"
                else:
                    alarm_set = True
                    _write_alarm_state("True")
                    message = "System armed"
                    level = "info"
            else:
                alarm_set = False
                if my_siren.get_siren_state() is False:
                    my_siren.disable()
                _write_alarm_state("False")
                _clear_excludes()
                message = "System disarmed"
                level = "info"
        else:
            message = "Incorrect code, system state unchanged"
            level = "warning"

        return message, level
