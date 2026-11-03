(() => {
  const eligible = (raw) => {
    try {
      const url = new URL(raw, location.href);
      const uetsList = location.hostname.endsWith('.etebligat.gov.tr') && url.origin === 'https://api.etebligat.gov.tr' && url.pathname === '/v1/messages';
      if (uetsList) return true;
      if (url.origin !== location.origin) return false;
      if (/login|logout|auth|token|session|sifre|password|giris|nats/i.test(url.pathname)) return false;
      return location.hostname.endsWith('uyap.gov.tr')
        ? /\.ajx$/i.test(url.pathname)
        : /\/api\//i.test(url.pathname);
    } catch { return false; }
  };
  const send = (raw, data) => {
    if (!eligible(raw) || typeof data !== 'object' || data === null) return;
    const url = new URL(raw, location.href);
    window.postMessage({ source: 'ozkurt-observer', path: url.pathname, data }, location.origin);
  };
  const originalFetch = window.fetch;
  let noticeSampleRunning = false;
  const diagnose = (raw, method, response) => {
    try {
      const url = new URL(raw, location.href);
      if (location.hostname !== 'ptt.etebligat.gov.tr' || url.hostname !== 'api.etebligat.gov.tr') return;
      if (/login|logout|auth|token|session|sifre|password|giris/i.test(url.pathname)) return;
      const safeParts = new Set(['v1', 'v2', 'messages', 'message', 'attachments', 'attachment', 'documents', 'document', 'download', '_download', 'evidence', 'file', 'files', 'content', 'read', 'detail', 'details', 'folders', 'inbox']);
      const path = url.pathname.split('/').map(part => safeParts.has(part.toLowerCase()) ? part.toLowerCase() : (part ? '{değer}' : '')).join('/');
      window.postMessage({source: 'ozkurt-diagnostic', path, method: String(method || 'GET').toUpperCase(), status: response.status, contentType: (response.headers?.get('content-type') || '').split(';')[0]}, location.origin);
    } catch {}
  };
  window.addEventListener('message', async event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.source !== 'ozkurt-request') return;
    const uyap = ['avukat.uyap.gov.tr', 'avukatbeta.uyap.gov.tr'].includes(location.hostname);
    const uets = location.hostname === 'ptt.etebligat.gov.tr';
    if (event.data.action === 'notice_sample') {
      if (!uets || window.top !== window || noticeSampleRunning) return;
      noticeSampleRunning = true;
      try {
        const accessToken = localStorage.getItem('accessToken');
        if (!accessToken) throw new Error('Oturum bulunamadı');
        const get = async path => {
          const response = await originalFetch.call(window, 'https://api.etebligat.gov.tr/v1' + path, {method: 'GET', credentials: 'omit', headers: {Authorization: `Bearer ${accessToken}`}});
          if (!response.ok) throw new Error(`Yanıt kodu: ${response.status}`);
          return response;
        };
        const rows = await (await get('/messages?sort=inserttime&folders_id=1&count=50')).json();
        if (!Array.isArray(rows)) throw new Error('Liste alınamadı');
        const selected = rows.find(item => item && item.status === 'read' && (item.id || item.messages_id));
        if (!selected) throw new Error('Açılmış tebligat bulunamadı');
        const id = String(selected.id || selected.messages_id);
        const details = await (await get('/messages/' + encodeURIComponent(id) + '?eyp_details=true')).json();
        const partIds = new Set();
        const walk = (value, depth = 0, inAttachments = false) => {
          if (depth > 20 || !value || typeof value !== 'object') return;
          if (Array.isArray(value)) { value.forEach(item => walk(item, depth + 1, inAttachments)); return; }
          if (value.BelgeId != null) partIds.add(String(value.BelgeId));
          if (inAttachments && value.Id != null) partIds.add(String(value.Id));
          for (const [key, item] of Object.entries(value)) walk(item, depth + 1, inAttachments || key === 'Ekler');
        };
        walk(details?.eyp_details);
        if (partIds.size > 30) throw new Error('Belge sayısı sınırı aşıldı');
        const files = [];
        const downloads = [];
        for (const partId of partIds) {
          if (!partId || partId.length > 256) continue;
          const response = await get('/messages/' + encodeURIComponent(id) + '/parts/' + encodeURIComponent(partId) + '/_download');
          const bytes = new Uint8Array(await response.arrayBuffer());
          if (bytes.length > 20_000_000) throw new Error('Belge boyutu sınırı aşıldı');
          const pdf = bytes.length >= 5 && bytes[0] === 37 && bytes[1] === 80 && bytes[2] === 68 && bytes[3] === 70 && bytes[4] === 45;
          downloads.push({bytes, pdf});
          let binary = '';
          for (let start = 0; start < bytes.length; start += 32768) binary += String.fromCharCode(...bytes.subarray(start, start + 32768));
          files.push({partId, contentType: (response.headers.get('content-type') || '').split(';')[0], content: btoa(binary)});
        }
        const hidden = /token|password|passwd|sifre|şifre|parola|secret|authorization|cookie|session|credential|otp|guvenlik.?kodu|güvenlik.?kodu|dogrulama|doğrulama|verification.?code|^pass$/i;
        const clean = value => Array.isArray(value) ? value.map(clean) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).filter(([key]) => !hidden.test(key)).map(([key, item]) => [key, clean(item)])) : value;
        const bundle = {source: 'UETS', list: clean(selected), details: clean(details), files};
        const download = (blob, name) => {
          const blobUrl = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = blobUrl;
          link.download = name;
          document.body.appendChild(link);
          link.click();
          link.remove();
          setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
        };
        download(new Blob([JSON.stringify(bundle)], {type: 'application/json'}), 'uets-ornek-tebligat.json');
        downloads.forEach((item, index) => download(new Blob([item.bytes], {type: item.pdf ? 'application/pdf' : 'application/octet-stream'}), `uets-ornek-belge-${index + 1}.${item.pdf ? 'pdf' : 'bin'}`));
        window.postMessage({source: 'ozkurt-result', ok: true}, location.origin);
      } catch (error) {
        const message = /^(Oturum bulunamadı|Açılmış tebligat bulunamadı|Liste alınamadı|Belge sayısı sınırı aşıldı|Belge boyutu sınırı aşıldı|Yanıt kodu: \d{3})$/.test(error.message) ? error.message : 'Bağlantı veya yanıt hatası';
        window.postMessage({source: 'ozkurt-result', ok: false, error: message}, location.origin);
      } finally {
        noticeSampleRunning = false;
      }
      return;
    }
    if (event.data.action === 'appeal_lists') {
      if (!uyap) return;
      const diagnostics = [];
      const post = async (path, body) => {
        const response = await originalFetch.call(window, path, {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
        if (!response.ok) throw new Error('http');
        const value = await response.json();
        if (!value || typeof value !== 'object' || value.error || value.errorCode) throw new Error('response');
        return value;
      };
      for (const category of [{name:'Ceza', code:'0'}, {name:'Hukuk', code:'1'}]) {
        try {
          const units = await post('/yargiBirimleriSorgula_brd.ajx', {yargiTuru:category.code});
          const matched = Array.isArray(units) ? units.filter(unit => unit?.tablo != null && /bölge adliye|istinaf/.test(String(unit.kod || '').toLocaleLowerCase('tr-TR'))).slice(0, 10) : [];
          if (!matched.length) { diagnostics.push({category:category.name, result:'birim_bulunamadi'}); continue; }
          for (const unit of matched) for (const state of ['acik', 'kapali']) {
            try {
              const body = {dosyaDurumKod:state === 'acik' ? 0 : 1, pageSize:50, pageNumber:1, birimTuru2:unit.tablo, birimTuru3:category.code};
              const data = await post('/search_phrase_detayli.ajx', body);
              if (!Array.isArray(data) || !Array.isArray(data[0])) { diagnostics.push({category:category.name, unit:unit.kod, state, result:'liste_alinamadi'}); continue; }
              send('/search_phrase_detayli.ajx', {kategori:category.name, birim:unit.kod, durum:state, inceleme:'istinaf', sonuc:data});
              diagnostics.push({category:category.name, unit:unit.kod, state, result:'ok'});
            } catch { diagnostics.push({category:category.name, unit:unit.kod, state, result:'sorgu_basarisiz'}); }
          }
        } catch { diagnostics.push({category:category.name, result:'sorgu_basarisiz'}); }
      }
      send('/istinaf-tani.ajx', diagnostics);
      window.postMessage({source:'ozkurt-result', ok:diagnostics.some(item => item.result === 'ok')}, location.origin);
      return;
    }
    if (event.data.action === 'deep_metadata') {
      if (!uyap || !Array.isArray(event.data.examples)) return;
      const diagnostics = [];
      const financeStates = new Set();
      for (const example of event.data.examples.slice(0, 36)) {
        if (!['Ceza', 'Hukuk', 'İcra', 'İdari Yargı', 'Satış Memurluğu', 'Arabuluculuk'].includes(example.category) || !['acik', 'kapali'].includes(example.state) || typeof example.caseId !== 'string' || !example.caseId || example.caseId.length > 256) continue;
        const paths = ['/dosyaAyrintiBilgileri_brd.ajx'];
        if (example.category === 'İcra' && !financeStates.has(example.state) && Number.isInteger(example.caseType)) {
          financeStates.add(example.state);
          paths.push('/dosya_tahsilat_reddiyat_bilgileri_brd.ajx', '/dosya_hesap_bilgileri.ajx');
        }
        for (const path of paths) {
          try {
            const body = {dosyaId: example.caseId};
            if (path === '/dosya_tahsilat_reddiyat_bilgileri_brd.ajx') body.dosyaTurKod = example.caseType;
            const response = await originalFetch.call(window, path, {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
            if (!response.ok) { diagnostics.push({category: example.category, state: example.state, path, result: 'http_error'}); continue; }
            const data = await response.json();
            if (!data || typeof data !== 'object' || data.error || data.errorCode) { diagnostics.push({category: example.category, state: example.state, path, result: 'response_error'}); continue; }
            send(path, {kategori: example.category, durum: example.state, dosyaId: example.caseId, sonuc: data, inceleme: 'derin'});
            diagnostics.push({category: example.category, state: example.state, path, result: 'ok'});
          } catch { diagnostics.push({category: example.category, state: example.state, path, result: 'connection_or_format_error'}); }
        }
      }
      send('/derin-inceleme-tani.ajx', diagnostics);
      window.postMessage({source: 'ozkurt-result', ok: diagnostics.some(item => item.result === 'ok')}, location.origin);
      return;
    }
    if (event.data.action === 'closed_case_types') {
      if (!uyap) return;
      const diagnostics = [];
      const categories = [{name: 'Ceza', code: '0'}, {name: 'Hukuk', code: '1'}, {name: 'İcra', code: '2'}, {name: 'İdari Yargı', code: '6'}, {name: 'Satış Memurluğu', code: '11'}, {name: 'Arabuluculuk', code: '25'}];
      const post = async (path, body) => {
        const response = await originalFetch.call(window, path, {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
        if (!response.ok) throw new Error('http');
        const value = await response.json();
        if (!value || typeof value !== 'object' || value.error || value.errorCode) throw new Error('response');
        return value;
      };
      for (const category of categories) {
        try {
          const units = await post('/yargiBirimleriSorgula_brd.ajx', {yargiTuru: category.code});
          const first = Array.isArray(units) && units.find(unit => unit && unit.tablo != null);
          if (!first) { diagnostics.push({category: category.name, result: 'birim_bulunamadi'}); continue; }
          const list = await post('/search_phrase_detayli.ajx', {dosyaDurumKod: 1, pageSize: 50, pageNumber: 1, birimTuru2: first.tablo, birimTuru3: category.code});
          if (!Array.isArray(list) || !Array.isArray(list[0])) { diagnostics.push({category: category.name, result: 'liste_alinamadi'}); continue; }
          send('/search_phrase_detayli.ajx', {kategori: category.name, birim: first.kod, durum: 'kapali', sonuc: list});
          diagnostics.push({category: category.name, result: 'liste_ok'});
          const selected = list[0].find(item => typeof item?.dosyaId === 'string' && item.dosyaId.length > 0 && item.dosyaId.length <= 256);
          if (!selected) continue;
          for (const path of ['/dosyaAyrintiBilgileri_brd.ajx', '/dosya_taraf_bilgileri_brd.ajx', '/list_dosya_evraklar.ajx']) {
            try {
              const body = {dosyaId: selected.dosyaId};
              if (path === '/list_dosya_evraklar.ajx') body.pageNumber = 1;
              const data = await post(path, body);
              send(path, {kategori: category.name, durum: 'kapali', dosyaId: selected.dosyaId, sonuc: data});
              diagnostics.push({category: category.name, path, result: 'ok'});
            } catch { diagnostics.push({category: category.name, path, result: 'sorgu_basarisiz'}); }
          }
        } catch { diagnostics.push({category: category.name, result: 'sorgu_basarisiz'}); }
      }
      send('/kapali-dosya-tani.ajx', diagnostics);
      window.postMessage({source: 'ozkurt-result', ok: diagnostics.some(item => item.result === 'liste_ok')}, location.origin);
      return;
    }
    if (event.data.action === 'type_examples') {
      if (!uyap || !Array.isArray(event.data.examples)) return;
      const diagnostics = [];
      for (const example of event.data.examples.slice(0, 4)) {
        if (!['Ceza', 'Hukuk', 'İcra', 'İdari Yargı'].includes(example.category) || typeof example.caseId !== 'string' || !example.caseId || example.caseId.length > 256) continue;
        for (const path of ['/dosyaAyrintiBilgileri_brd.ajx', '/dosya_taraf_bilgileri_brd.ajx']) {
          try {
            const response = await originalFetch.call(window, path, {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({dosyaId: example.caseId})});
            if (!response.ok) { diagnostics.push({category: example.category, path, status: response.status, result: 'http_error'}); continue; }
            const data = await response.json();
            if (!data || typeof data !== 'object' || data.error || data.errorCode) {
              const error = typeof data?.error === 'string' ? data.error : '';
              const reason = /yetki|erişim|erisim|izin/i.test(error) ? 'yetki' : /oturum|giriş|giris/i.test(error) ? 'oturum' : 'belirsiz';
              diagnostics.push({category: example.category, path, status: response.status, result: 'response_error', reason});
              continue;
            }
            send(response.url || path, {kategori: example.category, dosyaId: example.caseId, sonuc: data});
            diagnostics.push({category: example.category, path, status: response.status, result: 'ok'});
          } catch { diagnostics.push({category: example.category, path, result: 'connection_or_format_error'}); }
        }
      }
      send('/dosya-ornekleri-tani.ajx', diagnostics);
      window.postMessage({source: 'ozkurt-result', ok: diagnostics.some(item => item.result === 'ok')}, location.origin);
      return;
    }
    if (event.data.action === 'case_types') {
      if (!uyap) return;
      const diagnostics = [];
      const categories = [{name: 'Ceza', code: '0'}, {name: 'Hukuk', code: '1'}, {name: 'İcra', code: '2'}, {name: 'İdari Yargı', code: '6'}, {name: 'Satış Memurluğu', code: '11'}, {name: 'Arabuluculuk', code: '25'}];
      for (const category of categories) {
        try {
          const post = async (path, body) => {
            const response = await originalFetch.call(window, path, {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
            if (!response.ok) throw new Error('http');
            return response.json();
          };
          const units = await post('/yargiBirimleriSorgula_brd.ajx', {yargiTuru: category.code});
          if (!Array.isArray(units) || !units.length) { diagnostics.push({category: category.name, result: 'birim_bulunamadi'}); continue; }
          const first = units.find(unit => unit && unit.tablo != null);
          if (!first) { diagnostics.push({category: category.name, result: 'birim_kodu_bulunamadi'}); continue; }
          const body = {dosyaDurumKod: 0, pageSize: 50, pageNumber: 1, birimTuru2: first.tablo, birimTuru3: category.code};
          const data = await post('/search_phrase_detayli.ajx', body);
          if (!Array.isArray(data)) { diagnostics.push({category: category.name, result: 'liste_alinamadi'}); continue; }
          send('/search_phrase_detayli.ajx', {kategori: category.name, birim: first.kod, sonuc: data});
          diagnostics.push({category: category.name, result: 'ok'});
        } catch { diagnostics.push({category: category.name, result: 'sorgu_basarisiz'}); }
      }
      send('/dosya-turleri-tani.ajx', diagnostics);
      window.postMessage({source: 'ozkurt-result', ok: diagnostics.some(item => item.result === 'ok')}, location.origin);
      return;
    }
    if (event.data.action === 'case_example') {
      if (!uyap || typeof event.data.caseId !== 'string' || !event.data.caseId || event.data.caseId.length > 256) return;
      const diagnostics = [];
      for (const path of ['/dosyaAyrintiBilgileri_brd.ajx', '/dosya_taraf_bilgileri_brd.ajx']) {
        try {
          const response = await originalFetch.call(window, path, {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({dosyaId: event.data.caseId})});
          if (!response.ok) { diagnostics.push({path, status: response.status, result: 'http_error'}); continue; }
          const data = await response.json();
          if (!data || typeof data !== 'object' || data.error || data.errorCode) {
            diagnostics.push({path, status: response.status, result: 'response_error', errorCode: /^\d{1,6}$/.test(String(data?.errorCode)) ? String(data.errorCode) : null, valueType: typeof data, fields: data && !Array.isArray(data) && typeof data === 'object' ? Object.keys(data).slice(0, 30) : []});
            continue;
          }
          send(response.url || path, {dosyaId: event.data.caseId, sonuc: data});
          diagnostics.push({path, status: response.status, result: 'ok'});
        } catch {
          diagnostics.push({path, result: 'connection_or_format_error'});
        }
      }
      if ([event.data.unitId, event.data.unitType, event.data.jurisdiction].every(value => typeof value === 'string' && value.length > 0 && value.length <= 256)) {
        const path = '/search_phrase_detayli.ajx';
        try {
          const body = {dosyaDurumKod: 0, pageSize: 50, pageNumber: 1, birimId: event.data.unitId, birimTuru2: event.data.unitType, birimTuru3: event.data.jurisdiction};
          const response = await originalFetch.call(window, path, {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
          if (!response.ok) diagnostics.push({path, status: response.status, result: 'http_error'});
          else {
            const data = await response.json();
            if (!data || typeof data !== 'object' || data.error || data.errorCode) diagnostics.push({path, status: response.status, result: 'response_error'});
            else { send(response.url || path, data); diagnostics.push({path, status: response.status, result: 'ok'}); }
          }
        } catch { diagnostics.push({path, result: 'connection_or_format_error'}); }
      }
      send('/dosya-tani.ajx', diagnostics);
      window.postMessage({source: 'ozkurt-result', ok: diagnostics.every(item => item.result === 'ok')}, location.origin);
      return;
    }
    if (event.data.action !== 'query') return;
    try {
      let url, options;
      if (uyap) {
        const format = date => `${String(date.getDate()).padStart(2, '0')}.${String(date.getMonth() + 1).padStart(2, '0')}.${date.getFullYear()}`;
        const start = new Date();
        const end = new Date(start.getTime() + 7 * 86400000);
        url = '/avukat_durusma_sorgula_brd.ajx';
        options = {method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({baslangicTarihi: format(start), bitisTarihi: format(end)})};
      } else if (uets) {
        const accessToken = localStorage.getItem('accessToken');
        if (!accessToken) throw new Error('Oturum bulunamadı');
        url = 'https://api.etebligat.gov.tr/v1/messages?sort=inserttime&folders_id=1&count=50';
        options = {method: 'GET', credentials: 'omit', headers: {Authorization: `Bearer ${accessToken}`}};
      } else return;
      const response = await originalFetch.call(window, url, options);
      if (!response.ok) throw new Error(`Yanıt kodu: ${response.status}`);
      const data = await response.json();
      if (!data || typeof data !== 'object' || data.error || data.errorCode) throw new Error('Sorgu yanıtı alınamadı');
      send(response.url || url, data);
      window.postMessage({source: 'ozkurt-result', ok: true}, location.origin);
    } catch (error) {
      const status = /^Yanıt kodu: \d{3}$/.test(error.message) ? error.message : (error.message === 'Oturum bulunamadı' ? error.message : 'Bağlantı veya yanıt hatası');
      window.postMessage({source: 'ozkurt-result', ok: false, error: status}, location.origin);
    }
  });
  window.fetch = async function (...args) {
    const response = await originalFetch.apply(this, args);
    const url = response.url || (typeof args[0] === 'string' ? args[0] : args[0]?.url);
    diagnose(url, args[1]?.method || args[0]?.method || 'GET', response);
    if (eligible(url) && response.ok) {
      response.clone().json().then(data => send(url, data)).catch(() => {});
    }
    return response;
  };
  const open = XMLHttpRequest.prototype.open;
  const transmit = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__ozkurtUrl = url;
    this.__ozkurtMethod = method;
    return open.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener('load', function () {
      diagnose(this.responseURL || this.__ozkurtUrl, this.__ozkurtMethod, {status: this.status, headers: {get: () => this.getResponseHeader('content-type')}});
    });
    if (eligible(this.__ozkurtUrl)) this.addEventListener('load', function () {
      if (this.status < 200 || this.status >= 300) return;
      try {
        const value = this.responseType === 'json' ? this.response : JSON.parse(this.responseText);
        send(this.responseURL || this.__ozkurtUrl, value);
      } catch {}
    });
    return transmit.apply(this, args);
  };
})();
