function connectPortal() {
  const element = document.getElementById('portal-pair-key');
  if (!element) return;
  let key;
  try { key = JSON.parse(element.textContent); } catch { return; }
  if (typeof key !== 'string') return;
  chrome.runtime.sendMessage({type: 'pair', key}).then(result => {
    const status = document.getElementById('portal-pair-status');
    if (status) status.textContent = result?.ok ? 'Eklenti deneme sunucusuna bağlandı.' : 'Bağlantı kurulamadı.';
    element.remove();
  }).catch(() => {
    const status = document.getElementById('portal-pair-status');
    if (status) status.textContent = 'Eklentiye ulaşılamadı.';
    element.remove();
  });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', connectPortal, {once: true});
else connectPortal();
