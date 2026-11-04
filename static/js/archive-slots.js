(() => {
  document.addEventListener("change", async event => {
    const folder = event.target.closest("[data-archive-folder]");
    if (!folder) return;
    const form = folder.closest("form");
    const slots = form && form.querySelector("[data-archive-slot]");
    if (!slots) return;
    const help = slots.parentElement.querySelector("[data-archive-help], .form-text");
    const chosen = folder.value;
    slots.replaceChildren(new Option(chosen ? "Boş yerler yükleniyor…" : "Önce klasör seçiniz…", ""));
    if (!chosen) {
      slots.setCustomValidity("");
      if (help) help.textContent = "Yalnızca boş numaralar listelenir.";
      return;
    }
    slots.setCustomValidity("Boş yerlerin yüklenmesini bekleyin.");
    const url = new URL(document.body.dataset.archiveSlotsUrl, location.origin);
    url.searchParams.set("folder", chosen);
    if (folder.dataset.caseId) url.searchParams.set("case", folder.dataset.caseId);
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("Boş yerler alınamadı.");
      const result = await response.json();
      if (folder.value !== chosen) return;
      slots.replaceChildren(new Option(result.slots.length ? "Boş yer seçiniz…" : "Boş yer bulunamadı", ""));
      result.slots.forEach(value => slots.add(new Option(value, value)));
      slots.setCustomValidity("");
      if (help) help.textContent = result.capacity_missing
        ? "Önce klasör kapasitesini belirleyin."
        : "Yalnızca boş numaralar listelenir.";
    } catch {
      if (folder.value !== chosen) return;
      slots.replaceChildren(new Option("Boş yerler alınamadı", ""));
      slots.setCustomValidity("Boş yerler alınamadı; klasörü yeniden seçin.");
      if (help) help.textContent = "Boş yerler alınamadı; klasörü yeniden seçin.";
    }
  });
})();
