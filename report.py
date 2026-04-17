import pandas as pd
import yfinance as yf
from datetime import datetime
from typing import List
from scipy.stats import percentileofscore
from portfolio import PortfolioManager
from screener import MinerviniScreener, StockAnalysis
from notifier import EmailNotifier
from api_clients import fetch_stock_data


class ReportGenerator:
    def __init__(self, holdings_csv: str = "/home/alau/long_term_investing/holdings.csv"):
        self.portfolio = PortfolioManager(holdings_csv)
        self.screener = MinerviniScreener()
        self.notifier = EmailNotifier()
    
    def format_price(self, price: float) -> str:
        return f"${price:.2f}"
    
    def format_pct(self, pct: float) -> str:
        sign = "+" if pct > 0 else ""
        return f"{sign}{pct:.2f}%"
    
    def _get_status(self, analysis: StockAnalysis) -> str:
        if 'MINERVINI TREND TEMPLATE PASSED' in analysis.signals:
            return "OPTIMAL"
        elif analysis.trend_score >= 4:
            return "GOOD"
        elif analysis.trend_score >= 3:
            return "WEAK"
        else:
            return "SELL/WATCH"
    
    def _get_action(self, current_status: str) -> str:
        actions = {
            "OPTIMAL": "HOLD - Strong position maintained",
            "GOOD": "HOLD - Monitor for changes",
            "WEAK": "REVIEW - Consider reducing position",
            "SELL/WATCH": "SELL - No longer meets criteria"
        }
        return actions.get(current_status, "HOLD")
    
    def generate_report(self, recipient: str) -> bool:
        print("Generating weekly report...")

        print("\n=== Fetching external data ===")
        holdings_symbols = self.portfolio.get_symbols()
        opportunity_symbols = []
        print("\n=== Analyzing current holdings ===")
        sp500_data = yf.Ticker("^GSPC").history(period="2y")
        current_holdings = []
        for symbol in holdings_symbols:
            print(f"Checking {symbol}...")
            analysis = self.screener.analyze_stock(symbol, sp500_data)
            if analysis:
                # Need to compute RS rating and run full trend template check
                all_symbols = holdings_symbols
                all_raw_perfs = {}
                for sym in all_symbols:
                    a = self.screener.analyze_stock(sym, sp500_data)
                    if a:
                        all_raw_perfs[sym] = a.rs_raw_perf
                
                if analysis.symbol in all_raw_perfs:
                    all_raw = list(all_raw_perfs.values())
                    analysis.rs_rating = float(percentileofscore(all_raw, analysis.rs_raw_perf, kind='rank'))
                
                passed, req, score = self.screener._check_trend_template(
                    ma_data={
                        'ma_50': analysis.ma_50,
                        'ma_150': analysis.ma_150,
                        'ma_200': analysis.ma_200,
                        'ma_200_trending_up': analysis.ma_200_trending_up,
                    },
                    current_price=analysis.price,
                    high_52wk=analysis.price_52wk_high,
                    low_52wk=analysis.price_52wk_low,
                    rs_rating=analysis.rs_rating,
                )
                analysis.minervini_passed = passed
                analysis.trend_score = score
                analysis.trend_requirements = req
                
                signals = []
                if passed:
                    signals.append("✅ MINERVINI TREND TEMPLATE PASSED")
                else:
                    failed = [k for k, v in req.items() if not v]
                    signals.append(f"❌ Failed criteria: {', '.join(failed)}")
                if score >= 7:
                    signals.append(f"Strong trend ({score}/9 criteria)")
                if analysis.rs_rating >= 80:
                    signals.append(f"High relative strength (RS: {analysis.rs_rating:.0f})")
                analysis.signals = signals
                
                current_holdings.append(analysis)
        
        print("\n=== Finding top opportunities ===")
        opportunities = self.screener.find_top_opportunities(minervini_pass_only=True, limit=10)

        all_symbols_for_api = [o.symbol for o in opportunities] + holdings_symbols
        print(f"Fetching earnings and news data for {len(all_symbols_for_api)} symbols...")
        external_data = fetch_stock_data(all_symbols_for_api, use_finnhub=True)

        for o in opportunities:
            if o.symbol in external_data:
                data = external_data[o.symbol]
                o.next_earnings_date = data.get("next_earnings")
                o.recent_news = data.get("recent_news", [])
                o.catalyst = data.get("catalyst")

        for h in current_holdings:
            if h.symbol in external_data:
                data = external_data[h.symbol]
                h.next_earnings_date = data.get("next_earnings")
                h.recent_news = data.get("recent_news", [])
                h.catalyst = data.get("catalyst")
        
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #2c3e50; }}
                h2 {{ color: #34495e; border-bottom: 2px solid #3498db; padding-bottom: 5px; }}
                table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
                th {{ background-color: #3498db; color: white; }}
                .optimal {{ color: #27ae60; font-weight: bold; }}
                .good {{ color: #2980b9; }}
                .weak {{ color: #f39c12; }}
                .sell {{ color: #e74c3c; font-weight: bold; }}
                .positive {{ color: #27ae60; }}
                .negative {{ color: #e74c3c; }}
                .signals {{ background-color: #ecf0f1; padding: 10px; border-radius: 5px; }}
                .summary {{ background-color: #e8f6f3; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <h1>📈 Weekly Stock Report</h1>
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
            
            <div class="summary">
                <h3>Summary</h3>
                <p><strong>Current Holdings:</strong> {len(current_holdings)} stocks</p>
                <p><strong>Optimal Positions:</strong> {sum(1 for h in current_holdings if self._get_status(h) == 'OPTIMAL')}</p>
                <p><strong>Top Opportunities:</strong> {len(opportunities)} stocks passing Minervini template</p>
            </div>
            
            <h2>Current Holdings Analysis</h2>
            <table>
                <tr>
                    <th>Symbol</th>
                    <th>Price</th>
                    <th>Change</th>
                    <th>RS Rating</th>
                    <th>Trend Score</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
        """
        
        for holding in current_holdings:
            status = self._get_status(holding)
            action = self._get_action(status)
            price_class = "positive" if holding.change_pct >= 0 else "negative"
            status_class = status.lower()
            
            html += f"""
                <tr>
                    <td><strong>{holding.symbol}</strong><br><small>{holding.name}</small></td>
                    <td>{self.format_price(holding.price)}</td>
                    <td class="{price_class}">{self.format_pct(holding.change_pct)}</td>
                    <td>{holding.rs_rating:.0f}</td>
                    <td>{holding.trend_score}/9</td>
                    <td class="{status_class}">{status}</td>
                    <td>{action}</td>
                </tr>
            """
        
        html += """
            </table>
            
            <h2>Top 10 Opportunities (Minervini Pass)</h2>
        """
        
        if opportunities:
            html += """
            <table>
                <tr>
                    <th>Symbol</th>
                    <th>Price</th>
                    <th>Entry Zone</th>
                    <th>RS Rating</th>
                    <th>Trend Score</th>
                    <th>Next Earnings</th>
                    <th>Catalyst</th>
                </tr>
            """
            for opp in opportunities:
                entry_zone = opp.entry_zone or "-"
                earnings = opp.next_earnings_date or "-"
                catalyst = opp.catalyst or "-"
                html += f"""
                <tr>
                    <td><strong>{opp.symbol}</strong><br><small>{opp.name}</small></td>
                    <td>{self.format_price(opp.price)}</td>
                    <td>{entry_zone}</td>
                    <td>{opp.rs_rating:.0f}</td>
                    <td>{opp.trend_score}/9</td>
                    <td>{earnings}</td>
                    <td>{catalyst}</td>
                </tr>
                """
            html += "</table>"
        else:
            html += "<p>No stocks currently passing the Minervini template.</p>"

        if opportunities and any(o.recent_news for o in opportunities):
            html += """
            <h2>Recent Catalysts (News)</h2>
            <table>
                <tr>
                    <th>Symbol</th>
                    <th>Recent Headlines</th>
                </tr>
            """
            for opp in opportunities:
                if opp.recent_news:
                    news_html = "<br>".join(opp.recent_news[:2])
                    html += f"""
                    <tr>
                        <td><strong>{opp.symbol}</strong></td>
                        <td>{news_html}</td>
                    </tr>
                    """
            html += "</table>"
        
        html += """
            <h2>Understanding the Report</h2>
            <ul>
                <li><strong>RS Rating:</strong> Weighted relative strength vs S&P 500 (0-100, higher is better)</li>
                <li><strong>Trend Score:</strong> Minervini template checks passed (0-9)</li>
                <li><strong>OPTIMAL:</strong> Stock meets ALL 9 Minervini trend criteria + fundamentals</li>
                <li><strong>GOOD:</strong> Most criteria met (7+/9) - hold position</li>
                <li><strong>WEAK:</strong> Losing momentum (5-6/9) - review position</li>
                <li><strong>SELL/WATCH:</strong> No longer meets core criteria (<5/9) - consider selling</li>
            </ul>
            
            <p style="margin-top: 30px; color: #7f8c8d; font-size: 12px;">
                This report is generated based on Mark Minervini's stock selection method.
                Always do your own due diligence before making investment decisions.
            </p>
        </body>
        </html>
        """
        
        subject = f"Weekly Stock Report - {datetime.now().strftime('%Y-%m-%d')}"
        return self.notifier.send_report(recipient, subject, html)
    
    def run_weekly(self):
        recipient = "alau1158@gmail.com"
        self.generate_report(recipient)


if __name__ == "__main__":
    report = ReportGenerator()
    report.run_weekly()