# FarmProfit

Full-stack Flask farming profitability platform.

## Features

- Account registration and login
- Secure password hashing
- Demo login
- Profit / loss prediction
- Crop selection
- Yield, land and market price controls
- Eight production cost categories
- ROI, margin and risk calculation
- Break-even price and yield
- What-if simulator
- Saved plans and history
- Crop comparison
- Printable report
- JSON calculation API
- SQLite local database
- PostgreSQL / Render database support
- Render deployment configuration

## Local run

```bash
python -m venv .venv
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

Demo login:

- Email: demo@farmprofit.app
- Password: Demo@12345

Change the demo credentials before using this publicly.

## Render

Use the included `render.yaml` as a Blueprint, or configure:

Build command: `pip install -r requirements.txt`

Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`

Health check: `/health`

For persistent accounts and plans, use Render PostgreSQL and set `DATABASE_URL`.
