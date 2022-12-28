"""
Note: We aren't trying to hide the fact that these requests aren't coming from a
real Android phone. gpsoauth uses a really old Google Play services / SDK
version and sends "gpsoauth/<version>" as the user agent. The functions in this
module also leave out certain headers/data that the real apps normally send.
"""

import base64
import json
import re
import secrets

import gpsoauth
import httpx

import protoc
import utils

LINK_DEVICE_PAYLOAD_PROTO_FN = 'LinkDevicePayload.proto'

class APIError(Exception):
    """Error occurred calling Google API."""
    pass

class Credentials:
    def __init__(self, email, master_token, android_id):
        self.email = email
        self.master_token = master_token
        self.android_id = android_id

def login(email, password):
    """Logs in to Google and returns Credentials for API access."""

    # randomly generate android_id
    android_id = secrets.token_hex(8)
    r = gpsoauth.perform_master_login(email, password, android_id)
    if 'Token' not in r:
        raise APIError('Login failed.')
    return Credentials(email, r['Token'], android_id)

EVENT_HOOKS = {
    'request': [utils.httpx_rm_headers(['user-agent'])],
    'response': [utils.httpx_raise_on_err(APIError)]
}

# functions for injecting data into /batchexecute RPC payloads

def _pl_esc(value, level):
    """Escapes quote and backslash for insertion into payload."""
    extra_slashes = r'\\' * (level - 1)
    esc_slash = extra_slashes + r'\\'
    esc_quote = extra_slashes + r'\"'
    value = value.replace('\\', esc_slash)
    value = value.replace('"', esc_quote)
    return value

def _int_list_to_pl_str(l):
    """Converts an integer list to a string in payload format."""
    l_str = '['
    for i in range(len(l)):
        l_str += str(l[i])
        if i != len(l) - 1:
            l_str += ','
    l_str += ']'
    return l_str

class DeviceInfo:
    def __init__(self, device_name, device_id, device_cert, device_model='GOOGLE_HOME'):
        self.device_name = device_name
        self.device_id = device_id
        self.device_cert = device_cert
        self.device_model = device_model

class RoutinesAPI:
    """Manages Google Assistant routines."""

    SERVICE = 'oauth2:https://www.google.com/accounts/OAuthLogin'
    APP = 'com.google.android.googlequicksearchbox'
    CLIENT_SIG = '38918a453d07199354f8b19af05ec6562ced5788'

    BASE_URL = 'https://assistant.google.com'
    HEADERS = {'x-requested-with': APP}

    MULTILOGIN_URL = 'https://accounts.google.com/oauth/multilogin'

    def __init__(self, creds):
        """Authenticates with the API with the provided Credentials."""

        r = utils.gpsoauth_perform_oauth(creds.email, creds.master_token,
                                         creds.android_id, self.SERVICE,
                                         self.APP, self.CLIENT_SIG)
        if ('Auth' not in r) or ('accountId' not in r):
            raise APIError('OAuth error')

        auth_token = f'{r["Auth"]}:{r["accountId"]}'
        
        with httpx.Client(http2=True, event_hooks=EVENT_HOOKS) as h:
            # multilogin gives us cookies that we then use as authentication for
            # the Assistant API
            headers = {'authorization': f'MultiBearer {auth_token}'}
            data = {'source': 'agsa', 'targetUrls': 'https://www.google.com'}
            r = h.post(self.MULTILOGIN_URL, headers=headers, data=data)
            # for some reason, the text ")]}'\n" is always prepended to the JSON
            # body, so we have to remove it
            cookies_json = r.text[5:]
            cookies_dict = json.loads(cookies_json)['cookies']
            for c in cookies_dict:
                try:
                    domain = c['domain']
                except KeyError:
                    domain = c['host']
                h.cookies.set(c['name'], c['value'], domain, c['path'])
            
            r = h.get(f'{self.BASE_URL}/settings/routines?hl=en-US',
                      headers=self.HEADERS)
            r_text = r.text
            # save cookies for future requests
            self.cookies = h.cookies
        # the Routines settings page HTML contains "at" and "sid" parameters
        # that are sent with API requests made by the included JS. we extract
        # them with regex.
        at_re = r"""["']SNlM0e["']\s*:\s*["'](.+:-?[0-9]+)["']"""
        sid_re = r"""["']FdrFJe["']\s*:\s*["'](-?[0-9]+)["']"""
        m = re.search(at_re, r_text)
        if not m:
            raise APIError('"at" param not found in HTML')
        self.at_param = m.group(1)
        m = re.search(sid_re, r_text)
        if not m:
            raise APIError('"sid" param not found in HTML')
        self.sid_param = m.group(1)

    def create_routine(self, invocation, action_1, action_2, activation_time,
                       activation_days, device_info):
        """
        Creates a routine that activates the commands action_1 and action_2 on
        the specified device at the specified time on the specified days.
        Returns the routine UUID, or None if it couldn't be found.

        activation_time is a list of 3 integers [x, y, z] where x is the hour,
        y is the minute, and z is the second (in 24-hour). Note: The official
        app only sends hour and minute.

        activation_days is a list of 1-7 integers from 1-7 (Mon-Sun)
        representing which days to activate on.

        device_info is a DeviceInfo instance.
        """
        device_name = device_info.device_name
        device_id = device_info.device_id
        device_model = device_info.device_model

        # note: there's also supposed to be a "_reqid" parameter in these URLs,
        # but the server doesn't complain about its absence

        # endpoint for creating a routine
        CREATE_URL = (
            f'{self.BASE_URL}'
            '/_/AssistantSettingsWebFeaturesRoutinesUi/data/batchexecute?rpcids'
            f'=SyjXGb&f.sid={self.sid_param}&bl=boq_assistantsettingswebuiserve'
            'r_20201222.07_p0&hl=en-US&soc-app=162&soc-platform=1&soc-device=2&'
            'rt=c'
        )
        # endpoint for listing existing routines
        LIST_URL = (
            f'{self.BASE_URL}'
            '/_/AssistantSettingsWebFeaturesRoutinesUi/data/batchexecute?rpcids'
            f'=R9EEY&f.sid={self.sid_param}&bl=boq_assistantsettingswebuiserver'
            '_20201222.07_p0&hl=en-US&soc-app=162&soc-platform=1&soc-device=2&r'
            't=c'
        )

        # building a payload for the create endpoint

        payload = (
            r'[[["SyjXGb","[[\"\",null,null,true,\"New routine\",[[\"Run a cust'
            r'om command\",true,[\"type.googleapis.com/assistant.ui.CustomQuery'
            r'TaskSettingUi\",\"{{B64_ACTION_1}}\"],\"custom_query_task\",null,'
            r'null,101,null,null,null,1,null,[101,[\"https://fonts.gstatic.com/'
            r's/i/googlematerialicons/google_assistant/v9/gm_grey-24dp/1x/gm_go'
            r'ogle_assistant_gm_grey_24dp.png\",\"https://fonts.gstatic.com/s/i'
            r'/googlematerialicons/google_assistant/v9/24px.svg\"]]],[\"Run a c'
            r'ustom command\",true,[\"type.googleapis.com/assistant.ui.CustomQu'
            r'eryTaskSettingUi\",\"{{B64_ACTION_2}}\"],\"custom_query_task\",nu'
            r'll,null,101,null,null,null,1,null,[101,[\"https://fonts.gstatic.c'
            r'om/s/i/googlematerialicons/google_assistant/v9/gm_grey-24dp/1x/gm'
            r'_google_assistant_gm_grey_24dp.png\",\"https://fonts.gstatic.com/'
            r's/i/googlematerialicons/google_assistant/v9/24px.svg\"]]]],[],nul'
            r'l,\"category_template\",[null,[[\"{{INVOCATION}}\",true]]],4,null'
            r',null,null,null,true,[[[\"{{DEVICE_MODEL}}\",\"{{DEVICE_ID}}\",\"'
            r'{{DEVICE_NAME}}\",true]],[{{ACTIVATION_TIME}},{{ACTIVATION_DAYS}}'
            r'],false,\"\"],[],null,null,null,true,false,[\"https://www.gstatic'
            '.com/assistant/static/images/my-day/intro/ic/2x/custom_240dp.png\\'
            r'",\"https://www.gstatic.com/assistant/static/images/my-day/intro/'
            r'ic/1x/ic_routine_custom.svg\"],null,null,null,[],[false,true]],[]'
            r']",null,"generic"]]]'
        )

        # B64_ACTIONs are the following base64-encoded byte sequence:
        # 0x0A + (action string byte length) + (utf-8 action string)
        def encode_action(action):
            action_bytes = action.encode('utf-8')
            ab_len = len(action_bytes)
            if ab_len > 255:
                raise ValueError('Action must be <= 255 characters')
            encoded_action = b'\x0A' + ab_len.to_bytes(1, 'big') + action_bytes
            return base64.b64encode(encoded_action).decode('ascii')
        
        payload = payload.replace('{{B64_ACTION_1}}', encode_action(action_1))
        payload = payload.replace('{{B64_ACTION_2}}', encode_action(action_2))

        payload = payload.replace('{{INVOCATION}}', _pl_esc(invocation, 2))
        payload = payload.replace('{{DEVICE_MODEL}}', device_model)
        payload = payload.replace('{{DEVICE_ID}}', device_id)
        payload = payload.replace('{{DEVICE_NAME}}', _pl_esc(device_name, 2))

        payload = payload.replace('{{ACTIVATION_TIME}}',
                                  _int_list_to_pl_str(activation_time))
        payload = payload.replace('{{ACTIVATION_DAYS}}',
                                  _int_list_to_pl_str(activation_days))

        with httpx.Client(http2=True, event_hooks=EVENT_HOOKS,
                          cookies=self.cookies, headers=self.HEADERS) as h:
            # send the payload and create the routine
            r = h.post(CREATE_URL, data={'f.req': payload, 'at': self.at_param})
            # r.content gives us the raw bytes. the text part of the response
            # starts 12 bytes in.
            r_text = r.content[11:].decode('utf-8')
            # this text seems to be in all successful responses, but not in
            # error responses
            if r'[]\n' not in r_text:
                raise APIError('Unknown error creating routine')

            # the response doesn't return the routine UUID, so we need to call
            # the "list routines" API which returns all routines and their IDs
            r = h.post(LIST_URL, data={
                'f.req': '[[["R9EEY","[]",null,"1"]]]',
                'at': self.at_param
            })
            r_text = r.content[11:].decode('utf-8')

        # this is the raw text we're searching for in the response
        pl_invocation = r'\"' + _pl_esc(invocation, 2) + r'\"'
        # we need to escape it before inserting into regex
        a = re.escape(pl_invocation)
        # simple UUID regex
        e = (r'\\"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'
             r')\\",') + a
        
        m = re.search(e, r_text)
        uuid = None
        if m:
            uuid = m.group(1)
        return uuid

    def delete_routine(self, uuid):
        """Deletes a routine by its UUID."""
        
        URL = (
            f'{self.BASE_URL}'
            '/_/AssistantSettingsWebFeaturesRoutinesUi/data/batchexecute?rpcids'
            f'=PX6Sjd&f.sid={self.sid_param}&bl=boq_assistantsettingswebuiserve'
            'r_20201222.07_p0&hl=en-US&soc-app=162&soc-platform=1&soc-device=2&'
            'rt=c'
        )

        with httpx.Client(http2=True, event_hooks=EVENT_HOOKS,
                          cookies=self.cookies, headers=self.HEADERS) as h:
            payload = r'[[["PX6Sjd","[\"{{UUID}}\",\"\"]",null,"generic"]]]'
            payload = payload.replace('{{UUID}}', uuid)
            r = h.post(URL, data={'f.req': payload, 'at': self.at_param})
            r_text = r.content[11:].decode('utf-8')
            if r'[]\n' not in r_text:
                raise APIError('Unknown error deleting routine')

class DeviceLinkAPI:
    """Links devices to the Google account."""

    SERVICE = 'oauth2:https://www.google.com/accounts/OAuthLogin'
    APP = 'com.google.android.apps.chromecast.app'
    CLIENT_SIG = '24bb24c05e47e0aefa68a58a766179d9b613a600'

    BASE_URL = 'https://clients3.google.com/cast/orchestration'

    def __init__(self, creds):
        """Authenticates with the API with the provided Credentials."""
        r = gpsoauth.perform_oauth(creds.email, creds.master_token,
                                   creds.android_id, self.SERVICE, self.APP,
                                   self.CLIENT_SIG)
        if 'Auth' not in r:
            raise APIError('OAuth error')
        self.auth_token = r['Auth']
    
    def link_device(self, device_info):
        """
        Links a device to the Google account. device_info is a DeviceInfo
        instance.
        """
        device_name = device_info.device_name
        device_id = device_info.device_id
        device_cert = device_info.device_cert

        ENDPOINT = '/deviceuserlinksbatch?rt=b'

        headers = {
            'authorization': f'Bearer {self.auth_token}',
            'accept': 'application/protobuf',
            'mobile_protocol_version': '27',
            'cast_app_type': 'ANDROID',
            'imax_protocol_version': '27',
            'accept-language': 'en_US',
            'content-type': 'application/protobuf'
        }
        with httpx.Client(http2=True, event_hooks=EVENT_HOOKS,
                          headers=headers) as h:
            # protobuf text format is weird almost-JSON. I've named the
            # important fields, rest are unknown.
            pb_text = (
                'p {\n'
                '    device_id: "{{DEVICE_ID}}"\n'
                '    device_cert: "{{DEVICE_CERT}}"\n'
                '    device_name: "{{DEVICE_NAME}}"\n'
                '    s7: "b"\n'
                '    i8: 0\n'
                '    d {\n'
                '        i1: 1\n'
                '        i2: 0\n'
                '    }\n'
                '    i10: 2\n'
                '    i12: 0\n'
                '}'
            )
            device_cert = device_cert.replace('\n', '\\n')
            device_cert = device_cert.replace('-----BEGIN CERTIFICATE-----', '')
            device_cert = device_cert.replace('-----END CERTIFICATE-----', '')
            device_name = _pl_esc(device_name, 1)
            pb_text = pb_text.replace('{{DEVICE_NAME}}', device_name)
            pb_text = pb_text.replace('{{DEVICE_ID}}', device_id)
            pb_text = pb_text.replace('{{DEVICE_CERT}}', device_cert)
            pb_data = protoc.encode(pb_text, LINK_DEVICE_PAYLOAD_PROTO_FN,
                                    'LinkDevicePayload')
            r = h.post(self.BASE_URL + ENDPOINT, content=pb_data)

class HomeGraphAPI:
    """Gets tokens for local API."""

    SERVICE = 'oauth2:https://www.google.com/accounts/OAuthLogin'
    APP = 'com.google.android.apps.chromecast.app'
    CLIENT_SIG = '24bb24c05e47e0aefa68a58a766179d9b613a600'

    BASE_URL = 'https://googlehomefoyer-pa.googleapis.com'

    def __init__(self, creds):
        """Authenticates with the API with the provided Credentials."""
        r = gpsoauth.perform_oauth(creds.email, creds.master_token,
                                   creds.android_id, self.SERVICE, self.APP,
                                   self.CLIENT_SIG)
        if 'Auth' not in r:
            raise APIError('OAuth error')
        self.auth_token = r['Auth']

    def get_local_auth_tokens(self):
        """
        Returns a list of local auth tokens for all devices registered to the
        Google account (of length 1 if only 1 device is registered). If multiple
        are returned, just try each token until the correct one is found.
        """

        ENDPOINT = ('/google.internal.home.foyer.v1.StructuresService/GetHomeGr'
                    'aph')

        headers = {
            'user-agent': 'grpc-java-cronet/1.34.0-SNAPSHOT',
            'content-type': 'application/grpc',
            'te': 'trailers',
            'accept-language': 'en-US, en;q=0.8, en;q=0.5',
            'authorization': f'Bearer {self.auth_token}',
            'grpc-timeout': '29998018u'
        }
        event_hooks = {
            'request': [utils.httpx_rm_headers(['accept', 'accept-encoding'])],
            'response': [utils.httpx_raise_on_err(APIError)]
        }
        with httpx.Client(http2=True, event_hooks=event_hooks,
                          headers=headers) as h:
            payload = b'\x00\x00\x00\x00\x04\x20\x01\x28\x01'
            r = h.post(self.BASE_URL + ENDPOINT, content=payload)
            r_bytes = r.content
        
        # gRPC response is:
        # (1-byte compressed flag) + (4-byte length) + (protobuf response data)

        # 0 indicates non-compressed
        if r_bytes[0] != 0:
            raise APIError('Received compressed gRPC response')
        # extract protobuf data
        pb_data = r_bytes[5:]
        pb_text = protoc.decode_raw(pb_data)
        # extract tokens through regex
        tokens = re.findall(r'^  28: "([^ ]{80,})"$', pb_text, re.MULTILINE)
        if len(tokens) == 0:
            raise APIError('RegEx failed to find tokens')
        return tokens