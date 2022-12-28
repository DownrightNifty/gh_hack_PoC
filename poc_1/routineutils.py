import datetime
import secrets

import googleapi

# routines seem not to activate if activation time is within 10 seconds of
# creation, so we use 15 seconds
DELAY_SECONDS = 15

def run_commands(r, device_info, cmd_1, cmd_2):
    """
    Run cmd_1 then cmd_2 on the device after DELAY_SECONDS have passed by
    creating a routine. Returns a routine ID that can be used to delete the
    routine, or None if it couldn't be found (check before deleting).
    """
    # randomly generate the required invocation phrase
    invocation = secrets.token_hex(4)
    now = datetime.datetime.now()
    print(f'[*] Current time: {now.hour}:{now.minute}:{now.second}')
    a = now + datetime.timedelta(seconds=DELAY_SECONDS)
    print(f'[*] Routine will activate at: {a.hour}:{a.minute}:{a.second}')
    weekday = a.isoweekday()
    a = [a.hour, a.minute, a.second]
    routine_id = r.create_routine(invocation, cmd_1, cmd_2, a, [weekday],
                                  device_info)
    return routine_id

def try_delete(r, routine_id):
    """
    Try to delete a routine, accounting for the possibility that routine_id is
    None.
    """
    delete_fail = False
    if not routine_id:
        delete_fail = True
    else:
        try:
            r.delete_routine(routine_id)
        except googleapi.APIError:
            delete_fail = True
    if delete_fail:
        print('[-] Failed to delete routine')
    else:
        print('[+] Deleted routine')