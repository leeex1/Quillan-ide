// Exercise the packaged Electron app's IDE page over the CDP websocket.
const target = 'http://127.0.0.1:9222/json';

async function main() {
  const tabs = await (await fetch(target)).json();
  const page = tabs.find(t => t.type === 'page' && t.url.includes('/ide'));
  if (!page) throw new Error('IDE page not found in Electron');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let seq = 0;
  const pending = new Map();
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  };
  const call = (method, params = {}) => new Promise((resolve) => {
    const id = ++seq;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const r = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) {
      const d = r.result.exceptionDetails;
      throw new Error((d.exception && d.exception.description) || d.text || 'evaluation failed');
    }
    return r.result && r.result.result && r.result.result.value;
  };

  await call('Runtime.enable');
  await call('Page.enable');
  const title = await evaluate('document.title');
  const hasTextarea = await evaluate("!!document.querySelector('#content') && !!document.querySelector('#prompt')");
  await new Promise(r => setTimeout(r, 800));
  const fileCount = await evaluate("document.querySelectorAll('#tree .row').length");
  const beforePath = await evaluate("document.querySelector('#pathlabel').textContent");
  await evaluate("document.querySelector('#up').click(); 'up-clicked'");
  await new Promise(r => setTimeout(r, 400));
  const afterPath = await evaluate("document.querySelector('#pathlabel').textContent");
  await evaluate("document.querySelectorAll('#tree .row[data-dir=false]').forEach((r,i)=>{ if(i<2) r.click(); }); 'opened'");
  await new Promise(r => setTimeout(r, 500));
  const tabCount = await evaluate("document.querySelectorAll('.tab').length");
  await evaluate("document.querySelector('#prompt').value='Reply with exactly: QC_ELECTRON_UI_OK'; document.querySelector('#send').click(); 'clicked'");
  await new Promise(r => setTimeout(r, 2500));
  const answer = await evaluate("document.querySelector('#chat').textContent");
  const log = await evaluate("document.querySelector('#f-status').textContent");
  const shot = await call('Page.captureScreenshot', { format: 'png' });
  if (shot.result && shot.result.data) {
    const fs = require('fs');
    const path = require('path');
    const out = path.join(__dirname, 'electron_ui.png');
    fs.writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
    console.log('screenshot=' + out);
  }
  console.log(JSON.stringify({
    title, hasTextarea, fileCount, beforePath, afterPath, tabCount,
    answer: String(answer || '').slice(0, 200),
    log: String(log || '').slice(0, 200),
    ok: title === 'quillancode IDE' && hasTextarea === true && fileCount > 0 &&
        tabCount >= 1 && (afterPath !== beforePath || beforePath === '.') &&
        String(answer || '').includes('QC_ELECTRON_UI_OK'),
  }, null, 2));
  ws.close();
}
main().catch(e => { console.error('ELECTRON_UI_FAIL', e.message); process.exit(1); });
