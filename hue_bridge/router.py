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


__all__ = ("Router", )


from util import getLogger
import json
import queue
import typing
import mgw_dc


logger = getLogger(__name__.split(".", 1)[-1])


class Router:
    def __init__(self):
        self.cmd_queue = queue.Queue()

    def route(self, topic: str, payload: typing.AnyStr):
        try:
            self.cmd_queue.put_nowait((*mgw_dc.com.parse_command_topic(topic), json.loads(payload)))
        except Exception as ex:
            logger.error("can't route message - {}\n{}: {}".format(ex, topic, payload))
