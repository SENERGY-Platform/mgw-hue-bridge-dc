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

__all__ = ("Conf",)


import simple_env_var


@simple_env_var.configuration
class Conf:

    @simple_env_var.section
    class MsgBroker:
        host = "message-broker"
        port = 1883

    @simple_env_var.section
    class Logger:
        level = "info"
        enable_mqtt = False

    @simple_env_var.section
    class Client:
        clean_session = False
        keep_alive = 10
        id = "hue-bridge-dc"

    @simple_env_var.section
    class Bridge:
        api_key = None
        id = None

    @simple_env_var.section
    class Discovery:
        nupnp_url = "https://discovery.meethue.com"
        device_query_delay = 10
        device_id_prefix = None
        delay = 30
        check_delay = 60
        check_fail_safe = 2
        timeout = 5
        ip_file = "/opt/host_ip"

    @simple_env_var.section
    class StartDelay:
        enabled = False
        min = 5
        max = 20

    @simple_env_var.section
    class Senergy:
        dt_extended_color_light = None
        dt_on_off_plug_in_unit = None
        dt_color_light = None
        dt_color_temperature_light = None
        dt_dimmable_light = None
        dt_zll_switch = None
        dt_zll_presence = None
