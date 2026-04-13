import yfinance as yf
import pandas as pd
import numpy as np
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
    rs_rating: float
    trend_score: int
    fundamental_score: int
    overall_score: float
    signals: List[str]


class MinerviniScreener:
    def __init__(self):
        self.minervini_requirements = {
            'above_150ma': False,
            'above_200ma': False,
            '150_above_200': False,
            '200ma_trending_up': False,
            '50_above_150_200': False,
            'above_50ma': False,
            'within_25pct_high': False,
            'above_30pct_low': False,
        }
    
    def _calculate_moving_averages(self, data: pd.DataFrame) -> Dict:
        data = data.sort_index()
        ma50 = data['Close'].rolling(window=50).mean().iloc[-1]
        ma150 = data['Close'].rolling(window=150).mean().iloc[-1]
        ma200_series = data['Close'].rolling(window=200).mean()
        ma200 = ma200_series.iloc[-1]
        
        # Check if 200ma is trending up (comparing current to 20 days ago)
        ma200_20d_ago = ma200_series.iloc[-20] if len(ma200_series) > 20 else ma200
        ma200_trending_up = ma200 > ma200_20d_ago
        
        return {
            'ma_50': ma50, 
            'ma_150': ma150, 
            'ma_200': ma200,
            'ma_200_trending_up': ma200_trending_up
        }
    
    def _check_trend_template(self, ma_data: Dict, current_price: float, high_52wk: float, low_52wk: float) -> Tuple[bool, Dict, int]:
        req = self.minervini_requirements.copy()
        score = 0
        
        req['above_150ma'] = current_price > ma_data['ma_150']
        req['above_200ma'] = current_price > ma_data['ma_200']
        req['150_above_200'] = ma_data['ma_150'] > ma_data['ma_200']
        req['200ma_trending_up'] = ma_data['ma_200_trending_up']
        req['50_above_150_200'] = ma_data['ma_50'] > ma_data['ma_150'] and ma_data['ma_50'] > ma_data['ma_200']
        req['above_50ma'] = current_price > ma_data['ma_50']
        
        distance_from_high = ((high_52wk - current_price) / high_52wk) * 100
        req['within_25pct_high'] = distance_from_high <= 25
        
        above_low = ((current_price - low_52wk) / low_52wk) * 100
        req['above_30pct_low'] = above_low >= 30
        
        for key, value in req.items():
            if value:
                score += 1
        
        all_passed = all(req.values())
        return all_passed, req, score
    
    def _get_rs_rating(self, symbol: str, sp500_data: pd.DataFrame, stock_data: pd.DataFrame) -> float:
        """
        Calculates weighted relative strength (Minervini style proxy)
        Weights: 40% (3m), 20% (6m), 20% (9m), 20% (12m)
        """
        try:
            def get_return(data, days):
                if len(data) < days + 1:
                    return 0
                return (data['Close'].iloc[-1] / data['Close'].iloc[-(days+1)]) - 1

            periods = [63, 126, 189, 252] # approx 3, 6, 9, 12 months
            weights = [0.4, 0.2, 0.2, 0.2]
            
            stock_perf = sum(get_return(stock_data, p) * w for p, w in zip(periods, weights))
            sp_perf = sum(get_return(sp500_data, p) * w for p, w in zip(periods, weights))
            
            # Simple percentile-like mapping
            # In a real scenario, we'd compare this to all other stocks
            # Here we use a heuristic based on performance vs S&P 500
            diff = stock_perf - sp_perf
            rs_score = 70 + (diff * 100) # Base 70, +1 per 1% outperformance
            
            return max(1, min(99, rs_score))
        except:
            return 50.0
    
    def analyze_stock(self, symbol: str) -> Optional[StockAnalysis]:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            hist = ticker.history(period="2y")
            if len(hist) < 200:
                logger.warning(f"Insufficient data for {symbol}")
                return None
            
            current_price = hist['Close'].iloc[-1]
            high_52wk = hist['High'].max()
            low_52wk = hist['Low'].min()
            
            sp500 = yf.Ticker("^GSPC").history(period="2y")
            
            ma_data = self._calculate_moving_averages(hist)
            trend_passed, trend_req, trend_score = self._check_trend_template(
                ma_data, current_price, high_52wk, low_52wk
            )
            
            rs_rating = self._get_rs_rating(symbol, sp500, hist)
            
            eps = info.get('epsTrailingTwelveMonths')
            pe = info.get('trailingPE')
            eps_growth = info.get('earningsQuarterlyGrowth')
            revenue_growth = info.get('revenueGrowth')
            
            fundamental_score = 0
            if eps and eps > 0:
                fundamental_score += 1
            if pe and 0 < pe < 50: # Minervini is flexible on PE if growth is high
                fundamental_score += 1
            if eps_growth and eps_growth > 0.25: # Minervini looks for 25-50%+
                fundamental_score += 1
            if revenue_growth and revenue_growth > 0.25:
                fundamental_score += 1
            
            signals = []
            if trend_passed:
                signals.append("MINERVINI TREND TEMPLATE PASSED")
            if trend_score >= 6:
                signals.append(f"Strong trend ({trend_score}/8)")
            if rs_rating >= 80:
                signals.append(f"High relative strength (RS: {rs_rating:.0f})")
            if ma_data['ma_200_trending_up']:
                signals.append("Long-term 200d MA trending up")
            if eps_growth and eps_growth > 0.4:
                signals.append(f"Exceptional earnings growth ({eps_growth*100:.0f}%)")
            
            overall_score = (trend_score / 8 * 50) + (fundamental_score / 4 * 30) + (rs_rating / 100 * 20)
            
            change_pct = ((current_price - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100 if len(hist) > 1 else 0
            
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
                rs_rating=rs_rating,
                trend_score=trend_score,
                fundamental_score=fundamental_score,
                overall_score=overall_score,
                signals=signals
            )
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            return None
    
    def screen_candidates(self, symbols: List[str]) -> List[StockAnalysis]:
        results = []
        for symbol in symbols:
            logger.info(f"Analyzing {symbol}...")
            analysis = self.analyze_stock(symbol)
            if analysis:
                results.append(analysis)
        
        results.sort(key=lambda x: x.overall_score, reverse=True)
        return results
    
    def _get_sp500_symbols(self) -> List[str]:
        try:
            import requests
            from io import StringIO
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, timeout=10, headers=headers)
            dfs = pd.read_html(StringIO(response.text))
            df = dfs[0]
            symbols = df['Symbol'].str.replace('.', '-', regex=False).tolist()
            return symbols
        except Exception as e:
            logger.warning(f"Failed to fetch S&P 500 list: {e}, using fallback")
            return [
                'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'UNH', 'JNJ',
                'V', 'XOM', 'JPM', 'PG', 'MA', 'HD', 'CVX', 'LLY', 'ABBV', 'MRK',
                'AVGO', 'PEP', 'COST', 'KO', 'TMO', 'MCD', 'CSCO', 'ACN', 'WMT', 'DIS'
            ]
    
    def find_top_opportunities(self, minervini_pass_only: bool = True, limit: int = 10) -> List[StockAnalysis]:
        logger.info("Fetching S&P 500 symbols...")
        popular_stocks = self._get_sp500_symbols()
        logger.info(f"Loaded {len(popular_stocks)} S&P 500 stocks")
        
        results = self.screen_candidates(popular_stocks)
        
        if minervini_pass_only:
            results = [r for r in results if 'MINERVINI TREND TEMPLATE PASSED' in r.signals]
        
        return results[:limit]