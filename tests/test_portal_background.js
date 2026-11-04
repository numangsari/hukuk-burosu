const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup() {
  const storage = {};
  let listener;
  const healthRequests = [];
  const event = {addListener() {}};
  const chrome = {
    runtime: {onMessage:{addListener(fn) { listener = fn; }}, onInstalled:event, onStartup:event, getURL:s => `chrome-extension://ornek/${s}`},
    storage: {local: {
      async get(keys) { const result = {}; for (const key of (Array.isArray(keys) ? keys : [keys])) result[key] = storage[key]; return result; },
      async set(values) { Object.assign(storage, values); }
    }},
    alarms: {onAlarm:event, create() {}},
    tabs: {onUpdated:event, async query() { return []; }}
  };
  vm.runInNewContext(fs.readFileSync('uyap-uets-eklentisi/background.js','utf8'), {
    chrome, URL, AbortSignal, setTimeout() {}, Date, Math, JSON, Promise,
    fetch: async (url, options) => { healthRequests.push({url, body: JSON.parse(options.body)}); return {ok:true}; }
  });
  const uyap = {url:'https://avukat.uyap.gov.tr/',frameId:0};
  const call = (message, sender = uyap) => new Promise((resolve, reject) => {
    try {
      const pending = listener(message, sender, resolve);
      if (pending !== true) resolve(undefined);
    } catch (error) { reject(error); }
  });
  return {call, storage, healthRequests};
}

test('Tamamlanan UYAP örneğinin izi yeniden başlatmada korunur', async () => {
  const {call, storage} = setup();
  const fingerprint = 'a'.repeat(64);
  assert.equal((await call({type:'checkpoint',action:'add',fingerprint})).ok, true);
  assert.equal((await call({type:'checkpoint',action:'add',fingerprint})).ok, true);
  assert.deepEqual(Array.from((await call({type:'checkpoint',action:'get'})).fingerprints), [fingerprint]);
  assert.equal(storage.uyap_checkpoint.length, 1);
  assert.equal(await call({type:'checkpoint',action:'add',fingerprint:'yanlis'}), undefined);
  assert.equal(await call({type:'checkpoint',action:'clear'}, {url:'https://ptt.etebligat.gov.tr/',frameId:0}), undefined);
  assert.equal(storage.uyap_checkpoint.length, 1);
  await call({type:'checkpoint',action:'clear'});
  assert.equal(storage.uyap_checkpoint.length, 0);
});

test('Bağlantı bilgisi yalnızca yerel eşleştirme sayfasından kabul edilir', async () => {
  const {call, storage} = setup();
  const key = 'a'.repeat(43);
  assert.equal(await call({type:'pair',key}, {url:'https://avukat.uyap.gov.tr/',frameId:0}), undefined);
  assert.equal(storage.sync_key, undefined);
  const paired = await call({type:'pair',key}, {url:'http://127.0.0.1:3000/portal-inceleme/baglanti/',frameId:0});
  assert.equal(paired.ok, true);
  assert.equal(storage.sync_key, key);
});


test('Kaynak sahibi ayrımı tamamlanana kadar aktarım başlamaz', async () => {
  const {call, storage, healthRequests} = setup();
  storage.sync_key = 'a'.repeat(43);
  storage.attempted_uyap = 1700000000000;
  const result = await call({type:'start_scans'}, {url:'chrome-extension://ornek/popup.html',frameId:0});
  assert.equal(result.ok, true);
  assert.equal(storage.scan_uyap, 'durduruldu');
  assert.equal(storage.scan_uets, 'durduruldu');
});

test('Portal sayfalarına yalnızca ad kontrolü yüklenir', () => {
  const manifest = JSON.parse(fs.readFileSync('uyap-uets-eklentisi/manifest.json', 'utf8'));
  assert.ok(manifest.content_scripts.some(entry => entry.js.includes('pair.js')));
  const portal = manifest.content_scripts.filter(entry => entry.matches.some(match => match.includes('uyap.gov.tr') || match.includes('etebligat.gov.tr')));
  assert.deepEqual(portal.flatMap(entry => entry.js), ['account-name.js']);
});
