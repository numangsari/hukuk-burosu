const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function openForm() {
  const template = fs.readFileSync(path.join(__dirname, "../../templates/cases/form.html"), "utf8");
  const source = template.match(/<script>([\s\S]*?)<\/script>/)[1];
  const roles = {
    civil: [["plaintiff", "Davacı"], ["defendant", "Davalı"], ["interested", "İlgili Kişi"]],
    enforcement: [["creditor", "Alacaklı"], ["debtor", "Borçlu"]],
    consultancy: [["buyer", "Alıcı"], ["seller", "Satıcı"]],
  };
  const lanes = {
    civil: [
      { label: "Davacı tarafı", roles: ["plaintiff"] },
      { label: "Davalı tarafı", roles: ["defendant"] },
      { label: "Diğer ilgililer", roles: ["interested"] },
    ],
    enforcement: [
      { label: "Alacaklı tarafı", roles: ["creditor"] },
      { label: "Borçlu tarafı", roles: ["debtor"] },
    ],
    consultancy: [{ label: "Taraflar", roles: ["buyer", "seller"] }],
  };
  const total = { value: "0" };
  const inserted = [];
  const makeSelect = () => ({ value: "", replaceChildren(...options) { this.options = options; } });
  const clientRole = Object.assign(makeSelect(), { id: "id_client_role", value: "plaintiff" });
  const selects = [clientRole];
  const cards = [];
  const rows = {
    insertAdjacentHTML(position, html) {
      assert.equal(position, "beforeend");
      const select = makeSelect();
      selects.push(select);
      const card = { dataset: {}, querySelector: () => select };
      cards.push(card);
      this.lastElementChild = card;
      inserted.push(html);
    },
  };
  const elements = {
    "#id_parties-TOTAL_FORMS": total,
    "#id_client_role": clientRole,
    "#party-rows": rows,
    "#party-empty": { innerHTML: '<select name="parties-__prefix__-role" id="id_parties-__prefix__-role"></select>' },
  };
  const context = vm.createContext({
    document: {
      getElementById(id) {
        const data = id === "party-roles" ? roles : id === "party-lanes" ? lanes : { civil: {} };
        return { textContent: JSON.stringify(data) };
      },
    },
    Option: function(text, value) { this.text = text; this.value = value; },
  });
  vm.runInContext(source, context);
  const form = context.caseForm("civil");
  const opened = [];
  form.openCard = (card, fresh) => opened.push({ card, fresh });
  form.$root = {
    querySelector(selector) { return elements[selector]; },
    querySelectorAll(selector) { return selector === "[data-party-card]" ? cards : selects; },
  };
  return { form, total, inserted, selects, clientRole, opened };
}

test("Taraf ekle düğmesi ardışık ve ayrı isimli satırlar oluşturur", () => {
  const { form, total, inserted, selects, clientRole, opened } = openForm();
  form.addParty("a");
  form.addParty("b");
  assert.equal(Number(total.value), 2);
  assert.match(inserted[0], /name="parties-0-role"/);
  assert.match(inserted[1], /name="parties-1-role"/);
  assert.equal(clientRole.value, "plaintiff");
  assert.deepEqual(Array.from(selects[1].options, option => option.value), ["", "plaintiff", "defendant", "interested"]);
  assert.deepEqual(opened.map(item => item.fresh), [true, true]);
});

test("Yeni satır eklendiği bölümün ilk sıfatıyla gelir", () => {
  const { form, selects } = openForm();
  form.addParty("a");
  form.addParty("b");
  form.addParty("n");
  assert.deepEqual([selects[1].value, selects[2].value, selects[3].value], ["plaintiff", "defendant", "interested"]);
});

test("Müvekkilin bölümü sıfatına göre belirlenir", () => {
  const { form } = openForm();
  form.clientRole = "defendant";
  assert.equal(form.clientLane, "b");
  form.clientRole = "interested";
  assert.equal(form.clientLane, "n");
  form.clientRole = "";
  assert.equal(form.clientLane, null);
});

test("Tür değişince sıfat seçenekleri ve bölümler değişir", () => {
  const { form, selects, clientRole } = openForm();
  form.addParty("a");
  form.caseType = "enforcement";
  form.updateRoles();
  assert.equal(clientRole.value, "");
  assert.deepEqual(Array.from(selects[1].options, option => option.value), ["", "creditor", "debtor"]);
  assert.equal(form.lanes.length, 2);
  form.caseType = "consultancy";
  assert.equal(form.lanes.length, 1);
  assert.equal(form.laneKeyOf("seller"), "a");
});

test("Taraf sayısı sınırında yeni satır eklenmez", () => {
  const { form, total, inserted } = openForm();
  total.value = "50";
  form.addParty("a");
  assert.equal(inserted.length, 0);
  assert.equal(total.value, "50");
});
