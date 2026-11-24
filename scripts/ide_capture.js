// Open a file in the IDE and capture a screenshot: node scripts/ide_capture.js <filename> <out.png>
const file = process.argv[2] || 'README.md';
const out = process.argv[3] || 'capture.png';

async function main() {
  const tabs = await (await fetch('http://127.0.0.1:9222/json')).json();
  const page = tabs.find(t => t.url.includes('/ide'));
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 0;
  const pending = new Map();
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const call = (method, params = {}) => new Promise(r => {
    const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params }));
  });
  const ev = async x => (await call('Runtime.evaluate',
    { expression: x, returnByValue: true, awaitPromise: true })).result.result.value;
  await call('Runtime.enable');
  await call('Page.enable');
  await ev(`(async()=>{await loadTree('.');await openFile(${JSON.stringify(file)});})()`);
  await new Promise(r => setTimeout(r, 900));
  console.log('state=', await ev(`JSON.stringify({file:currentFile, viewer:document.querySelector('#viewer').textContent.slice(0,180), dims:(document.querySelector('#img-dims')||{}).textContent})`));
  const shot = await call('Page.captureScreenshot', { format: 'png' });
  require('fs').writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
  console.log('saved=', out);
  ws.close();
}
main().catch(e => { console.error('CAPTURE_FAIL', e.message); process.exit(1); });
