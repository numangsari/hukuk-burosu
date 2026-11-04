const hidden = /token|password|passwd|sifre|şifre|parola|secret|authorization|cookie|session|credential|otp|guvenlik.?kodu|güvenlik.?kodu|dogrulama|doğrulama|verification.?code|^pass$/i;
function redact(value, depth = 0) {
  if (depth > 30) return '[derinlik sınırı]';
  if (Array.isArray(value)) return value.map(item => redact(item, depth + 1));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, hidden.test(key) ? '[gizlendi]' : redact(item, depth + 1)]));
  }
  return value;
}
async function getServerUrl() {
  const data = await chrome.storage.local.get('server_url');
  return data.server_url || 'http://127.0.0.1:3000';
}
let queue = Promise.resolve();
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'pair') {
    let source;
    try { source = new URL(sender.url); } catch { return; }
    if (sender.frameId !== 0 || source.pathname !== '/portal-inceleme/baglanti/' || !/^[A-Za-z0-9_-]{43}$/.test(message.key || '')) return;
    const serverUrl = source.origin;
    chrome.storage.local.set({sync_key: message.key, server_url: serverUrl}).then(() => {
      sendResponse({ok: true});
      reportHealth();
      setTimeout(() => startScans(true), 5000);
    }).catch(() => sendResponse({ok: false}));
    return true;
  }
  if (message?.type === 'start_scans' && sender.url === chrome.runtime.getURL('popup.html')) {
    startScans(true).then(() => sendResponse({ok:true})).catch(() => sendResponse({ok:false}));
    return true;
  }
  if (!['check_name', 'capture', 'query_status', 'diagnostic', 'sync_item', 'scan_status', 'checkpoint'].includes(message?.type) || !sender.url) return;
  let url;
  try { url = new URL(sender.url); } catch { return; }
  const uyap = ['avukat.uyap.gov.tr', 'avukatbeta.uyap.gov.tr'].includes(url.hostname);
  const uets = url.hostname.endsWith('.etebligat.gov.tr');
  if (url.protocol !== 'https:' || (!uyap && !uets)) return;
  if (message.type === 'check_name') {
    if (sender.frameId !== 0 || typeof message.name !== 'string' || !message.name || message.name.length > 200) return;
    (async () => {
      const {sync_key: key} = await chrome.storage.local.get('sync_key');
      if (!key) return {ok:false, unavailable:true};
      const serverUrl = await getServerUrl();
      const response = await fetch(`${serverUrl}/portal-inceleme/isim-kontrol/`, {
        method:'POST', credentials:'omit', headers:{'Content-Type':'application/json', Authorization:`Bearer ${key}`},
        body:JSON.stringify({source:uyap ? 'uyap' : 'uets', name:message.name}), signal:AbortSignal.timeout(5000)
      });
      if (!response.ok) return {ok:false, unavailable:true};
      return {ok:(await response.json()).ok === true};
    })().then(sendResponse).catch(() => sendResponse({ok:false, unavailable:true}));
    return true;
  }
  if (message.type === 'checkpoint') {
    if (!uyap || sender.frameId !== 0 || !['get', 'add', 'clear'].includes(message.action)) return;
    if (message.action === 'add' && !/^[a-f0-9]{64}$/.test(message.fingerprint || '')) return;
    (async () => {
      const data = await chrome.storage.local.get('uyap_checkpoint');
      const current = Array.isArray(data.uyap_checkpoint) ? data.uyap_checkpoint.filter(x => /^[a-f0-9]{64}$/.test(x)) : [];
      if (message.action === 'add') {
        if (!current.includes(message.fingerprint)) current.push(message.fingerprint);
        if (current.length > 100000) return {ok:false};
        await chrome.storage.local.set({uyap_checkpoint:current});
      } else if (message.action === 'clear') {
        await chrome.storage.local.set({uyap_checkpoint:[]});
      }
      return {ok:true, fingerprints: message.action === 'get' ? current : []};
    })().then(sendResponse).catch(() => sendResponse({ok:false}));
    return true;
  }
  if (message.type === 'sync_item') {
    if (sender.frameId !== 0 || !message.data || (uyap && message.data.type !== 'uyap') || (uets && message.data.type !== 'notice')) return;
    (async () => {
      const {sync_key: key} = await chrome.storage.local.get('sync_key');
      if (!key) return {ok: false};
      const serverUrl = await getServerUrl();
      const response = await fetch(`${serverUrl}/portal-inceleme/eklentiden-al/`, {
        method: 'POST', credentials: 'omit', headers: {'Content-Type': 'application/json', Authorization: `Bearer ${key}`},
        body: JSON.stringify(redact(message.data)), signal: AbortSignal.timeout(120000)
      });
      return {ok: response.ok};
    })().then(sendResponse).catch(() => sendResponse({ok: false}));
    return true;
  }
  if (message.type === 'scan_status') {
    if (sender.frameId !== 0) return;
    const source = uyap ? 'uyap' : 'uets';
    const state = ['basladi', 'tamamlandi', 'eksik', 'oturum_yok', 'sunucu_yok', 'izin_yok'].includes(message.state) ? message.state : 'eksik';
    const updates = {['scan_' + source]: state};
    if (state === 'basladi') {
      updates['attempted_' + source] = Date.now();
      if (message.processed != null) updates['progress_' + source] = {
        total: message.total || 0,
        processed: message.processed || 0,
        currentFile: message.currentFile || ''
      };
    }
    if (state === 'oturum_yok') updates['attempted_' + source] = 0;
    if (state === 'tamamlandi') {
      updates['completed_' + source] = Date.now();
      updates['progress_' + source] = null;
    }
    chrome.storage.local.set(updates).then(() => reportHealth()).catch(() => {});
    if (state === 'oturum_yok' || state === 'sunucu_yok') chrome.alarms.create('portal-retry', {delayInMinutes: 5});
    return;
  }
  if (message.type === 'diagnostic') {
    if (!uets || typeof message.path !== 'string' || !/^\/(?:v1|v2)(?:\/(?:messages?|attachments?|documents?|download|_download|evidence|files?|content|read|details?|folders|inbox|\{değer\}))*\/?$/.test(message.path)) return;
    if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(message.method) || !Number.isInteger(message.status) || message.status < 100 || message.status > 599) return;
    const contentType = /^[a-z0-9.+-]+\/[a-z0-9.+-]+$/i.test(message.contentType || '') ? message.contentType : '';
    queue = queue.then(async () => {
      const current = (await chrome.storage.local.get('diagnostics')).diagnostics || [];
      const item = {path: message.path, method: message.method, status: message.status, contentType};
      if (!current.some(value => JSON.stringify(value) === JSON.stringify(item))) current.push(item);
      await chrome.storage.local.set({diagnostics: current.slice(-200)});
    }).catch(() => {});
    return;
  }
  if (message.type === 'query_status') {
    const safeError = /^(Yanıt kodu: \d{3}|Oturum bulunamadı|Bağlantı veya yanıt hatası|Açılmış tebligat bulunamadı|Liste alınamadı|Belge sayısı sınırı aşıldı|Belge boyutu sınırı aşıldı)$/.test(message.error || '') ? message.error : 'Sorgu başarısız';
    chrome.storage.local.set({['status_' + (uyap ? 'uyap' : 'uets')]: message.ok === true ? 'Yanıt alındı' : safeError});
    return;
  }
  if (typeof message.path !== 'string' || !message.path.startsWith('/') || /login|logout|auth|token|session|sifre|password|giris|nats/i.test(message.path)) return;
  if (!(uyap ? /\.ajx$/i.test(message.path) : /\/api\//i.test(message.path) || message.path === '/v1/messages')) return;
  queue = queue.then(async () => {
    const data = redact(message.data);
    if (JSON.stringify(data).length > 2_000_000) return;
    const current = (await chrome.storage.local.get('captures')).captures || [];
    current.push({ source: uyap ? 'UYAP' : 'UETS', path: message.path, capturedAt: new Date().toISOString(), data });
    await chrome.storage.local.set({ captures: current });
  }).catch(() => {});
});

const HEALTH_STATES = new Set(['bekliyor','basladi','tamamlandi','eksik','oturum_yok','sunucu_yok','sekme_hazir_degil','sekme_yok','durduruldu','izin_yok']);
async function reportHealth() {
  try {
    const values = await chrome.storage.local.get(['sync_key','scan_uyap','scan_uets','attempted_uyap','attempted_uets','completed_uyap','completed_uets']);
    if (!values.sync_key) return;
    const data = {};
    for (const source of ['uyap','uets']) {
      const state = values['scan_' + source];
      data[source] = {status: HEALTH_STATES.has(state) ? state : 'bekliyor', attempted: values['attempted_' + source] || null, completed: values['completed_' + source] || null};
    }
    const serverUrl = await getServerUrl();
    await fetch(`${serverUrl}/portal-inceleme/durum/`, {
      method: 'POST', credentials: 'omit', headers: {'Content-Type':'application/json', Authorization: `Bearer ${values.sync_key}`},
      body: JSON.stringify(data), signal: AbortSignal.timeout(5000)
    });
  } catch (_) { /* Sunucu kapalıysa sonraki kontrolde yeniden denenir. */ }
}

async function startScans(force = false) {
  // Tarama, sayfadaki avukat adı sunucudaki izinli kişiyle eşleşmeden başlamaz (bridge.js).
  await startScansWhenIdentityVerified(force);
  await reportHealth();
}

async function startScansWhenIdentityVerified(force = false) {
  const values = await chrome.storage.local.get(['sync_key', 'completed_uyap', 'completed_uets', 'attempted_uyap', 'attempted_uets', 'scan_uyap', 'scan_uets']);
  if (!values.sync_key) return;
  const tabs = await chrome.tabs.query({url: ['https://avukat.uyap.gov.tr/*', 'https://avukatbeta.uyap.gov.tr/*', 'https://ptt.etebligat.gov.tr/*']});
  for (const source of ['uyap', 'uets']) {
    const interval = values['scan_' + source] === 'sunucu_yok' ? 300000 : 7200000;
    const resume = source === 'uyap' && ['basladi', 'durduruldu'].includes(values.scan_uyap);
    if (!force && !resume && Date.now() - Math.max(values['completed_' + source] || 0, values['attempted_' + source] || 0) < interval) continue;
    const tab = tabs.find(item => source === 'uyap' ? /^https:\/\/(avukat|avukatbeta)\.uyap\.gov\.tr\//.test(item.url || '') : /^https:\/\/ptt\.etebligat\.gov\.tr\//.test(item.url || ''));
    if (tab?.id) chrome.tabs.sendMessage(tab.id, {type: 'auto_scan'}, {frameId: 0}).catch(() => chrome.storage.local.set({['scan_' + source]: 'sekme_hazir_degil'}));
    else chrome.storage.local.set({['scan_' + source]: 'sekme_yok'});
  }
}
function setupAlarm() { chrome.alarms.create('portal-scan', {periodInMinutes: 120, delayInMinutes: 1}); chrome.alarms.create('portal-health', {periodInMinutes: 1, delayInMinutes: 1}); }
chrome.runtime.onInstalled.addListener(() => { setupAlarm(); });
chrome.runtime.onStartup.addListener(() => { setupAlarm(); startScans(); });
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'portal-scan' || alarm.name === 'portal-retry') startScans(); else if (alarm.name === 'portal-health') reportHealth(); });
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if ((info.status === 'complete' || typeof info.url === 'string') && /^https:\/\/(avukat(?:beta)?\.uyap\.gov\.tr|ptt\.etebligat\.gov\.tr)\//.test(tab.url || '')) setTimeout(() => startScans(), 15000);
});
