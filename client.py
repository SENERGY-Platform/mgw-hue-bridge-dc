"""
   Copyright 2020 InfAI (CC SES)

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""


from util.logger import initLogger
from util.config import config
from util import mqtt
from hue_bridge.discovery import discoverBridge
from hue_bridge.monitor import Monitor
# from hue_bridge.controller import Controller
import signal
import sys


initLogger(config.Logger.level)


def sigtermHandler(_signo, _stack_frame):
    print("got SIGTERM - exiting ...")
    sys.exit(0)


device_pool = dict()

mqtt_client = mqtt.MQTTClient()

bridge_monitor = Monitor(mqtt_client=mqtt_client, device_pool=device_pool, bridge_id=config.Bridge.id)

# bridge_controller = Controller(device_manager, connector_client, config.Bridge.id)

mqtt_client.on_connect = bridge_monitor.set_all_devices


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, sigtermHandler)
    try:
        discoverBridge()
        bridge_monitor.start()
        # bridge_controller.start()
        mqtt_client.start()
    except KeyboardInterrupt:
        print("\ninterrupted by user\n")
    finally:
        pass
