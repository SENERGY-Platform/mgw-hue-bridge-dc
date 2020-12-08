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


from util import getLogger, conf, MQTTClient
from .device import Device
from threading import Thread
import time
import requests
import typing
import json
import mgw_dc


logger = getLogger(__name__.split(".", 1)[-1])


class Monitor(Thread):
    def __init__(self, bridge_host: str, mqtt_client: MQTTClient, device_pool: typing.Dict[str, Device], bridge_id: str):
        super().__init__(name="monitor-{}".format(bridge_id), daemon=True)
        self.__bridge_host = bridge_host
        self.__mqtt_client = mqtt_client
        self.__device_pool = device_pool

    def run(self):
        logger.info("starting '{}' ...".format(self.name))
        while True:
            queried_devices = self.__queryBridge()
            if queried_devices:
                self.__evaluate(queried_devices)
            time.sleep(conf.Discovery.device_query_delay)

    def __queryBridge(self):
        try:
            resp = requests.get(
                "https://{}/{}/{}/lights".format(self.__bridge_host, conf.Bridge.api_path, conf.Bridge.api_key),
                verify=False
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
                        logger.error("could not parse device - {}".format(ex))
                        logger.debug(device)
                return devices
            else:
                logger.error("could not query bridge - '{}'".format(resp.status_code))
        except requests.exceptions.RequestException as ex:
            logger.error("could not query bridge - '{}'".format(ex))

    def __handle_missing_device(self, device_id: str):
        try:
            device = self.__device_pool[device_id]
            logger.info("can't find '{}' with id '{}'".format(device.name, device.id))
            self.__mqtt_client.publish(
                topic=mgw_dc.dm.gen_device_topic(conf.Client.id),
                payload=json.dumps(mgw_dc.dm.gen_delete_device_msg(device)),
                qos=2
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
                **data[0]
            )
            logger.info("found '{}' with id '{}'".format(device.name, device_id))
            self.__mqtt_client.publish(
                topic=mgw_dc.dm.gen_device_topic(conf.Client.id),
                payload=json.dumps(mgw_dc.dm.gen_set_device_msg(device)),
                qos=2
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
            try:
                self.__mqtt_client.publish(
                    topic=mgw_dc.dm.gen_device_topic(conf.Client.id),
                    payload=json.dumps(mgw_dc.dm.gen_set_device_msg(device)),
                    qos=2
                )
            except Exception as ex:
                device.name = backup["name"]
                device.number = backup["number"]
                device.model = backup["model"]
                device.info = backup["info"]
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

    def set_all_devices(self):
        for device in self.__device_pool.values():
            try:
                self.__mqtt_client.publish(
                    topic=mgw_dc.dm.gen_device_topic(conf.Client.id),
                    payload=json.dumps(mgw_dc.dm.gen_set_device_msg(device)),
                    qos=2
                )
                self.__mqtt_client.subscribe(topic=mgw_dc.com.gen_command_topic(device.id), qos=1)
            except Exception as ex:
                logger.error("setting and subscribing device '{}' failed - {}".format(device.id, ex))
