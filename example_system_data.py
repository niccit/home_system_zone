import board

system_data = {
    'zones': [['<zone_name>', board.GPIO, '<MQTT feed name>', '<asyncio task name>'],
              ['<zone_name>', board.GPIO, '<MQTT feed name>', '<asyncio task name>'],
              ['<zone_name>', board.GPIO, '<MQTT feed name>', '<asyncio task name>'],
              ['<zone_name>', board.GPIO, '<MQTT feed name>', '<asyncio task name>'],
              ['<zone_name>', board.GPIO, '<MQTT feed name>', '<asyncio task name>']
              ],
    'siren_steady': board.GPIO,
    'siren_yelp': board.GPIO,
    'siren_feed_name': "<MQTT feed name>"  # Feed that publishes attempts to arm the system via code
}
