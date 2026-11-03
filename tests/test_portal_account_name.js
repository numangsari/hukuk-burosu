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
    chrome:{runtime:{async sendMessage(message) { sent.push(message.name); return {ok:true}; }},
      storage:{local:{async set(value) { Object.assign(stored, value); }}}},
    MutationObserver:class { observe() {} }, setInterval() {}, clearTimeout() {}, setTimeout() {}
  };
  vm.runInNewContext(fs.readFileSync('uyap-uets-deneme/account-name.js', 'utf8'), context);
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
