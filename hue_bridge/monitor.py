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


from util import get_logger, MQTTClient
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
    def __init__(self, hue_bridge: HueBridge, mqtt_client: MQTTClient, device_pool: typing.Dict[str, Device], type_map: typing.Dict, query_delay: int, request_timeout: int, device_id_prefix: str, dc_id: str):
        super().__init__(name="monitor-{}".format(hue_bridge.id), daemon=True)
        self.__hue_bridge = hue_bridge
        self.__mqtt_client = mqtt_client
        self.__device_pool = device_pool
        self.__type_map = type_map
        self.__query_delay = query_delay
        self.__request_timeout = request_timeout
        self.__device_id_prefix = device_id_prefix
        self.__dc_id = dc_id
        self.__refresh_flag = 0
        self.__lock = threading.Lock()
        self.__unsupported_types = set()

    def run(self):
        if not self.__mqtt_client.connected():
            time.sleep(3)
        logger.info("starting '{}' ...".format(self.name))
        while True:
            if self.__refresh_flag:
                self.__refresh_devices(self.__refresh_flag)
            queried_devices = self.__queryBridge(("lights", "sensors"))
            if queried_devices:
                self.__evaluate(queried_devices)
            time.sleep(self.__query_delay)

    def __queryBridge(self, apis):
        devices = dict()
        for api in apis:
            try:
                resp = requests.get(
                    f"https://{self.__hue_bridge.host}/api/{self.__hue_bridge.api_key}/{api}",
                    verify=False,
                    timeout=self.__request_timeout
                )
                if resp.ok:
                    resp = resp.json()
                    for number, device in resp.items():
                        try:
                            if device.get("type") in self.__type_map:
                                devices["{}{}".format(self.__device_id_prefix, device["uniqueid"])] = {
                                    "meta_data": {
                                        "name": device["name"],
                                        "model_id": device["modelid"],
                                        "type": device["type"],
                                        "manufacturer_name": device["manufacturername"],
                                        "sw_version": device["swversion"],
                                        "number": number,
                                        # "api": api
                                    },
                                    "data": {
                                        "state": device.get("state") or {},
                                        "config": device.get("config") or {}
                                    }
                                }
                            else:
                                if device.get("type") not in self.__unsupported_types:
                                    logger.warning("device type '{}' not supported".format(device.get("type")))
                                    self.__unsupported_types.add(device.get("type"))
                        except KeyError as ex:
                            logger.error("could not parse device - {}\n{}".format(ex, device))
                else:
                    raise RuntimeError(resp.status_code)
            except Exception as ex:
                logger.error("could not query bridge - '{}'".format(ex))
        return devices

    def __handle_missing_device(self, device_id: str):
        try:
            device = self.__device_pool[device_id]
            logger.info("can't find '{}' with id '{}'".format(device.name, device.id))
            self.__mqtt_client.publish(
                topic=mgw_dc.dm.gen_device_topic(self.__dc_id),
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
                type=self.__type_map[data["meta_data"]["type"]],
                bridge=self.__hue_bridge,
                **data
            )
            logger.info("found '{}' with id '{}'".format(device.name, device_id))
            self.__mqtt_client.publish(
                topic=mgw_dc.dm.gen_device_topic(self.__dc_id),
                payload=json.dumps(mgw_dc.dm.gen_set_device_msg(device)),
                qos=1
            )
            self.__mqtt_client.subscribe(topic=mgw_dc.com.gen_command_topic(device_id), qos=1)
            self.__device_pool[device.id] = device
        except Exception as ex:
            logger.error("can't add '{}' - {}".format(device_id, ex))

    def __handle_changed_meta_data(self, device_id: str, data: dict):
        try:
            device = self.__device_pool[device_id]
            meta_data_bk = device.data.copy()
            try:
                device.meta_data = data
                self.__mqtt_client.publish(
                    topic=mgw_dc.dm.gen_device_topic(self.__dc_id),
                    payload=json.dumps(mgw_dc.dm.gen_set_device_msg(device)),
                    qos=1
                )
            except Exception as ex:
                device.meta_data = meta_data_bk
                raise ex
        except Exception as ex:
            logger.error("can't update '{}' - {}".format(device_id, ex))

    def __handle_changed_data(self, device_id: str, data: dict):
        try:
            device = self.__device_pool[device_id]
            data_bk = device.data.copy()
            state_bk = device.state
            try:
                device.data = data
                if state_bk != device.state:
                    self.__mqtt_client.publish(
                        topic=mgw_dc.dm.gen_device_topic(self.__dc_id),
                        payload=json.dumps(mgw_dc.dm.gen_set_device_msg(device)),
                        qos=1
                    )
                if data_bk["state"] != device.data["state"]:
                    pass
            except Exception as ex:
                device.data = data_bk
                raise ex
        except Exception as ex:
            logger.error("can't update '{}' - {}".format(device_id, ex))

    def __diff(self, known: dict, unknown: dict):
        known_set = set(known)
        unknown_set = set(unknown)
        missing = known_set - unknown_set
        new = unknown_set - known_set
        changed_meta_data = {key for key in known_set & unknown_set if known[key].meta_data != unknown[key]["meta_data"]}
        changed_data = {key for key in known_set & unknown_set if known[key].data != unknown[key]["data"]}
        return missing, new, changed_meta_data, changed_data

    def __evaluate(self, queried_devices):
        try:
            missing_devices, new_devices, changed_meta_data, changed_data = self.__diff(self.__device_pool, queried_devices)
            if missing_devices:
                for device_id in missing_devices:
                    self.__handle_missing_device(device_id)
            if new_devices:
                for device_id in new_devices:
                    self.__handle_new_device(device_id, queried_devices[device_id])
            if changed_meta_data:
                for device_id in changed_meta_data:
                    self.__handle_changed_meta_data(device_id, queried_devices[device_id]["meta_data"])
            if changed_data:
                for device_id in changed_data:
                    self.__handle_changed_data(device_id, queried_devices[device_id]["data"])
        except Exception as ex:
            logger.error("can't evaluate devices - {}".format(ex))

    def __refresh_devices(self, flag: int):
        with self.__lock:
            if self.__refresh_flag == flag:
                self.__refresh_flag = 0
        for device in self.__device_pool.values():
            try:
                self.__mqtt_client.publish(
                    topic=mgw_dc.dm.gen_device_topic(self.__dc_id),
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
