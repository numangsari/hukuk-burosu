(() => {
  function initialize(root) {
    const forms = root.matches?.('[data-notice-task]') ? [root] : root.querySelectorAll('[data-notice-task]');
    forms.forEach(form => {
      if (form.dataset.caseFilterReady) return;
      form.dataset.caseFilterReady = '1';
      const client = form.querySelector('select[name="client"]');
      const cases = form.querySelector('select[name="case"]');
      if (!client || !cases) return;
      const allOptions = cases.innerHTML;
      let revision = 0;
      // Görev adı "[TEBLİGAT] " ile başlar; görev türü seçilince adın devamı türden gelir.
      const type = form.querySelector('select[name="task_type"]');
      const title = form.querySelector('input[name="title"]');
      const PREFIX = '[TEBLİGAT] ';
      let autoTitle = title ? title.value : '';
      if (type && title) {
        type.addEventListener('change', () => {
          const name = type.selectedOptions[0]?.value ? type.selectedOptions[0].text.trim() : '';
          if (title.value.trim() === '' || title.value === autoTitle || title.value === PREFIX) {
            autoTitle = name && name.toLocaleLowerCase('tr-TR') !== 'diğer' ? PREFIX + name : PREFIX;
            title.value = autoTitle;
          }
        });
      }
      // Ekip: yardımcı sorumlu görevin sorumlusu, sorumlu avukat kontrolcüsü olur.
      const assignee = form.querySelector('select[name="assignee"]');
      const reviewer = form.querySelector('select[name="reviewer"]');
      const setTeam = info => {
        if (!assignee || !reviewer || !info) return;
        const owner = info.intern || info.lawyer || '';
        const map = document.getElementById('supervisor-map');
        const supervisors = map ? JSON.parse(map.textContent) : {};
        const boss = info.intern && info.lawyer ? info.lawyer : (supervisors[owner] || '');
        assignee.value = owner ? String(owner) : '';
        reviewer.value = boss && String(boss) !== String(owner) ? String(boss) : '';
      };
      // Dosya seçilince müvekkil ve ekip dosyadan otomatik gelir.
      cases.addEventListener('change', async () => {
        if (!cases.value) return;
        const id = cases.value;
        try {
          const response = await fetch(form.dataset.caseOptionsUrl + '?' + new URLSearchParams({id, all: 1}));
          if (!response.ok) return;
          const [found] = (await response.json()).cases;
          if (found && found.client && cases.value === id) {
            client.value = found.client;
            client.dispatchEvent(new Event('searchable:refresh'));
            setTeam(found);
          }
        } catch (_) { /* müvekkil elle seçilebilir */ }
      });
      client.addEventListener('change', async () => {
        const current = ++revision, clientId = client.value, selected = cases.value;
        if (!clientId) {
          cases.innerHTML = allOptions;
          cases.value = selected;
          cases.dispatchEvent(new Event('searchable:refresh'));
          return;
        }
        try {
          const response = await fetch(form.dataset.caseOptionsUrl + '?' + new URLSearchParams({client: clientId}));
          if (!response.ok) return;
          const data = await response.json();
          if (current !== revision) return;
          cases.replaceChildren(new Option('Seçiniz…', ''));
          data.cases.filter(item => String(item.client) === clientId).forEach(item => cases.add(new Option(item.label, item.id)));
          cases.value = [...cases.options].some(option => option.value === selected) ? selected : '';
          cases.dispatchEvent(new Event('searchable:refresh'));
        } catch (_) {
          cases.value = '';
          cases.dispatchEvent(new Event('searchable:refresh'));
        }
      });
    });
  }
  initialize(document);
  document.addEventListener('htmx:afterSwap', event => initialize(event.detail.target));
})();
