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
        opportunities = self.screener.find_top_opportunities(minervini_pass_only=True, limit=10)

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

        print("\n=== Running AI Analysis (Gemini Flash) ===")
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
            <h1>📈 Weekly Stock Report</h1>
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
            
            <div class="summary">
                <h3>Summary</h3>
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
                html += f"""
                <tr>
                    <td><strong>{opp.symbol}</strong><br><small>{opp.name}</small></td>
                    <td>{self.format_price(opp.price)}</td>
                    <td>{entry_zone}</td>
                    <td>{opp.rs_rating:.0f}</td>
                    <td>{opp.trend_score}/8</td>
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
                <li><strong>Trend Score:</strong> Minervini template checks passed (0-8)</li>
                <li><strong>AI Catalysts:</strong> Key catalysts identified by AI analysis (first 5 stocks)</li>
                <li><strong>Entry Price:</strong> AI-suggested entry price based on technical setup</li>
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
        recipients = os.getenv("RECIPIENTS", os.getenv("SMTP_USER", "alau1158@gmail.com"))
        self.generate_report(recipients)


if __name__ == "__main__":
    report = ReportGenerator()
    report.run_weekly()