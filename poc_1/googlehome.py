import json
import time

import httpx

import utils

class APIError(Exception):
    """An error occurred calling local API."""
    pass

class LocalAPI:
    def __init__(self, ip):
        self.base_url = f'https://{ip}:8443'
    
    def get_device_info(self):
        """Returns the device name, ID, and certificate."""

        ENDPOINT = '/setup/eureka_info?params=name,device_info,sign'

        event_hooks = {
            'request': [utils.httpx_rm_headers(['user-agent'])],
            'response': [utils.httpx_raise_on_err(APIError)]
        }
        with httpx.Client(event_hooks=event_hooks, verify=False) as h:
            r = h.get(self.base_url + ENDPOINT)
            r_text = r.text
        j = json.loads(r_text)
        device_name = j['name']
        device_id = j['device_info']['cloud_device_id']
        device_cert = j['sign']['certificate'].replace('\n', '')
        return device_name, device_id, device_cert
    
    def enable_night_mode(self, potential_auth_tokens):
        """
        Enables night mode permanently with the lowest volume and LED
        brightness. Requires local auth token. potential_auth_tokens is a list
        of auth tokens to try. If all provided auth tokens are invalid, an error
        is raised.
        """
        ENDPOINT = '/setup/assistant/set_night_mode_params'

        event_hooks = {'request': [utils.httpx_rm_headers(['user-agent'])]}
        with httpx.Client(event_hooks=event_hooks, verify=False) as h:
            payload = {
                'enabled': True,
                'do_not_disturb': False,
                'led_brightness': 0.0,
                'volume': 0.0,
                'demo_to_user': False,
                'windows': [
                    {
                        'length_hours': 24,
                        'days': [0, 1, 2, 3, 4, 5, 6],
                        'start_hour': 0
                    }
                ]
            }
            success = False
            for token in potential_auth_tokens:
                headers = {'cast-local-authorization-token': token}
                r = h.post(self.base_url + ENDPOINT, json=payload,
                           headers=headers)
                if r.status_code == 200:
                    success = True
                    break
                elif r.status_code != 401:
                    # 401 is the usual Unauthorized response, so this is weird
                    print(f'Warn: Device returned status code {r.status_code}')
                time.sleep(1.0)
            if not success:
                raise APIError('Local authentication failed')