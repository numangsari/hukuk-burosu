// Oturum yoklaması: UYAP/UETS sayfası açıkken oturumun hâlâ geçerli olup olmadığını belirli aralıkla sorar
// ve sonucu eklentiye bildirir. Yalnızca oturum durumunu okur; hiçbir veri toplamaz veya göndermez.
(() => {
  if (window.top !== window) return;
  const uets = location.hostname === 'ptt.etebligat.gov.tr';
  const INTERVAL = 4 * 60 * 1000;

  // true: oturum açık, false: oturum kapalı, null: belirsiz (ağ hatası, sunucu hatası).
  async function check() {
    try {
      if (uets) {
        const key = localStorage.getItem('accessToken');
        if (!key) return false;
        const response = await fetch('https://api.etebligat.gov.tr/v1/messages?sort=inserttime&count=1&start=0', {
          method: 'GET', credentials: 'omit', headers: {Authorization: 'Bearer ' + key}, signal: AbortSignal.timeout(20000)
        });
        if (response.status === 401 || response.status === 403) return false;
        return response.status === 200 ? true : null;
      }
      const response = await fetch('/get_avukat_id.ajx', {
        method: 'POST', credentials: 'include', headers: {'Content-Type': 'application/json'}, body: '{}', signal: AbortSignal.timeout(20000)
      });
      if (response.status === 401 || response.status === 403) return false;
      if (response.status !== 200) return null;
      return /json/i.test(response.headers.get('content-type') || '');
    } catch (_) { return null; }
  }

  async function report() {
    const ok = await check();
    if (ok === null) return;
    chrome.runtime.sendMessage({type: 'session', ok}).catch(() => {});
  }

  setTimeout(report, 5000);
  setInterval(report, INTERVAL);
})();
