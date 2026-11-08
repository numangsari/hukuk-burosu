// Excel / PDF düğmeleri: sayfadaki güncel süzgeçleri (HTMX ile değişse de) çıktı adresine taşır.
(() => {
  document.addEventListener("click", event => {
    const link = event.target.closest("[data-export-link]");
    if (!link) return;
    const params = new URLSearchParams(location.search);
    params.delete("page");
    // Süzgeç formu adres çubuğundan daha günceldir.
    const form = document.querySelector("form.filter-bar, form[hx-get][hx-target]");
    if (form) {
      new FormData(form).forEach((value, key) => {
        if (key === "csrfmiddlewaretoken") return;
        params.delete(key);
        if (value !== "") params.append(key, value);
      });
    }
    params.set("export", link.dataset.exportLink);
    link.href = (link.dataset.exportBase || location.pathname) + "?" + params.toString();
  });
})();
