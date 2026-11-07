(() => {
  const nativeFetch = window.fetch.bind(window);
  let running = false;
  const status = (state, extra = {}) => window.postMessage({source: 'ozkurt-scan-status', state, ...extra}, location.origin);
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const verify = () => new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const timer = setTimeout(() => { window.removeEventListener('message', onReply); reject(new Error('izin')); }, 10000);
    function onReply(event) {
      if (event.source !== window || event.origin !== location.origin || event.data?.source !== 'ozkurt-verify-response' || event.data.id !== id) return;
      clearTimeout(timer); window.removeEventListener('message', onReply);
      event.data.ok ? resolve() : reject(new Error('izin'));
    }
    window.addEventListener('message', onReply);
    window.postMessage({source:'ozkurt-verify', id}, location.origin);
  });

  const send = data => new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const timer = setTimeout(() => { window.removeEventListener('message', onReply); reject(new Error('sunucu')); }, 135000);
    function onReply(event) {
      if (event.source !== window || event.origin !== location.origin || event.data?.source !== 'ozkurt-sync-response' || event.data.id !== id) return;
      clearTimeout(timer);
      window.removeEventListener('message', onReply);
      event.data.ok ? resolve() : reject(Object.assign(new Error('sunucu'), {status: event.data.status}));
    }
    window.addEventListener('message', onReply);
    window.postMessage({source: 'ozkurt-sync', id, data}, location.origin);
  });
  const checkpoint = (action, fingerprint) => new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const timer = setTimeout(() => { window.removeEventListener('message', onReply); reject(new Error('sunucu')); }, 30000);
    function onReply(event) {
      if (event.source !== window || event.origin !== location.origin || event.data?.source !== 'ozkurt-checkpoint-response' || event.data.id !== id) return;
      clearTimeout(timer);
      window.removeEventListener('message', onReply);
      event.data.ok ? resolve(event.data.fingerprints || []) : reject(new Error('sunucu'));
    }
    window.addEventListener('message', onReply);
    window.postMessage({source:'ozkurt-checkpoint', id, action, fingerprint}, location.origin);
  });
  const fingerprint = async value => {
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return [...new Uint8Array(bytes)].map(byte => byte.toString(16).padStart(2, '0')).join('');
  };
  const jsonResponse = async response => {
    if (response.status === 401) throw new Error('oturum');
    if (response.status === 403) throw new Error('yetki');
    if (!response.ok) throw new Error('yanit');
    if (/text\/html/i.test(response.headers?.get('content-type') || '')) throw new Error('oturum');
    const value = await response.json();
    if (!value || typeof value !== 'object' || value.error || value.errorCode) throw new Error('yanit');
    return value;
  };
  async function scanUets() {
    const accessToken = localStorage.getItem('accessToken');
    if (!accessToken) throw new Error('oturum');
    const get = async path => { await verify(); return nativeFetch('https://api.etebligat.gov.tr/v1' + path, {
      method: 'GET', credentials: 'omit', headers: {Authorization: `Bearer ${accessToken}`}, signal: AbortSignal.timeout(60000)
    }); };
    let partial = false;
    const seen = new Set();
    for (let page = 0; page < 2000; page++) {
      let rows;
      try { rows = await jsonResponse(await get(`/messages?sort=inserttime&count=50&start=${page * 50}`)); }
      catch (error) { if (error.message === 'yetki') throw new Error('oturum'); throw error; }
      if (!Array.isArray(rows)) throw new Error('yanit');
      let newCount = 0;
      for (const row of rows) {
        const id = row?.id || row?.messages_id;
        if (!id) { partial = true; continue; }
        if (seen.has(String(id))) continue;
        seen.add(String(id)); newCount++; status('basladi', {processed: seen.size});
        let details;
        try { details = await jsonResponse(await get('/messages/' + encodeURIComponent(String(id)) + '?eyp_details=true')); }
        catch (error) { if (['oturum', 'izin'].includes(error.message)) throw error; partial = true; continue; }
        await send({type: 'notice', list: row, details});
        if (!details.eyp_details || typeof details.eyp_details !== 'object') partial = true;
        const parts = new Map();
        const walk = (value, depth = 0, inAttachments = false) => {
          if (!value || typeof value !== 'object' || depth > 20) return;
          if (Array.isArray(value)) { value.forEach(item => walk(item, depth + 1, inAttachments)); return; }
          const id = value.BelgeId ?? (inAttachments ? value.Id : null);
          if (id != null && String(id).length <= 256) parts.set(String(id), String(value.DosyaAdi || value.BelgeAdi || ''));
          for (const [key, item] of Object.entries(value)) walk(item, depth + 1, inAttachments || key === 'Ekler');
        };
        walk(details.eyp_details);
        if (parts.size > 100) { partial = true; continue; }
        for (const [partId, name] of parts) {
          try {
            const response = await get('/messages/' + encodeURIComponent(String(id)) + '/parts/' + encodeURIComponent(partId) + '/_download');
            if (response.status === 401) throw new Error('oturum');
            if (!response.ok || /text\/html/i.test(response.headers.get('content-type') || '')) throw new Error('yanit');
            const length = Number(response.headers.get('content-length') || 0);
            if (length > 20000000) throw new Error('boyut');
            const bytes = new Uint8Array(await response.arrayBuffer());
            if (!bytes.length || bytes.length > 20000000) throw new Error('boyut');
            let binary = '';
            for (let start = 0; start < bytes.length; start += 32768) binary += String.fromCharCode(...bytes.subarray(start, start + 32768));
            await send({type: 'notice', list: row, details, document: {partId, name, content: btoa(binary)}});
          } catch (error) { if (['sunucu', 'oturum', 'izin'].includes(error.message)) throw error; partial = true; }
          await wait(150);
        }
      }
      if (rows.length < 50) return partial;
      if (!newCount) return true;
    }
    return true;
  }
  async function scanUyap() {
    let lastRequest = 0;
    const post = async (path, body) => {
      await verify();
      const delay = 5000 - (Date.now() - lastRequest);
      if (delay > 0) await wait(delay);
      await verify();
      lastRequest = Date.now();
      return jsonResponse(await nativeFetch(path, {
        method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), signal: AbortSignal.timeout(60000)
      }));
    };
    const DOCUMENT_DELAY = 2500;
    const MAX_DOCUMENT_BYTES = 20000000;
    const evrakList = async caseId => {
      const items = [];
      const pages = new Set();
      for (let page = 1; page <= 2000; page++) {
        const data = await post('/list_dosya_evraklar.ajx', {dosyaId: caseId, pageNumber: page});
        if (!data || !Array.isArray(data.son20Evrak)) throw new Error('yanit');
        const signature = JSON.stringify(data.son20Evrak);
        if (data.son20Evrak.length && pages.has(signature)) throw new Error('yanit');
        pages.add(signature);
        items.push(...data.son20Evrak);
        if (data.son20Evrak.length < 20) break;
        await wait(150);
      }
      return items;
    };
    // Evrak ve varsa ek evraklar; her biri ayrı indirilir.
    const evrakEntries = items => {
      const entries = [];
      for (const item of items) {
        if (!item || typeof item !== 'object') continue;
        const meta = value => String(value ?? '').slice(0, 120);
        if (item.evrakId != null && String(item.evrakId)) {
          entries.push({id: String(item.evrakId), meta: {tur: meta(item.tur), tip: meta(item.tip), onaylandigiTarih: meta(item.onaylandigiTarih), birimEvrakNo: meta(item.birimEvrakNo)}});
        }
        if (Array.isArray(item.ekEvrakListesi)) {
          for (const extra of item.ekEvrakListesi) {
            if (extra && typeof extra === 'object' && extra.evrakId != null && String(extra.evrakId)) {
              entries.push({id: String(extra.evrakId), meta: {tur: meta(extra.tur || ('Ek: ' + (item.tur || ''))), tip: meta(extra.tip || item.tip), onaylandigiTarih: meta(extra.onaylandigiTarih || item.onaylandigiTarih), birimEvrakNo: meta(item.birimEvrakNo)}});
            }
          }
        }
      }
      return [...new Map(entries.map(entry => [entry.id, entry])).values()];
    };
    const documentName = disposition => {
      const encoded = /filename\*=(?:UTF-8|utf-8)''([^;]+)/.exec(disposition || '');
      if (encoded) { try { return decodeURIComponent(encoded[1]).slice(0, 200); } catch (_) { /* düz ada düş */ } }
      const plain = /filename="?([^";]+)"?/i.exec(disposition || '');
      return plain ? plain[1].slice(0, 200) : '';
    };
    const downloadDocument = async (caseId, evrakId) => {
      await verify();
      const delay = DOCUMENT_DELAY - (Date.now() - lastRequest);
      if (delay > 0) await wait(delay);
      await verify();
      lastRequest = Date.now();
      const response = await nativeFetch('/download_document_brd.uyap?' + new URLSearchParams({dosyaId: caseId, evrakId}).toString(), {
        method: 'GET', credentials: 'include', signal: AbortSignal.timeout(120000)
      });
      if (response.status === 401) throw new Error('oturum');
      if (!response.ok) throw new Error('yanit');
      if (/text\/(html|xml)/i.test(response.headers.get('content-type') || '')) throw new Error('yanit');
      if (Number(response.headers.get('content-length') || 0) > MAX_DOCUMENT_BYTES) throw new Error('boyut');
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (!bytes.length || bytes.length > MAX_DOCUMENT_BYTES) throw new Error('boyut');
      let binary = '';
      for (let start = 0; start < bytes.length; start += 32768) binary += String.fromCharCode(...bytes.subarray(start, start + 32768));
      return {name: documentName(response.headers.get('content-disposition')), content: btoa(binary)};
    };
    const categories = [{name:'Ceza', code:'0'}, {name:'Hukuk', code:'1'}, {name:'İcra', code:'2'}, {name:'İdari Yargı', code:'6'}, {name:'Satış Memurluğu', code:'11'}, {name:'Arabuluculuk', code:'25'}];
    const paths = ['/dosyaAyrintiBilgileri_brd.ajx', '/dosya_taraf_bilgileri_brd.ajx', '/list_dosya_evraklar.ajx'];
    let partial = false;
    const seenCases = new Set();
    const completedCases = new Set(await checkpoint('get'));
    for (const category of categories) {
      const sampleCounts = {acik:0, kapali:0};
      let units;
      try { units = await post('/yargiBirimleriSorgula_brd.ajx', {yargiTuru: category.code}); }
      catch (error) { if (error.message === 'izin') throw error; if (error.message === 'oturum' || error.message === 'yetki') throw new Error('oturum'); partial = true; continue; }
      if (!Array.isArray(units)) { partial = true; continue; }
      const seenUnits = new Set();
      for (const unit of units) {
        if (unit?.tablo == null || seenUnits.has(String(unit.tablo))) continue;
        seenUnits.add(String(unit.tablo));
        for (const state of ['acik', 'kapali']) {
          
          const seenPages = new Set();
          for (let page = 1; page <= 2000; page++) {
            let result;
            try { result = await post('/search_phrase_detayli.ajx', {dosyaDurumKod: state === 'acik' ? 0 : 1, pageSize: 10, pageNumber: page, birimTuru2: unit.tablo, birimTuru3: category.code}); }
            catch (error) { if (['oturum', 'izin'].includes(error.message)) throw error; partial = true; break; }
            if (!Array.isArray(result) || !Array.isArray(result[0]) || !Number.isInteger(result[1])) { partial = true; break; }
            const pageRows = result[0];
            const signature = pageRows.map(row => String(row?.dosyaId || '')).join('|');
            if (pageRows.length && seenPages.has(signature)) { partial = true; break; }
            seenPages.add(signature);
            const rows = [];
            for (const row of pageRows) {
              if (typeof row?.dosyaId !== 'string' || !row.dosyaId) { partial = true; continue; }
              if (seenCases.has(row.dosyaId) || rows.some(item => item.dosyaId === row.dosyaId)) continue;
              rows.push(row);
              
            }
            if (rows.length) {
              const capture = {source:'UYAP', path:'/search_phrase_detayli.ajx', data:{kategori:category.name, birim:unit.kod, durum:state, sonuc:[rows, result[1]]}};
              await send({type:'uyap', captures:[capture]});
            }
            for (const row of rows) {
              const caseId = row?.dosyaId;
              seenCases.add(caseId);
              sampleCounts[state]++;
              const caseFingerprint = await fingerprint(caseId);
              const financeFingerprint = await fingerprint('finans1:' + caseId);
              const mainDone = completedCases.has(caseFingerprint);
              const financeDone = completedCases.has(financeFingerprint);
              const docsFingerprint = await fingerprint('belge1:' + caseId);
              const docsDone = completedCases.has(docsFingerprint);
              if (mainDone && financeDone && docsDone) continue;
              let evrakItems = null;
              let caseComplete = true; status('basladi', {total: result[1] || 0, processed: seenCases.size, currentFile: row?.dosyaNo || ''});
              const itemList = {source:'UYAP', path:'/search_phrase_detayli.ajx', data:{kategori:category.name, birim:unit.kod, durum:state, sonuc:[[row], 1]}};
              let captures = [itemList];
              const casePaths = [...paths];
              if (category.name === 'İcra') casePaths.push('/dosya_hesap_bilgileri.ajx');
              for (const path of (mainDone ? [] : casePaths)) {
                try {
                  const body = {dosyaId: caseId};
                  if (path === '/list_dosya_evraklar.ajx') {
                    const documentPages = new Set();
                    evrakItems = [];
                    for (let documentPage = 1; documentPage <= 2000; documentPage++) {
                      const data = await post(path, {...body, pageNumber:documentPage});
                      if (!data || !Array.isArray(data.son20Evrak)) { partial = true; caseComplete = false; evrakItems = null; break; }
                      const signature = JSON.stringify(data.son20Evrak);
                      if (data.son20Evrak.length && documentPages.has(signature)) { partial = true; caseComplete = false; evrakItems = null; break; }
                      documentPages.add(signature);
                      evrakItems.push(...data.son20Evrak);
                      captures.push({source:'UYAP', path, data:{kategori:category.name, durum:state, dosyaId:caseId, sonuc:data}});
                      if (captures.length >= 90) { await send({type:'uyap', captures}); captures = [itemList]; }
                      if (data.son20Evrak.length < 20) break;
                      if (documentPage === 2000) { partial = true; caseComplete = false; }
                      await wait(150);
                    }
                  } else {
                    const data = await post(path, body);
                    captures.push({source:'UYAP', path, data:{kategori:category.name, durum:state, dosyaId:caseId, sonuc:data}});
                  }
                } catch (error) {
                  if (['oturum', 'sunucu', 'izin'].includes(error.message)) throw error;
                  // Ceza dosyalarında /dosyaAyrintiBilgileri_brd.ajx bazen UYAP yetki yanıtı (error) döner;
                  // HTTP 200 ile gelen bu yanıt diğer uç noktaların tamamlanmasını engellememeli.
                  if (!(category.name === 'Ceza' && path === '/dosyaAyrintiBilgileri_brd.ajx' && error.message === 'yanit')) {
                    partial = true; caseComplete = false;
                  }
                }
                await wait(150);
              }
              let financeComplete = true;
              if (!financeDone) {
                // Tahsilat/reddiyat/harç yanıtı tüm dosya türleri için istenir; ödeyen ve tür ayrımı sunucuda yapılır.
                const financePath = '/dosya_tahsilat_reddiyat_bilgileri_brd.ajx';
                if (Number.isInteger(row?.dosyaTurKod)) {
                  try {
                    const data = await post(financePath, {dosyaId: caseId, dosyaTurKod: row.dosyaTurKod});
                    captures.push({source:'UYAP', path:financePath, data:{kategori:category.name, durum:state, dosyaId:caseId, sonuc:data}});
                  } catch (error) { if (['oturum', 'sunucu', 'izin'].includes(error.message)) throw error; partial = true; financeComplete = false; }
                  await wait(150);
                } else { partial = true; financeComplete = false; }
              }
              await send({type:'uyap', captures});
              if (caseComplete && !mainDone) { await checkpoint('add', caseFingerprint); completedCases.add(caseFingerprint); }
              if (financeComplete && !financeDone) { await checkpoint('add', financeFingerprint); completedCases.add(financeFingerprint); }
              if (!docsDone) {
                let items = caseComplete && evrakItems ? evrakItems : null;
                if (!items) {
                  try { items = await evrakList(caseId); }
                  catch (error) { if (['oturum', 'izin'].includes(error.message)) throw error; partial = true; items = null; }
                }
                if (items) {
                  let docsComplete = true;
                  for (const entry of evrakEntries(items)) {
                    try {
                      const file = await downloadDocument(caseId, entry.id);
                      await send({type:'uyap_document', dosyaId:caseId, evrakId:entry.id, meta:entry.meta, name:file.name, content:file.content});
                    } catch (error) {
                      if (['oturum', 'izin'].includes(error.message)) throw error;
                      if (error.message === 'sunucu' && ![400, 403, 404, 409].includes(error.status)) throw error;
                      partial = true;
                      // Sunucu belgeyi kalıcı reddetti (geçersiz/çok büyük): tekrar denemek yararsız.
                      if (!(error.message === 'boyut' || (error.message === 'sunucu' && error.status === 400))) docsComplete = false;
                    }
                    await wait(150);
                  }
                  if (docsComplete) { await checkpoint('add', docsFingerprint); completedCases.add(docsFingerprint); }
                }
              }
            }
            if (page * 10 >= result[1]) break;
            if (!pageRows.length || page === 2000) { partial = true; break; }
          }
        }
      }
    }
    await checkpoint('clear');
    return partial;
  }
  window.addEventListener('message', async event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.source !== 'ozkurt-auto' || event.data.action !== 'scan' || running || window.top !== window) return;
    running = true;
    status('basladi');
    try {
      const partial = location.hostname === 'ptt.etebligat.gov.tr' ? await scanUets() : await scanUyap();
      status(partial ? 'eksik' : 'tamamlandi');
    } catch (error) { status(error.message === 'oturum' ? 'oturum_yok' : error.message === 'sunucu' ? 'sunucu_yok' : error.message === 'izin' ? 'izin_yok' : 'eksik'); }
    finally { running = false; }
  });
})();
