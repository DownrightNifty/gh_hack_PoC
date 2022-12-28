"""
usage: google_login.py

Asks for Google email/password and generates credentials as google_creds.pickle
for use with link_device.py and call.py.
"""

import pickle
import sys

import googleapi

GOOGLE_CREDS_FN = 'google_creds.pickle'

if len(sys.argv) != 1:
    sys.exit('[-] See usage info at top of file')

email = input('Email: ')
password = input('Password: ')

print('[*] Logging in...')
creds = googleapi.login(email, password)
with open(GOOGLE_CREDS_FN, 'wb') as f:
    pickle.dump(creds, f)
print('[+] Saved credentials to google_creds.pickle')