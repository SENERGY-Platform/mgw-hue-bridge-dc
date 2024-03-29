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


__all__ = ("HueBridge", )


from util import get_logger
import urllib3
import threading
import subprocess
import time
import requests


logger = get_logger(__name__.split(".", 1)[-1])

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def ping(host) -> bool:
    return subprocess.call(['ping', '-c', '2', '-t', '2', host], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def get_local_ip(ip_file) -> str:
    try:
        with open(ip_file, "r") as file:
            ip_addr = file.readline().strip()
        if ip_addr:
            logger.debug("host ip address is '{}'".format(ip_addr))
            return ip_addr
        else:
            raise RuntimeError("file empty")
    except Exception as ex:
        raise Exception("could not get local ip - {}".format(ex))


def get_ip_range(local_ip) -> list:
    split_ip = local_ip.rsplit('.', 1)
    base_ip = split_ip[0] + '.'
    if len(split_ip) > 1:
        ip_range = [str(base_ip) + str(i) for i in range(1, 256)]
        ip_range.remove(local_ip)
        return ip_range
    return list()


def discover_hosts_worker(ip_range, alive_hosts):
    for ip in ip_range:
        if ping(ip):
            alive_hosts.append(ip)


def discover_hosts(ip_file) -> list:
    ip_range = get_ip_range(get_local_ip(ip_file))
    logger.debug("scanning ip range '{}-255' ...".format(ip_range[0]))
    alive_hosts = list()
    workers = list()
    bin = 0
    bin_size = 3
    if ip_range:
        for i in range(int(len(ip_range) / bin_size)):
            worker = threading.Thread(target=discover_hosts_worker, name='discoverHostsWorker', args=(ip_range[bin:bin + bin_size], alive_hosts))
            workers.append(worker)
            worker.start()
            bin = bin + bin_size
        if ip_range[bin:]:
            worker = threading.Thread(target=discover_hosts_worker, name='discoverHostsWorker', args=(ip_range[bin:], alive_hosts))
            workers.append(worker)
            worker.start()
        for worker in workers:
            worker.join()
    return alive_hosts


def discover_NUPnP(bridge_id, nupnp_url, timeout) -> str:
    try:
        response = requests.get(nupnp_url, timeout=timeout)
        if response.status_code == 200:
            host_list = response.json()
            for host in host_list:
                try:
                    if bridge_id in host.get('id').upper():
                        return host.get('internalipaddress')
                except AttributeError:
                    logger.error("could not extract host ip from '{}'".format(host))
    except Exception as ex:
        logger.warning("NUPnP discovery failed - {}".format(ex))


def probe_host(host, timeout) -> bool:
    try:
        response = requests.head("http://{}/api/na/config".format(host), timeout=timeout)
        if response.status_code == 200:
                return True
    except Exception:
        pass
    return False


def validate_host(host, bridge_id, timeout) -> bool:
    try:
        response = requests.get(
            "https://{}/api/na/config".format(host),
            verify=False,
            timeout=timeout
        )
        if response.status_code == 200:
            host_info = response.json()
            if bridge_id in  host_info.get('bridgeid'):
                return True
    except Exception:
        pass
    return False


def validate_hosts_worker(hosts, valid_hosts, bridge_id, timeout):
    for host in hosts:
        if probe_host(host, timeout) and validate_host(host, bridge_id, timeout):
            valid_hosts[bridge_id] = host


def validate_hosts(hosts, bridge_id, timeout) -> dict:
    valid_hosts = dict()
    workers = list()
    bin = 0
    bin_size = 2
    if len(hosts) <= bin_size:
        worker = threading.Thread(target=validate_hosts_worker, name='validateHostsWorker', args=(hosts, valid_hosts, bridge_id, timeout))
        workers.append(worker)
        worker.start()
    else:
        for i in range(int(len(hosts) / bin_size)):
            worker = threading.Thread(target=validate_hosts_worker, name='validateHostsWorker', args=(hosts[bin:bin + bin_size], valid_hosts, bridge_id, timeout))
            workers.append(worker)
            worker.start()
            bin = bin + bin_size
        if hosts[bin:]:
            worker = threading.Thread(target=validate_hosts_worker, name='validateHostsWorker', args=(hosts[bin:], valid_hosts, bridge_id, timeout))
            workers.append(worker)
            worker.start()
    for worker in workers:
        worker.join()
    return valid_hosts


class HueBridge:
    def __init__(self, id: str, api_key: str, nupnp_url: str, ip_file: str, request_timeout: int, delay: int, check_delay: int, check_fail_safe: int):
        self.__id = id.upper()
        self.__api_key = api_key
        self.__nupnp_url = nupnp_url
        self.__ip_file = ip_file
        self.__request_timeout = request_timeout
        self.__delay = delay
        self.__check_delay = check_delay
        self.__check_fail_safe = check_fail_safe
        self.__host = None
        self.__thread = threading.Thread(name="discovery-{}".format(id), target=self.__rediscover, daemon=True)

    @property
    def host(self):
        return self.__host

    @property
    def id(self):
        return self.__id

    @property
    def api_key(self):
        return self.__api_key

    @property
    def request_timeout(self):
        return self.__request_timeout

    def start_discovery(self):
        while not self.__host:
            self.__host = self.__discover()
            if not self.__host:
                time.sleep(self.__delay)
        logger.info("discovered '{}' at '{}'".format(self.__id, self.__host))
        self.__thread.start()

    def __discover(self):
        logger.info("trying to discover '{}' ...".format(self.__id))
        try:
            host = discover_NUPnP(self.__id, self.__nupnp_url, self.__request_timeout)
            if host and validate_host(host, self.__id, self.__request_timeout):
                return host
            logger.warning("could not discover '{}' via NUPnP".format(self.__id))
            # logger.warning("could not discover '{}' via NUPnP - reverting to ip range scan".format(self.__id))
            # valid_hosts = validate_hosts(discover_hosts(self.__ip_file), self.__id, self.__request_timeout)
            # if valid_hosts:
            #     return valid_hosts[self.__id]
            # logger.warning("ip range scan yielded no results for '{}'".format(self.__id))
        except Exception as ex:
            logger.error("discovery of '{}' failed - {}".format(self.__id, ex))
        return None

    def __rediscover(self):
        fail_safe = 0
        while True:
            delay = self.__check_delay
            if not validate_host(self.__host, self.__id, self.__request_timeout):
                if fail_safe > self.__check_fail_safe:
                    logger.warning("location of '{}' seems to have changed or is not reachable".format(self.__id))
                    host = self.__discover()
                    if host:
                        fail_safe = 0
                        self.__host = host
                        logger.info("discovered '{}' at '{}'".format(self.__id, self.__host))
                    else:
                        delay = self.__delay
                else:
                    fail_safe += 1
            else:
                if fail_safe > 0:
                    logger.info("location of '{}' is unchanged and reachable".format(self.__id))
                fail_safe = 0
            time.sleep(delay)
