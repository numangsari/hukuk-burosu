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
