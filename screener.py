import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import percentileofscore
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging
import argparse
import sys

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
    ma_200_trending_up: bool      # BUGFIX: store the real value from analyze_stock
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
    # New fields for entry points, earnings, and catalysts
    next_earnings_date: Optional[str] = None
    recent_news: List[str] = None
    entry_zone: Optional[str] = None
    entry_price: Optional[float] = None
    catalyst: Optional[str] = None


class MinerviniScreener:

    def __init__(self):
        # Cache for audit_stock to avoid re-screening the full universe per audit.
        # Keyed by index name ('sp500', 'sp400', 'sp600').
        self._audit_cache: Dict[str, List[StockAnalysis]] = {}

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

        # 200-MA trending up: require 2-month confirmation (today > 22d ago > 44d ago)
        # This prevents single-point noise from passing a stock whose 200-MA is choppy.
        ma200_22d_ago = ma200_series.iloc[-22] if len(ma200_series) > 22 else ma200
        ma200_44d_ago = ma200_series.iloc[-44] if len(ma200_series) > 44 else ma200_22d_ago
        ma200_trending_up = bool(ma200 > ma200_22d_ago and ma200_22d_ago > ma200_44d_ago)

        return {
            'ma_50': float(ma50),
            'ma_150': float(ma150),
            'ma_200': float(ma200),
            'ma_200_trending_up': ma200_trending_up,
        }

    def _identify_entry_zone(
        self,
        current_price: float,
        high_52wk: float,
        low_52wk: float,
        ma_50: float,
        ma_150: float,
        ma_200: float,
        ma_200_trending_up: bool,
    ) -> Tuple[Optional[str], Optional[float]]:
        pct_from_high = ((high_52wk - current_price) / high_52wk) * 100
        pct_from_low = ((current_price - low_52wk) / low_52wk) * 100

        ma_stack_aligned = ma_50 > ma_150 > ma_200

        if pct_from_high <= 5 and ma_stack_aligned:
            return "base_breakout", current_price
        elif pct_from_high <= 15 and ma_stack_aligned and pct_from_low >= 30:
            return "tight_consolidation", current_price
        elif ma_stack_aligned and ma_200_trending_up:
            if abs(current_price - ma_50) / ma_50 <= 0.03:
                return "at_50ma_pullback", ma_50
            elif abs(current_price - ma_150) / ma_150 <= 0.03:
                return "at_150ma_pullback", ma_150
        return None, None

    # ---------------------------------------------------------------------------
    # FIX #2 — RS rating: return raw weighted performance only.
    #           True percentile rank is assigned AFTER all stocks are scored.
    # ---------------------------------------------------------------------------
    def _get_rs_raw_performance(self, sp500_data: pd.DataFrame, stock_data: pd.DataFrame) -> float:
        """
        Weighted relative performance vs benchmark (S&P 500 / 400 / 600).
        Weights: 40% (3 m), 20% (6 m), 20% (9 m), 20% (12 m).
        Returns the raw outperformance figure — NOT a 1-99 score yet.

        NOTE: The percentile rank derived from this is computed against the
        screened universe (i.e., the chosen index), NOT the full broad market.
        IBD's official RS Rating ranks vs. ~7,000 listed stocks. A stock at
        the 60th percentile of the S&P 500 may rank far higher in the broad
        market, and vice versa for small-cap screens. Treat the RS rating
        here as an intra-index measure.
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

        # --- 30% above 52-week low (canonical Minervini Trend Template criterion #6) ---
        if low_52wk > 0:
            pct_above_low = ((current_price - low_52wk) / low_52wk) * 100
            req['30pct_above_52wk_low'] = pct_above_low >= 30
        else:
            req['30pct_above_52wk_low'] = False

        # --- RS rating (Minervini's preferred 80+ threshold) ---
        req['rs_rating_above_80']   = rs_rating >= 80

        # Denominator is now 9 criteria total (7 MA/price + 30%-above-low + RS)
        score = sum(1 for v in req.values() if v)

        # Hard binary: ALL criteria must pass
        all_passed = all(req.values())

        return all_passed, req, score

    # ---------------------------------------------------------------------------
    # Earnings acceleration check (Minervini SEPA fundamental component)
    # ---------------------------------------------------------------------------
    def _check_earnings_acceleration(self, ticker: "yf.Ticker") -> bool:
        """
        Returns True if the last 3 quarters show YoY EPS growth that is
        ACCELERATING (each quarter's YoY growth > prior quarter's YoY growth).
        Fails open (returns False) when data is unavailable or insufficient.
        """
        try:
            qe = None
            # Prefer quarterly_income_stmt (newer yfinance), fall back to quarterly_earnings
            try:
                qis = ticker.quarterly_income_stmt
                if qis is not None and not qis.empty and 'Diluted EPS' in qis.index:
                    qe = qis.loc['Diluted EPS'].dropna()
                elif qis is not None and not qis.empty and 'Basic EPS' in qis.index:
                    qe = qis.loc['Basic EPS'].dropna()
            except Exception:
                qe = None

            if qe is None or len(qe) < 7:
                # Need at least 7 quarters to compute 3 YoY growth points
                return False

            # qe is sorted with most-recent first in yfinance; ensure that order
            qe = qe.sort_index(ascending=False)
            eps_vals = qe.values.astype(float)

            # Compute YoY growth for the 3 most recent quarters
            yoy = []
            for i in range(3):
                cur = eps_vals[i]
                prior = eps_vals[i + 4]
                if prior == 0 or np.isnan(prior) or np.isnan(cur):
                    return False
                # Use absolute value of prior to handle negative-to-positive turnarounds
                growth = (cur - prior) / abs(prior)
                yoy.append(growth)

            # yoy[0] = most recent quarter, yoy[2] = oldest of the three
            # Accelerating means: most recent > prior > older
            return yoy[0] > yoy[1] > yoy[2]
        except Exception:
            return False

    # ---------------------------------------------------------------------------
    # Catalysts and news enrichment (best-effort, fails open)
    # ---------------------------------------------------------------------------
    def _get_next_earnings_date(self, ticker: "yf.Ticker") -> Optional[str]:
        try:
            cal = ticker.calendar
            if cal is None:
                return None
            # yfinance returns a dict in newer versions
            if isinstance(cal, dict):
                ed = cal.get('Earnings Date')
                if ed:
                    if isinstance(ed, list) and len(ed) > 0:
                        return str(ed[0])
                    return str(ed)
            # Older versions returned a DataFrame
            elif hasattr(cal, 'loc') and 'Earnings Date' in getattr(cal, 'index', []):
                val = cal.loc['Earnings Date']
                if hasattr(val, 'iloc'):
                    return str(val.iloc[0])
                return str(val)
        except Exception:
            pass
        return None

    def _get_recent_news(self, ticker: "yf.Ticker", limit: int = 3) -> List[str]:
        try:
            news = ticker.news or []
            titles = []
            for item in news[:limit]:
                # yfinance news item structure varies by version
                title = item.get('title') if isinstance(item, dict) else None
                if not title and isinstance(item, dict):
                    content = item.get('content') or {}
                    title = content.get('title') if isinstance(content, dict) else None
                if title:
                    titles.append(title)
            return titles
        except Exception:
            return []

    def _derive_catalyst(self, next_earnings_date: Optional[str], recent_news: List[str]) -> Optional[str]:
        try:
            if next_earnings_date:
                # Try to parse and detect if within 2 weeks
                for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S'):
                    try:
                        dt = datetime.strptime(next_earnings_date.split('+')[0].strip(), fmt)
                        days = (dt - datetime.now()).days
                        if 0 <= days <= 14:
                            return f"Upcoming earnings in {days}d"
                        break
                    except ValueError:
                        continue
            if recent_news:
                return f"Recent news: {recent_news[0][:80]}"
        except Exception:
            pass
        return None

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

            # yfinance field names: prefer canonical 'trailingEps', fall back for safety
            eps             = info.get('trailingEps') or info.get('epsTrailingTwelveMonths')
            pe              = info.get('trailingPE')
            eps_growth      = info.get('earningsQuarterlyGrowth')
            revenue_growth  = info.get('revenueGrowth')

            # Fundamental score (0-4) — Minervini SEPA fundamental components.
            # PE cap removed: Minervini does not use a PE filter; high-growth winners
            # frequently trade at PEs > 50 and should not be penalized.
            fundamental_score = 0
            if eps and eps > 0:
                fundamental_score += 1
            if eps_growth and eps_growth > 0.25:
                fundamental_score += 1
            if revenue_growth and revenue_growth > 0.25:
                fundamental_score += 1
            # Earnings acceleration across last 3 quarters (Phase 4)
            earnings_accelerating = self._check_earnings_acceleration(ticker)
            if earnings_accelerating:
                fundamental_score += 1

            # Catalysts / news enrichment (best-effort)
            next_earnings_date = self._get_next_earnings_date(ticker)
            recent_news        = self._get_recent_news(ticker)
            catalyst           = self._derive_catalyst(next_earnings_date, recent_news)

            change_pct = (
                ((current_price - float(hist['Close'].iloc[-2])) / float(hist['Close'].iloc[-2])) * 100
                if len(hist) > 1 else 0.0
            )

            entry_zone, entry_price = self._identify_entry_zone(
                current_price, high_52wk, low_52wk,
                ma_data['ma_50'], ma_data['ma_150'], ma_data['ma_200'],
                ma_data['ma_200_trending_up']
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
                ma_200_trending_up=ma_data['ma_200_trending_up'],  # BUGFIX: store real value
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
                next_earnings_date=next_earnings_date,
                recent_news=recent_news,
                entry_zone=entry_zone,
                entry_price=entry_price,
                catalyst=catalyst,
            )
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            return None

    # ---------------------------------------------------------------------------
    # FIX #2 — Percentile rank RS across ALL screened stocks, THEN score/filter
    # FIX #3 — overall_score is 0 for any stock that fails the template
    # FIX #4 — S&P 500 data fetched ONCE here, passed into every analyze_stock call
    # ---------------------------------------------------------------------------
    def screen_candidates(self, symbols: List[str], benchmark_ticker: str = "^GSPC") -> List[StockAnalysis]:
        # FIX #4: fetch benchmark data once
        logger.info(f"Fetching {benchmark_ticker} benchmark data...")
        sp500_data = yf.Ticker(benchmark_ticker).history(period="2y")

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
                    'ma_200_trending_up': r.ma_200_trending_up,  # BUGFIX: use stored value
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

            if score >= 8:
                signals.append(f"Strong trend ({score}/9 criteria)")
            if r.rs_rating >= 80:
                signals.append(f"High relative strength (RS: {r.rs_rating:.0f})")
            if req.get('200ma_trending_up'):
                signals.append("200-day MA trending up (2-month confirmed)")
            if r.eps_growth and r.eps_growth > 0.4:
                signals.append(f"Exceptional EPS growth ({r.eps_growth * 100:.0f}%)")
            if r.catalyst:
                signals.append(r.catalyst)

            r.signals = signals

            # Stocks that fail the template get overall_score = 0
            # RS contributes via its own term only (no double-count)
            # Denominators: trend = 9 criteria, fundamentals = 4 components
            if passed:
                r.overall_score = (
                    (score / 9)           * 50 +   # trend (9 criteria)
                    (r.fundamental_score / 4) * 30 + # fundamentals (EPS+, EPS gr, rev gr, accel)
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
    # S&P 400 (Mid-Cap) symbol list helper
    # ---------------------------------------------------------------------------
    def _get_sp400_symbols(self) -> List[str]:
        try:
            import requests
            from io import StringIO
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, timeout=10, headers=headers)
            dfs = pd.read_html(StringIO(response.text))
            symbols = dfs[0]['Symbol'].str.replace('.', '-', regex=False).tolist()
            return symbols
        except Exception as e:
            logger.warning(f"Failed to fetch S&P 400 list: {e}, using fallback")
            return []

    # ---------------------------------------------------------------------------
    # S&P 600 (Small-Cap) symbol list helper
    # ---------------------------------------------------------------------------
    def _get_sp600_symbols(self) -> List[str]:
        try:
            import requests
            from io import StringIO
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, timeout=10, headers=headers)
            dfs = pd.read_html(StringIO(response.text))
            symbols = dfs[0]['Symbol'].str.replace('.', '-', regex=False).tolist()
            return symbols
        except Exception as e:
            logger.warning(f"Failed to fetch S&P 600 list: {e}, using fallback")
            return []

    # ---------------------------------------------------------------------------
    # Main entry point
    # index: 'sp500' (default), 'sp400', or 'sp600'
    # ---------------------------------------------------------------------------
    def find_top_opportunities(self, minervini_pass_only: bool = True, limit: int = 10, index: str = 'sp500') -> List[StockAnalysis]:
        if index == 'sp400':
            logger.info("Fetching S&P 400 (Mid-Cap) symbols...")
            symbols = self._get_sp400_symbols()
            benchmark = "^SP400"
        elif index == 'sp600':
            logger.info("Fetching S&P 600 (Small-Cap) symbols...")
            symbols = self._get_sp600_symbols()
            benchmark = "^SP600"
        else:
            logger.info("Fetching S&P 500 symbols...")
            symbols = self._get_sp500_symbols()
            benchmark = "^GSPC"

        logger.info(f"Loaded {len(symbols)} symbols")

        results = self.screen_candidates(symbols, benchmark)

        if minervini_pass_only:
            results = [r for r in results if r.minervini_passed]

        return results[:limit]

    # ---------------------------------------------------------------------------
    # Convenience: audit a single stock with full breakdown (great for debugging)
    # ---------------------------------------------------------------------------
    def audit_stock(self, symbol: str, benchmark_ticker: str = "^GSPC") -> None:
        """
        Print a full pass/fail breakdown for a single stock.
        Calculates RS rating by comparing against the appropriate index.

        Uses an instance-level cache (`self._audit_cache`) so consecutive audits
        against the same index reuse a single full screen rather than re-running
        the full universe on every call.
        """
        # Determine which index to use based on benchmark_ticker
        if benchmark_ticker == "^GSPC":
            index = 'sp500'
        elif benchmark_ticker == "^SP400":
            index = 'sp400'
        elif benchmark_ticker == "^SP600":
            index = 'sp600'
        else:
            index = 'sp500'

        symbol_upper = symbol.upper()

        # Use cached results if available for this index
        results = self._audit_cache.get(index)

        # If cache miss OR symbol not in cached results, run the full screen
        if results is None or not any(r.symbol.upper() == symbol_upper for r in results):
            # Get the symbols for the index
            if index == 'sp500':
                symbols = self._get_sp500_symbols()
            elif index == 'sp400':
                symbols = self._get_sp400_symbols()
            elif index == 'sp600':
                symbols = self._get_sp600_symbols()
            else:
                symbols = self._get_sp500_symbols()

            # Make sure our symbol is in the list
            if symbol_upper not in [s.upper() for s in symbols]:
                symbols.append(symbol_upper)

            print(f"Calculating RS rating for {symbol_upper} (running full {index} screen — cached for subsequent audits)...")
            results = self.screen_candidates(symbols, benchmark_ticker)
            self._audit_cache[index] = results
        else:
            print(f"Using cached {index} screen for {symbol_upper}...")

        # Find our stock
        result = next((r for r in results if r.symbol.upper() == symbol_upper), None)
        if not result:
            print(f"Could not fetch data for {symbol}")
            return

        # Now print the audit breakdown
        passed = result.minervini_passed
        req = result.trend_requirements
        score = result.trend_score

        print(f"\n{'='*55}")
        print(f"  MINERVINI AUDIT — {symbol_upper}")
        print(f"{'='*55}")
        print(f"  Price      : ${result.price:.2f}")
        print(f"  50-day MA  : ${result.ma_50:.2f}   (price {'>' if result.price > result.ma_50 else '<'} MA)")
        print(f"  150-day MA : ${result.ma_150:.2f}   (price {'>' if result.price > result.ma_150 else '<'} MA)")
        print(f"  200-day MA : ${result.ma_200:.2f}   (price {'>' if result.price > result.ma_200 else '<'} MA)")
        print(f"  52wk High  : ${result.price_52wk_high:.2f}")
        print(f"  52wk Low   : ${result.price_52wk_low:.2f}")
        pct_above_low = ((result.price - result.price_52wk_low) / result.price_52wk_low * 100) if result.price_52wk_low > 0 else 0.0
        print(f"  Above Low  : {pct_above_low:.1f}%   (need \u2265 30%)")
        print(f"\n  Criteria breakdown:")
        for criterion, value in req.items():
            status = "✅" if value else "❌"
            print(f"    {status}  {criterion}")
        print(f"\n  Trend Score       : {score}/9")
        print(f"  RS Rating         : {result.rs_rating:.0f} (intra-{index} percentile)")
        print(f"  Fundamental Score : {result.fundamental_score}/4 (EPS+, EPS gr, rev gr, accel)")
        if result.next_earnings_date:
            print(f"  Next Earnings     : {result.next_earnings_date}")
        if result.catalyst:
            print(f"  Catalyst          : {result.catalyst}")
        print(f"  RESULT            : {'✅ PASSED' if passed else '❌ FAILED'}")
        print(f"{'='*55}\n")


# ---------------------------------------------------------------------------
# Quick-start
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Minervini Stock Screener')
    parser.add_argument('-sp400', action='store_true', help='Screen S&P 400 (Mid-Cap) stocks')
    parser.add_argument('-sp600', action='store_true', help='Screen S&P 600 (Small-Cap) stocks')
    parser.add_argument('--audit', type=str, help='Audit a specific stock symbol')
    parser.add_argument('--limit', type=int, default=10, help='Number of results to return (default: 10)')
    args = parser.parse_args()

    screener = MinerviniScreener()

    # Determine which index to use
    if args.sp400:
        index = 'sp400'
        index_name = 'S&P 400 (Mid-Cap)'
    elif args.sp600:
        index = 'sp600'
        index_name = 'S&P 600 (Small-Cap)'
    else:
        index = 'sp500'
        index_name = 'S&P 500'

    # Audit specific stock if requested
    if args.audit:
        benchmark_map = {'sp500': '^GSPC', 'sp400': '^SP400', 'sp600': '^SP600'}
        screener.audit_stock(args.audit.upper(), benchmark_map[index])
        sys.exit(0)

    # Audit specific stocks to verify logic
    for ticker in ["MU", "GOOG", "APH", "DELL", "MSFT"]:
        screener.audit_stock(ticker)

    # Full screen — only stocks passing ALL Minervini criteria
    print(f"\nRunning full {index_name} screen...\n")
    top = screener.find_top_opportunities(minervini_pass_only=True, limit=args.limit, index=index)
    for i, s in enumerate(top, 1):
        print(f"{i:2}. {s.symbol:<6}  Score: {s.overall_score:.1f}  RS: {s.rs_rating:.0f}  "
              f"Price: ${s.price:.2f}  Signals: {'; '.join(s.signals)}")
