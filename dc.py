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


from util import init_logger, conf, MQTTClient, handle_sigterm, delay_start, Router
from hue_bridge import HueBridge, Monitor, Controller
import signal


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)
    if conf.StartDelay.enabled:
        delay_start(conf.StartDelay.min, conf.StartDelay.max)
    init_logger(conf.Logger.level)
    try:
        device_pool = dict()
        mqtt_client = MQTTClient()
        hue_bridge = HueBridge(conf.Bridge.id)
        hue_bridge.start_discovery()
        bridge_monitor = Monitor(hue_bridge=hue_bridge, mqtt_client=mqtt_client, device_pool=device_pool)
        controller = Controller(device_pool=device_pool, mqtt_client=mqtt_client)
        router = Router(bridge_monitor.schedule_refresh, controller.put_command)
        mqtt_client.on_connect = bridge_monitor.schedule_refresh
        mqtt_client.on_message = router.route
        bridge_monitor.start()
        controller.start()
        mqtt_client.start()
    finally:
        pass
