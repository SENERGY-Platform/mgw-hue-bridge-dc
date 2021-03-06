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


__all__ = ("Monitor", )


from util import get_logger, conf, MQTTClient
from .device import Device
from .discovery import HueBridge
import threading
import time
import requests
import typing
import json
import mgw_dc


logger = get_logger(__name__.split(".", 1)[-1])


class Monitor(threading.Thread):
    def __init__(self, hue_bridge: HueBridge, mqtt_client: MQTTClient, device_pool: typing.Dict[str, Device]):
        super().__init__(name="monitor-{}".format(hue_bridge.id), daemon=True)
        self.__hue_bridge = hue_bridge
        self.__mqtt_client = mqtt_client
        self.__device_pool = device_pool
        self.__refresh_flag = 0
        self.__lock = threading.Lock()

    def run(self):
        if not self.__mqtt_client.connected():
            time.sleep(3)
        logger.info("starting '{}' ...".format(self.name))
        while True:
            if self.__refresh_flag:
                self.__refresh_devices(self.__refresh_flag)
            queried_devices = self.__queryBridge()
            if queried_devices:
                self.__evaluate(queried_devices)
            time.sleep(conf.Discovery.device_query_delay)

    def __queryBridge(self):
        try:
            resp = requests.get(
                "https://{}/{}/{}/lights".format(self.__hue_bridge.host, conf.Bridge.api_path, conf.Bridge.api_key),
                verify=False,
                timeout=conf.Discovery.timeout
            )
            if resp.ok:
                data = resp.json()
                devices = dict()
                for number, device in data.items():
                    try:
                        devices["{}{}".format(conf.Discovery.device_id_prefix, device["uniqueid"])] = (
                            {
                                "name": device["name"],
                                "model": device["modelid"],
                                "number": number,
                                "info": device["state"]
                            },
                            {
                                "product_name": device["productname"],
                                "manufacturer": device["manufacturername"],
                                "product_type": device["type"]
                            }
                        )
                    except KeyError as ex:
                        logger.error("could not parse device - {}\n{}".format(ex, device))
                return devices
            else:
                raise RuntimeError(resp.status_code)
        except Exception as ex:
            logger.error("could not query bridge - '{}'".format(ex))

    def __handle_missing_device(self, device_id: str):
        try:
            device = self.__device_pool[device_id]
            logger.info("can't find '{}' with id '{}'".format(device.name, device.id))
            self.__mqtt_client.publish(
                topic=mgw_dc.dm.gen_device_topic(conf.Client.id),
                payload=json.dumps(mgw_dc.dm.gen_delete_device_msg(device)),
                qos=1
            )
            try:
                self.__mqtt_client.unsubscribe(topic=mgw_dc.com.gen_command_topic(device.id))
            except Exception as ex:
                logger.warning("can't unsubscribe '{}' - {}".format(device.id, ex))
            del self.__device_pool[device.id]
        except Exception as ex:
            logger.error("can't remove '{}' - {}".format(device_id, ex))

    def __handle_new_device(self, device_id: str, data: dict):
        try:
            device = Device(
                id=device_id,
                type=data[1]["product_type"],
                bridge=self.__hue_bridge,
                **data[0]
            )
            logger.info("found '{}' with id '{}'".format(device.name, device_id))
            self.__mqtt_client.publish(
                topic=mgw_dc.dm.gen_device_topic(conf.Client.id),
                payload=json.dumps(mgw_dc.dm.gen_set_device_msg(device)),
                qos=1
            )
            self.__mqtt_client.subscribe(topic=mgw_dc.com.gen_command_topic(device_id), qos=1)
            self.__device_pool[device.id] = device
        except Exception as ex:
            logger.error("can't add '{}' - {}".format(device_id, ex))

    def __handle_changed_device(self, device_id: str, data: dict):
        try:
            device = self.__device_pool[device_id]
            backup = dict(device)
            device.name = data["name"]
            device.model = data["model"]
            device.number = data["number"]
            device.info = data["info"]
            if backup["name"] != data["name"] or backup["info"]["reachable"] != data["info"]["reachable"]:
                try:
                    self.__mqtt_client.publish(
                        topic=mgw_dc.dm.gen_device_topic(conf.Client.id),
                        payload=json.dumps(mgw_dc.dm.gen_set_device_msg(device)),
                        qos=1
                    )
                except Exception as ex:
                    device.name = backup["name"]
                    data["info"]["reachable"] = backup["info"]["reachable"]
                    device.info = data["info"]
                    raise ex
        except Exception as ex:
            logger.error("can't update '{}' - {}".format(device_id, ex))

    def __diff(self, known: dict, unknown: dict):
        known_set = set(known)
        unknown_set = set(unknown)
        missing = known_set - unknown_set
        new = unknown_set - known_set
        changed = {key for key in known_set & unknown_set if dict(known[key]) != unknown[key][0]}
        return missing, new, changed

    def __evaluate(self, queried_devices):
        try:
            missing_devices, new_devices, changed_devices = self.__diff(self.__device_pool, queried_devices)
            if missing_devices:
                for device_id in missing_devices:
                    self.__handle_missing_device(device_id)
            if new_devices:
                for device_id in new_devices:
                    self.__handle_new_device(device_id, queried_devices[device_id])
            if changed_devices:
                for device_id in changed_devices:
                    self.__handle_changed_device(device_id, queried_devices[device_id][0])
        except Exception as ex:
            logger.error("can't evaluate devices - {}".format(ex))

    def __refresh_devices(self, flag: int):
        with self.__lock:
            if self.__refresh_flag == flag:
                self.__refresh_flag = 0
        for device in self.__device_pool.values():
            try:
                self.__mqtt_client.publish(
                    topic=mgw_dc.dm.gen_device_topic(conf.Client.id),
                    payload=json.dumps(mgw_dc.dm.gen_set_device_msg(device)),
                    qos=1
                )
            except Exception as ex:
                logger.error("setting device '{}' failed - {}".format(device.id, ex))
            if flag > 1:
                try:
                    self.__mqtt_client.subscribe(topic=mgw_dc.com.gen_command_topic(device.id), qos=1)
                except Exception as ex:
                    logger.error("subscribing device '{}' failed - {}".format(device.id, ex))

    def schedule_refresh(self, subscribe: bool = False):
        with self.__lock:
            self.__refresh_flag = max(self.__refresh_flag, int(subscribe) + 1)

