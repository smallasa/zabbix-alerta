#!/usr/bin/env python
"""
    zac: Zabbix-Alerta Configurator
"""

import sys
import time
import logging

import protobix

from pyzabbix import ZabbixAPI, ZabbixAPIException


# debug logging
stream = logging.StreamHandler(sys.stdout)
stream.setLevel(logging.DEBUG)
log = logging.getLogger('pyzabbix')
log.addHandler(stream)
log.setLevel(logging.DEBUG)

__version__ = '3.4.0'

# command-line params
ZABBIX_SERVER = 'localhost'
ZABBIX_API_URL = "http://localhost:10080"
ZABBIX_API_USER = 'Admin'
ZABBIX_API_PASSWORD = 'zabbix'


ALERTA_API_URL = 'http://alerta/api'  # dockerized hostname
ALERTA_API_KEY = None
ALERTA_PROFILE = None  # 'production'


# media type
EMAIL = 0
SCRIPT = 1
SMS = 2
JABBER = 3
EZ_TEXTING = 100

# use if severity
NIWAHD = 63

# status
ENABLED = 0
DISABLED = 1

# eventsource
TRIGGERS = 0

# operation type
SEND_MESSAGE = 0

# default msg
USE_DATA_FROM_OPERATION = 0
USE_DATA_FROM_ACTION = 1

# maintenance mode
DO_NOT_PAUSE_EXEC = 0
PAUSE_EXECUTION = 1

# host
DEFAULT = 1
AGENT = 1

CONNECT_USING_DNS = 0
CONNECT_USING_IP = 1

# item type
ZABBIX_TRAPPER = 2

# item value type
TEXT = 4

# priority
NOT_CLASSIFIED = 0
INFORMATION = 1
WARNING = 2
AVERAGE = 3
HIGH = 4
DISASTER = 5

# trigger type
DO_NOT_GENERATE_MULTIPLE_EVENTS = 0
GENERATE_MULTIPLE_EVENTS = 1


class ZabbixConfig(object):

    def __init__(self, endpoint, user, password=''):

        self.zapi = ZabbixAPI(endpoint)
        self.zapi.login(user, password)
        print("Connected to Zabbix API Version %s" % self.zapi.api_version())

    def create_action(self, api_url, api_key=None, profile=None):

        use_zabbix_severity = False
        use_console_link = True

        medias = self.zapi.mediatype.get(output='extend')
        try:
            media_id = [m for m in medias if m['description'] == 'Alerta'][0]['mediatypeid']
        except Exception:
            print('media does not exist. creating...')
            response = self.zapi.mediatype.create(
                type=SCRIPT,
                description='Alerta',
                exec_path='zabbix-alerta',
                exec_params='{ALERT.SENDTO}\n{ALERT.SUBJECT}\n{ALERT.MESSAGE}\n',
                maxattempts='5',
                attempt_interval='5s'
            )
            media_id = response['mediatypeids'][0]

        users = self.zapi.user.get(output='extend')
        admin_user_id = [g for g in users if g['alias'] == 'Admin'][0]['userid']

        sendto = '%s;%s' % (api_url, api_key) if api_key else api_url
        media_alerta = {
            'mediatypeid': media_id,
            'sendto': sendto,
            'active': ENABLED,
            'severity': NIWAHD,
            'period': '1-7,00:00-24:00'
        }

        try:
            self.zapi.user.updatemedia(
                users={"userid": admin_user_id},
                medias=media_alerta
            )
        except ZabbixAPIException as e:
            print(e)
            sys.exit()

        default_message = (
            "resource={HOST.NAME1}\r\n"
            "event={ITEM.KEY1}\r\n"
            "environment=Production\r\n"
            "severity={TRIGGER.SEVERITY}" + ("!!" if use_zabbix_severity else "") + "\r\n"
            "status={TRIGGER.STATUS}\r\n"
            "ack={EVENT.ACK.STATUS}\r\n"
            "service={TRIGGER.HOSTGROUP.NAME}\r\n"
            "group=Zabbix\r\n"
            "value={ITEM.VALUE1}\r\n"
            "text={TRIGGER.STATUS}: {TRIGGER.NAME}\r\n"
            "tags={EVENT.TAGS}\r\n"
            "attributes.ip={HOST.IP1}\r\n"
            "attributes.thresholdInfo={TRIGGER.TEMPLATE.NAME}: {TRIGGER.EXPRESSION}\r\n"
            "type=zabbixAlert\r\n"
            "dateTime={EVENT.DATE}T{EVENT.TIME}Z\r\n"
        )

        operations_console_link = 'attributes.moreInfo=<a href="%s/tr_events.php?triggerid={TRIGGER.ID}&eventid={EVENT.ID}" target="_blank">Zabbix console</a>' % ZABBIX_API_URL
        operations = {
            "operationtype": SEND_MESSAGE,
            "opmessage": {
                "default_msg": USE_DATA_FROM_OPERATION,
                "mediatypeid": media_id,
                "subject": "{TRIGGER.STATUS}: {TRIGGER.NAME}",
                "message": default_message + operations_console_link if use_console_link else ''
            },
            "opmessage_usr": [
                {
                    "userid": admin_user_id
                }
            ]
        }

        recovery_console_link = 'attributes.moreInfo=<a href="%s/tr_events.php?triggerid={TRIGGER.ID}&eventid={EVENT.RECOVERY.ID}" target="_blank">Zabbix console</a>' % ZABBIX_API_URL
        recovery_operations = {
            "operationtype": SEND_MESSAGE,
            "opmessage": {
                "default_msg": USE_DATA_FROM_OPERATION,
                "mediatypeid": media_id,
                "subject": "{TRIGGER.STATUS}: {TRIGGER.NAME}",
                "message": default_message + recovery_console_link if use_console_link else ''
            },
            "opmessage_usr": [
                {
                    "userid": admin_user_id
                }
            ]
        }

        self.zapi.action.create(
            name='Forward to Alerta',
            eventsource=TRIGGERS,
            status=ENABLED,
            esc_period=120,
            def_shortdata="{TRIGGER.NAME}: {TRIGGER.STATUS}",
            def_longdata=default_message,
            r_shortdata="{TRIGGER.NAME}: {TRIGGER.STATUS}",
            r_longdata=default_message,
            maintenance_mode=DO_NOT_PAUSE_EXEC,
            operations=[operations],
            recovery_operations=[recovery_operations]
        )

    def test_action(self):

        hosts = self.zapi.host.get()
        zabbix_server_id = [h for h in hosts if h['name'] == 'Zabbix server'][0]['hostid']

        # enable zabbix server monitoring
        self.zapi.host.update(hostid=zabbix_server_id, status=ENABLED)

        try:
            response = self.zapi.item.create(
                name='Zabbix-Alerta Integration Test',
                type=ZABBIX_TRAPPER,
                key_='test.alerta',
                value_type=TEXT,
                hostid=zabbix_server_id,
                status=ENABLED
            )
            print(response)
            item_id = response['itemids'][0]

            response = self.zapi.trigger.create(
                hostid=zabbix_server_id,
                description='Zabbix triggered event on {HOST.NAME} (Test only)',
                expression='{Zabbix server:test.alerta.diff()}>0',
                type=GENERATE_MULTIPLE_EVENTS,
                priority=HIGH,
                status=ENABLED
            )
            print(response)
            trigger_id = response['triggerids'][0]
        except ZabbixAPIException:
            item_id = None
            trigger_id = None

        cfg = protobix.ZabbixAgentConfig()
        cfg.server_active = ZABBIX_SERVER
        zbx = protobix.DataContainer(cfg)

        zbx.data_type = 'items'
        zbx.add_item(host='Zabbix server', key='test.alerta', value='??')
        response = zbx.send()
        print(response)

        time.sleep(5)

        zbx.data_type = 'items'
        zbx.add_item(host='Zabbix server', key='test.alerta', value='OK')
        response = zbx.send()
        print(response)

        try:
            self.zapi.trigger.delete(trigger_id)
            self.zapi.item.delete(item_id)
        except ZabbixAPIException:
            pass


def main():

    zc = ZabbixConfig(ZABBIX_API_URL, user=ZABBIX_API_USER, password=ZABBIX_API_PASSWORD)
    zc.create_action(ALERTA_API_URL, ALERTA_API_KEY, ALERTA_PROFILE)
    zc.test_action()

if __name__ == '__main__':
    main()
