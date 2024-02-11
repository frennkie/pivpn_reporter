#!/usr/bin/env python3

import json
import logging
import os
import threading

import paho.mqtt.client as mqtt
import typer
from typing_extensions import Annotated, List  # Python3.6+

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s[%(lineno)d]: %(message)s')


class MqttPublishingClient:  # MPC
    def __init__(self,
                 mqtt_address: str,
                 mqtt_port: int,
                 mqtt_user: str,
                 mqtt_password: str,
                 discovery_topic_prefix: str,
                 topic_prefix: str,
                 update_frequency: int,
                 vpn_type: str):

        self.mqtt_address = mqtt_address
        self.mqtt_port = mqtt_port
        self.mqtt_user = mqtt_user
        self.mqtt_password = mqtt_password
        self.discovery_topic_prefix = discovery_topic_prefix
        self.topic_prefix = topic_prefix

        # Timer configuration
        self._update_frequency = update_frequency  # ToDo(frennkie): is this generic?

        self._reported_first_time: bool = False  # ToDo(frennkie) what is this?
        self._period_time_running_status: bool = False  # ToDo(frennkie) what is this?
        self._end_period_timer = threading.Timer(self._update_frequency * 60.0, self.period_timeout_handler)

        # custom parameters
        self.vpn_type = vpn_type

        # custom attributes derived from parameters
        self.state_topic = f'{self.topic_prefix}status'  # set last will

        # custom attributes
        self.client_list: List[str] = []

        # MQTT Client
        try:
            self.client = mqtt.Client()
        except TypeError:
            print("whelp")
            self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

    def run(self):
        self.client.on_connect = self.on_connect
        self.client.username_pw_set(self.mqtt_user, self.mqtt_password)
        self.client.will_set(self.state_topic, payload='offline', qos=0, retain=True)

        self.client.connect(self.mqtt_address, self.mqtt_port, 60)

        # get initial device list
        logging.info('Initial client list...')
        self.get_client_list()
        logging.info(self.client_list)

        # start period timer
        self.start_period_timer()

        # start MQTT loop
        self.client.loop_forever()

    def on_connect(self, userdata, flags, reason_code, properties):
        logging.debug('--> on_connect')
        logging.info('Connected with result code ' + str(reason_code))
        logging.debug(f'all: {userdata} - {flags} - {reason_code} - {properties}')
        self.state_topic = f'{self.topic_prefix}/status'  # ToDo(frennkie) is / needed?!
        self.client.publish(self.state_topic, payload='online', qos=0, retain=True)
        for client in self.client_list:
            self.publish_discovery(client)

    # Timer based on update frequency
    def period_timeout_handler(self):
        """Custom: Timer interrupt handler"""
        logging.info('Timer interrupt')

        updated_client_list = self.get_client_list()  # Get an upto date list of clients
        logging.info('Updated client list...')
        logging.info(updated_client_list)

        if self.client_list != updated_client_list:  # Compare the previous and current lists
            logging.info('Client lists are different')

            new_clients = [i for i in updated_client_list if i not in self.client_list]
            logging.info('New clients:')
            logging.info(new_clients)
            removed_clients = [i for i in self.client_list if i not in updated_client_list]
            logging.info('Removed Clients')
            logging.info(removed_clients)
            for client_name in new_clients:  # Create discovery data for new clients
                self.publish_discovery(client_name)
            for client_name in removed_clients:  # Remove HA entity for removed clients
                self.remove_discovery(client_name)

        else:
            logging.debug('Client lists are identical')

        self.publish_client_attributes()
        self.start_period_timer()

    def start_period_timer(self):
        """start the timer"""
        logging.debug('--> start_period_timer')

        self.stop_period_timer()
        self._end_period_timer = threading.Timer(self._update_frequency * 30.0, self.period_timeout_handler)
        self._end_period_timer.start()
        self._period_time_running_status = True
        logging.info('Timer Started')

    def stop_period_timer(self):
        """TBD: Stop the timer"""
        self._end_period_timer.cancel()
        self._period_time_running_status = False
        logging.info('Timer stopped')

    def get_client_list(self) -> List[str]:
        """Custom: Update the client list"""
        logging.debug('--> get_client_list')

        raw_clients = os.popen("pivpn -l").read().split()  # ToDo(frennkie) os.popen?!
        logging.debug(raw_clients)

        _client_list: list = []
        if self.vpn_type == 'WireGuard':
            client_count = (len(raw_clients) - 13) / 7
            x = 0
            name_position = 9
            while x < client_count:
                client_name = raw_clients[name_position]
                logging.info('Appending client ' + client_name + ' to client_list')
                self.client_list.append(client_name)
                x += 1
                name_position += 7
            return _client_list

        if self.vpn_type == 'OpenVPN':
            client_count = (len(raw_clients) - 27) / 5
            x = 0
            name_position = 28
            while x < client_count:
                client_name = raw_clients[name_position]
                logging.info('Appending client ' + client_name + ' to client_list')
                self.client_list.append(client_name)
                x += 1
                name_position += 5
            return _client_list

    def publish_discovery(self, client_name):
        """Custom: Publish discovery data for a client"""
        logging.debug('--> publish_discovery(' + client_name + ')')
        discovery_topic = f'{self.discovery_topic_prefix}{client_name}/config'
        payload = {}
        payload['name'] = f'VPN Client {client_name.title()}'
        payload['unique_id'] = f'VPN{self.vpn_type}{client_name}Client'
        payload['state_topic'] = f'{self.topic_prefix}{client_name}/state'
        # payload['payload_available'] = 'Online'  # ToDo(frennkie) is this needed?
        # payload['payload_not_available'] = 'Offline'  # ToDo(frennkie) is this needed?
        payload['availability_topic'] = f'{self.topic_prefix}status'
        payload['icon'] = 'mdi:vpn'
        payload['json_attributes_topic'] = f'{self.topic_prefix}{client_name}/attr'
        payload['dev'] = {
            'identifiers': ['vpncltmon'],
            'manufacturer': self.vpn_type,
            'name': 'VPN Client Monitor'
        }
        self.client.publish(discovery_topic, json.dumps(payload), 0, retain=True)

    def remove_discovery(self, client_name):
        """Remove discovery data for a client"""
        logging.debug('--> publish_discovery(' + client_name + ')')
        discovery_topic = f'{self.discovery_topic_prefix}{client_name}/config'
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
            topic = f'{self.topic_prefix}{client_name}/attr'
            self.client.publish(topic, str(data), retain=False)  # Publish attributes
            topic = f'{self.topic_prefix}{client_name}/state'
            self.client.publish(topic, state, retain=False)  # Publish state


def main(
        mqtt_address: Annotated[str, typer.Argument(
            envvar="MQTT_ADDRESS", help="MQTT address"
        )] = "homeassistant.local",
        mqtt_port: Annotated[int, typer.Argument(
            envvar="MQTT_PORT", help="MQTT port"
        )] = 1883,
        mqtt_user: Annotated[str, typer.Argument(
            envvar="MQTT_USER", help="MQTT user"
        )] = 'mqttuser',
        mqtt_password: Annotated[str, typer.Argument(
            envvar="MQTT_PASSWORD", help="MQTT password"
        )] = 'changeme',
        discovery_topic_prefix: str = typer.Argument(
            'homeassistant/sensor/pivpn/',
            help="Discovery topic prefix"
        ),
        topic_prefix: str = typer.Argument(
            'home/nodes/sensor/pivpn/',
            help="Topic prefix"
        ),
        update_frequency: int = typer.Argument(
            1,
            help="Update frequency in minutes"
        ),
        vpn_type: str = typer.Argument(
            "WireGuard",
            help="VPN type. Must be either 'WireGuard' or 'OpenVPN', case sensitive"
        )
):

    mpc = MqttPublishingClient(
        mqtt_address=mqtt_address,
        mqtt_port=mqtt_port,
        mqtt_user=mqtt_user,
        mqtt_password=mqtt_password,
        discovery_topic_prefix=discovery_topic_prefix,
        topic_prefix=topic_prefix,
        update_frequency=update_frequency,
        vpn_type=vpn_type
    )

    mpc.run()


if __name__ == "__main__":
    typer.run(main)
