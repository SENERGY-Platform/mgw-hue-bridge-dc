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


__all__ = ("service_map", )


from util import get_logger, conf
from .device import Device
import rgbxy
import datetime
import requests


logger = get_logger(__name__.split(".", 1)[-1])

converter_pool = dict()


def get_gamut(model_id):
    # https://developers.meethue.com/develop/hue-api/supported-devices/
    if model_id in ("LCT001", "LCT007", "LCT002", "LCT003", "LLM001"):
        return rgbxy.GamutB
    elif model_id in ("LCT010", "LCT014", "LCT015", "LCT016", "LCT011", "LLC020", "LST002", "LCT012", "LCT024"):
        return rgbxy.GamutC
    elif model_id in ("LLC010", "LLC006", "LST001", "LLC011", "LLC012", "LLC005", "LLC007", "LLC014"):
        return rgbxy.GamutA
    else:
        logger.warning("Model '{}' not supported - defaulting to Gamut C")
        return rgbxy.GamutC


def get_converter(model: str):
    if not model in converter_pool:
        converter = rgbxy.Converter(get_gamut(model))
        converter_pool[model] = converter
        return converter
    return converter_pool[model]


def put(host: str, d_number: str, data: dict):
    try:
        resp = requests.put(
            url="https://{}/{}/{}/lights/{}/state".format(
                host,
                conf.Bridge.api_path,
                conf.Bridge.api_key,
                d_number
            ),
            json=data,
            verify=False,
            timeout=conf.Discovery.timeout
        )
        if resp.status_code == 200:
            resp = resp.json()
            if isinstance(resp, list):
                if "success" in resp[0]:
                    return 0, "ok"
                if "error" in resp[0]:
                    return 1, resp[0]["error"]["description"]
            else:
                return 1, "unknown error"
        else:
            return 1, resp.status_code
    except Exception as ex:
        return 1, "could not send request to hue bridge - {}".format(ex)


def get(host: str, d_number: str):
    try:
        resp = requests.get(
            url="https://{}/{}/{}/lights/{}".format(
                host,
                conf.Bridge.api_path,
                conf.Bridge.api_key,
                d_number
            ),
            verify=False,
            timeout=conf.Discovery.timeout
        )
        if resp.status_code == 200:
            resp = resp.json()
            if isinstance(resp, dict):
                return 0, resp["state"]
            elif isinstance(resp, list):
                return 1, resp[0]["error"]["description"]
            else:
                return 1, "unknown error"
        else:
            return 1, resp.status_code
    except Exception as ex:
        return 1, "could not send request to hue bridge - {}".format(ex)


### Services ###


def set_power(device: Device, power: bool):
    err, body = put(
        device.bridge.host,
        device.number,
        {
            "on": power
        }
    )
    if err:
        logger.error("set power for '{}' failed - {}".format(device.id, body))
    return {"status": err}


def get_power(device: Device):
    payload = {
        "power": device.info["on"],
        "status": 0,
        "time": "{}Z".format(datetime.datetime.utcnow().isoformat())
    }
    err, body = get(device.bridge.host, device.number)
    if err:
        logger.warning("get power for '{}' failed - using possibly stale data - {}".format(device.id, body))
    else:
        payload["power"] = body["on"]
    return payload


def set_color(device: Device, red: int, green: int, blue: int, duration: float):
    err, body = put(
        device.bridge.host,
        device.number,
        {
            "on": True,
            "xy": get_converter(device.model).rgb_to_xy(red=red, green=green, blue=blue),
            "transitiontime": int(duration * 10)
        }
    )
    if err:
        logger.error("set color for '{}' failed - {}".format(device.id, body))
    return {"status": err}


def get_color(device: Device):
    r, g, b = get_converter(device.model).xy_to_rgb(device.info["xy"][0], device.info["xy"][1])
    payload = {
        "red": r,
        "green": g,
        "blue": b,
        "status": 0,
        "time": "{}Z".format(datetime.datetime.utcnow().isoformat())
    }
    err, body = get(device.bridge.host, device.number)
    if err:
        logger.warning("get color for '{}' failed - using possibly stale data - {}".format(device.id, body))
    else:
        r, g, b = get_converter(device.model).xy_to_rgb(body["xy"][0], body["xy"][1])
        payload["red"] = r
        payload["green"] = g
        payload["blue"] = b
    return payload


def set_brightness(device: Device, brightness: int, duration: float):
    err, body = put(
        device.bridge.host,
        device.number,
        {
            "on": True,
            "bri": round(brightness * 255 / 100),
            "transitiontime": int(duration * 10)
        }
    )
    if err:
        logger.error("set brightness for '{}' failed - {}".format(device.id, body))
    return {"status": err}


def get_brightness(device: Device):
    payload = {
        "brightness": round(device.info["bri"] * 100 / 255),
        "status": 0,
        "time": "{}Z".format(datetime.datetime.utcnow().isoformat())
    }
    err, body = get(device.bridge.host, device.number)
    if err:
        logger.warning("get brightness for '{}' failed - using possibly stale data - {}".format(device.id, body))
    else:
        payload["brightness"] = round(body["bri"] * 100 / 255)
    return payload


def set_kelvin(device: Device, kelvin: int, duration: float):
    err, body = put(
        device.bridge.host,
        device.number,
        {
            "on": True,
            "ct": round(1000000 / kelvin),
            "transitiontime": int(duration * 10)
        }
    )
    if err:
        logger.error("set kelvin for '{}' failed - {}".format(device.id, body))
    return {"status": err}


def get_kelvin(device: Device):
    payload = {
        "kelvin": round(round(1000000 / device.info["ct"]) / 10) * 10,
        "status": 0,
        "time": "{}Z".format(datetime.datetime.utcnow().isoformat())
    }
    err, body = get(device.bridge.host, device.number)
    if err:
        logger.warning("get brightness for '{}' failed - using possibly stale data - {}".format(device.id, body))
    else:
        payload["kelvin"] = round(round(1000000 / body["ct"]) / 10) * 10
    return payload


service_map = {
    "setPower": set_power,
    "getPower": get_power,
    "setColor": set_color,
    "getColor": get_color,
    "setBrightness": set_brightness,
    "getBrightness": get_brightness,
    "setKelvin": set_kelvin,
    "getKelvin": get_kelvin
}
