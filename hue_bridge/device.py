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
    __type_map = {
        "Extended color light": conf.Senergy.dt_extended_color_light,
        "Color light": conf.Senergy.dt_color_light,
        "On/Off plug-in unit": conf.Senergy.dt_on_off_plug_in_unit
    }

    def __init__(self, id: str, name: str, type: str, model: str, number: str, info: dict, bridge: HueBridge):
        super().__init__(id, name, Device.__type_map[type])
        self.model = model
        self.number = number
        self.info = info
        self.bridge = bridge

    @property
    def info(self) -> dict:
        return self.__info

    @info.setter
    def info(self, obj: dict):
        self.__info = obj
        self.state = mgw_dc.dm.device_state.online if obj["reachable"] else mgw_dc.dm.device_state.offline

    def __iter__(self):
        items = (
            ("name", self.name),
            ("model", self.model),
            ("number", self.number),
            ("info", self.info)
        )
        for item in items:
            yield item
