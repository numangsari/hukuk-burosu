const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function run(host, nodes) {
  const sent = [];
  const stored = {};
  const window = {}; window.top = window;
  const context = {
    window, location:{hostname:host},
    document:{documentElement:{}, querySelectorAll(selector) { return nodes[selector] || []; }},
    chrome:{runtime:{id:'var', async sendMessage(message) { sent.push(message.name); return {ok:true}; }},
      storage:{local:{async set(value) { Object.assign(stored, value); }}}},
    MutationObserver:class { observe() {} disconnect() {} }, setInterval() {}, clearInterval() {}, clearTimeout() {}, setTimeout() {}
  };
  vm.runInNewContext(fs.readFileSync('uyap-uets-eklentisi/account-name.js', 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  return {sent, stored};
}

test('UYAP profilindeki adı ve UETS seçili hesap adını gönderir', async () => {
  const uyap = await run('avukat.uyap.gov.tr', {'#dropdownMenuButton .dropdown-toggle':[{textContent:' IŞIL İNCİ '}]});
  const uets = await run('ptt.etebligat.gov.tr', {span:[{textContent:' Seçili Hesap: IŞIL İNCİ '}]});
  assert.deepEqual(uyap.sent, ['IŞIL İNCİ']);
  assert.deepEqual(uets.sent, ['IŞIL İNCİ']);
  assert.equal(uyap.stored.name_uyap, 'izinli');
  assert.equal(uets.stored.name_uets, 'izinli');
});

test('Ad bulunamaz veya belirsizse izin kontrolüne ad göndermez', async () => {
  const uets = await run('ptt.etebligat.gov.tr', {span:[{textContent:'Seçili Hesap: A'}, {textContent:'Seçili Hesap: B'}]});
  assert.deepEqual(uets.sent, []);
  assert.equal(uets.stored.name_uets, 'okunamadi');
});

test('Eklenti yeniden yüklenip bağlam geçersizleşince hata fırlatmaz ve durur', async () => {
  const stored = {};
  const window = {}; window.top = window;
  let cleared = 0, disconnected = 0, storageCalls = 0;
  const chrome = {runtime: {id: 'var', async sendMessage() { return {ok: true}; }},
    storage: {local: {async set(value) { storageCalls++; Object.assign(stored, value); }}}};
  const timers = [];
  const context = {
    window, location: {hostname: 'avukat.uyap.gov.tr'}, chrome,
    document: {documentElement: {}, querySelectorAll: () => [{textContent: ' IŞIL İNCİ '}]},
    MutationObserver: class { observe() {} disconnect() { disconnected++; } },
    setInterval: fn => { timers.push(fn); return 1; }, clearInterval: () => { cleared++; },
    clearTimeout() {}, setTimeout() {}
  };
  vm.runInNewContext(fs.readFileSync('uyap-uets-eklentisi/account-name.js', 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(storageCalls, 1);
  // Eklenti yeniden yüklendi: eski betiğin chrome.runtime.id değeri artık yok.
  chrome.runtime.id = undefined;
  await timers[0]();
  assert.equal(storageCalls, 1);
  assert.equal(disconnected, 1);
  assert.ok(cleared >= 1);
});

test('Depolama bağlam hatası verirse betik hata fırlatmadan durur', async () => {
  const window = {}; window.top = window;
  let disconnected = 0;
  const context = {
    window, location: {hostname: 'avukat.uyap.gov.tr'},
    document: {documentElement: {}, querySelectorAll: () => [{textContent: ' IŞIL İNCİ '}]},
    chrome: {runtime: {id: 'var', async sendMessage() { return {ok: true}; }},
      storage: {local: {async set() { throw new Error('Extension context invalidated.'); }}}},
    MutationObserver: class { observe() {} disconnect() { disconnected++; } },
    setInterval: () => 1, clearInterval() {}, clearTimeout() {}, setTimeout() {}
  };
  vm.runInNewContext(fs.readFileSync('uyap-uets-eklentisi/account-name.js', 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(disconnected, 1);
});
