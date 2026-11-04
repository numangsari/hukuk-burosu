const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const source = fs.readFileSync('uyap-uets-eklentisi/auto.js', 'utf8');

function response(data, bytes) {
  return {ok:true, status:200, headers:{get:() => ''}, json:async () => data,
    arrayBuffer:async () => new TextEncoder().encode(bytes || '').buffer};
}

async function run(hostname, fetch, serverOk = true, saved = new Set()) {
  const handlers = [];
  const statuses = [];
  const uploads = [];
  const delays = [];
  const origin = `https://${hostname}`;
  let finish;
  const finished = new Promise(resolve => { finish = resolve; });
  const window = {
    fetch,
    addEventListener(type, handler) { if (type === 'message') handlers.push(handler); },
    removeEventListener(type, handler) { const i = handlers.indexOf(handler); if (i >= 0) handlers.splice(i, 1); },
    postMessage(message) {
      if (message.source === 'ozkurt-scan-status') {
        statuses.push(message.state);
        if (message.state !== 'basladi') finish();
      }
      if (message.source === 'ozkurt-verify') queueMicrotask(() => dispatch({source:'ozkurt-verify-response', id:message.id, ok:true}));
      if (message.source === 'ozkurt-sync') {
        uploads.push(message.data);
        const ok = typeof serverOk === 'function' ? serverOk(message.data) : serverOk;
        queueMicrotask(() => dispatch({source:'ozkurt-sync-response', id:message.id, ok}));
      }
      if (message.source === 'ozkurt-checkpoint') {
        if (message.action === 'add') saved.add(message.fingerprint);
        if (message.action === 'clear') saved.clear();
        queueMicrotask(() => dispatch({source:'ozkurt-checkpoint-response', id:message.id, ok:true, fingerprints:[...saved]}));
      }
    }
  };
  window.top = window;
  function dispatch(data) { for (const handler of [...handlers]) handler({source:window, origin, data}); }
  const context = {window, location:{hostname, origin}, localStorage:{getItem:() => 'ornek'},
    crypto:{randomUUID:() => String(Math.random()), subtle:webcrypto.subtle}, AbortSignal, Uint8Array, TextEncoder, Map, Set,
    btoa: value => Buffer.from(value, 'binary').toString('base64'),
    setTimeout: (fn, ms) => { if (ms < 10000) { delays.push(ms); queueMicrotask(fn); } return 1; }, clearTimeout:() => {}};
  vm.runInNewContext(source, context);
  dispatch({source:'ozkurt-auto', action:'scan'});
  await finished;
  return {statuses, uploads, delays};
}

test('UETS sayfaları ve tebligat belgeleri sunucuya gönderilir', async () => {
  const starts = [];
  const result = await run('ptt.etebligat.gov.tr', async url => {
    const path = new URL(url);
    if (path.pathname.endsWith('/messages')) {
      const start = Number(path.searchParams.get('start'));
      starts.push(start);
      return response(Array.from({length:start === 0 ? 50 : 1}, (_, i) => ({id:String(start + i + 1)})));
    }
    if (path.pathname.includes('/parts/')) return response(null, '%PDF-1.4\nornek');
    return response({eyp_details:path.pathname.endsWith('/1') ? {UstYazi:{BelgeId:'b', DosyaAdi:'ornek.pdf'}} : {}});
  });
  assert.deepEqual(starts, [0, 50]);
  assert.equal(result.uploads.length, 52);
  assert.equal(result.uploads.filter(item => item.document).length, 1);
  assert.equal(result.statuses.at(-1), 'tamamlandi');
});

test('Sunucu veriyi kabul etmezse tarama tamamlandı denmez', async () => {
  const result = await run('ptt.etebligat.gov.tr', async url => {
    if (new URL(url).pathname.endsWith('/messages')) return response([{id:'1'}]);
    return response({eyp_details:{}});
  }, false);
  assert.equal(result.statuses.at(-1), 'sunucu_yok');
});

test('UYAP her durumdan en fazla üç örnek alır ve sorguları yavaşlatır', async () => {
  const queries = [];
  const result = await run('avukat.uyap.gov.tr', async (path, options) => {
    const body = JSON.parse(options.body);
    queries.push(path);
    if (path === '/yargiBirimleriSorgula_brd.ajx') return response(body.yargiTuru === '0' ? [{tablo:'birim', kod:'Örnek'}] : []);
    if (path === '/search_phrase_detayli.ajx') {
      if (body.dosyaDurumKod === 1) return response([[], 0]);
      const count = body.pageNumber === 1 ? 50 : 1;
      return response([Array.from({length:count}, (_, i) => ({dosyaId:String((body.pageNumber - 1) * 50 + i + 1), birimAdi:'Örnek', dosyaNo:`2026/${i + 1}`})), 51]);
    }
    if (path === '/list_dosya_evraklar.ajx') return response({son20Evrak:[]});
    return response({ornek:true});
  });
  assert.equal(queries.filter(path => path === '/search_phrase_detayli.ajx').length, 2);
  assert.equal(result.uploads.filter(item => item.captures.length === 4).length, 3);
  assert(result.uploads.every(item => item.captures.filter(c => c.path === '/search_phrase_detayli.ajx').every(c => c.data.sonuc[0].length <= 3)));
  assert(result.delays.some(ms => ms >= 4900));
  assert(!queries.some(path => /islem_gecmis|tahsilat|hesap/i.test(path)));
  assert.equal(result.statuses.at(-1), 'tamamlandi');
});

test('Kesilen UYAP örnek taraması tamamlanan dosyaları yeniden sorgulamaz', async () => {
  const saved = new Set();
  const details = [];
  const fetch = async (path, options) => {
    const body = JSON.parse(options.body);
    if (path === '/yargiBirimleriSorgula_brd.ajx') return response(body.yargiTuru === '0' ? [{tablo:'birim', kod:'Örnek'}] : []);
    if (path === '/search_phrase_detayli.ajx') return response(body.dosyaDurumKod === 0 ? [[1,2,3].map(i => ({dosyaId:String(i),birimAdi:'Örnek',dosyaNo:`2026/${i}`})),3] : [[],0]);
    details.push(body.dosyaId);
    return response(path === '/list_dosya_evraklar.ajx' ? {son20Evrak:[]} : {ornek:true});
  };
  const first = await run('avukat.uyap.gov.tr', fetch, data => !data.captures.some(c => c.data?.dosyaId === '2'), saved);
  assert.equal(first.statuses.at(-1), 'sunucu_yok');
  assert.equal(saved.size, 1);
  details.length = 0;
  const second = await run('avukat.uyap.gov.tr', fetch, true, saved);
  assert.equal(second.statuses.at(-1), 'tamamlandi');
  assert(!details.includes('1'));
  assert(details.includes('2'));
  assert.equal(saved.size, 0);
});

test('Açık ve kapalı dosyalardan ayrı ayrı en fazla üç örnek seçer', async () => {
  const result = await run('avukat.uyap.gov.tr', async (path, options) => {
    const body = JSON.parse(options.body);
    if (path === '/yargiBirimleriSorgula_brd.ajx') return response(body.yargiTuru === '0' ? [{tablo:'birim', kod:'Örnek'}] : []);
    if (path === '/search_phrase_detayli.ajx') {
      assert.equal(body.pageSize, 10);
      const prefix = body.dosyaDurumKod === 0 ? 'a' : 'k';
      return response([Array.from({length:10}, (_, i) => ({dosyaId:prefix+i, birimAdi:'Örnek', dosyaNo:`2026/${i+1}`})), 100]);
    }
    return response(path === '/list_dosya_evraklar.ajx' ? {son20Evrak:[]} : {ornek:true});
  });
  const cases = result.uploads.filter(item => item.captures.length === 4);
  assert.equal(cases.length, 6);
  assert.equal(cases.filter(item => item.captures[0].data.durum === 'acik').length, 3);
  assert.equal(cases.filter(item => item.captures[0].data.durum === 'kapali').length, 3);
  assert.equal(result.statuses.at(-1), 'tamamlandi');
});

test('Erişilemeyen tek dosya diğer dosyaların aktarımını durdurmaz', async () => {
  const result = await run('avukat.uyap.gov.tr', async (path, options) => {
    const body = JSON.parse(options.body);
    if (path === '/yargiBirimleriSorgula_brd.ajx') return response(body.yargiTuru === '0' ? [{tablo:'birim', kod:'Örnek'}] : []);
    if (path === '/search_phrase_detayli.ajx') return response(body.dosyaDurumKod === 0 ? [[{dosyaId:'a',birimAdi:'Örnek',dosyaNo:'2026/1'},{dosyaId:'b',birimAdi:'Örnek',dosyaNo:'2026/2'}],2] : [[],0]);
    if (path === '/dosyaAyrintiBilgileri_brd.ajx' && body.dosyaId === 'a') return {ok:false,status:403};
    if (path === '/list_dosya_evraklar.ajx') return response({son20Evrak:[]});
    return response({ornek:true});
  });
  assert.equal(result.statuses.at(-1), 'eksik');
  assert.equal(result.uploads.filter(item => item.captures.length === 4).length, 1);
  assert.equal(result.uploads.filter(item => item.captures.length === 3).length, 1);
});

test('UYAP evrak listesinin devam sayfalarını da kaydeder', async () => {
  const pages = [];
  const result = await run('avukat.uyap.gov.tr', async (path, options) => {
    const body = JSON.parse(options.body);
    if (path === '/yargiBirimleriSorgula_brd.ajx') return response(body.yargiTuru === '0' ? [{tablo:'birim', kod:'Örnek'}] : []);
    if (path === '/search_phrase_detayli.ajx') return response(body.dosyaDurumKod === 0 ? [[{dosyaId:'a',birimAdi:'Örnek',dosyaNo:'2026/1'}],1] : [[],0]);
    if (path === '/list_dosya_evraklar.ajx') {
      pages.push(body.pageNumber);
      return response({son20Evrak:Array.from({length:body.pageNumber === 1 ? 20 : 1}, (_, i) => ({ornek:i + body.pageNumber * 100}))});
    }
    return response({ornek:true});
  });
  assert.deepEqual(pages, [1, 2]);
  assert.equal(result.uploads.flatMap(item => item.captures).filter(item => item.path === '/list_dosya_evraklar.ajx').length, 2);
  assert.equal(result.statuses.at(-1), 'tamamlandi');
});
