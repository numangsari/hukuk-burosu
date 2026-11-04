(() => {
  function fold(value) {
    return value.toLocaleLowerCase("tr-TR").replace(/ı/g, "i")
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }

  function setup(select) {
    const wrapper = document.createElement("div");
    wrapper.className = "searchable-select";
    const search = document.createElement("input");
    search.type = "search";
    search.className = "form-control searchable-select-input";
    search.placeholder = select.dataset.searchable;
    search.id = select.id + "_search";
    search.autocomplete = "off";
    search.setAttribute("role", "combobox");
    search.setAttribute("aria-label", select.dataset.searchable);
    search.setAttribute("aria-autocomplete", "list");
    search.setAttribute("aria-expanded", "false");
    if (select.required) search.setAttribute("aria-required", "true");
    const list = document.createElement("div");
    list.id = select.id + "_options";
    list.className = "searchable-select-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;
    search.setAttribute("aria-controls", list.id);
    wrapper.append(search, list);
    select.before(wrapper);
    select.classList.add("visually-hidden");
    select.setAttribute("aria-hidden", "true");
    select.tabIndex = -1;
    const label = document.querySelector('label[for="' + select.id + '"]');
    if (label) label.htmlFor = search.id;
    let items = [];
    let active = -1;
    let editing = false;

    function sync() {
      const selected = select.selectedOptions[0];
      search.value = selected && selected.value ? selected.textContent.trim() : "";
      search.setCustomValidity("");
    }
    function close() {
      list.hidden = true;
      search.setAttribute("aria-expanded", "false");
      search.removeAttribute("aria-activedescendant");
      active = -1;
    }
    function choose(option) {
      select.value = option.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      sync();
      close();
    }
    function highlight(index) {
      if (!items.length) return;
      active = (index + items.length) % items.length;
      items.forEach((item, i) => item.setAttribute("aria-selected", i === active ? "true" : "false"));
      search.setAttribute("aria-activedescendant", items[active].id);
      items[active].scrollIntoView({ block: "nearest" });
    }
    function render(showAll = false) {
      const query = showAll ? "" : fold(search.value.trim());
      list.replaceChildren();
      items = [];
      active = -1;
      search.removeAttribute("aria-activedescendant");
      let lastGroup = null;
      for (const option of select.options) {
        if (!option.value || !option.textContent.trim() || option.disabled || option.parentElement?.disabled) continue;
        const group = option.parentElement?.tagName === "OPTGROUP" ? option.parentElement.label : "";
        if (query && !fold(option.textContent).includes(query) && !fold(group).includes(query)) continue;
        if (group && group !== lastGroup) {
          const heading = document.createElement("div");
          heading.className = "searchable-select-group";
          heading.textContent = group;
          heading.setAttribute("role", "presentation");
          list.append(heading);
        }
        lastGroup = group;
        const item = document.createElement("div");
        item.id = list.id + "_" + items.length;
        item.className = "searchable-select-option";
        item.textContent = option.textContent.trim();
        item.setAttribute("role", "option");
        item.setAttribute("aria-selected", "false");
        item.addEventListener("pointerdown", event => event.preventDefault());
        item.addEventListener("click", () => choose(option));
        list.append(item);
        items.push(item);
      }
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "searchable-select-empty";
        empty.textContent = "Eşleşen seçenek yok";
        list.append(empty);
      }
      list.hidden = false;
      search.setAttribute("aria-expanded", "true");
    }
    search.addEventListener("focus", () => {
      if (select.value) search.select();
      render(Boolean(select.value));
    });
    search.addEventListener("input", () => {
      search.setCustomValidity(search.value.trim() ? "Listeden bir seçim yapın." : "");
      if (select.value) {
        editing = true;
        select.value = "";
        select.dispatchEvent(new Event("change", { bubbles: true }));
        editing = false;
      }
      render();
    });
    search.addEventListener("keydown", event => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (list.hidden) render();
        highlight(active < 0 && event.key === "ArrowUp" ? items.length - 1 : active + (event.key === "ArrowDown" ? 1 : -1));
      } else if (event.key === "Enter" && !list.hidden) {
        if (items.length && (!select.value || active >= 0)) {
          event.preventDefault();
          items[active >= 0 ? active : 0].click();
        }
      } else if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    });
    search.addEventListener("blur", close);
    select.addEventListener("change", () => { if (!editing) sync(); });
    select.addEventListener("searchable:refresh", sync);
    select.addEventListener("invalid", event => {
      event.preventDefault();
      search.setCustomValidity("Listeden bir seçim yapın.");
      search.reportValidity();
      search.focus();
    });
    new MutationObserver(() => { if (!list.hidden) render(); }).observe(select, { childList: true, subtree: true });
    sync();
  }

  let sequence = 0;
  function initialize(root) {
    root.querySelectorAll("select[name=client], select[name=case], select[name=musteri], select[name=dosya]").forEach(select => {
      if (!select.dataset.searchable) {
        select.dataset.searchable = ["client", "musteri"].includes(select.name) ? "Müvekkil ara" : "Dosya ara";
      }
    });
    root.querySelectorAll("select[data-searchable]").forEach(select => {
      if (select.dataset.searchableReady || select.multiple) return;
      if (!select.id) select.id = "searchable-" + (++sequence);
      select.dataset.searchableReady = "1";
      setup(select);
    });
  }
  initialize(document);
  document.addEventListener("htmx:afterSwap", event => initialize(event.detail.target));
})();
