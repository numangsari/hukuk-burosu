// Görev formu (oluşturma sayfası ve görev penceresinde yerinde düzenleme ortak kullanır).
(() => {
  function setupDocumentList(root) {
    const input = root.querySelector("#id_document");
    const list = root.querySelector("#selected-documents");
    if (!input || !list || input.dataset.listReady) return;
    input.dataset.listReady = "1";
    let files = [];
    function update() {
      const selected = new DataTransfer();
      files.forEach(file => selected.items.add(file));
      input.files = selected.files;
      list.replaceChildren(...files.map((file, index) => {
        const item = document.createElement("li");
        item.className = "d-flex align-items-center gap-2 mb-1";
        const name = document.createElement("span");
        name.textContent = file.name;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn btn-sm btn-light";
        remove.textContent = "Kaldır";
        remove.setAttribute("aria-label", file.name + " belgesini kaldır");
        remove.addEventListener("click", () => { files.splice(index, 1); update(); });
        item.append(name, remove);
        return item;
      }));
    }
    input.addEventListener("change", () => {
      files.push(...Array.from(input.files));
      update();
    });
  }
  document.addEventListener("DOMContentLoaded", () => setupDocumentList(document));
  document.addEventListener("htmx:afterSwap", event => setupDocumentList(event.detail.target));

  window.taskForm = function () {
    return {
      url: "",
      allOptions: "",
      requiresDocument: false,
      requiresAccounting: false,
      frequency: "weekly",
      async load(params) {
        const r = await fetch(this.url + "?" + new URLSearchParams(params));
        return (await r.json()).cases;
      },
      init() {
        this.url = this.$root.dataset.caseOptionsUrl;
        const frequency = document.getElementById("id_frequency");
        if (frequency) this.frequency = frequency.value;
        // Müvekkil seçimi temizlenince sunucunun çizdiği tam liste geri konur.
        this.allOptions = this.$refs.case.innerHTML;
        const typeId = Number(document.getElementById("id_task_type").value);
        const checked = name => document.querySelector(`input[name="${name}"]:checked`);
        const doc = checked("requires_document"), acc = checked("requires_accounting");
        this.requiresDocument = doc ? doc.value === "yes" : this.typeIds("document-types", typeId);
        this.requiresAccounting = acc ? acc.value === "yes" : this.typeIds("accounting-types", typeId);
        document.querySelectorAll('input[name="requires_document"]').forEach(radio =>
          radio.addEventListener("change", () => { this.requiresDocument = radio.value === "yes"; }));
        document.querySelectorAll('input[name="requires_accounting"]').forEach(radio =>
          radio.addEventListener("change", () => { this.requiresAccounting = radio.value === "yes"; }));
      },
      typeIds(id, typeId) {
        return JSON.parse(document.getElementById(id).textContent).includes(typeId);
      },
      setRadio(name, value) {
        const radio = document.querySelector(`input[name="${name}"][value="${value ? "yes" : "no"}"]`);
        if (radio) radio.checked = true;
      },
      taskTypeChanged(event) {
        const selected = event.target.selectedOptions[0];
        const typeId = Number(event.target.value);
        // Görev türünün varsayılanları seçilir; oluşturan bunları değiştirebilir.
        this.requiresDocument = this.typeIds("document-types", typeId);
        this.requiresAccounting = this.typeIds("accounting-types", typeId);
        this.setRadio("requires_document", this.requiresDocument);
        this.setRadio("requires_accounting", this.requiresAccounting);
        const title = document.getElementById("id_title");
        title.value = selected && selected.value && selected.text.trim().toLocaleLowerCase('tr-TR') !== 'diğer'
          ? selected.text.trim() : '';
        if (selected && selected.text.trim().toLocaleLowerCase('tr-TR') === 'diğer') title.focus();
      },
      setResponsible(info) {
        const assigneeVal = info.intern || info.lawyer || "";
        document.getElementById("id_assignee").value = assigneeVal;
        const map = JSON.parse(document.getElementById("supervisor-map").textContent);
        const reviewerVal = (info.intern && info.lawyer) ? info.lawyer : (map[assigneeVal] || "");
        document.getElementById("id_reviewer").value = String(reviewerVal) !== String(assigneeVal) ? reviewerVal : "";
      },
      async filterCases() {
        const sel = this.$refs.case, client = this.$refs.client.value, keep = sel.value;
        if (!client) {
          sel.innerHTML = this.allOptions;
          sel.value = keep;
          sel.dispatchEvent(new Event("searchable:refresh"));
          return;
        }
        const info = await (await fetch(this.url + "?" + new URLSearchParams({ client_info: client }))).json();
        if (this.$refs.client.value !== client) return;
        this.setResponsible(info);
        const list = await this.load({ client });
        if (this.$refs.client.value !== client) return;
        sel.innerHTML = '<option value="">Seçiniz…</option>' +
          list.map(c => `<option value="${c.id}">${c.label.replace(/</g, "&lt;")}</option>`).join("");
        if (list.some(c => String(c.id) === keep)) sel.value = keep;
        sel.dispatchEvent(new Event("searchable:refresh"));
      },
      async caseChanged() {
        if (!this.$refs.case.value) return;
        const id = this.$refs.case.value;
        const [c] = await this.load({ id, all: 1 });
        if (!c || this.$refs.case.value !== id) return;
        this.$refs.client.value = c.client;
        this.$refs.client.dispatchEvent(new Event("searchable:refresh"));
        this.setResponsible(c);
      },
      // Sorumlu seçilince kontrolcü, sorumlunun kontrolcüsü olur; kullanıcı değiştirebilir.
      assigneeChanged() {
        const map = JSON.parse(document.getElementById("supervisor-map").textContent);
        const lawyer = map[document.getElementById("id_assignee").value];
        if (lawyer) document.getElementById("id_reviewer").value = String(lawyer);
      },
    };
  };
})();
