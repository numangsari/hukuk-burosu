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

const UNIT = body => response(body.yargiTuru === '0' ? [{tablo:'birim', kod:'Örnek'}] : []);

// UYAP sayfalı liste yanıtı: toplam `total` dosyadan istenen sayfayı döndürür.
function listPage(total, prefix, body) {
  const start = (body.pageNumber - 1) * body.pageSize;
  const count = Math.max(0, Math.min(body.pageSize, total - start));
  const rows = Array.from({length:count}, (_, i) => ({dosyaId:`${prefix}${start + i + 1}`, birimAdi:'Örnek', dosyaNo:`2026/${start + i + 1}`, dosyaTurKod:1}));
  return response([rows, total]);
}

const UYAP_PATHS = new Set([
  '/yargiBirimleriSorgula_brd.ajx', '/search_phrase_detayli.ajx', '/dosyaAyrintiBilgileri_brd.ajx',
  '/dosya_taraf_bilgileri_brd.ajx', '/list_dosya_evraklar.ajx', '/dosya_tahsilat_reddiyat_bilgileri_brd.ajx'
]);

test('UYAP tüm dosyaları sayfa sayfa tarar ve sorguları yavaşlatır', async () => {
  const queries = [];
  const result = await run('avukat.uyap.gov.tr', async (path, options) => {
    const body = JSON.parse(options.body);
    queries.push(path);
    if (path === '/yargiBirimleriSorgula_brd.ajx') return UNIT(body);
    if (path === '/search_phrase_detayli.ajx') return listPage(body.dosyaDurumKod === 0 ? 12 : 0, 'a', body);
    if (path === '/list_dosya_evraklar.ajx') return response({son20Evrak:[]});
    return response({ornek:true});
  });
  // Açık dosyalar 10'ar kayıtlık iki sayfa, kapalı dosyalar tek (boş) sayfa.
  assert.equal(queries.filter(path => path === '/search_phrase_detayli.ajx').length, 3);
  // Her dosya için liste kaydı, üç ayrıntı ve finans yanıtı gönderilir.
  const cases = result.uploads.filter(item => item.captures.length === 5);
  assert.equal(cases.length, 12);
  assert.equal(new Set(cases.map(item => item.captures[0].data.sonuc[0][0].dosyaId)).size, 12);
  assert(result.delays.some(ms => ms >= 4900));
  assert(queries.every(path => UYAP_PATHS.has(path)), 'beklenmeyen UYAP uç noktası çağrıldı');
  assert(!queries.some(path => /islem_gecmis/i.test(path)));
  assert.equal(result.statuses.at(-1), 'tamamlandi');
});

test('Kesilen UYAP taraması tamamlanan dosyaları yeniden sorgulamaz', async () => {
  const saved = new Set();
  const details = [];
  const fetch = async (path, options) => {
    const body = JSON.parse(options.body);
    if (path === '/yargiBirimleriSorgula_brd.ajx') return UNIT(body);
    if (path === '/search_phrase_detayli.ajx') return listPage(body.dosyaDurumKod === 0 ? 3 : 0, '', body);
    details.push(body.dosyaId);
    return response(path === '/list_dosya_evraklar.ajx' ? {son20Evrak:[]} : {ornek:true});
  };
  const first = await run('avukat.uyap.gov.tr', fetch, data => !data.captures.some(c => c.data?.dosyaId === '2'), saved);
  assert.equal(first.statuses.at(-1), 'sunucu_yok');
  assert.equal(saved.size, 2); // ilk dosyanın ana ve finans izi
  details.length = 0;
  const second = await run('avukat.uyap.gov.tr', fetch, true, saved);
  assert.equal(second.statuses.at(-1), 'tamamlandi');
  assert(!details.includes('1'));
  assert(details.includes('2'));
  assert.equal(saved.size, 0);
});

test('Açık ve kapalı dosyalar ayrı ayrı ve eksiksiz taranır', async () => {
  const result = await run('avukat.uyap.gov.tr', async (path, options) => {
    const body = JSON.parse(options.body);
    if (path === '/yargiBirimleriSorgula_brd.ajx') return UNIT(body);
    if (path === '/search_phrase_detayli.ajx') {
      assert.equal(body.pageSize, 10);
      return body.dosyaDurumKod === 0 ? listPage(15, 'a', body) : listPage(12, 'k', body);
    }
    return response(path === '/list_dosya_evraklar.ajx' ? {son20Evrak:[]} : {ornek:true});
  });
  const cases = result.uploads.filter(item => item.captures.length === 5);
  assert.equal(cases.length, 27);
  assert.equal(cases.filter(item => item.captures[0].data.durum === 'acik').length, 15);
  assert.equal(cases.filter(item => item.captures[0].data.durum === 'kapali').length, 12);
  assert.equal(result.statuses.at(-1), 'tamamlandi');
});

test('Erişilemeyen tek dosya diğer dosyaların aktarımını durdurmaz', async () => {
  const result = await run('avukat.uyap.gov.tr', async (path, options) => {
    const body = JSON.parse(options.body);
    if (path === '/yargiBirimleriSorgula_brd.ajx') return UNIT(body);
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
    if (path === '/yargiBirimleriSorgula_brd.ajx') return UNIT(body);
    if (path === '/search_phrase_detayli.ajx') return body.dosyaDurumKod === 0 ? listPage(1, 'a', body) : listPage(0, 'k', body);
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

test('Dosya türü kodu olmayan kayıtta finans yanıtı istenmez ve tarama eksik sayılır', async () => {
  const queries = [];
  const result = await run('avukat.uyap.gov.tr', async (path, options) => {
    const body = JSON.parse(options.body);
    queries.push(path);
    if (path === '/yargiBirimleriSorgula_brd.ajx') return UNIT(body);
    if (path === '/search_phrase_detayli.ajx') return response(body.dosyaDurumKod === 0 ? [[{dosyaId:'a',birimAdi:'Örnek',dosyaNo:'2026/1'}],1] : [[],0]);
    return response(path === '/list_dosya_evraklar.ajx' ? {son20Evrak:[]} : {ornek:true});
  });
  assert(!queries.includes('/dosya_tahsilat_reddiyat_bilgileri_brd.ajx'));
  assert.equal(result.statuses.at(-1), 'eksik');
});
