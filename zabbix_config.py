#!/usr/bin/env python
"""
    zac: Zabbix-Alerta Configurator
"""

import sys
import logging

from pyzabbix import ZabbixAPI, ZabbixAPIException


# debug logging
stream = logging.StreamHandler(sys.stdout)
stream.setLevel(logging.DEBUG)
log = logging.getLogger('pyzabbix')
log.addHandler(stream)
log.setLevel(logging.DEBUG)

__version__ = '3.4.0'

# command-line params
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

    def test_hosts(self):
        # docker setup specific for testing only

        hosts = self.zapi.host.get()
        zabbix_server_id = [h for h in hosts if h['name'] == 'Zabbix server'][0]['hostid']

        # enable zabbix server monitoring
        self.zapi.host.update(hostid=zabbix_server_id, status=0)

        HOSTS = [
            {'name': "Zabbix web", 'dns': 'zabbix-web', 'template': 'Template App Zabbix Server'},
            {'name': "Zabbix agent", 'dns': 'zabbix-agent', 'template': 'Template App Zabbix Agent'},
            {'name': "MySQL server", 'dns': 'mysql-server', 'template': 'Template App MySQL'},
            {'name': "Alerta server", 'dns': 'alerta', 'template': 'Template App HTTP Service'},
            {'name': "MongoDB server", 'dns': 'db', 'template': 'Template ICMP Ping'}
        ]

        hostgroups = self.zapi.hostgroup.get()
        linux_hostgroup_id = [hg for hg in hostgroups if hg['name'] == 'Linux servers'][0]['groupid']

        templates = self.zapi.template.get()

        def get_template_id(name):
            return [t for t in templates if t['name'] == name][0]['templateid']

        # self.zapi.item.get(output=['key_'])
        # self.zapi.trigger.get(output='extend')

        for h in HOSTS:
            r = self.zapi.host.create(
                host=h['name'],
                interfaces=[
                    {
                        "type": AGENT,
                        "main": DEFAULT,
                        "useip": CONNECT_USING_DNS,
                        "ip": "",
                        "dns": h['dns'],
                        "port": "10050"
                    }
                ],
                groups=[{"groupid": linux_hostgroup_id}],
                templates=[{"templateid": get_template_id(h['template'])}]
            )
            host_id = r['hostids'][0]

            self.zapi.item.create(
                name='Timestamp delta (test)',
                type=ZABBIX_TRAPPER,
                key_='test.timestamp',
                value_type=TEXT,
                hostid=host_id,
                status=ENABLED
            )
            self.zapi.trigger.create(
                hostid=host_id,
                description='Timestamp has changed on {HOST.NAME}',
                expression='{%s:test.timestamp.diff()}>0' % h['name'],
                type=GENERATE_MULTIPLE_EVENTS,
                priority=HIGH,
                status=ENABLED
            )


def main():

    zc = ZabbixConfig(ZABBIX_API_URL, user=ZABBIX_API_USER, password=ZABBIX_API_PASSWORD)
    zc.create_action(ALERTA_API_URL, ALERTA_API_KEY, ALERTA_PROFILE)
    zc.test_hosts()

if __name__ == '__main__':
    main()
