(() => {
  async function updateFolderNumber(form) {
    const category = form.querySelector("[data-folder-category]");
    const state = form.querySelector("[data-folder-state]");
    const stateWrap = form.querySelector("[data-folder-state-wrap]");
    const output = form.querySelector("[data-folder-number]");
    if (!category || !state || !output || !category.value) return;
    const requestedCategory = category.value;
    const requestedState = state.value;
    const url = new URL(form.dataset.nextUrl, location.origin);
    url.searchParams.set("category", requestedCategory);
    url.searchParams.set("state", requestedState);
    output.textContent = "Sıradaki numara hesaplanıyor…";
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("Numara alınamadı.");
      const result = await response.json();
      if (category.value !== requestedCategory || state.value !== requestedState) return;
      state.value = result.state;
      if (stateWrap) stateWrap.style.display = result.tracks_state ? "" : "none";
      const singleOption = state.querySelector('option[value="single"]');
      if (singleOption) singleOption.hidden = result.tracks_state;
      output.textContent = result.folder_name
        ? `Oluşturulacak klasör: ${result.folder_name}`
        : `Sıradaki klasör numarası: ${result.number}`;
    } catch {
      if (category.value === requestedCategory && state.value === requestedState)
        output.textContent = "Sıradaki numara alınamadı; kaydederken yeniden hesaplanacak.";
    }
  }

  document.addEventListener("change", async event => {
    const createForm = event.target.closest("[data-folder-create]");
    if (createForm && event.target.matches("[data-folder-category], [data-folder-state]")) {
      updateFolderNumber(createForm);
    }
    const client = event.target.closest("[data-archive-client]");
    if (client) {
      const form = client.closest("form");
      const folder = form && form.querySelector("[data-archive-folder]");
      const slots = form && form.querySelector("[data-archive-slot]");
      if (!folder || !slots || folder.dataset.clientId === client.value) return;
      const selectedClient = client.value;
      folder.dataset.clientId = selectedClient;
      folder.replaceChildren(new Option("Klasörler yükleniyor…", ""));
      slots.replaceChildren(new Option("Önce klasör seçiniz…", ""));
      folder.setCustomValidity("Klasörlerin yüklenmesini bekleyin.");
      const url = new URL(document.body.dataset.archiveFoldersUrl, location.origin);
      if (selectedClient) url.searchParams.set("client", selectedClient);
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error("Klasörler alınamadı.");
        const result = await response.json();
        if (client.value !== selectedClient) return;
        folder.replaceChildren(new Option("Klasör seçiniz…", ""));
        result.folders.forEach(value => folder.add(new Option(value, value)));
        folder.setCustomValidity("");
        slots.setCustomValidity("");
      } catch {
        if (client.value !== selectedClient) return;
        folder.replaceChildren(new Option("Klasörler alınamadı", ""));
        folder.setCustomValidity("Klasörler alınamadı; müvekkili yeniden seçin.");
      }
      return;
    }
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
    if (folder.dataset.clientId) url.searchParams.set("client", folder.dataset.clientId);
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
  document.querySelectorAll("[data-folder-create]").forEach(updateFolderNumber);
})();
