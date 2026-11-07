const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('uyap-uets-eklentisi/session.js', 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function response(status, contentType = 'text/json') {
  return {status, headers: {get: () => contentType}};
}

async function run(hostname, fetch, {top = true, storage = {}, account = 'ÖRNEK AVUKAT'} = {}) {
  const sent = [];
  const timers = [];
  const window = {};
  window.top = top ? window : {};
  const context = {
    window, fetch, AbortSignal,
    location: {hostname},
    document: {querySelectorAll: () => account === null ? [] : [{textContent: hostname === 'ptt.etebligat.gov.tr' ? 'Seçili Hesap: ' + account : ' ' + account + ' '}]},
    localStorage: {getItem: key => storage[key] ?? null},
    chrome: {runtime: {id: 'var', sendMessage: async message => { sent.push(message); }}},
    clearInterval: () => { context.cleared = (context.cleared || 0) + 1; },
    setTimeout: (fn, ms) => { timers.push({fn, ms, repeat: false}); return timers.length; },
    setInterval: (fn, ms) => { timers.push({fn, ms, repeat: true}); return timers.length; }
  };
  vm.runInNewContext(source, context);
  const first = timers.find(timer => !timer.repeat);
  if (first) await first.fn();
  return {sent, timers, context, tick: async () => { for (const timer of timers.filter(item => item.repeat)) await timer.fn(); }};
}

test('UYAP oturumu açıksa ve JSON dönerse açık bildirilir', async () => {
  const calls = [];
  const result = await run('avukat.uyap.gov.tr', async (url, options) => { calls.push({url, options}); return response(200); });
  assert.deepEqual(plain(result.sent), [{type: 'session', ok: true, name: 'ÖRNEK AVUKAT'}]);
  assert.equal(calls[0].url, '/get_avukat_id.ajx');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.credentials, 'include');
});

test('UYAP 401 döndürürse oturum kapalı bildirilir', async () => {
  const result = await run('avukat.uyap.gov.tr', async () => response(401, 'text/xml'));
  assert.deepEqual(plain(result.sent), [{type: 'session', ok: false, name: ''}]);
});

test('UYAP giriş sayfasını 200 ile döndürürse oturum kapalı sayılır', async () => {
  const result = await run('avukat.uyap.gov.tr', async () => response(200, 'text/html'));
  assert.deepEqual(plain(result.sent), [{type: 'session', ok: false, name: ''}]);
});

test('Sunucu veya ağ hatasında oturum durumu bildirilmez', async () => {
  const serverError = await run('avukat.uyap.gov.tr', async () => response(503));
  assert.deepEqual(plain(serverError.sent), []);
  const networkError = await run('avukat.uyap.gov.tr', async () => { throw new Error('ağ yok'); });
  assert.deepEqual(plain(networkError.sent), []);
});

test('UETS erişim anahtarı yoksa kapalı, varsa API yanıtına göre bildirilir', async () => {
  const noKey = await run('ptt.etebligat.gov.tr', async () => response(200));
  assert.deepEqual(plain(noKey.sent), [{type: 'session', ok: false, name: ''}]);
  const calls = [];
  const open = await run('ptt.etebligat.gov.tr', async (url, options) => { calls.push({url, options}); return response(200); }, {storage: {accessToken: 'ornek'}});
  assert.deepEqual(plain(open.sent), [{type: 'session', ok: true, name: 'ÖRNEK AVUKAT'}]);
  assert.match(calls[0].url, /^https:\/\/api\.etebligat\.gov\.tr\/v1\/messages\?/);
  assert.equal(calls[0].options.headers.Authorization, 'Bearer ornek');
  const expired = await run('ptt.etebligat.gov.tr', async () => response(401), {storage: {accessToken: 'ornek'}});
  assert.deepEqual(plain(expired.sent), [{type: 'session', ok: false, name: ''}]);
});

test('Yoklama dört dakikada bir yinelenir ve yalnızca üst çerçevede çalışır', async () => {
  const result = await run('avukat.uyap.gov.tr', async () => response(200));
  assert.equal(result.timers.find(timer => timer.repeat).ms, 4 * 60 * 1000);
  await result.tick();
  assert.equal(result.sent.length, 2);
  const frame = await run('avukat.uyap.gov.tr', async () => response(200), {top: false});
  assert.equal(frame.timers.length, 0);
  assert.deepEqual(plain(frame.sent), []);
});

test('Yoklama verisi toplamaz: yalnızca durum bilgisi gönderilir', async () => {
  const result = await run('avukat.uyap.gov.tr', async () => ({status: 200, headers: {get: () => 'text/json'}, text: async () => { throw new Error('gövde okunmamalı'); }}));
  assert.deepEqual(Object.keys(plain(result.sent[0])).sort(), ['name', 'ok', 'type']);
});

test('Açık hesap adı yalnızca oturum açıkken ve kırpılmış olarak bildirilir', async () => {
  const open = await run('avukat.uyap.gov.tr', async () => response(200));
  assert.equal(plain(open.sent)[0].name, 'ÖRNEK AVUKAT');
  const closed = await run('avukat.uyap.gov.tr', async () => response(401, 'text/xml'));
  assert.equal(plain(closed.sent)[0].name, '');
  const noName = await run('avukat.uyap.gov.tr', async () => response(200), {account: null});
  assert.equal(plain(noName.sent)[0].name, '');
});

test('Birden fazla hesap adı düğümü belirsizse ad gönderilmez', async () => {
  const sent = [];
  const window = {};
  window.top = window;
  const nodes = [{textContent: 'BİRİ'}, {textContent: 'BAŞKASI'}];
  const timers = [];
  vm.runInNewContext(source, {
    window, fetch: async () => response(200), AbortSignal, location: {hostname: 'avukat.uyap.gov.tr'},
    document: {querySelectorAll: () => nodes}, localStorage: {getItem: () => null},
    chrome: {runtime: {id: 'var', sendMessage: async message => { sent.push(message); }}},
    clearInterval() {}, setTimeout: (fn, ms) => { timers.push(fn); return 1; }, setInterval: () => 1
  });
  await timers[0]();
  assert.equal(plain(sent)[0].name, '');
});

test('Eklenti yeniden yüklenince yoklama hata fırlatmadan durur', async () => {
  const result = await run('avukat.uyap.gov.tr', async () => response(200));
  assert.equal(result.sent.length, 1);
  result.context.chrome.runtime.id = undefined;
  await result.tick();
  assert.equal(result.sent.length, 1);
  assert.ok(result.context.cleared >= 1);
});

test('Mesaj gönderimi bağlam hatası verirse yoklama durur', async () => {
  const result = await run('avukat.uyap.gov.tr', async () => response(200));
  result.context.chrome.runtime.sendMessage = async () => { throw new Error('Extension context invalidated.'); };
  await result.tick();
  assert.ok(result.context.cleared >= 1);
});
