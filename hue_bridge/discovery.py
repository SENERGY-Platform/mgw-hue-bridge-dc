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


from util import get_logger, conf
import urllib3
import urllib.parse
import threading
import subprocess
import time
import socket
import requests


logger = get_logger(__name__.split(".", 1)[-1])

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def ping(host) -> bool:
    return subprocess.call(['ping', '-c', '2', '-t', '2', host], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def get_local_ip() -> str:
    try:
        with open(conf.Discovery.ip_file, "r") as file:
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


def discover_hosts() -> list:
    ip_range = get_ip_range(get_local_ip())
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


def discover_NUPnP(bridge_id) -> str:
    try:
        response = requests.get(conf.Discovery.nupnp_url, timeout=conf.Discovery.timeout)
        if response.status_code == 200:
            host_list = response.json()
            for host in host_list:
                try:
                    if host.get('id').upper() in bridge_id:
                        return host.get('internalipaddress')
                except AttributeError:
                    logger.error("could not extract host ip from '{}'".format(host))
    except Exception as ex:
        logger.warning("NUPnP discovery failed - {}".format(ex))


def probe_host(host) -> bool:
    try:
        response = requests.head("http://{}/{}/na/config".format(host, conf.Bridge.api_path), timeout=conf.Discovery.timeout)
        if response.status_code == 200:
                return True
    except Exception:
        pass
    return False


def validate_host(host, bridge_id) -> bool:
    try:
        response = requests.get(
            "https://{}/{}/na/config".format(host, conf.Bridge.api_path),
            verify=False,
            timeout=conf.Discovery.timeout
        )
        if response.status_code == 200:
            host_info = response.json()
            if host_info.get('bridgeid') in bridge_id:
                return True
    except Exception:
        pass
    return False


def validate_hosts_worker(hosts, valid_hosts, bridge_id):
    for host in hosts:
        if probe_host(host) and validate_host(host, bridge_id):
            valid_hosts[bridge_id] = host


def validate_hosts(hosts, bridge_id) -> dict:
    valid_hosts = dict()
    workers = list()
    bin = 0
    bin_size = 2
    if len(hosts) <= bin_size:
        worker = threading.Thread(target=validate_hosts_worker, name='validateHostsWorker', args=(hosts, valid_hosts, bridge_id))
        workers.append(worker)
        worker.start()
    else:
        for i in range(int(len(hosts) / bin_size)):
            worker = threading.Thread(target=validate_hosts_worker, name='validateHostsWorker', args=(hosts[bin:bin + bin_size], valid_hosts, bridge_id))
            workers.append(worker)
            worker.start()
            bin = bin + bin_size
        if hosts[bin:]:
            worker = threading.Thread(target=validate_hosts_worker, name='validateHostsWorker', args=(hosts[bin:], valid_hosts, bridge_id))
            workers.append(worker)
            worker.start()
    for worker in workers:
        worker.join()
    return valid_hosts


class HueBridge:
    def __init__(self, id: str):
        self.__id = id
        self.__host = None
        self.__thread = threading.Thread(name="discovery-{}".format(id), target=self.__rediscover, daemon=True)

    @property
    def host(self):
        return self.__host

    @property
    def id(self):
        return self.__id

    def start_discovery(self):
        while not self.__host:
            self.__host = self.__discover()
            if not self.__host:
                time.sleep(conf.Discovery.delay)
        logger.info("discovered '{}' at '{}'".format(self.__id, self.__host))
        self.__thread.start()

    def __discover(self):
        logger.info("trying to discover '{}' ...".format(self.__id))
        try:
            host = discover_NUPnP(self.__id)
            if host and validate_host(host, self.__id):
                return host
            logger.warning("could not discover '{}' via NUPnP - reverting to ip range scan".format(self.__id))
            valid_hosts = validate_hosts(discover_hosts(), self.__id)
            if valid_hosts:
                return valid_hosts[self.__id]
            logger.warning("ip range scan yielded no results for '{}'".format(self.__id))
        except Exception as ex:
            logger.error("discovery of '{}' failed - {}".format(self.__id, ex))
        return None

    def __rediscover(self):
        fail_safe = 0
        while True:
            delay = conf.Discovery.check_delay
            if not validate_host(self.__host, self.__id):
                if fail_safe > conf.Discovery.check_fail_safe:
                    logger.warning("location of '{}' seems to have changed or is not reachable".format(self.__id))
                    host = self.__discover()
                    if host:
                        fail_safe = 0
                        self.__host = host
                        logger.info("discovered '{}' at '{}'".format(self.__id, self.__host))
                    else:
                        delay = conf.Discovery.delay
                else:
                    fail_safe += 1
            else:
                if fail_safe > 0:
                    logger.info("location of '{}' is unchanged and reachable".format(self.__id))
                fail_safe = 0
            time.sleep(delay)
