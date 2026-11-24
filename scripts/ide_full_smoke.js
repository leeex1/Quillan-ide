// Full UI smoke: exercise every IDE control and viewer over CDP.
const target = 'http://127.0.0.1:9222/json';

async function main() {
  const tabs = await (await fetch(target)).json();
  const page = tabs.find(t => t.type === 'page' && t.url.includes('/ide'));
  if (!page) throw new Error('IDE page not found');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let seq = 0;
  const pending = new Map();
  const errors = [];
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails;
      errors.push((d.exception && d.exception.description) || d.text || 'unknown');
    }
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
    const c={};
    const wait=ms=>new Promise(r=>setTimeout(r,ms));
    const post=(p,body)=>api(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    localStorage.removeItem('quillancode.ide.state');
    buffers={}; dirty=new Set(); openTabs=[]; renderTabs();
    const tag=Date.now().toString(36);
    const txt='qc_smoke_'+tag+'.txt', img='qc_smoke_'+tag+'.png', st='qc_smoke_'+tag+'.safetensors';
    try{
      c.tree = (await api('/api/files?path=.')).items.length>0;
      c.up = (document.querySelector('#up').click(), true);
      await post('/api/file',{path:txt,content:'smoke base'});
      await loadTree('.'); await openFile(txt);
      c.textOpen = document.querySelector('#content').value==='smoke base';
      c.highlight = document.querySelector('#highlight').innerHTML.length>0;
      toggleFind(true);
      c.findOpen = document.querySelector('#findbar').classList.contains('open');
      document.querySelector('#findtext').value='base';
      document.querySelector('#replacetext').value='changed';
      document.querySelector('#replaceone').click();
      c.replace = document.querySelector('#content').value==='smoke changed';
      await save();
      c.saved = (await api('/api/file?path='+encodeURIComponent(txt))).content==='smoke changed';
      document.querySelector('#findclose').click();
      c.findClose = !document.querySelector('#findbar').classList.contains('open');
      const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9kAAAAASUVORK5CYII=';
      await post('/api/file',{path:img,base64:png});
      await loadTree('.'); await openFile(img); await wait(300);
      c.imageViewer = !!document.querySelector('#viewer img') && document.querySelector('#artifact-img').naturalWidth>0;
      const h=JSON.stringify({weight:{dtype:'F16',shape:[2,2],data_offsets:[0,8]}});
      const b=new Uint8Array(8+h.length+8); new DataView(b.buffer).setBigUint64(0,BigInt(h.length),true);
      for(let i=0;i<h.length;i++)b[8+i]=h.charCodeAt(i);
      await post('/api/file',{path:st,base64:btoa(String.fromCharCode(...b))});
      await loadTree('.'); await openFile(st); await wait(400);
      c.tensorViewer = document.querySelector('#viewer').textContent.includes('F16') &&
        document.querySelectorAll('.sizebar i').length===1;
      c.tabs = document.querySelectorAll('.tab').length>=3;
      document.querySelector('#act-check').click(); await wait(400);
      c.checks = document.querySelector('#problems').textContent.length>3;
      document.querySelector('#act-setup').click();
      c.settings = document.querySelector('#setup').open===true;
      document.querySelector('#act-agent').click();
      c.agentFocus = document.activeElement.id==='prompt';
      const before=document.querySelectorAll('#chat .msg').length;
      document.querySelector('#prompt').value='Reply with exactly: QC_UI_SMOKE';
      document.querySelector('#send').click(); await wait(1200);
      c.chat = document.querySelectorAll('#chat .msg').length>before;
      document.querySelector('#clear').click();
      c.clear = document.querySelector('#chat').textContent.includes('cleared');
      c.palette = (document.querySelector('#pquery').value='README', await (async()=>{await runPalette();return document.querySelectorAll('#pres .res').length>0;})());
    }catch(e){ c.error=String(e); }
    for(const p of [txt,img,st]) await post('/api/delete',{path:p});
    return c;
  })()`);

  const failed = Object.entries(result).filter(([k, v]) => k !== 'error' && v !== true).map(([k]) => k);
  console.log(JSON.stringify({ checks: result, failed, console_errors: errors,
    ok: failed.length === 0 && !result.error && errors.length === 0 }, null, 2));
  ws.close();
  if (failed.length || result.error || errors.length) process.exit(1);
}
main().catch(e => { console.error('SMOKE_FAIL', e.message); process.exit(1); });
