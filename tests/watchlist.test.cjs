const test = require('node:test');
const assert = require('node:assert/strict');
const watchlist = require('../site/watchlist.js');

test('normalizes symbols, removes duplicates and rejects invalid input', () => {
  assert.deepEqual(watchlist.normalizeList([' aapl ', 'AAPL', 'brk-b', '0700.hk', '<script>', '']),
    ['AAPL', 'BRK.B', '0700.HK']);
  assert.deepEqual(watchlist.normalizeList('bad data'), []);
});

test('keeps a custom ticker visible without inventing a quote', () => {
  const rows = watchlist.rowsFor(['AAPL', 'NEW'], [{symbol:'AAPL', price:100, date:'2026-10-07'}]);
  assert.equal(rows[0].price, 100);
  assert.equal(rows[1].symbol, 'NEW');
  assert.equal(rows[1].price, null);
  assert.equal(rows[1].date, null);
});
