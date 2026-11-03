const privateKey = /token|password|passwd|sifre|şifre|parola|secret|authorization|cookie|session|credential|otp|guvenlik.?kodu|güvenlik.?kodu|dogrulama|doğrulama|verification.?code|^pass$/i;
function redact(value) {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, privateKey.test(key) ? '[gizlendi]' : redact(item)]));
  }
  return value;
}
async function availableCaptures() {
  const captures = (await chrome.storage.local.get('captures')).captures || [];
  return captures.filter(item => !/login|logout|auth|token|session|sifre|password|giris|nats/i.test(item.path || '')).map(redact);
}
async function refresh() {
  const captures = await availableCaptures();
  const nameStates = await chrome.storage.local.get(['name_uyap', 'name_uets']);
  const labels = {izinli:'Son kontrol: izinli', izin_yok:'Son kontrol: eşleşme yok', okunamadi:'Ad okunamadı', baglanti_yok:'Bağlantı yok'};
  for (const source of ['uyap', 'uets']) document.getElementById(source + '-name-state').textContent = labels[nameStates['name_' + source]] || 'Bekliyor';
  const connection = await chrome.storage.local.get('sync_key');
  document.getElementById('connection-state').textContent = connection.sync_key ? 'Bağlantı kaydı var' : 'Bağlantı kurulmamış';
  const status = await chrome.storage.local.get(['status_uyap', 'status_uets']);
  document.getElementById('status').textContent = `${captures.length} yanıt kaydedildi. UYAP: ${status.status_uyap || 'Bekliyor'}. UETS: ${status.status_uets || 'Bekliyor'}.`;
  document.getElementById('download').disabled = !captures.length;
  document.getElementById('auto-status').textContent = 'Kişi doğrulaması tamamlanana kadar otomatik aktarım kapalı.';
  document.getElementById('auto-scan').disabled = true;
}
document.getElementById('auto-scan').addEventListener('click', async () => {
  await chrome.runtime.sendMessage({type:'start_scans'});
  document.getElementById('auto-status').textContent = 'Açık portallar taranıyor; durumu görmek için pencereyi yeniden açın.';
});
document.getElementById('query').addEventListener('click', async () => {
  const tabs = await chrome.tabs.query({url: ['https://avukat.uyap.gov.tr/*', 'https://avukatbeta.uyap.gov.tr/*', 'https://ptt.etebligat.gov.tr/*']});
  await chrome.storage.local.set({status_uyap: 'Bekliyor', status_uets: 'Bekliyor'});
  await Promise.allSettled(tabs.map(tab => chrome.tabs.sendMessage(tab.id, {type: 'query'})));
  document.getElementById('status').textContent = 'Sorgular gönderildi. Birkaç saniye sonra pencereyi yeniden açın.';
});
document.getElementById('notice-sample').addEventListener('click', async () => {
  const tabs = await chrome.tabs.query({url: ['https://ptt.etebligat.gov.tr/*']});
  if (!tabs.length) { document.getElementById('status').textContent = 'Açık UETS sekmesi bulunamadı.'; return; }
  await chrome.storage.local.set({status_uets: 'Örnek tebligat indiriliyor'});
  await chrome.tabs.sendMessage(tabs[0].id, {type: 'notice_sample'});
  document.getElementById('status').textContent = 'Önceden açılmış bir tebligat ve belgeleri indiriliyor. Chrome birden fazla indirmeye izin isteyebilir.';
});
document.getElementById('case').addEventListener('click', async () => {
  const captures = await availableCaptures();
  const hearing = [...captures].reverse().find(item => item.path === '/avukat_durusma_sorgula_brd.ajx' && Array.isArray(item.data) && item.data.length);
  const selected = hearing?.data?.[0];
  const caseId = selected?.dosyaId;
  const tabs = await chrome.tabs.query({url: ['https://avukat.uyap.gov.tr/*', 'https://avukatbeta.uyap.gov.tr/*']});
  if (!caseId || !tabs.length) {
    document.getElementById('status').textContent = 'Duruşma verisi veya açık UYAP sekmesi bulunamadı.';
    return;
  }
  await chrome.storage.local.set({status_uyap: 'Bekliyor'});
  await chrome.tabs.sendMessage(tabs[0].id, {type: 'case_example', caseId, unitId: selected.birimId, unitType: selected.birimTuru2, jurisdiction: selected.birimTuru3});
  document.getElementById('status').textContent = 'Dosya sorgusu gönderildi. Birkaç saniye sonra pencereyi yeniden açın.';
});
document.getElementById('case-types').addEventListener('click', async () => {
  const tabs = await chrome.tabs.query({url: ['https://avukat.uyap.gov.tr/*', 'https://avukatbeta.uyap.gov.tr/*']});
  if (!tabs.length) { document.getElementById('status').textContent = 'Açık UYAP sekmesi bulunamadı.'; return; }
  await chrome.storage.local.set({status_uyap: 'Bekliyor'});
  await chrome.tabs.sendMessage(tabs[0].id, {type: 'case_types'});
  document.getElementById('status').textContent = 'Dosya listeleri sorgulanıyor. Tamamlanınca pencereyi yeniden açın.';
});
document.getElementById('type-examples').addEventListener('click', async () => {
  const captures = await availableCaptures();
  const examples = ['Ceza', 'Hukuk', 'İcra', 'İdari Yargı'].flatMap(category => {
    const capture = [...captures].reverse().find(item => item.path === '/search_phrase_detayli.ajx' && item.data?.kategori === category);
    const caseId = capture?.data?.sonuc?.[0]?.[0]?.dosyaId;
    return caseId ? [{category, caseId}] : [];
  });
  const tabs = await chrome.tabs.query({url: ['https://avukat.uyap.gov.tr/*', 'https://avukatbeta.uyap.gov.tr/*']});
  if (!tabs.length || !examples.length) { document.getElementById('status').textContent = 'Açık UYAP sekmesi veya örnek dosya bulunamadı.'; return; }
  await chrome.storage.local.set({status_uyap: 'Bekliyor'});
  await chrome.tabs.sendMessage(tabs[0].id, {type: 'type_examples', examples});
  document.getElementById('status').textContent = 'Örnek dosyalar sorgulanıyor. Tamamlanınca pencereyi yeniden açın.';
});
document.getElementById('closed-types').addEventListener('click', async () => {
  const tabs = await chrome.tabs.query({url: ['https://avukat.uyap.gov.tr/*', 'https://avukatbeta.uyap.gov.tr/*']});
  if (!tabs.length) { document.getElementById('status').textContent = 'Açık UYAP sekmesi bulunamadı.'; return; }
  await chrome.storage.local.set({status_uyap: 'Bekliyor'});
  await chrome.tabs.sendMessage(tabs[0].id, {type: 'closed_case_types'});
  document.getElementById('status').textContent = 'Kapalı dosyalar sorgulanıyor. Tamamlanınca pencereyi yeniden açın.';
});
document.getElementById('deep-metadata').addEventListener('click', async () => {
  const captures = await availableCaptures();
  const examples = [];
  for (const category of ['Ceza', 'Hukuk', 'İcra', 'İdari Yargı', 'Satış Memurluğu', 'Arabuluculuk']) {
    for (const state of ['acik', 'kapali']) {
      const capture = [...captures].reverse().find(item => item.path === '/search_phrase_detayli.ajx' && item.data?.kategori === category && (item.data?.durum || 'acik') === state);
      const rows = capture?.data?.sonuc?.[0];
      if (!Array.isArray(rows)) continue;
      for (const row of rows.slice(0, 3)) if (typeof row?.dosyaId === 'string') examples.push({category, state, caseId: row.dosyaId, caseType: row.dosyaTurKod});
    }
  }
  const tabs = await chrome.tabs.query({url: ['https://avukat.uyap.gov.tr/*', 'https://avukatbeta.uyap.gov.tr/*']});
  if (!tabs.length || !examples.length) { document.getElementById('status').textContent = 'Açık UYAP sekmesi veya örnek dosya listesi bulunamadı.'; return; }
  await chrome.storage.local.set({status_uyap: 'Bekliyor'});
  await chrome.tabs.sendMessage(tabs[0].id, {type: 'deep_metadata', examples});
  document.getElementById('status').textContent = `${examples.length} örnek inceleniyor. Tamamlanınca pencereyi yeniden açın.`;
});
document.getElementById('appeal-lists').addEventListener('click', async () => {
  const tabs = await chrome.tabs.query({url: ['https://avukat.uyap.gov.tr/*', 'https://avukatbeta.uyap.gov.tr/*']});
  if (!tabs.length) { document.getElementById('status').textContent = 'Açık UYAP sekmesi bulunamadı.'; return; }
  await chrome.storage.local.set({status_uyap:'Bekliyor'});
  await chrome.tabs.sendMessage(tabs[0].id, {type:'appeal_lists'});
  document.getElementById('status').textContent = 'İstinaf listeleri sorgulanıyor. Tamamlanınca pencereyi yeniden açın.';
});
document.getElementById('appeal-details').addEventListener('click', async () => {
  const captures = await availableCaptures();
  const examples = [];
  for (const category of ['Ceza', 'Hukuk']) {
    for (const state of ['acik', 'kapali']) {
      const capture = [...captures].reverse().find(item => item.path === '/search_phrase_detayli.ajx' && item.data?.inceleme === 'istinaf' && item.data?.kategori === category && item.data?.durum === state && item.data?.sonuc?.[0]?.length);
      for (const row of (capture?.data?.sonuc?.[0] || []).slice(0, 3)) {
        if (typeof row?.dosyaId === 'string') examples.push({category, state, caseId:row.dosyaId, caseType:row.dosyaTurKod});
      }
    }
  }
  const tabs = await chrome.tabs.query({url: ['https://avukat.uyap.gov.tr/*', 'https://avukatbeta.uyap.gov.tr/*']});
  if (!tabs.length || !examples.length) { document.getElementById('status').textContent = 'Açık UYAP sekmesi veya istinaf dosyası bulunamadı.'; return; }
  await chrome.storage.local.set({status_uyap:'Bekliyor'});
  await chrome.tabs.sendMessage(tabs[0].id, {type:'deep_metadata', examples});
  document.getElementById('status').textContent = `${examples.length} istinaf dosyası inceleniyor. Tamamlanınca pencereyi yeniden açın.`;
});
document.getElementById('download').addEventListener('click', async () => {
  const captures = await availableCaptures();
  const url = URL.createObjectURL(new Blob([JSON.stringify(captures, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'uyap-uets-deneme.json';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
document.getElementById('diagnostics').addEventListener('click', async () => {
  const diagnostics = (await chrome.storage.local.get('diagnostics')).diagnostics || [];
  const url = URL.createObjectURL(new Blob([JSON.stringify(diagnostics, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'uets-islem-inceleme.json';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
document.getElementById('open-settings').addEventListener('click', () => {
  chrome.tabs.create({url: 'http://127.0.0.1:3000/hesap/ayarlar/?bolum=eklenti'});
});
refresh();
