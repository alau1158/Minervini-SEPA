# Long Term Investing - Mark Minervini Strategy

Weekly stock screening and portfolio tracking using Mark Minervini's trend template method.

## Features

- **Mark Minervini Screening** - Identifies stocks passing the core trend template criteria
- **Portfolio Tracking** - Monitor your existing holdings against optimal conditions
- **Weekly Reports** - Automated HTML reports emailed every Sunday at 9 AM
- **Top Opportunities** - Finds 3-4 best stocks passing all criteria

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

## Minervini Trend Template

A stock passes when it meets ALL of:

1. Price > 150-day MA > 200-day MA
2. 50-day MA > 150-day MA > 200-day MA
3. Price within 25% of 52-week high
4. RS Rating > 80 (vs S&P 500)
5. Positive EPS and revenue growth

## Report Statuses

- **OPTIMAL** - All criteria met, strong position
- **GOOD** - Most criteria met, hold
- **WEAK** - Review position
- **SELL/WATCH** - No longer meets criteria

## Files

| File | Description |
|------|-------------|
| `holdings.csv` | Your stock portfolio |
| `screener.py` | Stock screening logic |
| `portfolio.py` | Holdings management |
| `report.py` | Report generator |
| `notifier.py` | Email sender |
| `scheduler.py` | Weekly scheduler |

## Disclaimer

This is for informational purposes only. Always do your own research before investing.