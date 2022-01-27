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


from util import init_logger, Conf, MQTTClient, handle_sigterm, delay_start, Router
from hue_bridge import HueBridge, Monitor, Controller
import signal


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)
    conf = Conf()
    if not all((conf.Bridge.id, conf.Bridge.api_key)):
        exit('Please provide Hue Bridge information')
    if not all((conf.Senergy.dt_extended_color_light, conf.Senergy.dt_on_off_plug_in_unit, conf.Senergy.dt_color_light)):
        exit('Please provide a SENERGY device types')
    if conf.StartDelay.enabled:
        delay_start(conf.StartDelay.min, conf.StartDelay.max)
    init_logger(conf.Logger.level)
    type_map = {
        "Extended color light": conf.Senergy.dt_extended_color_light,
        "Color light": conf.Senergy.dt_color_light,
        "Color temperature light": conf.Senergy.dt_color_temperature_light,
        "Dimmable light": conf.Senergy.dt_dimmable_light,
        "On/Off plug-in unit": conf.Senergy.dt_on_off_plug_in_unit,
        "ZLLSwitch": conf.Senergy.dt_zll_switch,
        "ZLLPresence": conf.Senergy.dt_zll_presence
    }
    try:
        device_pool = dict()
        mqtt_client = MQTTClient(
            host=conf.MsgBroker.host,
            port=conf.MsgBroker.port,
            client_id=conf.Client.id,
            clean_session=conf.Client.clean_session,
            keep_alive=conf.Client.keep_alive,
            sub_lvl_logger=conf.Logger.enable_mqtt
        )
        hue_bridge = HueBridge(
            id=conf.Bridge.id,
            api_key=conf.Bridge.api_key,
            nupnp_url=conf.Discovery.nupnp_url,
            ip_file=conf.Discovery.ip_file,
            request_timeout=conf.Discovery.timeout,
            delay=conf.Discovery.delay,
            check_delay=conf.Discovery.check_delay,
            check_fail_safe=conf.Discovery.check_fail_safe
        )
        hue_bridge.start_discovery()
        bridge_monitor = Monitor(
            hue_bridge=hue_bridge,
            mqtt_client=mqtt_client,
            device_pool=device_pool,
            type_map=type_map,
            query_delay=conf.Discovery.device_query_delay,
            request_timeout=conf.Discovery.timeout,
            device_id_prefix=conf.Discovery.device_id_prefix,
            dc_id=conf.Client.id
        )
        controller = Controller(device_pool=device_pool, mqtt_client=mqtt_client)
        router = Router(bridge_monitor.schedule_refresh, controller.put_command)
        mqtt_client.on_connect = bridge_monitor.schedule_refresh
        mqtt_client.on_message = router.route
        bridge_monitor.start()
        controller.start()
        mqtt_client.start()
    finally:
        pass
