"""Deterministic scoring tests with artificial INPUTS, not published market prices."""
import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'scripts' / 'update_data.py'
spec = importlib.util.spec_from_file_location('market_daily', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fake_stock(symbol, price=100, high=105, change5=3):
    return {'symbol': symbol, 'price': price, 'sma20': 90, 'sma50': 90, 'sma200': 85,
            'change_1d':2,'change_5d':change5,'high20':high,
            'currency':'HKD' if symbol.endswith('.HK') else 'USD'}


class HealthTests(unittest.TestCase):
    def full_data(self):
        stocks = {s:fake_stock(s) for s in [x[0] for x in m.WATCHLIST]}
        indices = {s:fake_stock(s) for s in m.SECTORS + ['SPY','SOXX']}
        macro = {'vix':{'value':13,'date':'2026-10-08'},
                 'treasury_10y':{'value':3.1,'date':'2026-10-08'},
                 'brent':{'value':70,'change_5obs_pct':-6},
                 'high_yield_spread':{'value':2.8}}
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

    def test_chip_health_full(self):
        stocks,indices,_=self.full_data()
        s=m.build_semi_health(stocks,indices)
        self.assertGreaterEqual(s['score'],80)
        self.assertGreaterEqual(s['chip_count'],6)

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

if __name__=='__main__':
    unittest.main()
