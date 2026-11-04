const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('Klasör seçilince yalnızca sunucunun bildirdiği boş yerleri gösterir', async () => {
  let onChange;
  const slots = {
    options: [], parentElement: { querySelector: () => help },
    replaceChildren(...options) { this.options = options; },
    add(option) { this.options.push(option); },
    setCustomValidity(value) { this.validity = value; },
  };
  const help = { textContent: '' };
  const folder = {
    value: 'Açık 1', dataset: { caseId: '5' },
    closest(selector) { return ['[data-folder-create]', '[data-archive-client]'].includes(selector) ? null : selector === 'form' ? { querySelector: () => slots } : this; },
  };
  const document = {
    body: { dataset: { archiveSlotsUrl: '/arsiv/bos-yerler/' } },
    addEventListener(type, handler) { if (type === 'change') onChange = handler; },
    querySelectorAll() { return []; },
  };
  let requested;
  const fetch = async url => { requested = url; return { ok: true, json: async () => ({ slots: ['1', '3'], capacity_missing: false }) }; };
  function Option(text, value) { this.text = text; this.value = value; }
  const source = fs.readFileSync(path.join(__dirname, '../../static/js/archive-slots.js'), 'utf8');
  vm.runInNewContext(source, { document, location: { origin: 'http://localhost' }, URL, Option, fetch });
  await onChange({ target: folder });
  assert.equal(requested.searchParams.get('folder'), 'Açık 1');
  assert.equal(requested.searchParams.get('case'), '5');
  assert.deepEqual(slots.options.map(option => option.value), ['', '1', '3']);
  assert.equal(slots.validity, '');
});
