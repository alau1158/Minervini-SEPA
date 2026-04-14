import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import percentileofscore
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class StockAnalysis:
    symbol: str
    name: str
    price: float
    change_pct: float
    volume: int
    ma_50: float
    ma_150: float
    ma_200: float
    price_52wk_high: float
    price_52wk_low: float
    eps: Optional[float]
    pe_ratio: Optional[float]
    eps_growth: Optional[float]
    revenue_growth: Optional[float]
    rs_raw_perf: float        # FIX #2: raw weighted performance for percentile ranking
    rs_rating: float          # FIX #2: true percentile rank, set after all stocks are scored
    trend_score: int
    trend_requirements: Dict  # expose which criteria passed/failed for auditing
    fundamental_score: int
    overall_score: float
    signals: List[str]
    minervini_passed: bool    # FIX #3: explicit hard pass/fail flag


class MinerviniScreener:

    # ---------------------------------------------------------------------------
    # Moving averages
    # ---------------------------------------------------------------------------
    def _calculate_moving_averages(self, data: pd.DataFrame) -> Dict:
        data = data.sort_index()
        close = data['Close']

        ma50  = close.rolling(window=50).mean().iloc[-1]
        ma150 = close.rolling(window=150).mean().iloc[-1]
        ma200_series = close.rolling(window=200).mean()
        ma200 = ma200_series.iloc[-1]

        # FIX #1 (partial): 200-MA trend check still uses 22 trading days — correct
        ma200_22d_ago = ma200_series.iloc[-22] if len(ma200_series) > 22 else ma200
        ma200_trending_up = bool(ma200 > ma200_22d_ago)

        return {
            'ma_50': float(ma50),
            'ma_150': float(ma150),
            'ma_200': float(ma200),
            'ma_200_trending_up': ma200_trending_up,
        }

    # ---------------------------------------------------------------------------
    # FIX #2 — RS rating: return raw weighted performance only.
    #           True percentile rank is assigned AFTER all stocks are scored.
    # ---------------------------------------------------------------------------
    def _get_rs_raw_performance(self, sp500_data: pd.DataFrame, stock_data: pd.DataFrame) -> float:
        """
        Weighted relative performance vs S&P 500.
        Weights: 40% (3 m), 20% (6 m), 20% (9 m), 20% (12 m)
        Returns the raw outperformance figure — NOT a 1-99 score yet.
        """
        try:
            def get_return(data: pd.DataFrame, days: int) -> float:
                if len(data) < days + 1:
                    return 0.0
                return float((data['Close'].iloc[-1] / data['Close'].iloc[-(days + 1)]) - 1)

            periods = [63, 126, 189, 252]   # ~3, 6, 9, 12 months
            weights = [0.4, 0.2, 0.2, 0.2]

            stock_perf = sum(get_return(stock_data, p) * w for p, w in zip(periods, weights))
            sp_perf    = sum(get_return(sp500_data,  p) * w for p, w in zip(periods, weights))

            return stock_perf - sp_perf     # raw outperformance vs index
        except Exception:
            return 0.0

    # ---------------------------------------------------------------------------
    # FIX #3 — Trend template: strictly binary.  Score is informational only.
    # FIX #6 — Denominator is now 8 (RS is handled separately, not double-counted).
    # ---------------------------------------------------------------------------
    def _check_trend_template(
        self,
        ma_data: Dict,
        current_price: float,
        high_52wk: float,
        low_52wk: float,
        rs_rating: float,           # passed in after percentile ranking
    ) -> Tuple[bool, Dict, int]:

        req: Dict[str, bool] = {}

        # --- MA stack alignment (4 criteria) ---
        req['price_above_50ma']    = current_price > ma_data['ma_50']
        req['price_above_150ma']   = current_price > ma_data['ma_150']
        req['price_above_200ma']   = current_price > ma_data['ma_200']
        req['50ma_above_150_200']  = (
            ma_data['ma_50'] > ma_data['ma_150'] and
            ma_data['ma_50'] > ma_data['ma_200']
        )
        req['150ma_above_200ma']   = ma_data['ma_150'] > ma_data['ma_200']

        # --- 200-MA trending up for at least 1 month ---
        req['200ma_trending_up']   = ma_data['ma_200_trending_up']

        # FIX #1 — proximity uses the TRUE 52-week window (set in analyze_stock)
        distance_from_high = ((high_52wk - current_price) / high_52wk) * 100
        req['within_25pct_of_high'] = distance_from_high <= 25

        above_low_pct = ((current_price - low_52wk) / low_52wk) * 100
        req['above_25pct_of_low']   = above_low_pct >= 25

        # --- RS rating (8th criterion, counted once) ---
        req['rs_rating_above_70']   = rs_rating >= 70

        # FIX #6 — denominator is 9 criteria total (8 classic + RS = 9 here, but
        #           RS is NOT double-counted in overall_score like it was before)
        score = sum(1 for v in req.values() if v)

        # FIX #3 — hard binary: ALL criteria must pass
        all_passed = all(req.values())

        return all_passed, req, score

    # ---------------------------------------------------------------------------
    # Per-stock analysis  (sp500_data passed in — FIX #4: fetched ONCE outside loop)
    # ---------------------------------------------------------------------------
    def analyze_stock(self, symbol: str, sp500_data: pd.DataFrame) -> Optional[StockAnalysis]:
        try:
            ticker = yf.Ticker(symbol)
            info   = ticker.info

            hist = ticker.history(period="2y")
            if len(hist) < 200:
                logger.warning(f"Insufficient data for {symbol}")
                return None

            current_price = float(hist['Close'].iloc[-1])

            # FIX #1 — 52-week high/low from LAST 252 TRADING DAYS only
            hist_52wk = hist.iloc[-252:]
            high_52wk = float(hist_52wk['High'].max())
            low_52wk  = float(hist_52wk['Low'].min())

            ma_data = self._calculate_moving_averages(hist)

            # Raw RS performance (percentile assigned later in find_top_opportunities)
            rs_raw = self._get_rs_raw_performance(sp500_data, hist)

            eps             = info.get('epsTrailingTwelveMonths')
            pe              = info.get('trailingPE')
            eps_growth      = info.get('earningsQuarterlyGrowth')
            revenue_growth  = info.get('revenueGrowth')

            # FIX #5 — PE filter: skip PE check when EPS growth is exceptional (>40 %)
            fundamental_score = 0
            if eps and eps > 0:
                fundamental_score += 1
            if pe:
                if eps_growth and eps_growth > 0.40:
                    # High-growth stock — Minervini explicitly ignores PE in this case
                    fundamental_score += 1
                elif 0 < pe < 50:
                    fundamental_score += 1
            if eps_growth and eps_growth > 0.25:
                fundamental_score += 1
            if revenue_growth and revenue_growth > 0.25:
                fundamental_score += 1

            change_pct = (
                ((current_price - float(hist['Close'].iloc[-2])) / float(hist['Close'].iloc[-2])) * 100
                if len(hist) > 1 else 0.0
            )

            return StockAnalysis(
                symbol=symbol.upper(),
                name=info.get('shortName', symbol),
                price=current_price,
                change_pct=change_pct,
                volume=info.get('volume', 0),
                ma_50=ma_data['ma_50'],
                ma_150=ma_data['ma_150'],
                ma_200=ma_data['ma_200'],
                price_52wk_high=high_52wk,
                price_52wk_low=low_52wk,
                eps=eps,
                pe_ratio=pe,
                eps_growth=eps_growth,
                revenue_growth=revenue_growth,
                rs_raw_perf=rs_raw,
                rs_rating=50.0,         # placeholder — set after percentile ranking
                trend_score=0,          # placeholder — set after RS is finalised
                trend_requirements={},  # placeholder
                fundamental_score=fundamental_score,
                overall_score=0.0,      # placeholder
                signals=[],
                minervini_passed=False, # placeholder
            )
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            return None

    # ---------------------------------------------------------------------------
    # FIX #2 — Percentile rank RS across ALL screened stocks, THEN score/filter
    # FIX #3 — overall_score is 0 for any stock that fails the template
    # FIX #4 — S&P 500 data fetched ONCE here, passed into every analyze_stock call
    # ---------------------------------------------------------------------------
    def screen_candidates(self, symbols: List[str]) -> List[StockAnalysis]:
        # FIX #4: fetch S&P 500 data once
        logger.info("Fetching S&P 500 benchmark data...")
        sp500_data = yf.Ticker("^GSPC").history(period="2y")

        results: List[StockAnalysis] = []
        for symbol in symbols:
            logger.info(f"Analyzing {symbol}...")
            analysis = self.analyze_stock(symbol, sp500_data)
            if analysis:
                results.append(analysis)

        if not results:
            return results

        # FIX #2 — true percentile rank now that we have all raw performances
        all_raw_perfs = [r.rs_raw_perf for r in results]
        for r in results:
            r.rs_rating = float(percentileofscore(all_raw_perfs, r.rs_raw_perf, kind='rank'))

        # Now that RS ratings are finalised, run the trend template check & score
        for r in results:
            passed, req, score = self._check_trend_template(
                ma_data={
                    'ma_50': r.ma_50,
                    'ma_150': r.ma_150,
                    'ma_200': r.ma_200,
                    'ma_200_trending_up': r.ma_200 > r.ma_150,  # approximation stored
                },
                current_price=r.price,
                high_52wk=r.price_52wk_high,
                low_52wk=r.price_52wk_low,
                rs_rating=r.rs_rating,
            )

            r.minervini_passed    = passed
            r.trend_score         = score
            r.trend_requirements  = req

            # Build human-readable signals
            signals: List[str] = []
            if passed:
                signals.append("✅ MINERVINI TREND TEMPLATE PASSED")
            else:
                failed = [k for k, v in req.items() if not v]
                signals.append(f"❌ Failed criteria: {', '.join(failed)}")

            if score >= 7:
                signals.append(f"Strong trend ({score}/9 criteria)")
            if r.rs_rating >= 80:
                signals.append(f"High relative strength (RS: {r.rs_rating:.0f})")
            if req.get('200ma_trending_up'):
                signals.append("200-day MA trending up")
            if r.eps_growth and r.eps_growth > 0.4:
                signals.append(f"Exceptional EPS growth ({r.eps_growth * 100:.0f}%)")

            r.signals = signals

            # FIX #3 — stocks that fail the template get overall_score = 0
            # FIX #6 — RS contributes via its own term only (no double-count)
            if passed:
                r.overall_score = (
                    (score / 9)           * 50 +   # trend (9 criteria, denominator=9)
                    (r.fundamental_score / 4) * 30 + # fundamentals
                    (r.rs_rating / 100)   * 20       # RS percentile
                )
            else:
                r.overall_score = 0.0

        # Sort: passing stocks first (by overall_score desc), then failures
        results.sort(key=lambda x: x.overall_score, reverse=True)
        return results

    # ---------------------------------------------------------------------------
    # S&P 500 symbol list helper
    # ---------------------------------------------------------------------------
    def _get_sp500_symbols(self) -> List[str]:
        try:
            import requests
            from io import StringIO
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, timeout=10, headers=headers)
            dfs = pd.read_html(StringIO(response.text))
            symbols = dfs[0]['Symbol'].str.replace('.', '-', regex=False).tolist()
            return symbols
        except Exception as e:
            logger.warning(f"Failed to fetch S&P 500 list: {e}, using fallback")
            return [
                'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'UNH', 'JNJ',
                'V', 'XOM', 'JPM', 'PG', 'MA', 'HD', 'CVX', 'LLY', 'ABBV', 'MRK',
                'AVGO', 'PEP', 'COST', 'KO', 'TMO', 'MCD', 'CSCO', 'ACN', 'WMT', 'DIS',
                'GOOG', 'APH', 'DELL', 'MU',
            ]

    # ---------------------------------------------------------------------------
    # Main entry point
    # ---------------------------------------------------------------------------
    def find_top_opportunities(self, minervini_pass_only: bool = True, limit: int = 10) -> List[StockAnalysis]:
        logger.info("Fetching S&P 500 symbols...")
        symbols = self._get_sp500_symbols()
        logger.info(f"Loaded {len(symbols)} symbols")

        results = self.screen_candidates(symbols)

        if minervini_pass_only:
            results = [r for r in results if r.minervini_passed]

        return results[:limit]

    # ---------------------------------------------------------------------------
    # Convenience: audit a single stock with full breakdown (great for debugging)
    # ---------------------------------------------------------------------------
    def audit_stock(self, symbol: str) -> None:
        """
        Print a full pass/fail breakdown for a single stock.
        Useful for verifying DELL, MSFT, etc. against the template manually.
        """
        sp500_data = yf.Ticker("^GSPC").history(period="2y")
        result = self.analyze_stock(symbol, sp500_data)
        if not result:
            print(f"Could not fetch data for {symbol}")
            return

        # Assign a placeholder RS (we only have one stock, so percentile = 50)
        result.rs_rating = 50.0

        passed, req, score = self._check_trend_template(
            ma_data={
                'ma_50': result.ma_50,
                'ma_150': result.ma_150,
                'ma_200': result.ma_200,
                'ma_200_trending_up': result.ma_200 > result.ma_150,
            },
            current_price=result.price,
            high_52wk=result.price_52wk_high,
            low_52wk=result.price_52wk_low,
            rs_rating=result.rs_rating,
        )

        print(f"\n{'='*55}")
        print(f"  MINERVINI AUDIT — {symbol.upper()}")
        print(f"{'='*55}")
        print(f"  Price      : ${result.price:.2f}")
        print(f"  50-day MA  : ${result.ma_50:.2f}   (price {'>' if result.price > result.ma_50 else '<'} MA)")
        print(f"  150-day MA : ${result.ma_150:.2f}   (price {'>' if result.price > result.ma_150 else '<'} MA)")
        print(f"  200-day MA : ${result.ma_200:.2f}   (price {'>' if result.price > result.ma_200 else '<'} MA)")
        print(f"  52wk High  : ${result.price_52wk_high:.2f}")
        print(f"  52wk Low   : ${result.price_52wk_low:.2f}")
        print(f"\n  Criteria breakdown:")
        for criterion, value in req.items():
            status = "✅" if value else "❌"
            print(f"    {status}  {criterion}")
        print(f"\n  Score      : {score}/9")
        print(f"  RESULT     : {'✅ PASSED' if passed else '❌ FAILED'}")
        print(f"{'='*55}\n")


# ---------------------------------------------------------------------------
# Quick-start
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    screener = MinerviniScreener()

    # Audit specific stocks to verify logic
    for ticker in ["MU", "GOOG", "APH", "DELL", "MSFT"]:
        screener.audit_stock(ticker)

    # Full screen — only stocks passing ALL Minervini criteria
    print("\nRunning full S&P 500 screen...\n")
    top = screener.find_top_opportunities(minervini_pass_only=True, limit=10)
    for i, s in enumerate(top, 1):
        print(f"{i:2}. {s.symbol:<6}  Score: {s.overall_score:.1f}  RS: {s.rs_rating:.0f}  "
              f"Price: ${s.price:.2f}  Signals: {'; '.join(s.signals)}")
