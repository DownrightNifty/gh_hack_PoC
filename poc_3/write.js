// usage: node write.js <GOOGLE HOME IP> <WRITE SERVER URL> <WRITE FOLDER>

const WebSocket = require('ws');
const http = require('http');

if (process.argv.length !== 5) {
  console.error('incorrect arguments'); process.exit(1);
}

let DEVICE_IP = process.argv[2];
let SERVER_URL = process.argv[3];
let WRITE_FOLDER = process.argv[4];

let cmdId = 1;
async function sendCmdCDP(
  ws, method, params = {}, sessionId = null
) {
  console.log(`${method}(${JSON.stringify(params)})`);
  let cmd = {
    id: cmdId,
    method: method,
    params: params
  };
  if (sessionId) { cmd.sessionId = sessionId; }
  return new Promise(resolve => {
    ws.send(JSON.stringify(cmd));
    cmdId++;
    ws.onmessage = function (msg) {
      let msgStr = msg.data;
      let msgObj = JSON.parse(msgStr);
      if (msgObj.id === cmd.id) {
        ws.onmessage = null;
        console.log(`result: ${msgStr}}`);
        resolve(msgObj.result);
      }
    };
  });
}

let options = {
  host: DEVICE_IP,
  port: 9222,
  path: '/json/version'
};
let req = http.request(options, async function (res) {
  let body = '';
  res.on('data', chunk => { body += chunk; });
  res.on('end', async function () {
    let wsUrl = JSON.parse(body).webSocketDebuggerUrl;
    const ws = new WebSocket(wsUrl);
    ws.onopen = async function () {
      let targetInfos = (await sendCmdCDP(ws, 'Target.getTargets')).targetInfos;
      let targetId = targetInfos.find(item => item.type === 'page').targetId;
      let sessionId = (await sendCmdCDP(ws, 'Target.attachToTarget', {
        targetId: targetId,
        flatten: true
      })).sessionId;
      await sendCmdCDP(ws, 'Page.navigate', {url: SERVER_URL}, sessionId);
      await sendCmdCDP(ws, 'Page.setDownloadBehavior', {
        behavior: 'allow',
        downloadPath: WRITE_FOLDER
      }, sessionId);
      let documentId = (await sendCmdCDP(ws, 'Runtime.evaluate', {
        expression: 'document',
        returnByValue: false,
        awaitPromise: true,
        userGesture: true
      }, sessionId)).result.objectId;
      await sendCmdCDP(ws, 'Runtime.callFunctionOn', {
        functionDeclaration: 'd => { d.querySelector("a").click(); }',
        arguments: [{objectId: documentId}],
        returnByValue: false,
        awaitPromise: true,
        userGesture: true,
        objectId: documentId
      }, sessionId);
    };
  });
});
req.end();