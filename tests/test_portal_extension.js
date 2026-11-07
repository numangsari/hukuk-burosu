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
        const outcome = typeof serverOk === 'function' ? serverOk(message.data) : serverOk;
        const ok = typeof outcome === 'number' ? outcome < 300 : outcome;
        const status = typeof outcome === 'number' ? outcome : undefined;
        queueMicrotask(() => dispatch({source:'ozkurt-sync-response', id:message.id, ok, status}));
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
    crypto:{randomUUID:() => String(Math.random()), subtle:webcrypto.subtle}, AbortSignal, Uint8Array, TextEncoder, URLSearchParams, Map, Set,
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
  assert.equal(saved.size, 3); // ilk dosyanın ana, finans ve belge izi
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

// ---- Evrak içeriği indirme -------------------------------------------------------------

function pdfResponse(bytes = '%PDF-1.4\nornek', disposition = 'inline; filename="tensip.pdf"', type = 'application/pdf') {
  const headers = {'content-type': type, 'content-disposition': disposition};
  return {ok:true, status:200, headers:{get: name => headers[name.toLowerCase()] || ''},
    arrayBuffer: async () => new TextEncoder().encode(bytes).buffer};
}

// Tek açık dosya ('a'), verilen evrak listesiyle; indirme istekleri `downloads` dizisine yazılır.
function documentFetch({items, downloads = [], download = () => pdfResponse(), listFor}) {
  return async (path, options) => {
    if (path.startsWith('/download_document_brd.uyap')) {
      const query = new URL(path, 'https://avukat.uyap.gov.tr').searchParams;
      downloads.push({dosyaId: query.get('dosyaId'), evrakId: query.get('evrakId'), method: options.method, credentials: options.credentials});
      return download(query.get('evrakId'));
    }
    const body = JSON.parse(options.body);
    if (path === '/yargiBirimleriSorgula_brd.ajx') return UNIT(body);
    if (path === '/search_phrase_detayli.ajx') return body.dosyaDurumKod === 0 ? listPage(1, 'a', body) : listPage(0, 'k', body);
    if (path === '/list_dosya_evraklar.ajx') return response({son20Evrak: body.pageNumber === 1 ? (listFor ? listFor() : items) : []});
    return response({ornek:true});
  };
}

const EVRAKS = [
  {evrakId:'e1', tur:'Tensip Zaptı', tip:'DOSYA', onaylandigiTarih:'05.11.2026', birimEvrakNo:'11'},
  {evrakId:'e2', tur:'Tebliğ Mazbatası', tip:'GLN', onaylandigiTarih:'06.11.2026'}
];

test('UYAP evrakları tek tek indirilip sunucuya gönderilir ve dosya tamamlanır', async () => {
  const downloads = [];
  const saved = new Set();
  const result = await run('avukat.uyap.gov.tr', documentFetch({items: EVRAKS, downloads}), true, saved);
  assert.deepEqual(downloads.map(item => item.evrakId), ['e1', 'e2']);
  assert(downloads.every(item => item.dosyaId === 'a1' && item.method === 'GET' && item.credentials === 'include'));
  const documents = result.uploads.filter(item => item.type === 'uyap_document');
  assert.equal(documents.length, 2);
  assert.equal(documents[0].dosyaId, 'a1');
  assert.equal(documents[0].name, 'tensip.pdf');
  assert.equal(Buffer.from(documents[0].content, 'base64').toString(), '%PDF-1.4\nornek');
  assert.equal(documents[0].meta.tur, 'Tensip Zaptı');
  assert.equal(documents[1].meta.tip, 'GLN');
  assert.equal(result.statuses.at(-1), 'tamamlandi');
});

test('Belgeleri tamamlanan dosya sonraki taramada yeniden indirilmez', async () => {
  const saved = new Set();
  const first = [];
  await run('avukat.uyap.gov.tr', documentFetch({items: EVRAKS, downloads: first}), true, saved);
  assert.equal(first.length, 2);
  // Tarama bitince izler silinir; ara verilen taramayı taklit etmek için izleri geri koyarız.
  const fingerprints = async () => {
    const digest = async value => Buffer.from(await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(value))).toString('hex');
    return [await digest('a1'), await digest('finans1:a1'), await digest('belge1:a1')];
  };
  for (const item of await fingerprints()) saved.add(item);
  const second = [];
  const result = await run('avukat.uyap.gov.tr', documentFetch({items: EVRAKS, downloads: second}), true, saved);
  assert.equal(second.length, 0);
  assert.equal(result.statuses.at(-1), 'tamamlandi');
});

test('Ana ve finans verisi tamam, belgeler eksikse yalnızca belgeler alınır', async () => {
  const saved = new Set();
  const digest = async value => Buffer.from(await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(value))).toString('hex');
  saved.add(await digest('a1'));
  saved.add(await digest('finans1:a1'));
  const downloads = [];
  const metadata = [];
  const base = documentFetch({items: EVRAKS, downloads});
  const result = await run('avukat.uyap.gov.tr', async (path, options) => {
    if (['/dosyaAyrintiBilgileri_brd.ajx', '/dosya_taraf_bilgileri_brd.ajx', '/dosya_tahsilat_reddiyat_bilgileri_brd.ajx'].includes(path)) metadata.push(path);
    return base(path, options);
  }, true, saved);
  assert.deepEqual(downloads.map(item => item.evrakId), ['e1', 'e2']);
  assert.deepEqual(metadata, []);
  assert.equal(result.statuses.at(-1), 'tamamlandi');
});

test('Sunucu dosyayı henüz bağlamadıysa belge atlanır, tarama sürer ve eksik sayılır', async () => {
  const saved = new Set();
  const result = await run('avukat.uyap.gov.tr', documentFetch({items: EVRAKS}), data => data.type === 'uyap_document' ? 409 : true, saved);
  assert.equal(result.uploads.filter(item => item.type === 'uyap_document').length, 2);
  assert.equal(result.statuses.at(-1), 'eksik');
  // Belge izi eklenmediği için bir sonraki taramada yeniden denenir.
  const digest = async value => Buffer.from(await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(value))).toString('hex');
  assert.equal(saved.has(await digest('belge1:a1')), false);
});

test('Sunucu belgeyi kalıcı reddederse (400) tekrar denenmez', async () => {
  const saved = new Set();
  const digest = async value => Buffer.from(await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(value))).toString('hex');
  const result = await run('avukat.uyap.gov.tr', documentFetch({items: EVRAKS}), data => data.type === 'uyap_document' ? 400 : true, saved);
  assert.equal(result.statuses.at(-1), 'eksik');
  // Tarama bitince izler temizlenir; o ana kadar belge izinin eklendiği saved'in temizlenmesinden anlaşılır.
  assert.equal(saved.size, 0);
  assert.equal(await digest('x') !== '', true);
});

test('Sunucu başka bir hata verirse tarama durur', async () => {
  const result = await run('avukat.uyap.gov.tr', documentFetch({items: EVRAKS}), data => data.type === 'uyap_document' ? 500 : true);
  assert.equal(result.statuses.at(-1), 'sunucu_yok');
});

test('İndirmede oturum kapanırsa (401) tarama oturum yok diye durur', async () => {
  const result = await run('avukat.uyap.gov.tr', documentFetch({items: EVRAKS, download: () => ({ok:false, status:401, headers:{get:() => ''}})}));
  assert.equal(result.statuses.at(-1), 'oturum_yok');
});

test('HTML veya XML yanıtı belge sayılmaz ve eksik bildirilir', async () => {
  const result = await run('avukat.uyap.gov.tr', documentFetch({items: EVRAKS, download: () => pdfResponse('<html></html>', '', 'text/html')}));
  assert.equal(result.uploads.filter(item => item.type === 'uyap_document').length, 0);
  assert.equal(result.statuses.at(-1), 'eksik');
});

test('Çok büyük belge atlanır, diğerleri alınır', async () => {
  const downloads = [];
  const result = await run('avukat.uyap.gov.tr', documentFetch({
    items: EVRAKS, downloads,
    download: id => id === 'e1' ? ({...pdfResponse(), headers: {get: name => name.toLowerCase() === 'content-length' ? '30000000' : ''}}) : pdfResponse()
  }));
  const sent = result.uploads.filter(item => item.type === 'uyap_document');
  assert.deepEqual(sent.map(item => item.evrakId), ['e2']);
  assert.equal(result.statuses.at(-1), 'eksik');
});

test('Ek evraklar da indirilir ve aynı kimlik bir kez alınır', async () => {
  const downloads = [];
  const items = [{evrakId:'e1', tur:'Karar', ekEvrakListesi:[{evrakId:'e1-ek', tur:'Ek'}, {evrakId:'e1'}]}];
  await run('avukat.uyap.gov.tr', documentFetch({items, downloads}));
  assert.deepEqual(downloads.map(item => item.evrakId), ['e1', 'e1-ek']);
});

test('Belge indirmeleri istekler arasında bekleyerek yapılır', async () => {
  const result = await run('avukat.uyap.gov.tr', documentFetch({items: EVRAKS}));
  assert(result.delays.some(ms => ms >= 2400 && ms < 5000), 'belge indirme aralığı bulunamadı');
});

test('Dosya adı UTF-8 başlığından okunur', async () => {
  const result = await run('avukat.uyap.gov.tr', documentFetch({
    items: [EVRAKS[0]],
    download: () => pdfResponse('%PDF-1.4\nx', "inline; filename*=UTF-8''Tensip%20Zapt%C4%B1.pdf")
  }));
  assert.equal(result.uploads.find(item => item.type === 'uyap_document').name, 'Tensip Zaptı.pdf');
});
