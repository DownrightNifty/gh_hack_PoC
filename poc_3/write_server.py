# usage: write_server.py <PATH TO FILE>

from flask import Flask, send_file
import sys
import os

HOST = '0.0.0.0'
PORT = 5000

if len(sys.argv) != 2:
    print('incorrect arguments')
    sys.exit(1)

FILE_PATH = sys.argv[1]
FILE_NAME = os.path.basename(FILE_PATH)

INDEX_HTML = f'<a href="/{FILE_NAME}" download>click</a>'

app = Flask(__name__)

@app.route('/')
def get_index():
    return INDEX_HTML

@app.route(f'/{FILE_NAME}')
def get_file():
    return send_file(FILE_PATH, attachment_filename=FILE_NAME,
                     mimetype='application/octet-stream')

app.run(host=HOST, port=PORT)