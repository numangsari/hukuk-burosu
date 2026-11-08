// Tarih alanlarında yıl en çok 4 hane olsun (tarayıcı varsayılanı 6 haneye izin verir).
(() => {
  const MAX = { "date": "9999-12-31", "datetime-local": "9999-12-31T23:59" };
  const limit = root => {
    root.querySelectorAll('input[type="date"], input[type="datetime-local"]').forEach(input => {
      if (!input.max) input.max = MAX[input.type];
    });
  };
  const start = () => {
    limit(document);
    new MutationObserver(records => records.forEach(r => r.addedNodes.forEach(node => {
      if (node.nodeType === 1) limit(node);
    }))).observe(document.body, { childList: true, subtree: true });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
