const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('Pencere bağlantı kaydını ve ayarlar bağlantısını gösterir', async () => {
  const html = fs.readFileSync('uyap-uets-eklentisi/popup.html', 'utf8');
  const elements = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(([, id]) => [id, {
    textContent: '', disabled: false, style: {}, addEventListener(_event, fn) { this.click = fn; }
  }]));
  let opened;
  const chrome = {
    storage: {local: {async get(key) { return key === 'sync_key' ? {sync_key: 'ornek'} : {}; }}},
    tabs: {create(options) { opened = options.url; }}
  };
  elements['auto-scan'].disabled = false;
  let intervalId;
  vm.runInNewContext(fs.readFileSync('uyap-uets-eklentisi/popup.js', 'utf8'), {
    chrome, document: {getElementById(id) { return elements[id]; }}, URL, Blob, setTimeout,
    setInterval(fn, ms) { intervalId = setInterval(fn, ms); return intervalId; },
    clearInterval(id) { clearInterval(id); }
  });
  await new Promise(resolve => setImmediate(resolve));
  clearInterval(intervalId);
  assert.equal(elements['connection-state'].textContent, 'Bağlantı kaydı var');
  assert.equal(elements['auto-scan'].disabled, false);
  elements['open-settings'].click();
  assert.equal(opened, 'http://127.0.0.1:3000/hesap/ayarlar/?bolum=eklenti');
  assert.match(html, /<div hidden>[\s\S]*id="query"/);
});
