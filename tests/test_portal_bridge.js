const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('Hesap değişince sorgu ve aktarım için izin vermez', async () => {
  let name = 'ÖRNEK AVUKAT';
  let pageListener, extensionListener;
  const messages = [], sent = [];
  const window = {addEventListener(_, fn) { pageListener = fn; }, postMessage(message) { messages.push(message); }};
  window.top = window;
  const chrome = {runtime:{id:'var', onMessage:{addListener(fn) { extensionListener = fn; }}, async sendMessage(message) {
    sent.push(message); return {ok: message.type !== 'check_name' || message.name === 'ÖRNEK AVUKAT'};
  }}};
  const location = {hostname:'ptt.etebligat.gov.tr', origin:'https://ptt.etebligat.gov.tr'};
  const document = {querySelectorAll() { return [{textContent:'Seçili Hesap: ' + name}]; }};
  vm.runInNewContext(fs.readFileSync('uyap-uets-eklentisi/bridge.js', 'utf8'), {window, document, location, chrome});
  extensionListener({type:'auto_scan'});
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(messages.some(item => item.source === 'ozkurt-auto'));
  name = 'BAŞKA AVUKAT';
  pageListener({source:window, origin:location.origin, data:{source:'ozkurt-verify', id:'1'}});
  pageListener({source:window, origin:location.origin, data:{source:'ozkurt-sync', id:'2', data:{type:'notice'}}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(messages.find(item => item.source === 'ozkurt-verify-response').ok, false);
  assert.equal(messages.find(item => item.source === 'ozkurt-sync-response').ok, false);
  assert.equal(sent.some(item => item.type === 'sync_item'), false);
});

test('Eklenti yeniden yüklenip bağlam geçersizleşince sayfa mesajları yok sayılır', async () => {
  let pageListener;
  const messages = [], sent = [];
  const window = {addEventListener(_, fn) { pageListener = fn; }, postMessage(message) { messages.push(message); }};
  window.top = window;
  const chrome = {runtime:{id:'var', onMessage:{addListener() {}}, async sendMessage(message) { sent.push(message); return {ok:true}; }}};
  const location = {hostname:'ptt.etebligat.gov.tr', origin:'https://ptt.etebligat.gov.tr'};
  const document = {querySelectorAll() { return [{textContent:'Seçili Hesap: ÖRNEK AVUKAT'}]; }};
  vm.runInNewContext(fs.readFileSync('uyap-uets-eklentisi/bridge.js', 'utf8'), {window, document, location, chrome});
  chrome.runtime.id = undefined;
  assert.doesNotThrow(() => pageListener({source:window, origin:location.origin, data:{source:'ozkurt-verify', id:'1'}}));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(messages, []);
  assert.deepEqual(sent, []);
});
