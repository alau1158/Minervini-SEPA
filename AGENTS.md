# Long Term Investing - Mark Minervini Strategy

## Quick Start

```bash
pip install -r requirements.txt
python scheduler.py          # Run weekly reports (Sundays 9am)
python report.py              # Run single report
```

## Project Structure

| File | Purpose |
|------|---------|
| `holdings.csv` | Your stock portfolio - edit with your IRA holdings |
| `screener.py` | Mark Minervini trend template screening |
| `portfolio.py` | Holdings management |
| `report.py` | Weekly HTML report generation |
| `notifier.py` | Gmail SMTP email sending |
| `scheduler.py` | Weekly cron job |

## Dependencies

- yfinance, pandas, numpy, python-dotenv, schedule
- System requires pip (not available in this environment - run locally)

## Key Files

- `.env` contains SMTP credentials (Gmail app password in SMTP_PASSWORD)
- `holdings.csv` format: `symbol,shares,purchase_date,purchase_price`

## Running

- `python report.py` - sends report to email in SMTP_USER (.env)
- Edit `holdings.csv` with your actual stocks before first run

## Minervini Criteria Used

- Price > 150-day MA > 200-day MA
- 50-day MA > 150-day MA > 200-day MA
- Price within 25% of 52-week high
- RS rating > 80 vs S&P 500
- Positive EPS and revenue growth