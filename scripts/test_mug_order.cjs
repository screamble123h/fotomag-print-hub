/* Exercise production catalogue/request logic without a browser or network. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const mug = require('../assets/mugs.js');
const items = JSON.parse(fs.readFileSync(path.join(__dirname, '../assets/mug-catalog.json'), 'utf8')).items;
const base = 'https://screamble123h.github.io/fotomag-print-hub/mugs.html?group=Other&step=4#old';
assert.equal(mug.PAGE, 8);
for (const item of items) {
  const key = item.sku || 'classic';
  const url = new URL(mug.productURL(item, base));
  assert.equal(url.origin, 'https://screamble123h.github.io');
  assert.equal(url.pathname, '/fotomag-print-hub/mugs.html');
  assert.equal(url.searchParams.get('sku'), key);
  assert.equal([...url.searchParams].length, 1, 'shared product links must not carry comments or stale filters');
  assert.equal(url.hash, '');
  const text = mug.orderText(item, 3, '  Подарок — фото с двух сторон  ', base);
  for (const required of [item.series, item.name, mug.color(item), 'Количество: 3 шт.', url.href, 'Пожелания: Подарок — фото с двух сторон']) {
    assert.ok(text.includes(required), `${key}: missing ${required}`);
  }
  if (item.sku) assert.ok(text.includes('Артикул: ' + item.sku));
  if (typeof item.price === 'number') assert.ok(text.includes(`Розничная цена за штуку: ${item.price} ₽`));
  else assert.ok(text.includes('Розничная цена: уточним до оформления.'));
}
const groups = new Map();
for (const item of items) groups.set(item.series, mug.getGroup(item.series));
assert.equal(groups.get('Цветные 330 мл'), 'Классические и цветные');
assert.equal(groups.get('Высокие цветные 420 мл'), 'Классические и цветные');
assert.equal(groups.get('Stackable'), 'Классические и цветные');
assert.equal(groups.get('Латте'), 'Конусные');
assert.equal(groups.get('Хамелеон латте'), 'Хамелеоны');
assert.equal(groups.get('Молочник'), 'Молочники');
assert.equal([...groups.values()].filter(group => group === 'Термокружки').length, 0,
  'No current source model is certified as a thermomug; the UI must show an empty category.');
assert.equal(mug.quantity(1.9), 1);
assert.equal(mug.quantity(-4), 1);
assert.equal(mug.quantity(999), 100);
assert.equal(mug.quantity(''), 1);
assert.equal(mug.quantity('invalid'), 1);
const classic = items.find(item => !item.sku);
const milk = items.find(item => item.sku === '10335');
assert.equal(classic.price, 650);
assert.equal(milk.price, 1250);
assert.equal(items.filter(item => typeof item.price === 'number').length, 2);
assert.ok(mug.orderText(classic, 2, '', base).includes('?sku=classic'));
assert.ok(!mug.orderText(milk, 2, '', base).includes('Пожелания:'));
assert.equal(mug.orderText(null, 1, '', base), '');
console.log('PASS mug request contract: all 139 SKU/title/colour/quantity/price/product links; corrected groups; integer quantities.');
