// Oturum yoklaması: UYAP/UETS sayfası açıkken oturumun hâlâ geçerli olup olmadığını belirli aralıkla sorar
// ve sonucu (oturum açık mı, hangi hesap açık) eklentiye bildirir. Başka veri toplamaz veya göndermez.
(() => {
  if (window.top !== window) return;
  const uets = location.hostname === 'ptt.etebligat.gov.tr';
  const INTERVAL = 4 * 60 * 1000;

  // Sayfada açık hesabın adı (bridge.js ile aynı kaynak); belirsizse boş.
  function accountName() {
    const nodes = uets
      ? [...document.querySelectorAll('span')].filter(node => /^\s*Seçili Hesap:\s*[^\n]+\s*$/.test(node.textContent))
      : [...document.querySelectorAll('#dropdownMenuButton .dropdown-toggle')];
    if (nodes.length !== 1) return '';
    const text = uets ? nodes[0].textContent.replace(/^\s*Seçili Hesap:\s*/, '') : nodes[0].textContent;
    return text.trim().slice(0, 200);
  }

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

  // Sayfanın kendi boşta kalma sayacı yalnızca fare/klavye olaylarını görür; yoklama isteği onu sıfırlamaz.
  // Yoklamayla birlikte hafif bir fare hareketi bildirilir ki sayfa kullanıcı etkinliği var saysın.
  function keepActive() {
    try {
      const target = document.body || document;
      const options = {bubbles: true, cancelable: true, clientX: 1 + Math.floor(Math.random() * 50), clientY: 1 + Math.floor(Math.random() * 50)};
      target.dispatchEvent(new MouseEvent('mousemove', options));
    } catch (_) { /* olay gönderilemezse yalnızca yoklama çalışır */ }
  }

  // Eklenti yeniden yüklenince sayfada kalan eski betiğin bağlamı geçersiz olur; sessizce durur.
  const alive = () => { try { return Boolean(chrome.runtime?.id); } catch (_) { return false; } };
  let interval;

  async function report() {
    if (!alive()) { clearInterval(interval); return; }
    const ok = await check();
    if (ok === null) return;
    if (ok) keepActive();
    try {
      await chrome.runtime.sendMessage({type: 'session', ok, name: ok ? accountName() : ''});
    } catch (_) { clearInterval(interval); }
  }

  setTimeout(report, 5000);
  interval = setInterval(report, INTERVAL);
})();
