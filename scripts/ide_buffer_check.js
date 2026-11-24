// Verify the IDE preserves unsaved edits when switching text tabs (CDP).
const target = 'http://127.0.0.1:9222/json';

async function main() {
  const tabs = await (await fetch(target)).json();
  const page = tabs.find(t => t.type === 'page' && t.url.includes('/ide'));
  if (!page) throw new Error('IDE page not found');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let seq = 0;
  const pending = new Map();
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const call = (method, params = {}) => new Promise(r => {
    const id = ++seq; pending.set(id, r);
    ws.send(JSON.stringify({ id, method, params }));
  });
  const ev = async x => {
    const r = await call('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.text);
    return r.result.result.value;
  };
  await call('Runtime.enable');
  const result = await ev(`(async()=>{
    await openFile('README.md');
    document.querySelector('#content').value='QC_BUFFER_PROBE';
    document.querySelector('#content').dispatchEvent(new Event('input'));
    await openFile('pyproject.toml');
    const other=document.querySelector('#content').value.slice(0,20);
    await openFile('README.md');
    const restored=document.querySelector('#content').value;
    return {other, restored, dirty:[...dirty]};
  })()`);
  console.log(JSON.stringify({
    ...result,
    ok: result.restored === 'QC_BUFFER_PROBE' && result.other !== 'QC_BUFFER_PROBE',
  }, null, 2));
  ws.close();
}
main().catch(e => { console.error('BUFFER_CHECK_FAIL', e.message); process.exit(1); });
