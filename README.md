# Long Term Investing - Mark Minervini Strategy

Weekly stock screening and portfolio tracking using Mark Minervini's SEPA (Specific Entry Point Analysis) method.

## Features

- **Mark Minervini Screening** - Identifies stocks passing all 9 trend template criteria
- **Portfolio Tracking** - Monitor your existing holdings against optimal conditions
- **Weekly Reports** - Automated HTML reports emailed every Sunday at 9 AM
- **Top 10 Opportunities** - Finds best stocks passing all criteria with RS rating ranking
- **Risk Management** - 22-day ATR% calculation for position sizing
- **AI Analysis** - Gemini Pro AI analysis with entry prices and catalysts
- **Multiple Index Support** - S&P 500, S&P 400 (Mid-Cap), S&P 600 (Small-Cap)

## Installation

```bash
# After ensurepip, use full path to pip
python3 -m ensurepip --upgrade
~/.local/bin/pip3 install -r requirements.txt

# Or add to PATH
export PATH="$HOME/.local/bin:$PATH"
pip3 install -r requirements.txt
```

## Troubleshooting

**Error: `pip: command not found`**
```bash
# Install pip via ensurepip
python3 -m ensurepip --upgrade

# Or install via get-pip.py
curl -sS https://bootstrap.pypa.io/get-pip.py | python3
```

## Setup

1. **Edit holdings.csv** - Add your current stock holdings:
   ```csv
   symbol,shares,purchase_date,purchase_price
   AAPL,50,2024-01-15,185.00
   ```

2. **Configure email** - Already set in `.env`:
   - SMTP_USER: username@gmail.com
   - SMTP_PASSWORD: Gmail app password

## Usage

```bash
# Run once (S&P 500 by default)
python report.py

# Run for S&P 400 (Mid-Cap)
python report.py -sp400

# Run for S&P 600 (Small-Cap)
python report.py -sp600

# Screen S&P 500 stocks
python screener.py

# Screen S&P 400 stocks
python screener.py -sp400

# Screen S&P 600 stocks
python screener.py -sp600

# Audit a specific stock
python screener.py --audit AAPL

# Run scheduler (sends weekly - S&P 500)
python scheduler.py
```

## Minervini Trend Template (9 Criteria)

A stock passes when it meets ALL of:

1. Current price > 50-day moving average
2. Current price > 150-day moving average
3. Current price > 200-day moving average
4. 50-day MA > 150-day MA and 50-day MA > 200-day MA
5. 150-day MA > 200-day MA
6. 200-day MA trending up (2-month confirmed)
7. Price within 25% of 52-week high
8. Price ≥ 30% above 52-week low
9. RS Rating ≥ 80 (vs S&P 500/index)

## Risk Management - Position Sizing

The report includes **22-Day ATR%** for each stock to help with position sizing and stop loss placement.

**Position Sizing Formula:**
```
Shares to Buy = 0.02(T) / (E)(1.5)(A)
```

Where:
- **T** = Total portfolio size
- **E** = Entry price
- **A** = 22-Day ATR% (as decimal, e.g., 2.5% = 0.025)

**Example:** For a $100,000 portfolio, entry at $50, ATR% of 2.5%:
```
Shares = 0.02($100,000) / ($50)(1.5)(0.025)
       = 2,000 / 1.875
       = ~1,066 shares
```

## Report Output

Reports include:
- **Symbol, Price, Entry Zone** - Stock info with suggested entry points
- **RS Rating** - Weighted relative strength vs index (0-100)
- **Trend Score** - Number of Minervini criteria passed (0-9)
- **22-Day ATR %** - Volatility measure for position sizing
- **Next Earnings** - Upcoming earnings date
- **AI Catalysts** - Key catalysts identified by AI analysis
- **Entry Price** - AI-suggested entry price based on technical setup

## Files

| File | Description |
|------|-------------|
| `holdings.csv` | Your stock portfolio |
| `screener.py` | Stock screening logic with Minervini trend template |
| `portfolio.py` | Holdings management |
| `report.py` | HTML report generator with ATR% and position sizing |
| `notifier.py` | Gmail SMTP email sender |
| `scheduler.py` | Weekly cron job scheduler |
| `api_clients.py` | External API clients (Finnhub, etc.) |
| `ai_analyst.py` | AI analysis using Gemini Pro |

## Disclaimer

This is for informational purposes only. Always do your own research before investing.
