import os
import sys
import pandas as pd
import yfinance as yf
from datetime import datetime
from typing import List
from scipy.stats import percentileofscore
from dotenv import load_dotenv
import argparse

load_dotenv()

from screener import MinerviniScreener, StockAnalysis
from notifier import EmailNotifier
from api_clients import fetch_stock_data
from ai_analyst import get_ai_analysis


class ReportGenerator:
    def __init__(self):
        self.screener = MinerviniScreener()
        self.notifier = EmailNotifier()
    
    def format_price(self, price: float) -> str:
        return f"${price:.2f}"
    
    def format_pct(self, pct: float) -> str:
        sign = "+" if pct > 0 else ""
        return f"{sign}{pct:.2f}%"
    
    def generate_report(self, recipient: str, index: str = 'sp500') -> bool:
        # Map index to display name
        index_names = {
            'sp500': 'S&P 500',
            'sp400': 'S&P 400 (Mid-Cap)',
            'sp600': 'S&P 600 (Small-Cap)'
        }
        index_name = index_names.get(index, 'S&P 500')

        print(f"Generating weekly report for {index_name}...")

        print("\n=== Finding top opportunities ===")
        opportunities = self.screener.find_top_opportunities(minervini_pass_only=True, limit=10, index=index)

        # Sort by RS rating (highest first)
        opportunities.sort(key=lambda x: x.rs_rating, reverse=True)

        all_symbols_for_api = [o.symbol for o in opportunities]
        print(f"Fetching earnings and news data for {len(all_symbols_for_api)} symbols...")
        external_data = fetch_stock_data(all_symbols_for_api, use_finnhub=True)

        for o in opportunities:
            if o.symbol in external_data:
                data = external_data[o.symbol]
                o.next_earnings_date = data.get("next_earnings")
                o.recent_news = data.get("recent_news", [])
                o.catalyst = data.get("catalyst")

        print("\n=== Running AI Analysis (Gemini Pro) ===")
        ai_analysis = get_ai_analysis(opportunities)

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
                .ai-buy {{ color: #27ae60; font-weight: bold; }}
                .ai-hold {{ color: #f39c12; }}
                .ai-skip {{ color: #e74c3c; }}
            </style>
        </head>
        <body>
            <h1>📈 Minervini SEPA - {index_name} - {datetime.now().strftime('%Y-%m-%d')}</h1>
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

            <div class="summary">
                <h3>Summary</h3>
                <p><strong>Index:</strong> {index_name}</p>
                <p><strong>Top Opportunities:</strong> {len(opportunities)} stocks passing Minervini template</p>
            </div>

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
                    <th>22-Day ATR %</th>
                    <th>Next Earnings</th>
                    <th>AI Catalysts</th>
                    <th>Entry Price</th>
                </tr>
            """
            for opp in opportunities:
                entry_zone = opp.entry_zone or "-"
                earnings = opp.next_earnings_date or "-"
                ai = ai_analysis.get(opp.symbol) if ai_analysis else None
                if ai and ai.key_catalysts:
                    catalysts_html = "<br>".join(ai.key_catalysts[:3])
                else:
                    catalysts_html = "-"
                ai_entry = self.format_price(ai.estimated_entry_price) if ai and ai.estimated_entry_price else "-"
                atr_pct = f"{opp.atr_pct:.2f}%" if opp.atr_pct else "-"
                html += f"""
                <tr>
                    <td><strong>{opp.symbol}</strong><br><small>{opp.name}</small></td>
                    <td>{self.format_price(opp.price)}</td>
                    <td>{entry_zone}</td>
                    <td>{opp.rs_rating:.0f}</td>
                    <td>{opp.trend_score}/9</td>
                    <td>{atr_pct}</td>
                    <td>{earnings}</td>
                    <td>{catalysts_html}</td>
                    <td>{ai_entry}</td>
                </tr>
                """
            html += "</table>"
        else:
            html += "<p>No stocks currently passing the Minervini template.</p>"

        html += """
            <h2>Understanding the Report</h2>
            <ul>
                <li><strong>RS Rating:</strong> Weighted relative strength vs S&P 500 (0-100, higher is better)</li>
                <li><strong>Trend Score:</strong> Minervini template checks passed (0-9)</li>
                <li><strong>AI Catalysts:</strong> Key catalysts identified by AI analysis (first 5 stocks)</li>
                <li><strong>Entry Price:</strong> AI-suggested entry price based on technical setup</li>
            </ul>

            <h2>Minervini Trend Template Criteria (9 Total)</h2>
            <ol>
                <li>Current price > 50-day moving average</li>
                <li>Current price > 150-day moving average</li>
                <li>Current price > 200-day moving average</li>
                <li>50-day MA > 150-day MA and 50-day MA > 200-day MA</li>
                <li>150-day MA > 200-day MA</li>
                <li>200-day MA trending up (2-month confirmed)</li>
                <li>Price within 25% of 52-week high</li>
                <li>Price ≥30% above 52-week low</li>
                <li>RS rating (intra-index percentile) ≥80</li>
            </ol>

            <h2>Position Sizing Formula (Risk Management)</h2>
            <p><strong>Shares to Buy = 0.02(T) / (E)(1.5)(A)</strong></p>
            <ul>
                <li><strong>T</strong> = Total portfolio size</li>
                <li><strong>E</strong> = Entry price</li>
                <li><strong>A</strong> = 22-Day ATR % (as decimal, e.g., 2.5% = 0.025)</li>
            </ul>
            <p><em>Example: For a $100,000 portfolio, entry at $50, ATR% of 2.5%:<br>
            Shares = 0.02($100,000) / ($50)(1.5)(0.025) = 2,000 / 1.875 = ~1,066 shares</em></p>
            
            <p style="margin-top: 30px; color: #7f8c8d; font-size: 12px;">
                This report is generated based on Mark Minervini's stock selection method.
                Always do your own due diligence before making investment decisions.
            </p>
        </body>
        </html>
        """
        
        subject = f"Minervini SEPA stocks - {datetime.now().strftime('%Y-%m-%d')}"
        return self.notifier.send_report(recipient, subject, html)
    
    def run_weekly(self, index: str = 'sp500'):
        recipients = os.getenv("RECIPIENTS", os.getenv("SMTP_USER"))
        self.generate_report(recipients, index)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Minervini Weekly Report Generator')
    parser.add_argument('-sp400', action='store_true', help='Use S&P 400 (Mid-Cap) stocks')
    parser.add_argument('-sp600', action='store_true', help='Use S&P 600 (Small-Cap) stocks')
    args = parser.parse_args()

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

    print(f"Generating report for {index_name}...")
    report = ReportGenerator()
    report.run_weekly(index)
