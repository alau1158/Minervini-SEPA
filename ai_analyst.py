import os
import json
import requests
from typing import List, Dict, Optional
from dotenv import load_dotenv
from dataclasses import dataclass

load_dotenv()


@dataclass
class AIAnalysis:
    symbol: str
    summary: str
    setup_quality: str
    risk_level: str
    key_catalysts: List[str]
    recommendation: str
    estimated_entry_price: Optional[float] = None


class GeminiAnalyst:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = "gemini-2.5-flash-lite"

    def analyze_stock(self, symbol: str, stock_data: Dict) -> Optional[AIAnalysis]:
        if not self.api_key:
            return None

        try:
            prompt = f"""Analyze {symbol} stock for investment.

Data:
- Price: ${stock_data.get('price', 'N/A')}
- Entry Zone: {stock_data.get('entry_zone', 'N/A')}
- RS Rating: {stock_data.get('rs_rating', 'N/A')}
- Trend Score: {stock_data.get('trend_score', 'N/A')}
- Earnings: {stock_data.get('next_earnings', 'N/A')}
- Catalyst: {stock_data.get('catalyst', 'N/A')}
- Recent News: {stock_data.get('recent_news', [])[:3]}

Review these major catalysts to assess their impact on the stock's near-term outlook.

Reply with EXACT format:
- SU: [exceptional/good/weak]
- RI: [low/medium/high]
- CA: [catalyst 1]
- CA: [catalyst 2 if available]
- CA: [catalyst 3 if available]
- EP: [estimated entry price, e.g., $123.45]
- RE: [strong_buy/buy/hold/skip]
- SU: [1 sentence summary]"""

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 500,
                }
            }

            response = requests.post(url, json=payload, timeout=30)
            if response.status_code != 200:
                print(f"Gemini API error: {response.status_code}")
                return None

            result = response.json()
            text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

            lines = [l.strip() for l in text.split("\n") if l.strip()]
            setup = risk = rec = summary = None
            catalysts = []
            entry_price = None
            for line in lines:
                if line.startswith("- SU:"):
                    val = line.split("SU:")[1].strip()
                    if setup is None:
                        setup = val
                    else:
                        summary = val
                elif line.startswith("- RI:"):
                    risk = line.split("RI:")[1].strip()
                elif line.startswith("- CA:"):
                    catalysts.append(line.split("CA:")[1].strip())
                elif line.startswith("- EP:"):
                    try:
                        entry_price = float(line.split("EP:")[1].strip().replace("$", ""))
                    except:
                        entry_price = None
                elif line.startswith("- RE:"):
                    rec = line.split("RE:")[1].strip()

            return AIAnalysis(
                symbol=symbol,
                summary=summary or "Analysis unavailable",
                setup_quality=setup or "N/A",
                risk_level=risk or "N/A",
                key_catalysts=catalysts or [],
                recommendation=rec or "skip",
                estimated_entry_price=entry_price,
            )
        except Exception as e:
            print(f"AI analysis failed for {symbol}: {e}")
            return None

    def analyze_opportunities(self, stocks: List) -> Dict[str, AIAnalysis]:
        results = {}
        if not self.api_key:
            print("No Gemini API key configured - skipping AI analysis")
            return results

        for stock in stocks[:10]:
            stock_data = {
                "price": getattr(stock, "price", None),
                "entry_zone": getattr(stock, "entry_zone", None),
                "rs_rating": getattr(stock, "rs_rating", None),
                "trend_score": getattr(stock, "trend_score", None),
                "next_earnings": getattr(stock, "next_earnings_date", None),
                "catalyst": getattr(stock, "catalyst", None),
                "recent_news": getattr(stock, "recent_news", []) or [],
            }
            analysis = self.analyze_stock(stock.symbol, stock_data)
            if analysis:
                results[stock.symbol] = analysis

        return results

    def _extract_field(self, text: str, field: str) -> Optional[str]:
        for line in text.split("\n"):
            if f"- {field}:" in line:
                return line.split(f"- {field}:")[1].strip()
        return None

    def _extract_list(self, text: str, field: str) -> List[str]:
        items = []
        in_list = False
        for line in text.split("\n"):
            if f"- {field}:" in line:
                in_list = True
                content = line.split(f"- {field}:")[1].strip()
                if content and content.lower() != "none":
                    items.append(content)
            elif in_list and line.strip().startswith("-"):
                item = line.strip("- ").strip()
                if item and item.lower() != "none":
                    items.append(item)
                if not line.strip().startswith("-"):
                    break
        return items[:3]


def get_ai_analysis(stocks: List) -> Dict[str, AIAnalysis]:
    analyst = GeminiAnalyst()
    return analyst.analyze_opportunities(stocks)