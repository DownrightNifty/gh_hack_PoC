"""
usage: reset_volume.py volume_level

Expects a google_creds.pickle (from google_login.py) and
linked_device_info.pickle (from link_device.py) to be present.

link_device.py enables night mode, which sets the volume to 0. This resets the
volume to the provided volume_level (from 1-10).

Both your computer and the device must have an Internet connection.
"""
import pickle
import sys
import time

import googleapi
from routineutils import run_commands, try_delete, DELAY_SECONDS

GOOGLE_CREDS_FN = 'google_creds.pickle'
DEVICE_INFO_FN = 'linked_device_info.pickle'

def reset_volume(r, device_info, volume):
    print('[*] Creating routine to reset volume...')
    cmd = f'set the volume to {volume}'
    routine_id = run_commands(r, device_info, cmd, cmd)
    print('[+] Created routine. Volume should be reset in ~20 seconds')
    print('[*] Waiting until routine activates to delete it...')
    # we can't actually query the volume or activation status, so we just wait
    time.sleep(DELAY_SECONDS + 5)
    print('[*] Deleting routine...')
    try_delete(r, routine_id)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit('[-] See usage info at top of file')
    
    volume = sys.argv[1]

    if not (1 <= int(volume) <= 10):
        sys.exit('[-] See usage info at top of file')

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
    reset_volume(r, device_info, volume)