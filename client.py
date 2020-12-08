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


from util import initLogger, conf, MQTTClient, sigtermHandler
from hue_bridge import HueBridge, Monitor, Controller, Router
import signal


initLogger(conf.Logger.level)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, sigtermHandler)
    try:
        device_pool = dict()
        mqtt_client = MQTTClient()
        hue_bridge = HueBridge(conf.Bridge.id)
        hue_bridge.start_discovery()
        bridge_monitor = Monitor(hue_bridge=hue_bridge, mqtt_client=mqtt_client, device_pool=device_pool)
        bridge_controller = Controller(hue_bridge=hue_bridge, device_pool=device_pool, command_queue=router.cmd_queue, mqtt_client=mqtt_client)
        mqtt_client.on_connect = bridge_monitor.set_all_devices
        bridge_monitor.start()
        bridge_controller.start()
        mqtt_client.start()
    except KeyboardInterrupt:
        print("\ninterrupted by user\n")
    finally:
        pass
