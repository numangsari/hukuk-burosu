(() => {
  if (window.top !== window) return;
  const source = location.hostname === 'ptt.etebligat.gov.tr' ? 'uets' : 'uyap';
  let sequence = 0;
  let timer;
  function selectedName() {
    if (source === 'uyap') {
      const nodes = document.querySelectorAll('#dropdownMenuButton .dropdown-toggle');
      return nodes.length === 1 ? nodes[0].textContent.trim() : '';
    }
    const nodes = [...document.querySelectorAll('span')].filter(node =>
      /^\s*Seçili Hesap:\s*[^\n]+\s*$/.test(node.textContent)
    );
    if (nodes.length !== 1) return '';
    return nodes[0].textContent.replace(/^\s*Seçili Hesap:\s*/, '').trim();
  }
  async function check() {
    const current = ++sequence;
    const name = selectedName();
    let result = 'okunamadi';
    if (name) {
      try {
        const response = await chrome.runtime.sendMessage({type:'check_name', name});
        result = response?.unavailable ? 'baglanti_yok' : response?.ok === true ? 'izinli' : 'izin_yok';
      } catch (_) { result = 'baglanti_yok'; }
    }
    if (current !== sequence || name !== selectedName()) return;
    await chrome.storage.local.set({['name_' + source]:result});
  }
  function schedule() {
    ++sequence;
    clearTimeout(timer);
    timer = setTimeout(check, 500);
  }
  new MutationObserver(schedule).observe(document.documentElement, {childList:true, subtree:true, characterData:true});
  setInterval(check, 60000);
  check();
})();
