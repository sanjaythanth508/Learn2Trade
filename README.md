# 📈 Learn2Trade - Interactive Stock Market & Paper Trading Platform

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Plotly](https://img.shields.io/badge/Plotly-3F4F75?style=for-the-badge&logo=plotly&logoColor=white)](https://plotly.com/)
[![yfinance](https://img.shields.io/badge/yfinance-Market_Data-green?style=for-the-badge)](https://pypi.org/project/yfinance/)

**Learn2Trade** is a financial education and real-time paper trading simulator built with **Python**, **Streamlit**, and **PostgreSQL**. It empowers aspiring traders and investors to master financial markets risk-free through real-time market data streaming, advanced technical charting, virtual portfolio execution, and structured educational curriculum.

---

## 🌟 Key Features

### 📊 Real-Time Market Data & Analytics
- Live price streaming and historical market OHLCV data powered by Yahoo Finance (`yfinance`).
- Interactive financial charts utilizing **Plotly** and **Matplotlib**:
  - High-precision candlestick charts with volume bars.
  - Dynamic timeframe selector (1D, 5D, 1M, 6M, 1Y, 5Y, Max).
- Comprehensive technical indicators:
  - Simple & Exponential Moving Averages (SMA / EMA).
  - Relative Strength Index (RSI).
  - Moving Average Convergence Divergence (MACD).
  - Bollinger Bands and volatility envelopes.

### 💼 Virtual Paper Trading (Zero Risk)
- Simulated trading environment with virtual capital.
- Instant market buy and sell order execution.
- Real-time **Portfolio Tracker**:
  - Total portfolio valuation and unrealized/realized Profit & Loss (P&L).
  - Holding distribution, average purchase prices, and current market values.
  - Transaction history log with order timestamps.

### 📚 Structured Stock Market Academy
- Built-in multi-level curriculum (`STOCK_MARKET_COURSES`) covering:
  - Foundations of equities and capital markets.
  - Technical analysis and chart pattern recognition.
  - Fundamental analysis, balance sheets, and valuation ratios.
  - Risk management, position sizing, and trading psychology.
- Persistent course tracking: users can mark lessons as completed and track milestones stored in the database.

### 🔍 Watchlist & Equities Database
- Pre-populated equities database (`stocks_database.csv`) covering market leaders (Apple, Microsoft, Nvidia, Google, Tesla, Amazon, etc.).
- Personalized user watchlist with fast-access stock monitors and price alerts.

### 🔐 Secure Multi-User Authentication
- User signup and login system featuring SHA-256 password hashing.
- Isolated individual portfolio data and learning progress per user account.

---

## 🏛️ System Architecture

```
                       ┌─────────────────────────┐
                       │     Streamlit UI        │
                       │   (stock_app3.py)       │
                       └───────────┬─────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│ Market Data API  │      │ Technical Engine │      │  PostgreSQL DB   │
│    (yfinance)    │      │ (Plotly / Pandas)│      │  (psycopg2)      │
│Live Stock Quotes │      │Candlestick, RSI, │      │Users, Portfolios,│
│& Historical Data │      │MACD, Indicators  │      │Lessons Progress  │
└──────────────────┘      └──────────────────┘      └──────────────────┘
```

---

## 📁 Repository Structure

```text
Learn2Trade/
├── stock_app3.py         # Main application source code (UI, Trading Engine, Course Modules)
├── stocks_database.csv   # Catalog of tracked stock tickers and company profiles
├── requirements.txt      # Python dependencies and third-party packages
└── README.md             # Project documentation
```

---

## 🛠️ Installation & Setup Guide

### 1. Prerequisites
- **Python 3.9+** installed on your system.
- **PostgreSQL** server running locally or hosted in the cloud.

### 2. Clone the Repository
```bash
git clone https://github.com/sanjaythanth508/Learn2Trade.git
cd Learn2Trade
```

### 3. Create a Virtual Environment (Recommended)
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Database Configuration
1. Open your PostgreSQL console (psql or pgAdmin) and create the database:
   ```sql
   CREATE DATABASE learntotrade_db;
   ```
2. Verify or update connection credentials in `stock_app3.py` under the `DatabaseManager` class:
   ```python
   self.connection = psycopg2.connect(
       host="localhost",
       port="5432",
       database="learntotrade_db",
       user="postgres",
       password="your_password"
   )
   ```

### 6. Launch the Application
```bash
streamlit run stock_app3.py
```
Your default browser will automatically open to [http://localhost:8501](http://localhost:8501).

---

## 📦 Required Dependencies

- **streamlit**: Web dashboard framework
- **yfinance**: Real-time market feed
- **pandas** & **numpy**: Financial computations and data structures
- **plotly** & **matplotlib**: Interactive charting and technical visualizations
- **psycopg2-binary**: PostgreSQL database adapter
- **python-dotenv**: Environment variable configuration

---

## 👤 Author

- **Sanjay Thanth** ([@sanjaythanth508](https://github.com/sanjaythanth508))
