// HTMX istekleri başarısız olursa kullanıcıya Türkçe bildirim gösterir ("butona bastım, bir şey olmadı" önlenir).
(() => {
  const MESSAGES = {
    400: "İstek anlaşılamadı. Sayfayı yenileyip tekrar deneyin.",
    403: "Bu işlem için yetkiniz yok veya oturum doğrulaması sona erdi. Sayfayı yenileyin.",
    404: "Kayıt bulunamadı ya da erişim izniniz yok.",
    429: "Çok fazla istek gönderildi. Biraz bekleyip tekrar deneyin.",
  };
  const NETWORK = "Sunucuya ulaşılamadı. Bağlantıyı kontrol edip tekrar deneyin.";
  const SERVER = "Sunucuda bir hata oluştu. İşlem tamamlanmamış olabilir; sayfayı yenileyip kontrol edin.";

  function stack() {
    let el = document.querySelector(".toast-stack");
    if (!el) {
      el = document.createElement("div");
      el.className = "toast-stack";
      document.body.appendChild(el);
    }
    return el;
  }

  function show(text) {
    const alert = document.createElement("div");
    alert.className = "alert alert-danger d-flex align-items-center gap-2";
    alert.setAttribute("role", "alert");
    const icon = document.createElement("i");
    icon.className = "bi bi-exclamation-octagon";
    const span = document.createElement("span");
    span.textContent = text;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn-close btn-sm ms-auto";
    close.setAttribute("aria-label", "Bildirimi kapat");
    close.addEventListener("click", () => alert.remove());
    alert.append(icon, span, close);
    stack().appendChild(alert);
    setTimeout(() => alert.remove(), 10000);
  }

  document.addEventListener("htmx:responseError", event => {
    const status = event.detail.xhr ? event.detail.xhr.status : 0;
    show(MESSAGES[status] || (status >= 500 ? SERVER : NETWORK));
  });
  document.addEventListener("htmx:sendError", () => show(NETWORK));
  document.addEventListener("htmx:timeout", () => show(NETWORK));
})();
