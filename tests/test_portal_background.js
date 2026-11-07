const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup({tabs = []} = {}) {
  const storage = {};
  let listener;
  const healthRequests = [];
  const tabMessages = [];
  const event = {addListener() {}};
  const chrome = {
    runtime: {onMessage:{addListener(fn) { listener = fn; }}, onInstalled:event, onStartup:event, getURL:s => `chrome-extension://ornek/${s}`},
    storage: {local: {
      async get(keys) { const result = {}; for (const key of (Array.isArray(keys) ? keys : [keys])) result[key] = storage[key]; return result; },
      async set(values) { Object.assign(storage, values); }
    }},
    alarms: {onAlarm:event, create() {}},
    tabs: {onUpdated:event, async query() { return tabs; }, async sendMessage(id, message) { tabMessages.push({id, message}); }}
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
  return {call, storage, healthRequests, tabMessages};
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


test('Açık portal sekmesi yoksa tarama başlamaz ve durum kaydedilir', async () => {
  const {call, storage} = setup();
  storage.sync_key = 'a'.repeat(43);
  storage.attempted_uyap = 1700000000000;
  const result = await call({type:'start_scans'}, {url:'chrome-extension://ornek/popup.html',frameId:0});
  assert.equal(result.ok, true);
  assert.equal(storage.scan_uyap, 'sekme_yok');
  assert.equal(storage.scan_uets, 'sekme_yok');
});

test('Eşleştirme olmadan tarama başlatılmaz', async () => {
  const {call, storage} = setup();
  const result = await call({type:'start_scans'}, {url:'chrome-extension://ornek/popup.html',frameId:0});
  assert.equal(result.ok, true);
  assert.equal(storage.scan_uyap, undefined);
});

test('Portal sayfalarına ad kontrolü, doğrulama köprüsü, oturum yoklaması ve tarayıcı betiği yüklenir', () => {
  const manifest = JSON.parse(fs.readFileSync('uyap-uets-eklentisi/manifest.json', 'utf8'));
  assert.ok(manifest.content_scripts.some(entry => entry.js.includes('pair.js')));
  const portal = manifest.content_scripts.filter(entry => entry.matches.some(match => match.includes('uyap.gov.tr') || match.includes('etebligat.gov.tr')));
  assert.deepEqual(portal.flatMap(entry => entry.js), ['account-name.js', 'bridge.js', 'session.js', 'auto.js']);
  // Tarama betiği sayfanın kendi bağlamında, köprü ise yalıtılmış bağlamda çalışır.
  assert.equal(portal.find(entry => entry.js.includes('auto.js')).world, 'MAIN');
  assert.equal(portal.find(entry => entry.js.includes('bridge.js')).world, undefined);
});

test('Oturum yoklaması sonucu saklanır ve duruma eklenerek sunucuya bildirilir', async () => {
  const {call, storage, healthRequests} = setup();
  storage.sync_key = 'a'.repeat(43);
  await call({type:'session', ok:true});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(storage.session_uyap.ok, true);
  assert.ok(Number.isInteger(storage.session_uyap.at));
  const report = healthRequests.at(-1).body;
  assert.equal(report.uyap.session.ok, true);
  assert.equal(report.uets.session, undefined);
  await call({type:'session', ok:false}, {url:'https://ptt.etebligat.gov.tr/',frameId:0});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(storage.session_uets.ok, false);
});

test('Geçersiz veya alt çerçeveden gelen oturum bildirimi yok sayılır', async () => {
  const {call, storage} = setup();
  assert.equal(await call({type:'session', ok:'evet'}), undefined);
  assert.equal(await call({type:'session', ok:true}, {url:'https://avukat.uyap.gov.tr/',frameId:3}), undefined);
  assert.equal(await call({type:'session', ok:true}, {url:'https://baska.example/',frameId:0}), undefined);
  assert.equal(storage.session_uyap, undefined);
});

test('Oturum bildirimindeki hesap adı saklanır ve durumla birlikte iletilir', async () => {
  const {call, storage, healthRequests} = setup();
  storage.sync_key = 'a'.repeat(43);
  await call({type:'session', ok:true, name:'ÖRNEK AVUKAT'});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(storage.session_uyap.name, 'ÖRNEK AVUKAT');
  assert.equal(healthRequests.at(-1).body.uyap.session.name, 'ÖRNEK AVUKAT');
  await call({type:'session', ok:true, name:'x'.repeat(201)});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(storage.session_uyap.name, '');
});

test('Oturum kapalıyken açılınca tarama kendiliğinden başlatılır', async () => {
  const tab = {id: 7, url: 'https://avukat.uyap.gov.tr/'};
  const {call, storage, tabMessages} = setup({tabs: [tab]});
  storage.sync_key = 'a'.repeat(43);
  storage.session_uyap = {ok: false, at: 1, name: ''};
  storage.attempted_uyap = 0;
  await call({type:'session', ok:true, name:'ÖRNEK AVUKAT'});
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(tabMessages.map(item => [item.id, item.message.type]), [[7, 'auto_scan']]);
});

test('Oturum zaten açıksa her yoklamada yeni tarama başlatılmaz', async () => {
  const tab = {id: 7, url: 'https://avukat.uyap.gov.tr/'};
  const {call, storage, tabMessages} = setup({tabs: [tab]});
  storage.sync_key = 'a'.repeat(43);
  storage.session_uyap = {ok: true, at: 1, name: 'ÖRNEK AVUKAT'};
  await call({type:'session', ok:true, name:'ÖRNEK AVUKAT'});
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(tabMessages, []);
});

test('Oturum kapanınca tarama başlatılmaz', async () => {
  const tab = {id: 7, url: 'https://avukat.uyap.gov.tr/'};
  const {call, storage, tabMessages} = setup({tabs: [tab]});
  storage.sync_key = 'a'.repeat(43);
  storage.session_uyap = {ok: true, at: 1, name: ''};
  await call({type:'session', ok:false, name:''});
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(tabMessages, []);
});

test('Son tarama izin_yok ise oturum açıkken beş dakika sonra yeniden denenir', async () => {
  const tab = {id: 7, url: 'https://avukat.uyap.gov.tr/'};
  const {call, storage, tabMessages} = setup({tabs: [tab]});
  storage.sync_key = 'a'.repeat(43);
  storage.session_uyap = {ok: true, at: 1, name: 'ÖRNEK AVUKAT'};
  storage.scan_uyap = 'izin_yok';
  storage.attempted_uyap = Date.now() - 6 * 60 * 1000;
  await call({type:'session', ok:true, name:'ÖRNEK AVUKAT'});
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(tabMessages.map(item => item.message.type), ['auto_scan']);
});

test('izin_yok sonrası beş dakika dolmadan yeniden denenmez', async () => {
  const tab = {id: 7, url: 'https://avukat.uyap.gov.tr/'};
  const {call, storage, tabMessages} = setup({tabs: [tab]});
  storage.sync_key = 'a'.repeat(43);
  storage.session_uyap = {ok: true, at: 1, name: 'ÖRNEK AVUKAT'};
  storage.scan_uyap = 'izin_yok';
  storage.attempted_uyap = Date.now() - 60 * 1000;
  await call({type:'session', ok:true, name:'ÖRNEK AVUKAT'});
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(tabMessages, []);
});

test('Tarama tamamlanmışsa oturum yoklaması yeni tarama başlatmaz', async () => {
  const tab = {id: 7, url: 'https://avukat.uyap.gov.tr/'};
  const {call, storage, tabMessages} = setup({tabs: [tab]});
  storage.sync_key = 'a'.repeat(43);
  storage.session_uyap = {ok: true, at: 1, name: 'ÖRNEK AVUKAT'};
  storage.scan_uyap = 'tamamlandi';
  storage.completed_uyap = Date.now() - 10 * 60 * 1000;
  storage.attempted_uyap = Date.now() - 10 * 60 * 1000;
  await call({type:'session', ok:true, name:'ÖRNEK AVUKAT'});
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(tabMessages, []);
});
