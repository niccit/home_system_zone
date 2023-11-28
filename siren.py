# SPDX-License-Identifier: MIT

# This class will return a siren object
# There is only one object, if your system has multiple sires you chance which siren triggered via set_siren()

import digitalio
import local_logger as logger
import local_mqtt

main_siren = None
siren_cache = {}


def _addSiren():
    global main_siren

    if main_siren is None:
        main_siren = Siren()
        log_message = "Created Siren singleton"
        main_siren.my_log.log_message(log_message, "info")


# Create or retrieve a siren object by name; only retrieves siren objects created using this function.
# If a siren object with this name does not exist, one is created
# def getSiren(pin, feed, siren_name: Hashtable = "") -> "Siren":
def getSiren():
    _addSiren()
    return main_siren


# Get Siren data needed to trigger alarm states
try:
    from system_data import system_data
except ImportError:
    message = "System data must be in system_data.py, please create file"
    print(message)
    raise


class Siren:

    # Initialize the siren object
    # This should never be called directly, use getSiren() instead
    def __init__(self):
        self.name = None
        self.pin = None
        self.feed = system_data["siren_feed_name"]
        self.state = True  # Off
        self.my_log = logger.getLocalLogger()  # Get the logger singleton here to avoid startup timing conflicts
        self.my_mqtt = local_mqtt.getMqtt()  # Get the MQTT singleton here to avoid startup timing conflicts

    # Return the siren state
    def get_siren_state(self):
        return self.state

    # Trigger the yelp siren
    def yelp(self):
        self.name = "yelp"
        log_message = "Siren " + str(self.name) + " triggered"
        self.my_mqtt.publish(self.my_mqtt.gen_topic, log_message, "warning")
        if self.name not in siren_cache:
            Alarm.__create_alarm(self, system_data["siren_yelp"])
        Alarm.__enable(self)

    # Trigger the steady siren
    def steady(self):
        self.name = "steady"
        log_message = "Siren " + str(self.name) + " triggered"
        self.my_mqtt.publish(self.my_mqtt.gen_topic, log_message, "warning")
        if self.name not in siren_cache:
            Alarm.__create_alarm(self, system_data["siren_steady"])
        Alarm.__enable(self)

    # Disable active siren
    def disable(self):
        log_message = "Siren " + str(self.name) + " disabled"
        self.my_mqtt.publish(self.my_mqtt.gen_topic, log_message, "info")
        if self.state is False:
            self.state = True
            self.pin.value = True


# Creating and activating an alarm is private
# It can only be accessed via yelp() or steady()
class Alarm(Siren):
    def __create_alarm(self, pin):
        self.pin = digitalio.DigitalInOut(pin)
        self.pin.direction = digitalio.Direction.OUTPUT
        siren_cache[self.name] = self.name

    def __enable(self):
        if self.state is True:
            self.pin.value = False
            self.state = False
