'use strict';
(function (root) {
  function normalizeSymbol(value) {
    if (typeof value !== 'string') return '';
    const symbol = value.trim().toUpperCase().replaceAll('-', '.');
    return /^[A-Z0-9][A-Z0-9.]{0,11}$/.test(symbol) ? symbol : '';
  }

  function normalizeList(value) {
    if (!Array.isArray(value)) return [];
    const seen = new Set();
    const symbols = [];
    for (const valueItem of value) {
      const symbol = normalizeSymbol(valueItem);
      if (!symbol || seen.has(symbol)) continue;
      seen.add(symbol);
      symbols.push(symbol);
      if (symbols.length === 80) break;
    }
    return symbols;
  }

  function rowsFor(symbols, quotes) {
    const available = new Map((Array.isArray(quotes) ? quotes : []).map(quote => [quote.symbol, quote]));
    return normalizeList(symbols).map(symbol => available.get(symbol) || {
      symbol, name: '未收录每日行情', category: '自定义', currency: null,
      price: null, date: null, change_1d: null, change_5d: null,
      volume_multiple: null, sparkline: [], alerts: [], unpriced: true,
    });
  }

  const api = {normalizeSymbol, normalizeList, rowsFor};
  root.MarketPulseWatchlist = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(globalThis);
