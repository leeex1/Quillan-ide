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
      if(window.quillancode && window.quillancode.copyText){
        await window.quillancode.copyText('QC_CLIP_PROBE');
        c.clipboardWrite = (await window.quillancode.readClipboard())==='QC_CLIP_PROBE';
        document.querySelector('#content').setSelectionRange(0,0);
        await window.quillancode.copyText('PASTED>');
        await pasteInto();
        c.clipboardPaste = document.querySelector('#content').value.startsWith('PASTED>');
      }
      document.querySelector('#findclose').click();
      c.findClose = !document.querySelector('#findbar').classList.contains('open');
      const cv=document.createElement('canvas'); cv.width=240; cv.height=120;
      const cx=cv.getContext('2d'); cx.fillStyle='#7c5cff'; cx.fillRect(0,0,240,120);
      cx.fillStyle='#ffffff'; cx.font='bold 32px monospace'; cx.fillText('QC',80,70);
      const png=cv.toDataURL('image/png').split(',')[1];
      await post('/api/file',{path:img,base64:png});
      await loadTree('.'); await openFile(img); await wait(500);
      const ii=document.querySelector('#artifact-img');
      c.imageViewer = !!ii && ii.naturalWidth>100 &&
        String((document.querySelector('#img-dims')||{}).textContent||'').includes('rendered');
      if(window.quillancode && window.quillancode.copyImage){
        document.querySelector('#vc-copy-image').click(); await wait(350);
        const data=await window.quillancode.readClipboardImage();
        c.copyImage = String(data).startsWith('data:image/png');
      }
      const h=JSON.stringify({w1:{dtype:'F32',shape:[64,64],data_offsets:[0,16384]},
        w2:{dtype:'BF16',shape:[64],data_offsets:[16384,16512]},
        w3:{dtype:'F16',shape:[512,128],data_offsets:[16512,149504]}});
      const b=new Uint8Array(8+h.length+8); new DataView(b.buffer).setBigUint64(0,BigInt(h.length),true);
      for(let i=0;i<h.length;i++)b[8+i]=h.charCodeAt(i);
      await post('/api/file',{path:st,base64:btoa(String.fromCharCode(...b))});
      await loadTree('.'); await openFile(st); await wait(500);
      c.tensorViewer = document.querySelector('#viewer').textContent.includes('BF16') &&
        document.querySelectorAll('.sizebar i').length===3;
      if(window.quillancode && window.quillancode.copyText){
        document.querySelector('#vc-copy-table').click(); await wait(200);
        c.copyTable = (await window.quillancode.readClipboard()).includes('dtype');
        document.querySelector('#vc-copy-path').click(); await wait(200);
        c.copyPath = (await window.quillancode.readClipboard())===st;
      }
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
      toggleCommands(true);
      c.commands = document.querySelectorAll('.cmdrow').length>3;
      toggleCommands(false);
      c.selectionBar = (document.querySelector('#content').setSelectionRange(0,5),
        document.querySelector('#content').dispatchEvent(new Event('mouseup')),
        document.querySelector('#selbar').classList.contains('open'));
      await showDiff(); await wait(250);
      c.diffView = document.querySelector('#viewer').textContent.includes('git diff');
      await runCouncil(); await wait(600);
      c.council = document.querySelector('#chat').textContent.includes('synthesis');
      try{ await showViewer('qc_missing_artifact_'+tag+'.png','png');
           c.missingArtifactGraceful = document.querySelector('#viewer').textContent.length>0; }
      catch(e){ c.missingArtifactGraceful=false; }
    }catch(e){ c.error=String(e); }
    for(const p of [txt,img,st]) await post('/api/delete',{path:p});
    await loadTree('.');
    openTabs=[]; dirty=new Set(); buffers={}; renderTabs(); persistState();
    await openFile('README.md');
    return c;
  })()`);

  const failed = Object.entries(result).filter(([k, v]) => k !== 'error' && v !== true).map(([k]) => k);
  console.log(JSON.stringify({ checks: result, failed, console_errors: errors,
    ok: failed.length === 0 && !result.error && errors.length === 0 }, null, 2));
  ws.close();
  if (failed.length || result.error || errors.length) process.exit(1);
}
main().catch(e => { console.error('SMOKE_FAIL', e.message); process.exit(1); });
