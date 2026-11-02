const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup(options) {
  class Element {
    constructor(tag = '') { this.tagName = tag.toUpperCase(); this.children = []; this.handlers = {}; this.attrs = {}; this.value = ''; this.hidden = false; this.classList = { add() {} }; }
    append(...children) { this.children.push(...children); }
    before(node) { this.inserted = node; }
    replaceChildren(...children) { this.children = children; }
    setAttribute(name, value) { this.attrs[name] = value; }
    removeAttribute(name) { delete this.attrs[name]; }
    addEventListener(name, fn) { (this.handlers[name] ??= []).push(fn); }
    dispatchEvent(event) { for (const fn of this.handlers[event.type] ?? []) fn(event); }
    click() { this.dispatchEvent({type: 'click'}); }
    focus() {}
    select() {}
    scrollIntoView() {}
    setCustomValidity(value) { this.validation = value; }
    reportValidity() {}
  }
  const select = new Element('select');
  select.id = 'id_type'; select.dataset = { searchable: 'Görev türü ara' }; select.options = options;
  Object.defineProperty(select, 'selectedOptions', { get() { return this.options.filter(item => item.value === this.value); } });
  let observer;
  const document = { createElement: tag => new Element(tag), querySelectorAll: () => [select], querySelector: () => null };
  class MutationObserver { constructor(fn) { observer = fn; } observe() {} }
  class Event { constructor(type, options) { this.type = type; this.bubbles = options?.bubbles; } }
  const source = fs.readFileSync(path.join(__dirname, '../../static/js/searchable-select.js'), 'utf8');
  vm.runInNewContext(source, { document, MutationObserver, Event });
  return { select, search: select.inserted.children[0], list: select.inserted.children[1], refresh: () => observer() };
}

function option(value, text, category = '') {
  return { value, textContent: text, parentElement: category ? { tagName: 'OPTGROUP', label: category } : { tagName: 'SELECT' } };
}

test('Yazarken Türkçe eşleşmeleri gösterir ve seçimi iletir', () => {
  const s = setup([option('1', 'IŞIK YILMAZ'), option('2', 'İPEK CAN')]);
  let changes = 0;
  s.select.addEventListener('change', () => changes++);
  s.search.value = 'isik'; s.search.dispatchEvent({type:'input'});
  assert.equal(s.list.hidden, false);
  assert.equal(s.list.children.length, 1);
  assert.equal(s.list.children[0].textContent, 'IŞIK YILMAZ');
  s.list.children[0].click();
  assert.equal(s.select.value, '1');
  assert.equal(s.search.value, 'IŞIK YILMAZ');
  assert.equal(s.list.hidden, true);
  assert.equal(changes, 1);
  s.search.value = 'ipek'; s.search.dispatchEvent({type:'input'});
  assert.equal(s.select.value, '');
  assert.equal(s.search.validation, 'Listeden bir seçim yapın.');
});

test('Kategorileri gösterir, kategori adıyla arar ve yenilenen seçenekleri kullanır', () => {
  const s = setup([option('1','Satış Talebi','İcra İşlemleri'), option('2','Dilekçe','Dava İşlemleri')]);
  s.search.value='icra'; s.search.dispatchEvent({type:'input'});
  assert.deepEqual(s.list.children.map(x => x.textContent), ['İcra İşlemleri', 'Satış Talebi']);
  s.select.options.push(option('3','İcra Dosyası','İcra İşlemleri'));
  s.refresh();
  assert.equal(s.list.children.at(-1).textContent, 'İcra Dosyası');
  s.select.value = '3'; s.select.dispatchEvent({type:'searchable:refresh'});
  assert.equal(s.search.value, 'İcra Dosyası');
});

test('Klavye ile seçim ve eşleşmeyen arama', () => {
  const s = setup([option('1','Dosya Bir'), option('2','Dosya İki')]);
  s.search.value='dosya'; s.search.dispatchEvent({type:'input'});
  const key = name => s.search.dispatchEvent({type:'keydown', key:name, preventDefault() {}});
  key('ArrowDown'); key('ArrowDown'); key('Enter');
  assert.equal(s.select.value, '2');
  s.search.value='bulunmayan'; s.search.dispatchEvent({type:'input'});
  assert.equal(s.list.children[0].textContent, 'Eşleşen seçenek yok');
  key('Escape'); assert.equal(s.list.hidden, true);
});
