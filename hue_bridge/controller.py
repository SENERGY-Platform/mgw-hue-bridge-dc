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


__all__ = ("Controller", )


from util import getLogger, conf, MQTTClient
from .device import Device
from .service import service_map
from .discovery import HueBridge
import threading
import queue
import time
import json
import mgw_dc


logger = getLogger(__name__.split(".", 1)[-1])


class Worker(threading.Thread):
    def __init__(self, device: Device, hue_bridge: HueBridge, mqtt_client: MQTTClient):
        super().__init__(name="worker-{}".format(device.id), daemon=True)
        self.__device = device
        self.__hue_bridge = hue_bridge
        self.__mqtt_client = mqtt_client
        self.__stop = False
        self.__command_queue = queue.Queue()

    def run(self) -> None:
        logger.debug("'{}': starting ...".format(self.name))
        while not self.__stop:
            try:
                dev_id, srv_id, cmd = self.__command_queue.get(timeout=30)
                logger.debug("{}: '{}' <- '{}'".format(self.name, srv_id, cmd))
                try:
                    if cmd[mgw_dc.com.command.data]:
                        data = service_map[srv_id](self.__hue_bridge.host, self.__device, **json.loads(cmd[mgw_dc.com.command.data]))
                    else:
                        data = service_map[srv_id](self.__hue_bridge.host, self.__device)
                    resp_msg = mgw_dc.com.gen_response_msg(cmd[mgw_dc.com.command.id], json.dumps(data))
                except KeyError as ex:
                    logger.error("{}: unknown service - {}".format(self.name, ex))
                    resp_msg = mgw_dc.com.gen_response_msg(cmd[mgw_dc.com.command.id], json.dumps({"status": 1}))
                except json.JSONDecodeError as ex:
                    logger.error("{}: could not parse command data - {}".format(self.name, ex))
                    resp_msg = mgw_dc.com.gen_response_msg(cmd[mgw_dc.com.command.id], json.dumps({"status": 1}))
                except TypeError as ex:
                    logger.error("{}: could not parse command response data - {}".format(self.name, ex))
                    resp_msg = mgw_dc.com.gen_response_msg(cmd[mgw_dc.com.command.id], json.dumps({"status": 1}))
                logger.debug("{}: '{}'".format(self.name, resp_msg))
                try:
                    self.__mqtt_client.publish(
                        topic=mgw_dc.com.gen_response_topic(dev_id, srv_id),
                        payload=json.dumps(resp_msg),
                        qos=1
                    )
                except Exception as ex:
                    logger.error(
                        "{}: could not send response message for '{}' - {}".format(
                            self.name,
                            cmd[mgw_dc.com.command.id],
                            ex
                        )
                    )
            except queue.Empty:
                pass
        del self.__device
        del self.__mqtt_client
        del self.__command_queue
        logger.debug("'{}': quit".format(self.name))

    def stop(self):
        self.__stop = True

    def execute(self, command):
        self.__command_queue.put_nowait(command)


class Controller(threading.Thread):
    def __init__(self, hue_bridge: HueBridge, device_pool: dict, command_queue: queue.Queue, mqtt_client: MQTTClient):
        super().__init__(name="controller-{}".format(hue_bridge.id), daemon=True)
        self.__hue_bridge = hue_bridge
        self.__device_pool = device_pool
        self.__command_queue = command_queue
        self.__mqtt_client = mqtt_client
        self.__worker_pool = dict()

    def run(self):
        logger.info("starting '{}' ...".format(self.name))
        garbage_collector_time = time.time()
        while True:
            try:
                cmd = self.__command_queue.get(timeout=30)
                try:
                    device = self.__device_pool[cmd[0]]
                    if device.id not in self.__worker_pool:
                        worker = Worker(device=device, hue_bridge=self.__hue_bridge, mqtt_client=self.__mqtt_client)
                        worker.start()
                        self.__worker_pool[device.id] = worker
                    else:
                        worker = self.__worker_pool[device.id]
                    worker.execute(cmd)
                except KeyError:
                    logger.error("received command for unknown device '{}'".format(cmd[mgw_dc.com.command.id]))
            except queue.Empty:
                if time.time() - garbage_collector_time > 120:
                    self.__collectGarbage()
                    garbage_collector_time = time.time()

    def __collectGarbage(self):
        garbage_workers = set(self.__worker_pool) - set(self.__device_pool)
        for worker_id in garbage_workers:
            worker = self.__worker_pool[worker_id]
            logger.debug("stopping '{}'".format(worker.name))
            worker.stop()
            del self.__worker_pool[worker_id]
