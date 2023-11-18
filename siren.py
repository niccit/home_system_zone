# SPDX-License-Identifier: MIT

# This class will return a siren object
# There is only one object, if your system has multiple sires you chance which siren triggered via set_siren()

import board
import digitalio
import local_logger as logger
import one_mqtt

main_siren = None
siren_cache = {}
my_log = None
my_mqtt = None


def _addSiren():
    global main_siren, my_log, my_mqtt

    my_log = logger.getLocalLogger()
    my_mqtt = one_mqtt.getMqtt()

    if main_siren is None:
        main_siren = Siren()
        log_message = "Created Siren singleton"
        my_log.log_message(log_message, "info")


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
    my_log.log_message(message, "critical")
    raise


class Siren:

    # Initialize the siren object
    # This should never be called directly, use getSiren() instead
    def __init__(self):
        self.name = None
        self.pin = None
        self.feed = system_data["siren_feed_name"]
        self.state = True  # Off

    # Return the siren state
    def get_siren_state(self):
        return self.state

    # Trigger the yelp siren
    def yelp(self):
        self.name = "yelp"
        log_message = "Siren " + str(self.name) + " triggered"
        my_mqtt.publish(my_mqtt.gen_topic, log_message, "warning", True)
        if self.name not in siren_cache:
            Alarm.__create_alarm(self, system_data["siren_yelp"])
        Alarm.__enable(self)

    # Trigger the steady siren
    def steady(self):
        self.name = "steady"
        log_message = "Siren " + str(self.name) + " triggered"
        my_mqtt.publish(my_mqtt.gen_topic, log_message, "warning", True)
        if self.name not in siren_cache:
            Alarm.__create_alarm(self, system_data["siren_steady"])
        Alarm.__enable(self)

    # Disable active siren
    def disable(self):
        log_message = "Siren " + str(self.name) + " disabled"
        my_mqtt.publish(my_mqtt.gen_topic, log_message, "info", True)
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




