"""Deterministic scoring tests with artificial INPUTS, not published market prices."""
import importlib.util
import unittest
from unittest import mock
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'scripts' / 'update_data.py'
spec = importlib.util.spec_from_file_location('market_daily', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fake_stock(symbol, price=100, high=105, change5=3):
    return {'symbol': symbol, 'price': price, 'sma20': 90, 'sma50': 90, 'sma200': 85,
            'change_1d':2,'change_5d':change5,'high20':high,
            'date':'2026-10-08',
            'currency':'HKD' if symbol.endswith('.HK') else 'USD'}


class HealthTests(unittest.TestCase):
    def test_extra_display_stock_does_not_change_market_breadth(self):
        stocks, indices, macro = self.full_data()
        baseline = next(x for x in m.build_health(stocks, indices, macro)['components'] if x['key'] == 'breadth')
        stocks['EXTRA'] = fake_stock('EXTRA', price=1)
        updated = next(x for x in m.build_health(stocks, indices, macro)['components'] if x['key'] == 'breadth')
        self.assertEqual(updated, baseline)

    def test_score_inputs_are_fetched_without_display_watchlist(self):
        universe = m.quote_universe([])
        self.assertIn('AAPL', universe)
        self.assertIn('NVDA', universe)
        self.assertIn('SPY', universe)
        self.assertIn('XLC', universe)
        self.assertEqual(len(universe), len(set(universe)))

    def test_breadth_uses_same_market_date_as_spy(self):
        stocks, indices, macro = self.full_data()
        for stock in stocks.values(): stock['date'] = '2026-10-08'
        for index in indices.values(): index['date'] = '2026-10-08'
        stocks['AAPL']['date'] = '2026-10-07'
        indices['XLC']['date'] = '2026-10-07'
        breadth = next(x for x in m.build_health(stocks, indices, macro)['components'] if x['key'] == 'breadth')
        self.assertEqual(breadth['coverage'], '10个行业ETF + 35只美股')

    def test_quality_report_exposes_sample_and_macro_fallback(self):
        stocks, indices, macro = self.full_data()
        indices['SPY']['date'] = '2026-10-08'
        for stock in stocks.values(): stock['date'] = '2026-10-08'
        for index in indices.values(): index['date'] = '2026-10-08'
        macro['vix']['source'] = 'Yahoo Finance · ^VIX'
        quality = m.build_health(stocks, indices, macro)['data_quality']
        self.assertEqual(quality['reference_date'], '2026-10-08')
        self.assertEqual(quality['sector_count'], 11)
        self.assertEqual(quality['stock_count'], 36)
        self.assertEqual(quality['macro_proxy_count'], 1)

    def test_quality_counts_only_sources_used_in_score(self):
        stocks, indices, macro = self.full_data()
        macro['treasury_10y']['source'] = 'Yahoo Finance · ^TNX'
        del macro['brent']
        quality = m.build_health(stocks, indices, macro)['data_quality']
        self.assertEqual(quality['macro_proxy_count'], 0)

    def test_old_macro_observation_is_not_scored(self):
        stocks, indices, macro = self.full_data()
        for stock in stocks.values(): stock['date'] = '2026-10-08'
        for index in indices.values(): index['date'] = '2026-10-08'
        macro['vix']['date'] = '2026-09-30'
        health = m.build_health(stocks, indices, macro)
        self.assertNotIn('volatility', [part['key'] for part in health['components']])
        self.assertEqual(health['coverage'], 80)

    def full_data(self):
        stocks = {s:fake_stock(s) for s in [x[0] for x in m.WATCHLIST]}
        indices = {s:fake_stock(s) for s in m.SECTORS + ['SPY','SOXX']}
        macro = {'vix':{'value':13,'date':'2026-10-08'},
                 'treasury_10y':{'value':3.1,'date':'2026-10-08'},
                 'brent':{'value':70,'change_5obs_pct':-6,'date':'2026-10-08'},
                 'high_yield_spread':{'value':2.8,'date':'2026-10-08'}}
        return stocks,indices,macro

    def test_health_bullish_full_score(self):
        stocks,indices,macro=self.full_data()
        h=m.build_health(stocks,indices,macro)
        self.assertEqual(h['score'],100)
        self.assertEqual(h['coverage'],100)
        self.assertEqual(len(h['components']),5)

    def test_health_bearish_not_bullish(self):
        stocks,indices,macro=self.full_data()
        for v in stocks.values(): v['price']=50
        for v in indices.values(): v['price']=50
        macro['vix']['value']=43
        macro['treasury_10y']['value']=6
        macro['brent']['change_5obs_pct']=15
        macro['high_yield_spread']['value']=8
        h=m.build_health(stocks,indices,macro)
        self.assertEqual(h['score'],0)
        self.assertEqual(h['coverage'],100)

    def test_missing_inputs_no_fake_score(self):
        h=m.build_health({}, {}, {})
        self.assertIsNone(h['score'])
        self.assertEqual(h['coverage'],0)
        self.assertIsNone(m.build_semi_health({}, {})['score'])

    def test_missing_spy_reference_does_not_publish_a_market_score(self):
        stocks, indices, macro = self.full_data()
        del indices['SPY']
        self.assertIsNone(m.build_health(stocks, indices, macro)['score'])

    def test_chip_health_full(self):
        stocks,indices,_=self.full_data()
        s=m.build_semi_health(stocks,indices)
        self.assertGreaterEqual(s['score'],80)
        self.assertGreaterEqual(s['chip_count'],6)

    def test_semi_excludes_mismatched_chip_and_spy_dates(self):
        stocks, indices, _ = self.full_data()
        for stock in stocks.values(): stock['date'] = '2026-10-08'
        indices['SOXX']['date'] = '2026-10-08'
        indices['SPY']['date'] = '2026-10-07'
        stocks['NVDA']['date'] = '2026-10-07'
        semi = m.build_semi_health(stocks, indices)
        self.assertEqual(semi['chip_count'], 14)
        self.assertEqual(semi['coverage'], 80)

    def test_price_move_alerts(self):
        a=m.alert_for({'change_1d':-6.4,'change_5d':-11,'volume_multiple':2.3,'volume':8000})
        self.assertEqual(len(a),3)
        self.assertEqual(m.alert_for({'change_1d':1,'change_5d':2,'volume_multiple':1.1,'volume':300}),[])

    def test_no_partial_intraday_candle(self):
        from datetime import datetime,timezone
        market_now=m.NOW.astimezone(m.ET)
        if market_now.hour<16:
            dates=[{'date':'2026-01-01'},{'date':market_now.date().isoformat()}]
            self.assertEqual(len(m.keep_completed_bars('NVDA',dates)),1)

    def test_old_quote_rejected(self):
        self.assertFalse(m.accept_market_snapshot({'date':'2020-01-01'}))
        self.assertFalse(m.accept_market_snapshot(None))

    def test_missing_history_no_moving_average(self):
        self.assertIsNone(m.sma([1,2,3],20))
        self.assertIsNone(m.pct(None,20))

    def test_hk_currency_and_actual_candle_dates(self):
        bars=[{'close':10,'volume':1000,'high':12,'low':9,'date':'2026-10-07','ts':1791334800},
              {'close':11,'volume':1200,'high':12,'low':10,'date':'2026-10-08','ts':1791421200}]
        s=m.summarize_candles('0700.HK',bars,'unit')
        self.assertEqual(s['date'],'2026-10-08')
        self.assertEqual(s['currency'],'HKD')
        self.assertEqual(s['change_1d'],10.0)

class MacroLoaderTests(unittest.TestCase):
    """FRED 会屏蔽部分 CI 出口 IP，缺失时必须回退取数而不是整段留空。"""

    def observation(self, key='vix', source='Yahoo Finance · ^VIX (fallback)'):
        return {'key': key, 'name': key, 'unit': '', 'value': 21.5,
                'date': m.NOW.astimezone(m.ET).date().isoformat(),
                'change_5obs': 1.0, 'change_5obs_pct': 4.9,
                'source': source, 'url': 'https://finance.yahoo.com/quote/%5EVIX'}

    def test_yahoo_macro_maps_daily_close_to_observation(self):
        daily = {'symbol': '^VIX', 'price': 21.5, 'date': '2026-10-07', 'change_5d': 4.2,
                 'sparkline': [18, 18.5, 19, 20, 20.5, 21.5]}
        with mock.patch.object(m, 'yahoo_daily', lambda symbol: daily):
            obs = m.yahoo_macro('vix', '^VIX', 'VIX波动率指数', '')
        self.assertEqual(obs['value'], 21.5)
        self.assertEqual(obs['date'], '2026-10-07')
        self.assertEqual(obs['change_5obs_pct'], 4.2)
        self.assertAlmostEqual(obs['change_5obs'], 3.5, places=3)
        self.assertIn('^VIX', obs['source'])
        self.assertIn('yahoo', obs['url'].lower())

    def test_fred_failure_falls_back_to_yahoo(self):
        seen = []
        def fred_fail(*a, **k):
            raise m.requests.ConnectionError('fred blocked')
        def yahoo_ok(key, symbol, label, unit):
            seen.append(key)
            return self.observation(key)
        with mock.patch.object(m, 'fred_series', fred_fail), mock.patch.object(m, 'yahoo_macro', yahoo_ok, create=True):
            out = m.load_fred()
        self.assertEqual(sorted(out), ['brent', 'treasury_10y', 'treasury_30y', 'vix'])
        self.assertEqual(out['vix']['value'], 21.5)
        self.assertEqual(sorted(seen), ['brent', 'treasury_10y', 'treasury_30y', 'vix'])

    def test_fred_success_skips_yahoo_fallback(self):
        def fred_ok(key, series_id, label, unit):
            return self.observation(key, source=f'FRED · {series_id}')
        def yahoo_boom(*a, **k):
            raise AssertionError('FRED 正常时不应调用 Yahoo 兜底')
        with mock.patch.object(m, 'fred_series', fred_ok), mock.patch.object(m, 'yahoo_macro', yahoo_boom, create=True):
            out = m.load_fred()
        self.assertEqual(len(out), len(m.FRED))
        self.assertIn('high_yield_spread', out)

    def test_series_without_yahoo_equivalent_is_dropped(self):
        def fred_fail(*a, **k):
            raise m.requests.ConnectionError('fred blocked')
        def yahoo_ok(key, symbol, label, unit):
            return self.observation(key)
        with mock.patch.object(m, 'fred_series', fred_fail), mock.patch.object(m, 'yahoo_macro', yahoo_ok, create=True):
            out = m.load_fred()
        self.assertNotIn('high_yield_spread', out)


if __name__=='__main__':
    unittest.main()
