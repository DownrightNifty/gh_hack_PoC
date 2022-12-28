"""
usage: call_device.py phone_number

Expects a google_creds.pickle (from google_login.py) and
linked_device_info.pickle (from link_device.py) to be present.

Tells the linked device to silently call the provided phone number (by first
issuing a "set volume to 0" command, then a "call <number>" command).
Automatically resets the volume afterwards.

Both your computer and the device must have an Internet connection.
"""
import pickle
import sys

import googleapi
from reset_volume import reset_volume
from routineutils import run_commands, try_delete, DELAY_SECONDS

GOOGLE_CREDS_FN = 'google_creds.pickle'
DEVICE_INFO_FN = 'linked_device_info.pickle'

# used to reset volume after call
RESET_VOLUME = 4

if len(sys.argv) != 2:
    sys.exit('[-] See usage info at top of file')

phone_number = sys.argv[1]

try:
    with open(GOOGLE_CREDS_FN, 'rb') as f:
        creds = pickle.load(f)
except FileNotFoundError:
    sys.exit('[-] Run google_login.py first')

try:
    with open(DEVICE_INFO_FN, 'rb') as f:
        device_info = pickle.load(f)
except FileNotFoundError:
    sys.exit('[-] Run link_device.py first')

print('[*] Authenticating with Routines API...')
r = googleapi.RoutinesAPI(creds)
print('[*] Creating routine...')
routine_id = run_commands(r, device_info, 'set the volume to 0',
                          f'call {phone_number}')
print('[+] Created routine. You should receive a call in ~20 seconds')
input('[!] Press enter to delete routine, reset device volume, and exit\n')
print('[*] Deleting routine...')
try_delete(r, routine_id)
reset_volume(r, device_info, RESET_VOLUME)