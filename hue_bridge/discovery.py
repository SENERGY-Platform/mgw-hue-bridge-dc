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


__all__ = ("discover_hue_bridge", )


from util import getLogger, conf
import urllib3
import urllib.parse
import threading
import subprocess
import time
import socket
import requests


logger = getLogger(__name__.split(".", 1)[-1])

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def ping(host) -> bool:
    return subprocess.call(['ping', '-c', '2', '-t', '2', host], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def get_local_ip(host) -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((host, 80))
        ip_addr = s.getsockname()[0]
        s.close()
        logger.debug("local ip address is '{}'".format(ip_addr))
        return ip_addr
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
    ip_range = get_ip_range(get_local_ip(urllib.parse.urlparse(conf.Discovery.nupnp_url).netloc))
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


def discover_NUPnP() -> str:
    try:
        response = requests.get(conf.Discovery.nupnp_url)
        if response.status_code == 200:
            host_list = response.json()
            for host in host_list:
                try:
                    if host.get('id').upper() in conf.Bridge.id:
                        return host.get('internalipaddress')
                except AttributeError:
                    logger.error("could not extract host ip from '{}'".format(host))
    except Exception as ex:
        logger.warning("NUPnP discovery failed - {}".format(ex))


def probe_host(host) -> bool:
    try:
        response = requests.head("http://{}/{}/na/config".format(host, conf.Bridge.api_path))
        if response.status_code == 200:
                return True
    except Exception:
        pass
    return False


def validate_host(host) -> bool:
    try:
        response = requests.get("https://{}/{}/na/config".format(host, conf.Bridge.api_path), verify=False)
        if response.status_code == 200:
            host_info = response.json()
            if host_info.get('bridgeid') in conf.Bridge.id:
                return True
    except Exception:
        pass
    return False


def validate_hosts_worker(hosts, valid_hosts):
    for host in hosts:
        if probe_host(host) and validate_host(host):
            valid_hosts[conf.Bridge.id] = host


def validate_hosts(hosts) -> dict:
    valid_hosts = dict()
    workers = list()
    bin = 0
    bin_size = 2
    if len(hosts) <= bin_size:
        worker = threading.Thread(target=validate_hosts_worker, name='validateHostsWorker', args=(hosts, valid_hosts))
        workers.append(worker)
        worker.start()
    else:
        for i in range(int(len(hosts) / bin_size)):
            worker = threading.Thread(target=validate_hosts_worker, name='validateHostsWorker', args=(hosts[bin:bin + bin_size], valid_hosts))
            workers.append(worker)
            worker.start()
            bin = bin + bin_size
        if hosts[bin:]:
            worker = threading.Thread(target=validate_hosts_worker, name='validateHostsWorker', args=(hosts[bin:], valid_hosts))
            workers.append(worker)
            worker.start()
    for worker in workers:
        worker.join()
    return valid_hosts


def discover_hue_bridge():
    host = None
    while not host:
        try:
            host = discover_NUPnP()
            if host and not validate_host(host):
                host = None
            if not host:
                logger.warning("could not discover host via NUPnP - reverting to ip range scan")
                valid_hosts = validate_hosts(discover_hosts())
                if valid_hosts:
                    host = valid_hosts[conf.Bridge.id]
                    continue
                else:
                    logger.warning("ip range scan yielded no results")
            else:
                continue
        except Exception as ex:
            logger.error("discovery failed - {}".format(ex))
        time.sleep(conf.Discovery.delay)
    logger.info("discovered hue bridge '{}' at '{}'".format(conf.Bridge.id, host))
    return host
