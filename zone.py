# SPDX-License-Identifier: MIT
import time
import digitalio
import local_mqtt
import local_logger as logger

zone_cache = {}
all_zones = []

# import zone information
try:
    from system_data import system_data
except ImportError:
    print("Zone information stored in system_data.py, please create file", "critical")
    raise

# import mqtt data for publishing
try:
    from mqtt_data import mqtt_data
except ImportError:
    print("MQTT information is stored in mtqq_data.py, please create file", "critical")
    raise


# If a zone object does not already exist in the zone_cache, create it and append it the array of all zones
def _addZone(name, pin, feed, task) -> None:
    if name not in zone_cache:
        new_zone = Zone(pin, feed, name, task)
        if name in ["zone_3", "zone_4"]:  # remove me before real life!
            zone_cache[name] = new_zone
            all_zones.append(zone_cache[name])


# This is the method that's called
# It will get all the zones to create from "zones" in the system_data.py file
# It will return an array of zone objects
def buildZones():

    zone_list = system_data["zones"]
    for zone in range(len(zone_list)):
        tmp_zone = zone_list[zone]
        _addZone(tmp_zone[0], tmp_zone[1], tmp_zone[2], tmp_zone[3])

    message = "Done building security zones"
    all_zones[0].my_log.log_message(message, "info")
    return all_zones


# Return the list of zones
def getZones():
    return all_zones


# Build a security zone object
class Zone:

    # The zone object
    # Assigns the pin and direction for the zone
    # Sets the current state for the pin (True/False)
    # Initial object has a previous state of False
    # Assigns the name that it is passed; useful for logging clarity
    # Should never be called directly, use buildZones() instead
    def __init__(self, pin, feed_name, name, task):
        self.pin = digitalio.DigitalInOut(pin)
        self.pin.direction = digitalio.Direction.INPUT
        self.pin.pull = digitalio.Pull.UP
        self.pinID = pin
        self.name = name
        self.feed_name = feed_name
        self.task = task
        self.state_value = 0
        self.previous_zone_state = False
        self.previous_state_value = 0
        self.state_change = False
        self.on_startup = True
        self.my_log = logger.getLocalLogger()
        self.my_mqtt = local_mqtt.getMqtt()

    # --- Getters --- #

    # Return the current zone state
    def get_zone_state(self):
        return self.state_value

    # Return the attribute that determines if we log a zone change state
    def get_state_change(self):
        return self.state_change

    # --- Setters --- #

    # Change the on_startup attribute
    # Typically done after the first check is done on start up of microcontroller
    def set_on_startup(self, value: bool):
        self.on_startup = value

    # Get the current zone state and set the zone object attribute
    def set_zone_state(self):
        if self.pin.value is True:
            self.state_value = 1
        else:
            self.state_value = 0

    # Get the current state of the zone and update values as needed
    # When check_zone() is called it will set the state_change and alarm_trigger
    def check_zone(self):
        self.set_zone_state()
        value = self.get_zone_state()

        if value != self.previous_state_value and self.on_startup is False:
            self.state_change = True
        else:
            self.state_change = False

    # Log on initial start up and zone state changes only
    def report(self, log_level: str = "notset"):

        if self.my_mqtt.get_io() is None:
            log_message = "MQTT not initialized, will attempt to initialize"
            self.my_log.log_message(log_message, "warning")
            self.my_mqtt.connect()

        # Set the zone topic for logging
        zone_topic = local_mqtt.get_formatted_topic(self.feed_name)

        # Set human readable values for zone states for logging
        if self.state_value is 1:
            zone_state = "Open"
        else:
            zone_state = "Closed"

        zone_log_message = {"value": self.state_value}

        # General logging message is different based on initial startup or state change
        if self.on_startup is True:
            gen_message = ("Publishing initial state for: " + str(self.name) + ": " + str(zone_state))
        else:
            gen_message = (str(self.name) + " state has changed from: " + str(self.previous_zone_state) + " to " +
                           str(zone_state))

        # Report on zone and update attributes
        if self.get_state_change() is True or self.on_startup is True:
            self.my_mqtt.publish(zone_topic, zone_log_message, "notset")
            if self.get_state_change() is True and self.state_value == 1:
                log_level = "warning"
            self.my_mqtt.publish(self.my_mqtt.gen_topic, gen_message, log_level)
            self.set_on_startup(False)

        # update zone attributes
        self.previous_state_value = self.state_value
        self.previous_zone_state = zone_state
