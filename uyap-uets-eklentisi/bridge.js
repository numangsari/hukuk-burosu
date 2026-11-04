let expectedName = null;
let scanActive = false;
function accountName() {
  if (location.hostname === 'ptt.etebligat.gov.tr') {
    const nodes = [...document.querySelectorAll('span')].filter(node => /^\s*Seçili Hesap:\s*[^\n]+\s*$/.test(node.textContent));
    return nodes.length === 1 ? nodes[0].textContent.replace(/^\s*Seçili Hesap:\s*/, '').trim() : '';
  }
  const nodes = document.querySelectorAll('#dropdownMenuButton .dropdown-toggle');
  return nodes.length === 1 ? nodes[0].textContent.trim() : '';
}
async function verifiedName(start = false) {
  const name = accountName();
  if (!name || (!start && name !== expectedName)) return '';
  const result = await chrome.runtime.sendMessage({type:'check_name', name});
  if (!result?.ok || accountName() !== name) return '';
  if (start) expectedName = name;
  return name;
}
window.addEventListener('message', event => {
  if (event.source === window && event.origin === location.origin && event.data?.source === 'ozkurt-checkpoint') {
    if (window.top !== window || typeof event.data.id !== 'string') return;
    chrome.runtime.sendMessage({type:'checkpoint', action:event.data.action, fingerprint:event.data.fingerprint}).then(result => {
      window.postMessage({source:'ozkurt-checkpoint-response', id:event.data.id, ok:result?.ok === true, fingerprints:result?.fingerprints || []}, location.origin);
    }).catch(() => window.postMessage({source:'ozkurt-checkpoint-response', id:event.data.id, ok:false}, location.origin));
    return;
  }
  if (event.source === window && event.origin === location.origin && event.data?.source === 'ozkurt-verify') {
    if (window.top !== window || typeof event.data.id !== 'string') return;
    verifiedName().then(name => window.postMessage({source:'ozkurt-verify-response', id:event.data.id, ok:!!name}, location.origin))
      .catch(() => window.postMessage({source:'ozkurt-verify-response', id:event.data.id, ok:false}, location.origin));
    return;
  }
  if (event.source === window && event.origin === location.origin && event.data?.source === 'ozkurt-sync') {
    if (window.top !== window || typeof event.data.id !== 'string') return;
    verifiedName().then(name => name ? chrome.runtime.sendMessage({type: 'sync_item', data: {...event.data.data, lawyer_name:name}}) : {ok:false}).then(result => {
      window.postMessage({source: 'ozkurt-sync-response', id: event.data.id, ok: result?.ok === true}, location.origin);
    }).catch(() => window.postMessage({source: 'ozkurt-sync-response', id: event.data.id, ok: false}, location.origin));
    return;
  }
  if (event.source === window && event.origin === location.origin && event.data?.source === 'ozkurt-scan-status') {
    if (event.data.state !== 'basladi') { scanActive = false; expectedName = null; }
    chrome.runtime.sendMessage({
      type: 'scan_status',
      state: event.data.state,
      total: event.data.total,
      processed: event.data.processed,
      currentFile: event.data.currentFile
    }).catch(() => {});
    return;
  }
  if (event.source === window && event.origin === location.origin && event.data?.source === 'ozkurt-diagnostic') {
    chrome.runtime.sendMessage({type: 'diagnostic', path: event.data.path, method: event.data.method, status: event.data.status, contentType: event.data.contentType}).catch(() => {});
    return;
  }
  if (event.source === window && event.origin === location.origin && event.data?.source === 'ozkurt-result') {
    chrome.runtime.sendMessage({type: 'query_status', ok: event.data.ok === true, error: event.data.error}).catch(() => {});
    return;
  }
  if (event.source !== window || event.origin !== location.origin || event.data?.source !== 'ozkurt-observer') return;
  chrome.runtime.sendMessage({ type: 'capture', path: event.data.path, data: event.data.data }).catch(() => {});
});
chrome.runtime.onMessage.addListener(message => {
  if (message?.type === 'auto_scan' && !scanActive) {
    scanActive = true;
    verifiedName(true).then(name => {
    if (name) window.postMessage({source: 'ozkurt-auto', action: 'scan'}, location.origin);
    else { scanActive = false; chrome.runtime.sendMessage({type:'scan_status', state:'izin_yok'}).catch(() => {}); }
  }).catch(() => { scanActive = false; chrome.runtime.sendMessage({type:'scan_status', state:'izin_yok'}).catch(() => {}); });
  }
  if (message?.type === 'query') window.postMessage({source: 'ozkurt-request', action: 'query'}, location.origin);
  if (message?.type === 'notice_sample') window.postMessage({source: 'ozkurt-request', action: 'notice_sample'}, location.origin);
  if (message?.type === 'case_types') window.postMessage({source: 'ozkurt-request', action: 'case_types'}, location.origin);
  if (message?.type === 'closed_case_types') window.postMessage({source: 'ozkurt-request', action: 'closed_case_types'}, location.origin);
  if (message?.type === 'deep_metadata') window.postMessage({source: 'ozkurt-request', action: 'deep_metadata', examples: message.examples}, location.origin);
  if (message?.type === 'appeal_lists') window.postMessage({source: 'ozkurt-request', action: 'appeal_lists'}, location.origin);
  if (message?.type === 'type_examples') window.postMessage({source: 'ozkurt-request', action: 'type_examples', examples: message.examples}, location.origin);
  if (message?.type === 'case_example') window.postMessage({source: 'ozkurt-request', action: 'case_example', caseId: message.caseId, unitId: message.unitId, unitType: message.unitType, jurisdiction: message.jurisdiction}, location.origin);
});
