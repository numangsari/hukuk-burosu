// Dosya seçen formlarda sürükle-bırak: dosya form üzerine bırakılınca formun dosya alanına konur.
// Sunucu tarafı doğrulama (tür, boyut, imza) değişmez; burada yalnızca seçim kolaylaştırılır.
(() => {
  const target = event => {
    const form = event.target.closest && event.target.closest("form");
    const input = form && form.querySelector('input[type="file"]:not([disabled])');
    return input ? { form, input } : null;
  };
  const hasFiles = event => event.dataTransfer && Array.from(event.dataTransfer.types || []).includes("Files");

  document.addEventListener("dragover", event => {
    if (!hasFiles(event)) return;
    const found = target(event);
    if (!found) return;
    event.preventDefault();
    found.form.classList.add("is-dragover");
  });
  document.addEventListener("dragleave", event => {
    const form = event.target.closest && event.target.closest("form");
    if (form && !form.contains(event.relatedTarget)) form.classList.remove("is-dragover");
  });
  document.addEventListener("drop", event => {
    document.querySelectorAll("form.is-dragover").forEach(form => form.classList.remove("is-dragover"));
    if (!hasFiles(event)) return;
    const found = target(event);
    if (!found) return;
    event.preventDefault();
    const files = Array.from(event.dataTransfer.files);
    if (!files.length) return;
    const transfer = new DataTransfer();
    (found.input.multiple ? files : files.slice(0, 1)).forEach(file => transfer.items.add(file));
    found.input.files = transfer.files;
    found.input.dispatchEvent(new Event("change", { bubbles: true }));
  });
})();
