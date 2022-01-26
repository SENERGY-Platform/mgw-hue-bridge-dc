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


__all__ = ("Device", )


from .discovery import HueBridge
import mgw_dc


class Device(mgw_dc.dm.Device):
    def __init__(self, id: str, type: str, meta_data: dict, data: dict, bridge: HueBridge):
        super().__init__(id, meta_data["name"], type)
        self.meta_data = meta_data
        self.data = data
        self.bridge = bridge

    @property
    def number(self):
        return self.__meta_data["number"]

    @property
    def model_id(self):
        return self.__meta_data["model_id"]

    # @property
    # def api(self):
    #     return self.__meta_data["api"]

    @property
    def meta_data(self) -> dict:
        return self.__meta_data

    @meta_data.setter
    def meta_data(self, obj: dict):
        self.__meta_data = obj
        self.name = self.__meta_data["name"]
        self.attributes = [
            mgw_dc.dm.gen_attribute("manufacturer", self.__meta_data["manufacturer_name"]),
            mgw_dc.dm.gen_attribute("model", self.__meta_data["model_id"]),
            mgw_dc.dm.gen_attribute("firmware", self.__meta_data["sw_version"])
        ]

    @property
    def data(self) -> dict:
        return self.__data

    @data.setter
    def data(self, obj: dict):
        self.__data = obj
        if self.__data["state"].get("reachable") or self.__data["config"].get("reachable"):
            self.state = mgw_dc.dm.device_state.online
        else:
            self.state = mgw_dc.dm.device_state.offline

    def __str__(self):
        return super().__str__(meta_data=self.meta_data, data=self.data)
