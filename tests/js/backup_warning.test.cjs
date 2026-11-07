const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// Alpine x-init değerini ifade olarak derler; çıplak try/catch geçerli ifade değildir.
const template = fs.readFileSync(path.join(__dirname, '../../templates/base.html'), 'utf8');
const expression = template.match(/id="backup-stale-alert"[\s\S]*?x-init="([^"]+)"/)[1];
const run = new Function('scope', `with (scope) { return (${expression}); }`);

test('Yedek uyarısı aynı gün gizleme tercihini okur', () => {
  const scope = {key: 'backupStaleHidden', today: 'test-day', hidden: false,
    localStorage: {getItem: () => 'test-day'}};
  run(scope);
  assert.equal(scope.hidden, true);
  scope.today = 'next-day';
  run(scope);
  assert.equal(scope.hidden, false);
});

test('Depolama kapalıysa yedek uyarısı görünür kalır', () => {
  const scope = {key: 'backupStaleHidden', today: 'test-day', hidden: false,
    localStorage: {getItem: () => { throw new Error('blocked'); }}};
  run(scope);
  assert.equal(scope.hidden, false);
});

test("Bootstrap d-flex gizleme stilini geçersiz kılmaz", () => {
  assert.match(template, /x-show\.important="!hidden"/);
});
