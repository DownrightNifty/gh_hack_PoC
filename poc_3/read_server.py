# usage: read_server.py

from flask import Flask, request
import os

HOST = '0.0.0.0'
PORT = 5000

# folder (relative to current directory) to store dumped files
DUMP_LOCATION = 'dumped_files'

INDEX_HTML = '''
<html>
  <head>
    <script>
      function onChange(event) {
        let uploadBtn = document.querySelector('#uploadBtn');
        uploadBtn.click();
      }
      function onSubmit(event) {
        let url = event.target.action;
        let request = new XMLHttpRequest();
        request.open(event.target.method, url, true);
        request.onload = function () {
          console.log('uploaded:', request.responseText);
          event.target.reset();
        };
        request.onerror = function () {
          console.log('upload failed');
          event.target.reset();
        };
        request.send(new FormData(event.target));
        event.preventDefault();
      }
    </script>
  </head>
  <body>
    <form onsubmit="onSubmit(event)" action="/upload" method="POST" enctype="multipart/form-data">
      <input id="selectBtn" onchange="onChange(event)" type="file" name="file">
      <input id="uploadBtn" type="submit" value="Upload">
    </form>
  </body>
</html>
'''

os.makedirs(DUMP_LOCATION, exist_ok=True)

app = Flask(__name__)

@app.route('/')
def get_index():
    return INDEX_HTML

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return 'OK'
    file = request.files['file']
    if file.filename == '':
        return 'OK'
    filename = os.path.join(DUMP_LOCATION, file.filename)
    print(f'saving {filename}...')
    file.save(filename)
    return 'OK'

app.run(host=HOST, port=PORT)