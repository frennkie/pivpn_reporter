#!/usr/bin/env python3

import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Optional

import paho.mqtt.client as mqtt
import typer
from typing_extensions import Annotated, List  # Python3.6+

__version__ = "0.1.0"

logging.basicConfig(level=logging.INFO,
                    format='%(levelname)-6s %(message)s')


def version_callback(value: bool):
    if value:
        print(f"PIVPN Reporter Version: {__version__}")
        raise typer.Exit()


class MqttClient:  # MC
    def __init__(self,
                 mqtt_host: str,
                 mqtt_port: int,
                 mqtt_user: str,
                 mqtt_password: str,
                 discovery_topic_prefix: str,
                 topic_prefix: str,
                 update_interval: int,
                 vpn_type: str):

        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_user = mqtt_user
        self.mqtt_password = mqtt_password

        # ensure there is no trailing slash on discovery_topic_prefix
        if discovery_topic_prefix.endswith('/'):
            self.discovery_topic_prefix = discovery_topic_prefix[:-1]
        else:
            self.discovery_topic_prefix = discovery_topic_prefix

        # ensure there is no trailing slash on topic_prefix
        if topic_prefix.endswith('/'):
            self.topic_prefix = topic_prefix[:-1]
        else:
            self.topic_prefix = topic_prefix

        self.update_interval = update_interval

        # register signal handler
        signal.signal(signal.SIGINT, self.signal_handler)

        # MQTT Client
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

        self.client.username_pw_set(self.mqtt_user, self.mqtt_password)
        self.client.will_set(f'{self.topic_prefix}/status', payload='offline', qos=0, retain=True)

        # custom parameters
        self.vpn_type = vpn_type

        # custom attributes
        self.client_list: List[str] = []

    def on_connect(self, client, userdata, flags, rc, properties=None):
        logging.debug('--> on_connect')
        logging.debug(f'all: {client} - {userdata} - {flags} - {rc} - {properties}')
        if rc != 0:
            logging.error(f'Connection failed with reason code: {rc}')
            sys.exit(1)
        else:
            logging.info(f'Connection successful with reason code: {rc}')

            logging.debug(f'Initial publishing of status')
            self.client.publish(f'{self.topic_prefix}/status', payload='online', qos=0, retain=True)

            for client in self.client_list:
                logging.debug(f'Publishing discovery for {client}')
                self.publish_discovery(client)

    def on_disconnect(self, client, userdata, rc=0):
        logging.debug(f'--> on_disconnected - reason code: {rc}')
        client.loop_stop()

    def on_message(self, client, userdata, message):
        logging.debug(f'--> on_message: {message.topic} {message.payload}')

    def run(self):
        # print key configuration settings
        logging.info(f'### SETTINGS Start ###')
        logging.info(f'Connection: {self.mqtt_user}@{self.mqtt_host}:{self.mqtt_port}')
        logging.info(f'Discovery topic prefix: {self.discovery_topic_prefix}')
        logging.info(f'Topic prefix: {self.topic_prefix}')
        logging.info(f'VPN type: {self.vpn_type}')
        logging.info(f'Update interval: {self.update_interval}')
        logging.info(f'### SETTINGS End ###')

        self.client.connect(self.mqtt_host, self.mqtt_port, 60)

        # start MQTT loop
        self.client.loop_start()

        # get initial client list
        self.client_list = self.get_client_list(self.vpn_type)
        logging.info('Initial client list...')
        logging.info(self.client_list)

        while True:
            logging.debug(f'Active threads: {threading.active_count()}')
            if threading.active_count() == 1:
                logging.error(f'Only one thread running, should be at least two -> exiting.')
                sys.exit(1)

            # call regular update
            self.regular_update()

            # sleep for a while
            time.sleep(self.update_interval)

    def regular_update(self):
        """Regular update"""
        logging.info('--> regular_update')

        stored_client_list = self.client_list.copy()
        logging.debug('Stored client list...')
        logging.debug(stored_client_list)

        self.client_list = self.get_client_list(self.vpn_type)  # Get an updated list of clients
        logging.debug('Current client list...')
        logging.debug(self.client_list)

        if self.client_list == stored_client_list:  # Compare the previous and current lists
            logging.debug('Client lists are identical')
        else:
            logging.info('Client lists are different')

            new_clients = [i for i in self.client_list if i not in stored_client_list]
            logging.info('New clients:')
            logging.info(new_clients)

            removed_clients = [i for i in stored_client_list if i not in self.client_list]
            logging.info('Removed Clients')
            logging.info(removed_clients)

            for client_name in new_clients:  # Create discovery data for new clients
                self.publish_discovery(client_name)
            for client_name in removed_clients:  # Remove HA entity for removed clients
                self.remove_discovery(client_name)

        self.publish_client_attributes()

    @staticmethod
    def get_client_list(vpn_type: str = 'WireGuard') -> List[str]:
        """Custom: Update the client list"""
        logging.debug('--> get_client_list')

        raw_clients = os.popen("pivpn -l").read().split()  # ToDo(frennkie) os.popen?!
        logging.debug('Raw clients...')
        logging.debug(raw_clients)

        client_list: list = []

        if vpn_type == 'WireGuard':
            client_count = (len(raw_clients) - 13) / 7
            x = 0
            name_position = 9
            while x < client_count:
                client_name = raw_clients[name_position]
                logging.info('Collecting client ' + client_name + ' for client_list')
                client_list.append(client_name)
                x += 1
                name_position += 7

        elif vpn_type == 'OpenVPN':
            client_count = (len(raw_clients) - 27) / 5
            x = 0
            name_position = 28
            while x < client_count:
                client_name = raw_clients[name_position]
                logging.info('Collecting client ' + client_name + ' for client_list')
                client_list.append(client_name)
                x += 1
                name_position += 5

        else:
            raise ValueError(f'Invalid VPN type: {vpn_type}')

        return client_list

    def publish_discovery(self, client_name: str):
        """Custom: Publish discovery data for a client"""
        logging.debug('--> publish_discovery(' + client_name + ')')
        discovery_topic = f'{self.discovery_topic_prefix}/{client_name}/config'
        payload = {}
        payload['name'] = f'VPN Client {client_name.title()}'
        payload['unique_id'] = f'VPN{self.vpn_type}{client_name}Client'
        payload['state_topic'] = f'{self.topic_prefix}/{client_name}/state'
        payload['availability_topic'] = f'{self.topic_prefix}/status'
        payload['icon'] = 'mdi:vpn'
        payload['json_attributes_topic'] = f'{self.topic_prefix}/{client_name}/attr'
        payload['dev'] = {
            'identifiers': ['vpncltmon'],
            'manufacturer': self.vpn_type,
            'name': 'VPN Client Monitor'
        }
        self.client.publish(discovery_topic, json.dumps(payload), 0, retain=True)

    def remove_discovery(self, client_name: str):
        """Remove discovery data for a client"""
        logging.debug('--> publish_discovery(' + client_name + ')')
        discovery_topic = f'{self.discovery_topic_prefix}/{client_name}/config'
        payload = {}
        self.client.publish(discovery_topic, json.dumps(payload), 0, retain=True)

    def publish_client_attributes(self):
        """Publish client attributes"""
        logging.debug('--> publish_client_attributes')
        data: str = ""
        state: str = ""

        for client_name in self.client_list:
            logging.info('Getting client attributes for ' + client_name)
            query = "pivpn -c | grep '" + client_name + "'"  # Get client row data
            client_record = os.popen(query).read().split()  # ToDo(frennkie) os.popen?!
            if self.vpn_type == 'WireGuard':
                if client_record[5] == "(not":
                    data = json.dumps(
                        {"client": client_record[0], "remote_ip": client_record[1], "local_ip": client_record[2],
                         "received": client_record[3], "sent": client_record[4],
                         "seen": client_record[5] + ' ' + client_record[6]})
                    state = client_record[5] + ' ' + client_record[6]
                else:
                    data = json.dumps(
                        {"client": client_record[0], "remote_ip": client_record[1], "local_ip": client_record[2],
                         "received": client_record[3],
                         "sent": client_record[4],
                         "seen": f'{client_record[5]} {client_record[6]} {client_record[7]} {client_record[8]} '
                                 f'{client_record[9]}'})
                    state = (f'{client_record[5]} {client_record[6]} {client_record[7]} {client_record[8]} '
                             f'{client_record[9]}')
            if self.vpn_type == 'OpenVPN':
                if len(client_record) == 0:
                    data = json.dumps({"client": client_name, "remote_ip": "", "local_ip": "", "received": "",
                                       "sent": "", "seen": ""})
                    state = "Not Connected"
                else:
                    data = json.dumps(
                        {"client": client_record[0], "remote_ip": client_record[1], "virtual_ip": client_record[2],
                         "received": client_record[3], "sent": client_record[4],
                         "connected_since": f'{client_record[5]} {client_record[6]} {client_record[7]} '
                                            f'{client_record[8]} {client_record[9]}'})
                    state = (f'{client_record[5]} {client_record[6]} {client_record[7]} {client_record[8]} '
                             f'{client_record[9]}')
            logging.info('Client attributes...')
            logging.info(data)
            logging.info('Client state...')
            logging.info(state)
            topic = f'{self.topic_prefix}/{client_name}/attr'
            self.client.publish(topic, str(data), retain=False)  # Publish attributes
            topic = f'{self.topic_prefix}/{client_name}/state'
            self.client.publish(topic, state, retain=False)  # Publish state

    def signal_handler(self, sig, frame):
        logging.debug('received SIGINT')

        self.client.publish(f'{self.topic_prefix}/status', payload='goodbye', qos=0, retain=True)

        self.client.disconnect()

        logging.info('--> clean exit')
        sys.exit(0)


def main(
        mqtt_host: Annotated[
            str, typer.Option("--mqtt-host", "-H",
                              envvar="MQTT_HOST", help="MQTT host")
        ] = "homeassistant.local",
        mqtt_port: Annotated[
            int, typer.Option("--mqtt-port", "-P",
                              envvar="MQTT_PORT", help="MQTT port")
        ] = 1883,
        mqtt_user: Annotated[
            str, typer.Option("--mqtt-user", "-u",
                              envvar="MQTT_USER", help="MQTT user")
        ] = 'mqttuser',
        mqtt_password: Annotated[
            str, typer.Option("--mqtt-password", "-p",
                              envvar="MQTT_PASSWORD", help="MQTT password")
        ] = 'changeme',
        discovery_topic_prefix: Annotated[str, typer.Option(
            "--discovery-topic-prefix", "-d",
            envvar="DISCOVERY_TOPIC_PREFIX",
            help="Discovery topic prefix"
        )] = 'homeassistant/sensor/pivpn',
        topic_prefix: Annotated[
            str, typer.Option("--topic-prefix", "-t",
                              envvar="TOPIC_PREFIX", help="Topic prefix")
        ] = 'home/nodes/sensor/pivpn',
        update_interval: Annotated[
            int, typer.Option("--update-interval", "-i",
                              envvar="UPDATE_INTERVAL",
                              help="Update interval in seconds.")
        ] = 300,
        vpn_type: Annotated[
            str, typer.Option("--vpn-type",
                              envvar="VPN_TYPE", help="VPN type. Either 'WireGuard' or 'OpenVPN', case sensitive")
        ] = "WireGuard",
        debug: Annotated[
            bool, typer.Option("--debug",
                               envvar="DEBUG", help="Enable debug mode")
        ] = False,
        version: Annotated[
            Optional[bool], typer.Option("--version", callback=version_callback,
                                         help="Print version info.", is_eager=True)
        ] = None,
):
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    mpc = MqttClient(
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        mqtt_user=mqtt_user,
        mqtt_password=mqtt_password,
        discovery_topic_prefix=discovery_topic_prefix,
        topic_prefix=topic_prefix,
        update_interval=update_interval,
        vpn_type=vpn_type
    )

    mpc.run()


if __name__ == "__main__":
    typer.run(main)
