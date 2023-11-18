import adafruit_logging as logger

data = {
    'timezone': '<your timezone>', # see http://wordtimeapi.org/timezones
    'tz_offset': 0,  # Replace with your TZ offset, be sure to handle when time changes! Need this for NTP
    'log_level': logger.INFO,  # debug, info, warning, error, critical
    'watchdog_timeout': 10,  # how long is the MCU unresponsive before the watchdog raises an error
    'siren_timeout': 30,  # how long should the siren sound if no one disables it
    'sd_logfile': '<your system log file dir/filename>',  # The name of the file where you store you system log info
    'sd_logfile_feed_name': '<your MQTT feed name'>,  # This is the MQTT feed to subscribe to that knows when to dump log data
    'sd_logfile_lines_to_output': 12, # How many lines of the syslog file to read
    'alarm_management_feed_name': '<your MQTT feed name>', # This is the MQTT feed to subscribe to that handles arming system
    'alarm_code': 1234, # Your alarm code
    'alarm_state_file': '<your alarm state dir/filename>',  # Where the state of the system is stored (armed/disarmed)
    'excluded_zones_file': '<your excluded zones dir/filename>'  # Where the state of the excluded zones are stored
}
