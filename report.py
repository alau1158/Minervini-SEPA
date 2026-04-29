import os
import pandas as pd
import yfinance as yf
from datetime import datetime
from typing import List
from scipy.stats import percentileofscore
from dotenv import load_dotenv

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
    
    def generate_report(self, recipient: str) -> bool:
        print("Generating weekly report...")

        print("\n=== Finding top opportunities ===")
        opportunities = self.screener.find_top_opportunities(minervini_pass_only=True, limit=25)

        all_symbols_for_api = [o.symbol for o in opportunities]
        print(f"Fetching earnings and news data for {len(all_symbols_for_api)} symbols...")
        external_data = fetch_stock_data(all_symbols_for_api, use_finnhub=True)

        for o in opportunities:
            if o.symbol in external_data:
                data = external_data[o.symbol]
                o.next_earnings_date = data.get("next_earnings")
                o.recent_news = data.get("recent_news", [])
                o.catalyst = data.get("catalyst")

        print("\n=== Running AI Analysis (Gemini Flash) ===")
        ai_analysis = get_ai_analysis(opportunities)
        ai_analysis = None

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
            <h1>📈 Weekly Stock Report</h1>
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
            
            <div class="summary">
                <h3>Summary</h3>
                <p><strong>Top Opportunities:</strong> {len(opportunities)} stocks passing Minervini template</p>
            </div>
            
            <h2>Top 25 Opportunities (Minervini Pass)</h2>
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

        if ai_analysis:
            html += """
            <h2>AI Analysis (Gemini Flash)</h2>
            <div class="summary">
            """
            for symbol, ai in ai_analysis.items():
                color = "#27ae60" if ai.recommendation in ["strong_buy", "buy"] else "#f39c12" if ai.recommendation == "hold" else "#e74c3c"
                html += f"""
                <div style="margin-bottom: 15px; padding: 10px; border-left: 3px solid {color}; background-color: #fafafa;">
                    <strong>{symbol}</strong> <span style="color: {color};">[{ai.recommendation.upper()}]</span><br>
                    <small>{ai.summary}</small><br>
                    <small>Setup: {ai.setup_quality} | Risk: {ai.risk_level}</small>
                </div>
                """
            html += "</div>"

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
        recipient = os.getenv("SMTP_USER", "alau1158@gmail.com")
        self.generate_report(recipient)


if __name__ == "__main__":
    report = ReportGenerator()
    report.run_weekly()