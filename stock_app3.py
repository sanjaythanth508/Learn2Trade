import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import plotly.graph_objects as go
import random
from datetime import datetime, timedelta
import time as time_module
from plotly.subplots import make_subplots
import psycopg2
from psycopg2 import sql
import hashlib


# ==================== CLASSES ====================

class DatabaseManager:
    """OOP Class for database operations"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        self.connection = None
    
    def get_connection(self):
        """Create a connection to PostgreSQL database"""
        if self.connection is None or self.connection.closed:
            try:
                self.connection = psycopg2.connect(
                    host="localhost",
                    port="5432",
                    database="learntotrade_db",
                    user="postgres",
                    password="123"
                )
                # Set autocommit to True to avoid transaction issues
                self.connection.autocommit = True
            except Exception as e:
                st.error(f"Database connection error: {e}")
                return None
        return self.connection
    
    def close_connection(self):
        """Close the database connection"""
        if self.connection and not self.connection.closed:
            self.connection.close()
            self.connection = None

class User:
    """OOP Class for user operations"""
    def __init__(self, user_id, username):
        self.user_id = user_id
        self.username = username
        self.db = DatabaseManager()
    
    def get_portfolio(self):
        """Get user portfolio"""
        return get_user_portfolio(self.user_id)
    
    def get_watchlist(self):
        """Get user watchlist"""
        return get_watchlist(self.user_id)
    
    def get_learning_progress(self):
        """Get learning progress from database"""
        conn = self.db.get_connection()
        if conn is None:
            return {}
        
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT course_category, lesson_name, completed FROM learning_progress WHERE user_id = %s",
                (self.user_id,)
            )
            rows = cur.fetchall()
            cur.close()
            
            progress = {}
            for category, lesson, completed in rows:
                if category not in progress:
                    progress[category] = {'completed': 0, 'total': 0, 'lessons': {}}
                progress[category]['total'] += 1
                progress[category]['completed'] += 1 if completed else 0
                progress[category]['lessons'][lesson] = completed
            
            # Ensure all categories have correct totals
            for category in STOCK_MARKET_COURSES:
                if category not in progress:
                    progress[category] = {
                        'completed': 0, 
                        'total': len(STOCK_MARKET_COURSES[category]),
                        'lessons': {}
                    }
                else:
                    # Update total count
                    progress[category]['total'] = len(STOCK_MARKET_COURSES[category])
            
            return progress
            
        except Exception as e:
            st.error(f"Error getting learning progress: {e}")
            return {}

    def get_completed_lesson_count(self):
        """Get total number of completed lessons"""
        progress = self.get_learning_progress()
        completed = 0
        for category in progress:
            completed += progress[category].get('completed', 0)
        return completed
    
    def mark_lesson_complete(self, course_category, lesson_name):
        """Mark a lesson as complete for user - prevents duplicate completions"""
        conn = self.db.get_connection()
        if conn is None:
            return False
        
        try:
            cur = conn.cursor()
            
            # Check if already completed
            cur.execute(
                """SELECT completed FROM learning_progress 
                WHERE user_id = %s AND course_category = %s AND lesson_name = %s""",
                (self.user_id, course_category, lesson_name)
            )
            existing = cur.fetchone()
            
            if existing:
                # Already exists, if already completed, return False
                if existing[0]:
                    cur.close()
                    return False  # Already completed, don't mark again
                else:
                    # Update to complete
                    cur.execute(
                        """UPDATE learning_progress SET completed = TRUE, completed_at = CURRENT_TIMESTAMP
                        WHERE user_id = %s AND course_category = %s AND lesson_name = %s""",
                        (self.user_id, course_category, lesson_name)
                    )
            else:
                # Insert new record as completed
                cur.execute(
                    """INSERT INTO learning_progress (user_id, course_category, lesson_name, completed, completed_at)
                    VALUES (%s, %s, %s, TRUE, CURRENT_TIMESTAMP)""",
                    (self.user_id, course_category, lesson_name)
                )
            
            # Commit the transaction
            conn.commit()
            cur.close()
            return True
        
        except Exception as e:
            conn.rollback()
            st.error(f"Error marking lesson complete: {e}")
            return False

class Stock:
    """OOP Class for stock operations"""
    def __init__(self, symbol, company_name=""):
        self.symbol = symbol
        self.company_name = company_name
        self.ticker = yf.Ticker(symbol)
    
    def get_current_price(self):
        """Get current stock price"""
        try:
            price = self.ticker.fast_info.get("last_price")
            if price is None:
                hist = self.ticker.history(period="1d")
                if not hist.empty:
                    price = hist['Close'].iloc[-1]
            return price
        except:
            return None
    
    def get_historical_data(self, period="1mo", interval="1d"):
        """Get historical stock data"""
        try:
            return self.ticker.history(period=period, interval=interval)
        except:
            return pd.DataFrame()
    
    def get_stock_info(self):
        """Get stock information"""
        info = {
            'current_price': self.get_current_price(),
            'company_name': self.company_name,
            'symbol': self.symbol
        }
        return info

class Portfolio:
    """OOP Class for portfolio management"""
    def __init__(self, user):
        self.user = user
        self.db = DatabaseManager()
        self.portfolio_data = None
    
    def load_portfolio(self):
        """Load portfolio data"""
        self.portfolio_data = get_user_portfolio(self.user.user_id)
        return self.portfolio_data
    
    def get_total_value(self):
        """Calculate total portfolio value"""
        if not self.portfolio_data:
            self.load_portfolio()
        
        if not self.portfolio_data:
            return 100000.00
        
        total_value = self.portfolio_data['cash']
        
        for symbol, holding in self.portfolio_data['holdings'].items():
            try:
                stock = Stock(symbol)
                current_price = stock.get_current_price()
                if current_price is None:
                    current_price = holding['avg_price']
                total_value += holding['shares'] * current_price
            except:
                total_value += holding['shares'] * holding['avg_price']
        
        return total_value
    
    def execute_trade(self, symbol, action, shares, price, company_name=""):
        """Execute a trade"""
        return update_portfolio_db(self.user.user_id, symbol, action, shares, price, company_name)

# ==================== DATABASE FUNCTIONS ====================

# Database connection
def get_db_connection():
    """Create a connection to PostgreSQL database"""
    try:
        conn = psycopg2.connect(
            host="localhost",
            port="5432",
            database="learntotrade_db",
            user="postgres",
            password="123"
        )
        # Set autocommit to True to avoid transaction issues
        conn.autocommit = True
        return conn
    except Exception as e:
        st.error(f"Database connection error: {e}")
        return None

# Initialize database tables if they don't exist
def initialize_database():
    """Initialize database tables if they don't exist"""
    conn = get_db_connection()
    if conn is None:
        return False
    
    try:
        cur = conn.cursor()
        
        # Check if learning_progress table exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'learning_progress'
            );
        """)
        table_exists = cur.fetchone()[0]
        
        if not table_exists:
            # Create learning_progress table
            cur.execute("""
                CREATE TABLE learning_progress (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    course_category VARCHAR(100) NOT NULL,
                    lesson_name VARCHAR(200) NOT NULL,
                    completed BOOLEAN DEFAULT FALSE,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, course_category, lesson_name)
                );
            """)
            st.info("Created learning_progress table")
        
        cur.close()
        return True
        
    except Exception as e:
        st.error(f"Error initializing database: {e}")
        return False
    finally:
        if conn:
            conn.close()

# User authentication functions
def hash_password(password):
    """Hash a password for storing"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(stored_password, provided_password):
    """Verify a stored password against one provided by user"""
    return stored_password == hash_password(provided_password)

def register_user(username, email, password):
    """Register a new user and automatically login"""
    conn = get_db_connection()
    if conn is None:
        return False, "Database connection failed", None
    
    try:
        cur = conn.cursor()
        
        # Check if username or email already exists
        cur.execute("SELECT id FROM users WHERE username = %s OR email = %s", (username, email))
        if cur.fetchone():
            cur.close()
            conn.close()
            return False, "Username or email already exists", None
        
        # Hash password
        password_hash = hash_password(password)
        
        # Insert new user
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (username, email, password_hash)
        )
        user_id = cur.fetchone()[0]
        
        # Create default portfolio for user
        cur.execute(
            "INSERT INTO portfolios (user_id) VALUES (%s)",
            (user_id,)
        )
        
        conn.commit()
        cur.close()
        conn.close()
        
        # Initialize database tables
        initialize_database()
        
        # Return success with user_id so we can auto-login
        return True, "Registration successful", user_id
        
    except Exception as e:
        return False, f"Registration failed: {str(e)}", None

def login_user(username, password):
    """Login a user"""
    conn = get_db_connection()
    if conn is None:
        return False, "Database connection failed", None
    
    try:
        cur = conn.cursor()
        
        # Get user by username
        cur.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (username,)
        )
        user = cur.fetchone()
        
        if user is None:
            cur.close()
            conn.close()
            return False, "Invalid username or password", None
        
        user_id, username, stored_hash = user
        
        # Verify password
        if not verify_password(stored_hash, password):
            cur.close()
            conn.close()
            return False, "Invalid username or password", None
        
        # Update last login
        cur.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s",
            (user_id,)
        )
        
        conn.commit()
        cur.close()
        conn.close()
        
        return True, "Login successful", user_id
        
    except Exception as e:
        return False, f"Login failed: {str(e)}", None

# Portfolio functions - MUST BE DEFINED BEFORE THEY ARE CALLED
def get_user_portfolio(user_id):
    """Get or create user portfolio from database"""
    conn = get_db_connection()
    if conn is None:
        return None
    
    try:
        cur = conn.cursor()
        
        # Get portfolio
        cur.execute(
            "SELECT id, cash FROM portfolios WHERE user_id = %s",
            (user_id,)
        )
        portfolio_data = cur.fetchone()
        
        if portfolio_data:
            portfolio_id, cash = portfolio_data
            
            # Get holdings
            cur.execute(
                "SELECT symbol, company_name, shares, avg_price, total_invested FROM holdings WHERE portfolio_id = %s",
                (portfolio_id,)
            )
            holdings_rows = cur.fetchall()
            
            holdings = {}
            for row in holdings_rows:
                symbol, company_name, shares, avg_price, total_invested = row
                holdings[symbol] = {
                    'shares': shares,
                    'avg_price': float(avg_price),
                    'total_invested': float(total_invested),
                    'company_name': company_name
                }
            
            # Get recent orders (last 50)
            cur.execute(
                """SELECT symbol, company_name, action, shares, price, total, profit_loss, timestamp 
                   FROM orders WHERE portfolio_id = %s ORDER BY timestamp DESC LIMIT 50""",
                (portfolio_id,)
            )
            orders_rows = cur.fetchall()
            
            orders = []
            for row in orders_rows:
                symbol, company_name, action, shares, price, total, profit_loss, timestamp = row
                orders.append({
                    'timestamp': timestamp,
                    'symbol': symbol,
                    'company_name': company_name,
                    'action': action,
                    'shares': shares,
                    'price': float(price),
                    'total': float(total),
                    'profit_loss': float(profit_loss) if profit_loss else None
                })
            
            cur.close()
            conn.close()
            
            portfolio = {
                'cash': float(cash),
                'holdings': holdings,
                'orders': orders,
                'portfolio_id': portfolio_id
            }
            
            return portfolio
        else:
            # Create new portfolio
            cur.execute(
                "INSERT INTO portfolios (user_id) VALUES (%s) RETURNING id",
                (user_id,)
            )
            portfolio_id = cur.fetchone()[0]
            conn.commit()
            
            cur.close()
            conn.close()
            
            return {
                'cash': 100000.00,
                'holdings': {},
                'orders': [],
                'portfolio_id': portfolio_id
            }
            
    except Exception as e:
        st.error(f"Error getting portfolio: {e}")
        return None

def calculate_portfolio_value(user_id):
    """Calculate total portfolio value including holdings"""
    portfolio = get_user_portfolio(user_id)
    if portfolio is None:
        return 100000.00
    
    total_value = portfolio['cash']
    
    for symbol, holding in portfolio['holdings'].items():
        try:
            ticker = yf.Ticker(symbol)
            current_price = ticker.fast_info.get("last_price", holding['avg_price'])
            if current_price is None:
                current_price = holding['avg_price']
            total_value += holding['shares'] * current_price
        except:
            total_value += holding['shares'] * holding['avg_price']
    
    # Update total value in database
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE portfolios SET total_value = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s",
                (total_value, user_id)
            )
            conn.commit()
            cur.close()
            conn.close()
        except:
            pass
    
    return total_value

def update_portfolio_db(user_id, symbol, action, shares, price, company_name=""):
    """Update user portfolio in database"""
    portfolio = get_user_portfolio(user_id)
    if portfolio is None:
        return False, "Portfolio not found"
    
    portfolio_id = portfolio['portfolio_id']
    cash = portfolio['cash']
    holdings = portfolio['holdings']
    
    conn = get_db_connection()
    if conn is None:
        return False, "Database connection failed"
    
    try:
        cur = conn.cursor()
        
        if action == 'buy':
            total_cost = shares * price
            
            # Check if user has enough cash
            if total_cost > cash:
                cur.close()
                conn.close()
                return False, "Insufficient funds"
            
            new_cash = cash - total_cost
            
            # Update portfolio cash
            cur.execute(
                "UPDATE portfolios SET cash = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (new_cash, portfolio_id)
            )
            
            # Check if holding exists
            cur.execute(
                "SELECT id FROM holdings WHERE portfolio_id = %s AND symbol = %s",
                (portfolio_id, symbol)
            )
            holding_exists = cur.fetchone()
            
            if holding_exists:
                # Update existing holding
                cur.execute("""
                    UPDATE holdings 
                    SET shares = shares + %s,
                        total_invested = total_invested + %s,
                        avg_price = (total_invested + %s) / (shares + %s),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE portfolio_id = %s AND symbol = %s
                """, (shares, total_cost, total_cost, shares, portfolio_id, symbol))
            else:
                # Insert new holding
                cur.execute("""
                    INSERT INTO holdings (portfolio_id, symbol, company_name, shares, avg_price, total_invested)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (portfolio_id, symbol, company_name, shares, price, total_cost))
            
            # Record order
            cur.execute("""
                INSERT INTO orders (portfolio_id, symbol, company_name, action, shares, price, total)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (portfolio_id, symbol, company_name, 'buy', shares, price, total_cost))
            
            conn.commit()
            cur.close()
            conn.close()
            
            return True, "Buy order executed"
        
        elif action == 'sell':
            if symbol not in holdings:
                cur.close()
                conn.close()
                return False, "No shares to sell"
            
            holding = holdings[symbol]
            if holding['shares'] < shares:
                cur.close()
                conn.close()
                return False, "Insufficient shares"
            
            # Calculate P&L
            avg_price = holding['avg_price']
            profit_loss = (price - avg_price) * shares
            total_value = shares * price
            new_cash = cash + total_value
            
            # Update portfolio cash
            cur.execute(
                "UPDATE portfolios SET cash = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (new_cash, portfolio_id)
            )
            
            # Update holdings
            remaining_shares = holding['shares'] - shares
            if remaining_shares == 0:
                # Delete holding
                cur.execute(
                    "DELETE FROM holdings WHERE portfolio_id = %s AND symbol = %s",
                    (portfolio_id, symbol)
                )
            else:
                # Update holding
                new_total_invested = remaining_shares * avg_price
                cur.execute("""
                    UPDATE holdings 
                    SET shares = %s, 
                        total_invested = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE portfolio_id = %s AND symbol = %s
                """, (remaining_shares, new_total_invested, portfolio_id, symbol))
            
            # Record order
            cur.execute("""
                INSERT INTO orders (portfolio_id, symbol, company_name, action, shares, price, total, profit_loss)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (portfolio_id, symbol, company_name, 'sell', shares, price, total_value, profit_loss))
            
            conn.commit()
            cur.close()
            conn.close()
            
            # FIXED: Removed extra parenthesis
            return True, f"Sell order executed (P&L: ₹{profit_loss:.2f})"
    
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return False, f"Transaction failed: {str(e)}"

# Watchlist functions
def add_to_watchlist(user_id, symbol, company_name, notes=""):
    """Add a stock to user's watchlist"""
    conn = get_db_connection()
    if conn is None:
        return False, "Database connection failed"
    
    try:
        cur = conn.cursor()
        
        # Check if already in watchlist
        cur.execute(
            "SELECT id FROM watchlists WHERE user_id = %s AND symbol = %s",
            (user_id, symbol)
        )
        if cur.fetchone():
            cur.close()
            conn.close()
            return False, "Stock already in watchlist"
        
        # Add to watchlist
        cur.execute(
            "INSERT INTO watchlists (user_id, symbol, company_name, notes) VALUES (%s, %s, %s, %s)",
            (user_id, symbol, company_name, notes)
        )
        
        conn.commit()
        cur.close()
        conn.close()
        
        return True, "Added to watchlist"
        
    except Exception as e:
        return False, f"Failed to add to watchlist: {str(e)}"

def remove_from_watchlist(user_id, symbol):
    """Remove a stock from user's watchlist"""
    conn = get_db_connection()
    if conn is None:
        return False, "Database connection failed"
    
    try:
        cur = conn.cursor()
        
        cur.execute(
            "DELETE FROM watchlists WHERE user_id = %s AND symbol = %s",
            (user_id, symbol)
        )
        
        conn.commit()
        cur.close()
        conn.close()
        
        return True, "Removed from watchlist"
        
    except Exception as e:
        return False, f"Failed to remove from watchlist: {str(e)}"

def get_watchlist(user_id):
    """Get user's watchlist"""
    conn = get_db_connection()
    if conn is None:
        return []
    
    try:
        cur = conn.cursor()
        
        cur.execute(
            "SELECT symbol, company_name, notes, added_at FROM watchlists WHERE user_id = %s ORDER BY added_at DESC",
            (user_id,)
        )
        
        watchlist = []
        for row in cur.fetchall():
            symbol, company_name, notes, added_at = row
            watchlist.append({
                'symbol': symbol,
                'company_name': company_name,
                'notes': notes,
                'added_at': added_at
            })
        
        cur.close()
        conn.close()
        
        return watchlist
        
    except Exception as e:
        st.error(f"Error getting watchlist: {e}")
        return []



# Market hours check functions
def is_market_open_now():
    """Check if market is currently open based on Indian market hours"""
    now = datetime.now()
    current_time = now.time()
    
    # Indian market hours: 9:15 AM to 3:30 PM
    from datetime import time
    market_open = time(9, 15)
    market_close = time(15, 30)
    
    # Check if it's a weekday (Monday=0, Friday=4)
    is_weekday = now.weekday() < 5
    
    return is_weekday and market_open <= current_time <= market_close

def get_live_data_period():
    """Calculate the time period for live data (last 30 minutes)"""
    now = datetime.now()
    start_time = now - timedelta(minutes=30)
    
    current_time = now.time()
    from datetime import time
    market_open = time(9, 15)
    
    if current_time < market_open:
        yesterday = now - timedelta(days=1)
        market_close_yesterday = time(15, 30)
        start_time = datetime.combine(yesterday.date(), market_close_yesterday) - timedelta(minutes=30)
        end_time = datetime.combine(yesterday.date(), market_close_yesterday)
    else:
        end_time = now
    
    return start_time, end_time

# Stock Market Learning Content
STOCK_MARKET_COURSES = {
    "Basics": {
        "What is Stock Market?": {
            "content": """
            # 📈 What is Stock Market?
            
            ## Understanding the Stock Market
            
            The stock market is a **public marketplace** where shares of publicly traded companies are bought and sold. It's like a giant supermarket for company ownership!
            
            ### Key Components:
            
            **1. Stocks/Shares**: 
            - Represent ownership in a company
            - When you buy a stock, you own a small piece of that company
            - Companies issue stocks to raise money for growth
            
            **2. Stock Exchanges**:
            - Physical/virtual places where trading happens
            - Indian Examples: BSE (Bombay Stock Exchange), NSE (National Stock Exchange)
            - International: NYSE, NASDAQ
            
            **3. Market Participants**:
            - Retail Investors (like you and me)
            - Institutional Investors (mutual funds, insurance companies)
            - Market Makers
            - Brokers
            
            ### Why Stock Market Exists?
            
            *For Companies*:
            - Raise capital for expansion
            - Increase visibility and credibility
            - Provide liquidity to early investors
            
            *For Investors*:
            - Grow wealth through capital appreciation
            - Earn dividends (company profits)
            - Beat inflation
            - Participate in economic growth
            
            ## How it Works - Simple Analogy
            
            Imagine a pizza restaurant needs money to open new branches:
            
            1. **Company**: Pizza Palace needs ₹10 crores
            2. **IPO**: They issue 10 lakh shares at ₹100 each
            3. **You buy**: Purchase 100 shares for ₹10,000
            4. **You own**: Now own 0.01% of Pizza Palace
            5. **Growth**: Pizza Palace expands, profits increase
            6. **Share price rises**: Your ₹10,000 becomes ₹15,000
            7. **Dividends**: You also get yearly pizza discount coupons (dividends)
            
            ## Types of Markets
            
            1. **Primary Market**: Where companies first sell shares (IPOs)
            2. **Secondary Market**: Where investors trade shares among themselves
            3. **Bull Market**: When prices are rising (optimism)
            4. **Bear Market**: When prices are falling (pessimism)
            
            ## Basic Terms to Know
            
            - **BSE Sensex**: Index of 30 large companies on BSE
            - **NSE Nifty**: Index of 50 large companies on NSE
            - **Market Capitalization**: Company value = Share price × Total shares
            - **Volume**: Number of shares traded
            - **Liquidity**: How easily shares can be bought/sold
            
            ## Common Misconceptions
            
            ❌ **Myth**: Stock market is gambling
            ✅ **Truth**: It's investing based on research and analysis
            
            ❌ **Myth**: Need lots of money to start
            ✅ **Truth**: Can start with as little as ₹500
            
            ❌ **Myth**: Only experts can make money
            ✅ **Truth**: Anyone can learn and succeed
            
            ## Why Learn Stock Market?
            
            **Financial Freedom**: Create wealth over time
            **Beat Inflation**: Grow money faster than bank deposits
            **Passive Income**: Earn dividends regularly
            **Tax Benefits**: Long-term investments have tax advantages
            
            ## Quick Start Checklist
            
            ✅ Understand basic terms
            ✅ Open Demat & Trading account
            ✅ Start with small amounts
            ✅ Learn before you earn
            ✅ Practice with virtual trading
            
            **Remember**: The stock market is not a get-rich-quick scheme. It's a **wealth-building journey** that requires patience, learning, and discipline.
            """,
            "level": "Beginner",
            "time": "10 min read",
            "icon": "📚"
        },
        "Stock Market Basics": {
            "content": """
            # 📊 Stock Market Basics
            
            ## Types of Stocks
            
            **1. Common Stocks**
            - Most common type
            - Voting rights in company decisions
            - Potential for dividends
            - Higher risk, higher potential return
            
            **2. Preferred Stocks**
            - Fixed dividends
            - No voting rights
            - Priority in bankruptcy
            - Less volatile than common stocks
            
            **3. Blue-chip Stocks**
            - Large, established companies
            - Stable dividends
            - Examples: Reliance, TCS, HDFC Bank
            
            **4. Growth Stocks**
            - Fast-growing companies
            - Reinvest profits (no/small dividends)
            - Higher risk
            - Examples: New tech companies
            
            **5. Value Stocks**
            - Undervalued companies
            - Trading below intrinsic value
            - Good for long-term investors
            
            ## How to Read Stock Prices
            
            **Stock Quote Example**:
            ```
            RELIANCE: ₹2,450.75
            Change: +15.25 (+0.63%)
            High: ₹2,465.00
            Low: ₹2,430.50
            Volume: 25,45,000 shares
            ```
            
            **Understanding the Numbers**:
            
            * **Last Traded Price**: ₹2,450.75
            * **Day's Range**: ₹2,430.50 - ₹2,465.00
            * **Change**: +15.25 points or +0.63%
            * **Volume**: 25.45 lakh shares traded
            
            ## Market Orders
            
            **1. Market Order**
            - Buy/sell at current market price
            - Immediate execution
            - Price not guaranteed
            
            **2. Limit Order**
            - Buy/sell at specific price
            - Price guaranteed
            - Execution not guaranteed
            
            **3. Stop Loss Order**
            - Sell automatically if price drops to certain level
            - Limits losses
            - Crucial for risk management
            
            **4. Bracket Order**
            - Combination of limit and stop loss
            - Defines target and stop loss together
            
            ## Trading Sessions
            
            **Indian Market Timings**:
            
            * **Pre-open Session**: 9:00 AM - 9:15 AM
              - Order collection period
              - Price discovery
              
            * **Normal Trading**: 9:15 AM - 3:30 PM
              - Continuous trading
              - Most active period
              
            * **Post-close Session**: 3:40 PM - 4:00 PM
              - Only market orders
              
            ## Important Concepts
            
            **Market Capitalization**:
            ```
            Large Cap: > ₹20,000 crores
            Mid Cap: ₹5,000 - ₹20,000 crores
            Small Cap: < ₹5,000 crores
            ```
            
            **Circuit Breakers**:
            - Prevent extreme volatility
            - Trading halts at 10%, 15%, 20% moves
            
            **Margin Trading**:
            - Trade with borrowed money
            - Higher risk, higher reward
            - Requires experience
            
            ## Price Determination
            
            **Demand & Supply Rule**:
            ```
            More Buyers = Price ↗
            More Sellers = Price ↘
            ```
            
            **Factors Affecting Prices**:
            1. Company performance
            2. Industry trends
            3. Economic conditions
            4. Government policies
            5. Global markets
            6. Investor sentiment
            
            ## Basic Calculations
            
            **Return Calculation**:
            ```
            Buy Price: ₹100
            Sell Price: ₹120
            Return = [(120-100)/100] × 100 = 20%
            ```
            
            **Dividend Yield**:
            ```
            Annual Dividend: ₹5 per share
            Stock Price: ₹100
            Yield = (5/100) × 100 = 5%
            ```
            
            **P/E Ratio**:
            ```
            Stock Price: ₹100
            EPS (Earnings Per Share): ₹5
            P/E = 100/5 = 20
            ```
            
            ## Practical Tips for Beginners
            
            **1. Start Small**: Begin with ₹5,000-₹10,000
            **2. Diversify**: Don't put all money in one stock
            **3. Learn First**: Paper trade before real money
            **4. Long-term View**: Think years, not days
            **5. Ignore Noise**: Don't follow every market rumor
            
            ## Common Beginner Mistakes
            
            ❌ **Chasing hot tips**
            ❌ **Panic selling**
            ❌ **Overtrading**
            ❌ **Not having stop loss**
            ❌ **Emotional decisions**
            ❌ **Falling for "get rich quick" schemes**
            
            ## Next Steps
            
            Now that you understand basics:
            
            1. **Open Demat Account**
            2. **Start Paper Trading**
            3. **Follow 5-10 companies regularly**
            4. **Read company annual reports**
            5. **Join investor communities**
            
            **Golden Rule**: Never invest money you can't afford to lose!
            """,
            "level": "Beginner",
            "time": "15 min read",
            "icon": "🎯"
        },
        "How to Start Investing": {
            "content": """
            # 🚀 How to Start Investing in Stocks
            
            ## Step-by-Step Guide for Beginners
            
            ### Step 1: Mental Preparation
            
            **Right Mindset**:
            - Stocks are long-term investments
            - Expect volatility (ups and downs)
            - You WILL make mistakes (learn from them)
            - Patience is more important than knowledge
            
            **Set Realistic Goals**:
            ```
            Short-term (1-3 years): 10-15% annual return
            Medium-term (3-5 years): 12-18% annual return
            Long-term (5+ years): 15-20% annual return
            ```
            
            ### Step 2: Financial Preparation
            
            **Emergency Fund First**:
            - Keep 6 months expenses in savings account
            - Never invest emergency money
            - This prevents panic selling
            
            **Determine Investment Amount**:
            ```
            Monthly Income: ₹50,000
            Monthly Expenses: ₹30,000
            Savings: ₹10,000
            Investment: ₹5,000-₹7,000 (10-15% of income)
            ```
            
            **Debt Management**:
            - Clear high-interest debts first (>12% interest)
            - Low-interest debts can continue
            
            ### Step 3: Open Necessary Accounts
            
            **Accounts Needed**:
            
            1. **Bank Account** (you already have)
            2. **Demat Account** (holds shares electronically)
            3. **Trading Account** (to place orders)
            
            **Popular Brokers in India**:
            - Zerodha
            - Upstox
            - Angel Broking
            - ICICI Direct
            - HDFC Securities
            
            **Account Opening Process**:
            ```
            1. Choose broker
            2. Fill online form
            3. Upload documents
            4. Video verification
            5. Activate account (2-3 days)
            ```
            
            **Documents Required**:
            - PAN Card
            - Aadhaar Card
            - Bank details
            - Cancelled cheque
            - Passport size photo
            
            ### Step 4: Learn Basic Platform Operations
            
            **Key Platform Features**:
            
            * **Watchlist**: Add stocks to monitor
            * **Market Watch**: Real-time prices
            * **Order Placement**: Buy/Sell options
            * **Portfolio**: Track investments
            * **Charts**: Technical analysis tools
            
            **Practice First**:
            - Use virtual trading platforms
            - Paper trade for 1-2 months
            - Learn without risking money
            
            ### Step 5: Your First Investment Plan
            
            **Conservative Beginner Portfolio**:
            ```
            Total Investment: ₹10,000
            
            1. Large Cap ETF: ₹4,000 (40%)
            2. Index Fund: ₹3,000 (30%)
            3. Blue-chip Stock: ₹2,000 (20%)
            4. Keep ₹1,000 cash (10%)
            ```
            
            **First Stock Selection Criteria**:
            1. Large, well-known company
            2. Profitable for last 10 years
            3. Pays regular dividends
            4. Low debt
            5. Industry leader
            
            ### Step 6: Making Your First Purchase
            
            **Step-by-Step Process**:
            
            1. **Research**: Choose 2-3 good companies
            2. **Analyze**: Check fundamentals
            3. **Decide**: Select one to start
            4. **Order Type**: Use limit order
            5. **Quantity**: Start with 5-10 shares
            6. **Place Order**: Through trading platform
            7. **Confirm**: Check order execution
            
            **Example First Trade**:
            ```
            Company: TCS
            Decision: Buy 5 shares
            Current Price: ₹3,200
            Limit Order: ₹3,190
            Total Cost: ₹15,950 + brokerage
            ```
            
            ### Step 7: Post-Purchase Actions
            
            **Immediate Actions**:
            - Note purchase price
            - Set price alerts
            - Add to portfolio tracker
            - Note brokerage charges
            
            **Monitoring Plan**:
            - Check weekly (not daily)
            - Review quarterly results
            - Annual report reading
            - Industry news tracking
            
            ### Step 8: Build Your Strategy
            
            **Investment Approaches**:
            
            **1. SIP (Systematic Investment Plan)**:
            - Invest fixed amount monthly
            - Example: ₹5,000 every 5th of month
            - Reduces timing risk
            
            **2. Value Investing**:
            - Buy undervalued stocks
            - Hold for long term
            - Warren Buffett style
            
            **3. Growth Investing**:
            - Focus on fast-growing companies
            - Higher risk, higher reward
            
            ### Step 9: Risk Management
            
            **Essential Rules**:
            
            1. **Stop Loss**: Always use (5-10% below buy price)
            2. **Diversification**: 8-12 stocks across sectors
            3. **Position Size**: Max 10% in one stock
            4. **No Leverage**: Avoid margin trading initially
            5. **Emotion Control**: Stick to your plan
            
            **Beginner Portfolio Structure**:
            ```
            Large Cap: 50%
            Mid Cap: 30%
            Small Cap: 10%
            Cash: 10%
            ```
            
            ### Step 10: Continuous Learning
            
            **Daily Learning Routine**:
            - 30 minutes market news
            - Follow 1 company daily
            - Read 1 annual report weekly
            - Join investor forums
            
            **Recommended Resources**:
            
            * **Books**: "The Intelligent Investor", "Rich Dad Poor Dad"
            * **Websites**: Moneycontrol, Economic Times, Screener.in
            * **YouTube**: honest explanations from SEBI registered advisors
            * **Apps**: ET Markets, Moneycontrol, TradingView
            
            ## Common Beginner Questions
            
            **Q: How much money do I need to start?**
            A: As low as ₹500 for some stocks/ETFs
            
            **Q: Which stock should I buy first?**
            A: Start with Nifty 50 index fund or large-cap ETF
            
            **Q: How often should I check prices?**
            A: Once a day is enough, not every minute
            
            **Q: When should I sell?**
            A: When fundamentals deteriorate or you need money
            
            **Q: What if price falls immediately?**
            A: Don't panic! Review fundamentals. If good, consider buying more
            
            ## Your First Month Checklist
            
            ✅ Open Demat & Trading account
            ✅ Transfer ₹5,000-₹10,000
            ✅ Practice on virtual platform
            ✅ Make first small investment
            ✅ Set up portfolio tracker
            ✅ Join investor community
            ✅ Read one investing book
            
            ## Final Advice
            
            **Start Today, Not Tomorrow**:
            - Time in market > Timing the market
            - Small regular investments grow huge over time
            - Every expert was once a beginner
            
            **Remember**: 
            "The best time to plant a tree was 20 years ago. The second best time is now."
            
            Start your investment journey today!
            """,
            "level": "Beginner",
            "time": "20 min read",
            "icon": "🚀"
        }
    },
    "Intermediate": {
        "Technical Analysis Basics": {
            "content": """
            # 📊 Technical Analysis: The Complete Guide
            
            ## What is Technical Analysis?
            
            Technical analysis is the study of **price and volume** patterns to predict future price movements. Unlike fundamental analysis (which looks at company health), TA focuses purely on market psychology and historical patterns.
            
            ### Core Principles:
            
            1. **Price Discounts Everything**: All known information is already in the price
            2. **Prices Move in Trends**: Trends persist until clear reversal signals
            3. **History Repeats Itself**: Patterns repeat due to human psychology
            
            ## Chart Types & Timeframes
            
            **Common Timeframes**:
            ```
            Intraday: 1min, 5min, 15min, 1 hour
            Short-term: Daily, Weekly
            Long-term: Monthly, Quarterly
            ```
            
            **Chart Types**:
            
            **1. Line Chart**:
            - Simple closing price line
            - Best for trend identification
            - Clean, no noise
            
            **2. Bar Chart**:
            - Shows OHLC (Open, High, Low, Close)
            - Good for volatility analysis
            ```
            |───|  High
            |   |
            |───|  Open/Close
            |   |
            |───|  Low
            ```
            
            **3. Candlestick Chart**:
            - Japanese origin
            - Shows emotion through colors
            - Best for pattern recognition
            
            **4. Renko Chart**:
            - Filters noise
            - Only shows significant moves
            - Good for clear trends
            
            ## Support and Resistance
            
            **Support**: Price level where buying interest is strong
            **Resistance**: Price level where selling pressure is strong
            
            **Key Levels**:
            ```
            Strong Support: Multiple touches, high volume
            Weak Support: Few touches, low volume
            Breakout: Price closes above resistance
            Breakdown: Price closes below support
            ```
            
            **Trading Rules**:
            - Buy near support
            - Sell near resistance
            - Buy breakout above resistance
            - Sell breakdown below support
            
            ## Trend Analysis
            
            **Trend Types**:
            
            **1. Uptrend**:
            - Higher highs and higher lows
            - Buy on dips
            - Moving averages sloping up
            
            **2. Downtrend**:
            - Lower highs and lower lows
            - Sell on rallies
            - Moving averages sloping down
            
            **3. Sideways/Range-bound**:
            - Horizontal movement
            - Trade between support/resistance
            - Wait for breakout
            
            **Trend Strength Indicators**:
            - Angle of trendline (steeper = stronger)
            - Volume confirmation
            - Time duration
            
            ## Candlestick Patterns
            
            **Single Candle Patterns**:
            
            **1. Doji**:
            - Open = Close
            - Indecision
            - Potential reversal
            
            **2. Hammer**:
            - Small body, long lower wick
            - Bullish reversal
            - At bottom of downtrend
            
            **3. Shooting Star**:
            - Small body, long upper wick
            - Bearish reversal
            - At top of uptrend
            
            **4. Marubozu**:
            - No wicks
            - Strong momentum
            - Continuation pattern
            
            **Multiple Candle Patterns**:
            
            **Bullish Patterns**:
            - Morning Star (3 candles)
            - Bullish Engulfing (2 candles)
            - Piercing Pattern (2 candles)
            - Three White Soldiers (3 candles)
            
            **Bearish Patterns**:
            - Evening Star (3 candles)
            - Bearish Engulfing (2 candles)
            - Dark Cloud Cover (2 candles)
            - Three Black Crows (3 candles)
            
            ## Volume Analysis
            
            **Volume Rules**:
            ```
            Price ↗ + Volume ↗ = Strong uptrend
            Price ↗ + Volume ↘ = Weak uptrend
            Price ↘ + Volume ↗ = Strong downtrend
            Price ↘ + Volume ↘ = Weak downtrend
            ```
            
            **Volume Patterns**:
            
            **1. Volume Breakout**:
            - High volume on breakout
            - Confirms trend strength
            - Reduces false signals
            
            **2. Volume Divergence**:
            - Price makes new high, volume doesn't
            - Warning of trend weakness
            - Possible reversal
            
            **3. Climax Volume**:
            - Extremely high volume
            - Often marks tops/bottoms
            - Capitulation point
            
            ## Moving Averages
            
            **Types of MAs**:
            
            **1. Simple MA (SMA)**:
            - Equal weight to all prices
            - Smooth but lagging
            
            **2. Exponential MA (EMA)**:
            - More weight to recent prices
            - Faster response
            - Better for short-term
            
            **Common Periods**:
            ```
            Short-term: 5, 10, 20 periods
            Medium-term: 50 periods
            Long-term: 100, 200 periods
            ```
            
            **MA Strategies**:
            
            **1. Golden Cross**:
            - 50 MA crosses above 200 MA
            - Bullish signal
            - Long-term buy
            
            **2. Death Cross**:
            - 50 MA crosses below 200 MA
            - Bearish signal
            - Long-term sell
            
            **3. MA Crossover**:
            - Fast MA crosses slow MA
            - Short-term signals
            - Quick entries/exits
            
            ## Technical Indicators
            
            **Trend Indicators**:
            
            **1. MACD (Moving Average Convergence Divergence)**:
            - Trend strength and direction
            - Signal line crossovers
            - Histogram for momentum
            
            **2. ADX (Average Directional Index)**:
            - Measures trend strength (not direction)
            - >25 = Strong trend
            - <20 = Weak trend/range
            
            **Momentum Indicators**:
            
            **1. RSI (Relative Strength Index)**:
            - Overbought/Oversold
            - 0-100 scale
            - >70 = Overbought (sell)
            - <30 = Oversold (buy)
            
            **2. Stochastic Oscillator**:
            - Similar to RSI
            - Faster signals
            - %K and %D lines
            
            **Volatility Indicators**:
            
            **1. Bollinger Bands**:
            - MA with ±2 standard deviations
            - Squeeze = Low volatility, big move coming
            - Bands expansion = High volatility
            
            **2. ATR (Average True Range)**:
            - Measures volatility
            - Sets stop losses
            - Position sizing
            
            ## Chart Patterns
            
            **Continuation Patterns**:
            
            **1. Flag/Pennant**:
            - Small consolidation after big move
            - Continuation of trend
            - Measured move target
            
            **2. Triangle**:
            - Ascending (bullish)
            - Descending (bearish)
            - Symmetrical (neutral)
            
            **Reversal Patterns**:
            
            **1. Head & Shoulders**:
            - Major reversal pattern
            - Left shoulder, head, right shoulder
            - Neckline breakout confirmation
            
            **2. Double Top/Bottom**:
            - M or W shape
            - Failed attempt at new high/low
            - Neckline breakout
            
            **3. Cup and Handle**:
            - Bullish continuation
            - Rounded bottom (cup)
            - Small consolidation (handle)
            
            ## Fibonacci Tools
            
            **Fibonacci Retracement**:
            - Key levels: 23.6%, 38.2%, 50%, 61.8%, 78.6%
            - Pullback entry points
            - Trend continuation zones
            
            **Fibonacci Extension**:
            - Profit targets: 127.2%, 161.8%, 261.8%
            - Measured moves
            - Trend exhaustion points
            
            ## Practical Trading Setup
            
            **Complete Analysis Framework**:
            
            ```
            1. Identify Trend (Daily chart)
               - Uptrend/Downtrend/Sideways
               - Use 50/200 EMA
               
            2. Find Key Levels
               - Support/Resistance
               - Previous swing highs/lows
               
            3. Wait for Setup (Lower timeframe)
               - Candlestick pattern
               - Indicator confirmation
               
            4. Entry Strategy
               - Buy at support/breakout
               - Confirm with volume
               
            5. Risk Management
               - Stop loss below support
               - Position size 1-2% risk
               
            6. Exit Strategy
               - Target at next resistance
               - Trailing stop for trends
            ```
            
            ## Common TA Mistakes
            
            ❌ **Using too many indicators** (3-4 max)
            ❌ **Ignoring volume**
            ❌ **Trading against trend**
            ❌ **No stop loss**
            ❌ **Overtrading small patterns**
            ❌ **Ignoring higher timeframe trend**
            
            ## Advanced Concepts
            
            **Multiple Timeframe Analysis**:
            - Use 3 timeframes minimum
            - Higher TF = Trend direction
            - Middle TF = Setup
            - Lower TF = Entry timing
            
            **Market Structure**:
            - Higher highs/lows = Bullish
            - Lower highs/lows = Bearish
            - Break of structure = Trend change
            
            **Order Flow Analysis**:
            - Bid-ask spread
            - Market depth
            - Large order blocks
            
            ## Practice Exercises
            
            **Exercise 1**: Find 3 stocks in clear uptrend
            **Exercise 2**: Identify support/resistance on Nifty
            **Exercise 3**: Spot candlestick patterns on charts
            **Exercise 4**: Practice setting stop losses
            **Exercise 5**: Backtest a simple MA crossover strategy
            
            ## Tools & Resources
            
            **Free Charting Platforms**:
            - TradingView (Best for learning)
            - Investing.com
            - Chartink (for Indian markets)
            
            **Recommended Books**:
            - "Technical Analysis of Financial Markets" by John Murphy
            - "Japanese Candlestick Charting Techniques" by Steve Nison
            - "Encyclopedia of Chart Patterns" by Thomas Bulkowski
            
            **YouTube Channels**:
            - Rayner Teo
            - Trading Rush
            - The Trading Channel
            
            ## Final Tips
            
            **Start Simple**:
            1. Master support/resistance
            2. Learn 3 candlestick patterns
            3. Use 2 indicators only
            4. Paper trade for 3 months
            
            **Remember**: 
            "Technical analysis is not about predicting the future. It's about calculating probabilities and managing risk."
            
            Practice daily, be patient, and let the charts teach you!
            """,
            "level": "Intermediate",
            "time": "25 min read",
            "icon": "📈"
        },
        "Fundamental Analysis": {
            "content": """
            # 📊 Fundamental Analysis: The Investor's Toolkit
            
            ## What is Fundamental Analysis?
            
            Fundamental Analysis (FA) is the method of evaluating a company's **intrinsic value** by examining related economic, financial, and other qualitative and quantitative factors. It's like being a detective investigating a company's true worth.
            
            ### Three Pillars of FA:
            
            1. **Economic Analysis**: Macro environment
            2. **Industry Analysis**: Sector prospects
            3. **Company Analysis**: Financial health
            
            ## Economic Analysis (Top-Down Approach)
            
            **Macroeconomic Factors**:
            
            **1. GDP Growth Rate**:
            - India: 6-7% normal
            - >8% = Bullish for markets
            - <5% = Concern
            
            **2. Inflation (CPI)**:
            - RBI target: 4% (±2%)
            - High inflation → Higher interest rates → Lower stock prices
            - Controlled inflation → Stable markets
            
            **3. Interest Rates**:
            - Repo Rate (RBI lending rate)
            - Low rates → Cheaper borrowing → Good for growth stocks
            - High rates → Expensive borrowing → Good for banks
            
            **4. Fiscal Policy**:
            - Government spending
            - Tax policies
            - Budget deficits/surpluses
            
            **5. Monsoon & Agriculture**:
            - Crucial for Indian economy
            - Good monsoon → Rural demand ↗ → Auto, FMCG stocks ↗
            
            ## Industry Analysis
            
            **Key Industry Metrics**:
            
            **1. Market Size & Growth**:
            ```
            Growing Industry: >15% annual growth
            Mature Industry: 5-10% growth
            Declining Industry: <5% growth
            ```
            
            **2. Competitive Landscape**:
            - Number of players
            - Market share concentration
            - Entry barriers
            - Pricing power
            
            **3. Regulatory Environment**:
            - Government policies
            - Compliance costs
            - License requirements
            
            **4. Cyclical vs Defensive**:
            
            **Cyclical Industries** (Follow economic cycles):
            - Auto, Real Estate, Capital Goods
            - Buy during recession, sell during boom
            
            **Defensive Industries** (Recession-proof):
            - FMCG, Pharma, Utilities
            - Stable demand always
            
            ## Company Analysis - Financial Statements
            
            **Three Key Statements**:
            
            **1. Balance Sheet** (Snapshot of finances):
            ```
            ASSETS = LIABILITIES + EQUITY
            
            Key Items:
            - Current Assets (Cash, Inventory)
            - Non-current Assets (Property, Equipment)
            - Current Liabilities (Short-term debt)
            - Non-current Liabilities (Long-term debt)
            - Shareholders' Equity
            ```
            
            **2. Profit & Loss Statement** (Performance over time):
            ```
            Revenue
            - Cost of Goods Sold
            = Gross Profit
            - Operating Expenses
            = Operating Profit (EBIT)
            - Interest, Taxes
            = Net Profit
            ```
            
            **3. Cash Flow Statement** (Actual cash movement):
            ```
            Operating Cash Flow: From business operations
            Investing Cash Flow: From buying/selling assets
            Financing Cash Flow: From loans, equity
            ```
            
            ## Key Financial Ratios
            
            **Profitability Ratios**:
            
            **1. Gross Margin**:
            ```
            = (Gross Profit / Revenue) × 100
            Good: >30% (Depends on industry)
            ```
            
            **2. Operating Margin**:
            ```
            = (Operating Profit / Revenue) × 100
            Good: >15%
            ```
            
            **3. Net Profit Margin**:
            ```
            = (Net Profit / Revenue) × 100
            Good: >10%
            ```
            
            **4. Return on Equity (ROE)**:
            ```
            = (Net Profit / Shareholders' Equity) × 100
            Excellent: >20%
            Good: 15-20%
            Poor: <10%
            ```
            
            **5. Return on Capital Employed (ROCE)**:
            ```
            = EBIT / (Total Assets - Current Liabilities)
            Good: >15%
            ```
            
            **Valuation Ratios**:
            
            **1. Price to Earnings (P/E)**:
            ```
            = Market Price / EPS
            Low P/E: Undervalued (but check why)
            High P/E: Growth expectations
            ```
            
            *Industry Benchmarks*:
            ```
            FMCG: 40-60
            IT: 25-35
            Banks: 15-25
            Auto: 15-30
            ```
            
            **2. Price to Book (P/B)**:
            ```
            = Market Price / Book Value per share
            <1: Possibly undervalued
            1-3: Normal range
            >3: Growth company
            ```
            
            **3. Price to Sales (P/S)**:
            ```
            = Market Cap / Total Revenue
            Useful for loss-making companies
            Lower is better (<2 usually good)
            ```
            
            **Liquidity Ratios**:
            
            **1. Current Ratio**:
            ```
            = Current Assets / Current Liabilities
            Healthy: 1.5-3
            <1: Liquidity issues
            ```
            
            **2. Quick Ratio**:
            ```
            = (Current Assets - Inventory) / Current Liabilities
            Better measure of liquidity
            >1 is good
            ```
            
            **Debt Ratios**:
            
            **1. Debt to Equity**:
            ```
            = Total Debt / Shareholders' Equity
            Ideal: <1 (Depends on industry)
            Infrastructure: 2-3 acceptable
            IT: <0.5 preferred
            ```
            
            **2. Interest Coverage Ratio**:
            ```
            = EBIT / Interest Expense
            Safe: >3
            Danger: <1.5
            ```
            
            **Efficiency Ratios**:
            
            **1. Inventory Turnover**:
            ```
            = Cost of Goods Sold / Average Inventory
            Higher = Better inventory management
            ```
            
            **2. Receivables Days**:
            ```
            = (Accounts Receivable / Revenue) × 365
            Lower = Faster collection
            Compare with industry average
            ```
            
            ## Growth Metrics
            
            **Revenue Growth**:
            ```
            Year-over-Year (YoY) growth
            5-year CAGR (Compound Annual Growth Rate)
            Consistent >15% = Excellent growth
            ```
            
            **Profit Growth**:
            ```
            PAT (Profit After Tax) growth
            Consistent profit growth > Revenue growth = Good
            ```
            
            **Future Growth Drivers**:
            - New products/services
            - Market expansion
            - Acquisitions
            - Cost reductions
            
            ## Management Quality Assessment
            
            **Key Management Traits**:
            
            **1. Track Record**:
            - Past performance
            - Capital allocation
            - Shareholder returns
            
            **2. Transparency**:
            - Clear communication
            - Honesty about challenges
            - No accounting tricks
            
            **3. Integrity**:
            - No fraud history
            - Ethical practices
            - Fair to all stakeholders
            
            **4. Skin in the Game**:
            - Promoter holding >50% = High confidence
            - Promoter buying shares = Bullish
            - Promoter selling heavily = Red flag
            
            **Check These Documents**:
            - Annual Report (Chairman's message)
            - Conference call transcripts
            - Insider trading patterns
            - Related party transactions
            
            ## Competitive Advantage (Moat)
            
            **Types of Moats**:
            
            **1. Brand Moat** (Coca-Cola, Nike):
            - Customer loyalty
            - Premium pricing power
            
            **2. Cost Moat** (Reliance, Asian Paints):
            - Lowest cost producer
            - Economies of scale
            
            **3. Network Moat** (Facebook, Uber):
            - More users = More valuable
            
            **4. Regulatory Moat** (Banks, Insurance):
            - Licenses required
            - High entry barriers
            
            **5. Switching Cost Moat** (Microsoft, SAP):
            - Difficult to change providers
            
            **Moat Indicators**:
            - High & stable profit margins
            - High return on capital
            - Market leadership
            - Pricing power
            
            ## Intrinsic Value Calculation
            
            **Discounted Cash Flow (DCF)**:
            
            ```
            Steps:
            1. Forecast free cash flows (5-10 years)
            2. Calculate terminal value
            3. Discount to present value
            4. Add cash, subtract debt
            5. Divide by shares outstanding
            ```
            
            **Simplified Graham Formula**:
            ```
            Intrinsic Value = √(22.5 × EPS × BVPS)
            Where:
            EPS = Earnings per share
            BVPS = Book value per share
            
            Margin of Safety: Buy at 50-70% of intrinsic value
            ```
            
            ## Red Flags in Financial Statements
            
            **Accounting Red Flags**:
            - Sudden change in accounting policies
            - Rising receivables without sales growth
            - Declining cash flow despite profits
            - Frequent "exceptional items"
            - Related party transactions
            
            **Business Red Flags**:
            - Declining market share
            - High employee turnover
            - Frequent management changes
            - Multiple business segments (conglomerate discount)
            - High customer concentration
            
            **Debt Red Flags**:
            - Rising debt levels
            - Short-term debt funding long-term assets
            - Debt refinancing difficulties
            - Declining interest coverage
            
            ## Complete Analysis Checklist
            
            **Step 1: Quick Screening**:
            ✅ Revenue growth > 10% (5 years)
            ✅ Profit growth > 15% (5 years)
            ✅ ROE > 15%
            ✅ Debt/Equity < 1
            ✅ Promoter holding > 50%
            
            **Step 2: Deep Analysis**:
            ✅ Read last 3 annual reports
            ✅ Analyze 5-year financials
            ✅ Study industry position
            ✅ Assess management quality
            ✅ Calculate intrinsic value
            
            **Step 3: Decision Making**:
            ✅ Compare with peers
            ✅ Check valuation multiples
            ✅ Determine margin of safety
            ✅ Set buy price (50-70% of intrinsic value)
            ✅ Plan position size (max 5-10% of portfolio)
            
            ## Practical Examples
            
            **Example 1: Analyzing a FMCG Company**
            ```
            Company: Hindustan Unilever
            Strengths: Strong brands, distribution, pricing power
            Weaknesses: Slow growth, premium valuations
            Key Metrics: ROE 75%, Debt/Equity 0.1, 5-year growth 10%
            ```
            
            **Example 2: Analyzing a Bank**
            ```
            Company: HDFC Bank
            Strengths: NIM 4%, Low NPAs, Strong CASA
            Weaknesses: Regulatory constraints, Competition
            Key Metrics: ROE 16%, CAR 18%, NPA 1.2%
            ```
            
            ## Resources & Tools
            
            **Free Resources**:
            - Screener.in (Best for Indian stocks)
            - Moneycontrol.com
            - BSE/NSE websites
            - Company annual reports
            
            **Paid Tools**:
            - Tijori Finance
            - Capitaline
            - Bloomberg Terminal (expensive)
            
            **Recommended Books**:
            - "The Intelligent Investor" by Benjamin Graham
            - "Security Analysis" by Benjamin Graham
            - "Common Stocks and Uncommon Profits" by Philip Fisher
            - "Little Book of Valuation" by Aswath Damodaran
            
            ## Common Mistakes to Avoid
            
            ❌ **Ignoring qualitative factors**
            ❌ **Relying only on P/E ratio**
            ❌ **Not reading annual reports**
            ❌ **Following herd mentality**
            ❌ **No margin of safety**
            ❌ **Overlooking debt levels**
            ❌ **Ignoring management quality**
            ❌ **Not understanding the business**
            
            ## Practice Exercises
            
            **Exercise 1**: Analyze 3 companies in same industry
            **Exercise 2**: Calculate intrinsic value for a known company
            **Exercise 3**: Read one complete annual report
            **Exercise 4**: Identify red flags in a poorly performing company
            **Exercise 5**: Compare valuation of industry leaders
            
            ## Final Thoughts
            
            **Remember**: 
            "Price is what you pay, value is what you get."
            - Warren Buffett
            
            Fundamental analysis is not about predicting short-term price movements. It's about understanding business value and buying when there's a significant discount to that value.
            
            **Golden Rules**:
            1. Understand the business first
            2. Read annual reports thoroughly
            3. Look for competitive advantages
            4. Buy with margin of safety
            5. Be patient - good investments take time
            
            Start analyzing one company per week, and in a year, you'll be analyzing like a pro!
            """,
            "level": "Intermediate",
            "time": "30 min read",
            "icon": "📊"
        }
    },
    "Advanced": {
        "Options Trading Strategies": {
            "content": """
            # 🎯 Options Trading: Advanced Strategies
            
            ## Options Basics Recap
            
            **What are Options?**
            Options are contracts that give the buyer the **right**, but not the obligation, to buy or sell an asset at a specific price on or before a certain date.
            
            **Key Terminology**:
            - **Call Option**: Right to BUY
            - **Put Option**: Right to SELL
            - **Strike Price**: Pre-determined price
            - **Expiry Date**: Contract expiration
            - **Premium**: Price paid for option
            - **Lot Size**: Standard quantity (Nifty: 75 shares)
            
            **Indian Options Specifics**:
            - Weekly, Monthly expiries
            - European style (exercise only at expiry)
            - Cash settled (no physical delivery)
            
            ## Greeks - Understanding Option Pricing
            
            **Delta (Δ)**:
            ```
            Measures: Price change for ₹1 change in underlying
            Call Delta: 0 to +1
            Put Delta: -1 to 0
            ATM Delta: ~0.5 for calls, ~-0.5 for puts
            ```
            
            **Gamma (Γ)**:
            ```
            Measures: Rate of change of Delta
            Highest: ATM options near expiry
            Importance: Accelerates profits/losses
            ```
            
            **Theta (Θ)**:
            ```
            Measures: Time decay (daily)
            Always negative for buyers
            Positive for sellers (premium collected)
            ```
            
            **Vega (ν)**:
            ```
            Measures: Sensitivity to volatility
            Higher volatility = Higher premium
            Long options = Positive Vega
            Short options = Negative Vega
            ```
            
            **Rho (ρ)**:
            ```
            Measures: Interest rate sensitivity
            Less important for short-term trades
            ```
            
            ## Basic Strategies
            
            **1. Long Call (Bullish)**:
            ```
            Action: Buy Call Option
            Max Profit: Unlimited
            Max Loss: Premium paid
            Breakeven: Strike Price + Premium
            Best For: Strong bullish view
            ```
            
            **2. Long Put (Bearish)**:
            ```
            Action: Buy Put Option
            Max Profit: (Strike - 0) - Premium
            Max Loss: Premium paid
            Breakeven: Strike Price - Premium
            Best For: Strong bearish view
            ```
            
            **3. Covered Call**:
            ```
            Action: Own Stock + Sell Call
            Profit: Limited (Premium + Stock gain upto strike)
            Loss: Unlimited downside on stock
            Best For: Generating income on existing holdings
            ```
            
            **4. Protective Put**:
            ```
            Action: Own Stock + Buy Put
            Profit: Unlimited upside
            Loss: Limited to Put premium
            Best For: Insurance against downside
            ```
            
            ## Income Generation Strategies
            
            **1. Cash Secured Put**:
            ```
            Action: Sell Put + Keep cash for assignment
            Profit: Premium received
            Risk: Obligation to buy at strike
            Best For: Want to buy stock at lower price
            ```
            
            **2. Credit Spreads**:
            
            **Bull Put Spread** (Bullish):
            ```
            Sell higher strike Put
            Buy lower strike Put
            Net Credit received
            Limited risk, limited reward
            ```
            
            **Bear Call Spread** (Bearish):
            ```
            Sell lower strike Call
            Buy higher strike Call
            Net Credit received
            Limited risk, limited reward
            ```
            
            ## Volatility Strategies
            
            **1. Straddle** (Volatility Play):
            ```
            Action: Buy Call + Buy Put (Same strike, expiry)
            Profit: Large move in either direction
            Loss: Premium paid (if small move)
            Best For: Earnings announcements, events
            ```
            
            **2. Strangle** (Cheaper Straddle):
            ```
            Action: Buy OTM Call + Buy OTM Put
            Profit: Very large move needed
            Loss: Lower premium than straddle
            Best For: High expected volatility
            ```
            
            **3. Iron Condor** (Range-bound):
            ```
            Action: Sell OTM Call spread + Sell OTM Put spread
            Profit: Premium received (if stays in range)
            Loss: Limited (defined risk)
            Best For: Low volatility, range-bound markets
            Probability: 70-80% success
            ```
            
            ## Advanced Multi-leg Strategies
            
            **1. Butterfly Spread**:
            
            **Long Call Butterfly** (Neutral):
            ```
            Buy 1 ITM Call
            Sell 2 ATM Calls
            Buy 1 OTM Call
            All same expiry
            Profit: If stock at middle strike at expiry
            Max Profit: High (3:1 risk-reward)
            ```
            
            **2. Calendar Spread**:
            ```
            Sell near-term option
            Buy longer-term option
            Same strike price
            Profit: Time decay differential
            Best For: Low volatility, sideways market
            ```
            
            **3. Diagonal Spread**:
            ```
            Combination of vertical and calendar
            Different strikes and expiries
            Complex adjustments possible
            For experienced traders only
            ```
            
            ## Nifty/Bank Nifty Specific Strategies
            
            **Weekly Options Strategy**:
            
            **Wednesday Expiry Play**:
            ```
            Day: Monday/Tuesday
            Strategy: Sell Iron Condor
            Strikes: 1 SD away (68% probability)
            Exit: Tuesday EOD or 50% profit
            Risk: Event risk (avoid Wednesdays)
            ```
            
            **Monthly Expiry Strategy**:
            ```
            Time: 7-10 days before expiry
            Strategy: Strangle or Straddle
            Adjust: Based on PCR (Put-Call Ratio)
            Exit: 2-3 days before expiry
            ```
            
            ## Risk Management in Options
            
            **Position Sizing Rules**:
            ```
            Max per trade: 2-5% of capital
            Max concurrent trades: 3-5
            Max loss per month: 10%
            Stop loss: 50-100% of premium
            ```
            
            **Adjustment Techniques**:
            
            **1. Rolling**:
            - Move position to further expiry
            - Can roll for credit or debit
            - Changes strike prices if needed
            
            **2. Hedging**:
            - Add opposing position
            - Use futures for delta hedge
            - Buy cheap options for protection
            
            **3. Taking Partial Profits**:
            - Close 50% at 25% profit
            - Move stop to breakeven
            - Let winners run with trailing stop
            
            ## Trading Psychology for Options
            
            **Common Psychological Traps**:
            
            **1. Overtrading**:
            - Too many positions
            - Solution: Max 5 active trades
            
            **2. Revenge Trading**:
            - Trying to recover losses quickly
            - Solution: Daily loss limit
            
            **3. Hope Trading**:
            - Not exiting losing trades
            - Solution: Strict stop losses
            
            **4. FOMO (Fear Of Missing Out)**:
            - Chasing trades
            - Solution: Wait for setups
            
            **Mental Rules**:
            - Trade the plan, not P&L
            - Accept small losses gracefully
            - Celebrate consistency, not profits
            - Review trades weekly
            - Take breaks after losses
            
            ## Practical Trading Plan
            
            **Daily Routine**:
            
            **Pre-Market (9:00-9:15)**:
            1. Check global markets
            2. Analyze FII/DII data
            3. Check PCR levels
            4. Identify support/resistance
            5. Plan trades (max 2 for day)
            
            **Market Hours**:
            1. Execute planned trades only
            2. Monitor open positions
            3. Take profits at targets
            4. Never chase movements
            5. Stick to stop losses
            
            **Post-Market**:
            1. Journal all trades
            2. Review mistakes
            3. Plan for next day
            4. Check margin requirements
            
            ## Tools & Platforms
            
            **Essential Tools**:
            
            **1. Option Chain Analyzer**:
            - OI (Open Interest) changes
            - Volume analysis
            - Max Pain point
            - PCR calculation
            
            **2. Greeks Calculator**:
            - Real-time Greek values
            - Breakeven calculator
            - Probability calculator
            
            **3. Backtesting Software**:
            - Strategy testing
            - Historical volatility
            - Performance metrics
            
            **Recommended Platforms**:
            - Sensibull (Best for options)
            - Opstra (Advanced analytics)
            - Zerodha Kite (Execution)
            - TradingView (Charts)
            
            ## Money Management System
            
            **Capital Allocation**:
            ```
            Total Capital: ₹10,00,000
            Trading Capital: ₹2,00,000 (20%)
            Per Trade Risk: ₹4,000 (2% of trading capital)
            Monthly Target: 5-10% return
            ```
            
            **Risk-Reward Ratio**:
            - Minimum 1:2
            - Ideal 1:3
            - Never take 1:1 trades
            
            **Drawdown Control**:
            - 5% drawdown: Reduce position size 50%
            - 10% drawdown: Stop trading for week
            - 15% drawdown: Complete review required
            
            ## Common Mistakes & Solutions
            
            **Mistake 1: Selling Naked Options**
            ```
            Problem: Unlimited risk
            Solution: Always use defined risk strategies
            ```
            
            **Mistake 2: Ignoring Time Decay**
            ```
            Problem: Buying options too early
            Solution: Buy 30-45 days before expiry
            ```
            
            **Mistake 3: Wrong Position Sizing**
            ```
            Problem: Too large positions
            Solution: Use premium-based sizing
            ```
            
            **Mistake 4: No Exit Plan**
            ```
            Problem: Holding losing positions
            Solution: Pre-defined exit rules
            ```
            
            ## Advanced Concepts
            
            **Volatility Trading**:
            
            **1. IV Rank/Percentile**:
            ```
            IV Rank: Current IV vs 52-week range
            IV Percentile: % of days IV was lower
            High IV (>70%): Sell options
            Low IV (<30%): Buy options
            ```
            
            **2. Volatility Smile/Skew**:
            - OTM puts more expensive (fear)
            - OTM calls cheaper (greed)
            - Trade the skew
            
            **Market Microstructure**:
            - Order flow analysis
            - Dark pool trading
            - Smart money tracking
            
            ## Practice Exercises
            
            **Exercise 1**: Paper trade Iron Condor for 1 month
            **Exercise 2**: Calculate Greeks for Nifty options
            **Exercise 3**: Backtest straddle strategy on earnings
            **Exercise 4**: Create trading journal template
            **Exercise 5**: Simulate margin requirements for strategies
            
            ## Final Checklist
            
            **Before Trading Options**:
            ✅ Understand all risks
            ✅ Paper trade for 3 months
            ✅ Have adequate capital (min ₹2 lakhs)
            ✅ Learn from experienced trader
            ✅ Start with defined risk strategies only
            
            **Daily Trading Checklist**:
            ✅ Check market sentiment
            ✅ Review open positions
            ✅ Set alerts for adjustments
            ✅ Never trade without stop loss
            ✅ Journal every decision
            
            **Monthly Review**:
            ✅ Analyze win rate
            ✅ Calculate risk-adjusted returns
            ✅ Identify patterns in losses
            ✅ Adjust strategy if needed
            ✅ Take profits out of account
            
            ## Wisdom from Experts
            
            **Key Quotes**:
            
            "The option market is a market of probabilities, not possibilities."
            
            "Options are like fire - useful tool if controlled, dangerous if not."
            
            "Amateurs think about profits, professionals think about risk."
            
            **Golden Rules**:
            1. Preserve capital first
            2. Trade small, trade often
            3. Let probabilities work for you
            4. Stay disciplined always
            5. Keep learning continuously
            
            ## Resources
            
            **Books**:
            - "Options as a Strategic Investment" by Lawrence McMillan
            - "Trading Options Greeks" by Dan Passarelli
            - "The Bible of Options Strategies" by Guy Cohen
            
            **Courses**:
            - NSE Academy options course
            - Zerodha Varsity (free)
            - Sensibull learning center
            
            **Communities**:
            - TradingQnA
            - Traderji
            - ValuePickr (for discussions)
            
            **Remember**: 
            Options trading is a skill that takes years to master. Start slow, stay small, and focus on consistency rather than quick profits. The market will always be there tomorrow!
            
            Trade safe and trade smart! 🎯
            """,
            "level": "Advanced",
            "time": "35 min read",
            "icon": "🎯"
        },
        "Risk Management Mastery": {
            "content": """
            # 🛡️ Risk Management: The Ultimate Guide
            
            ## Why Risk Management is Everything
            
            In trading and investing, risk management isn't just important—it's **EVERYTHING**. Without proper risk management, you're not investing, you're gambling.
            
            **Famous Statistics**:
            ```
            90% of traders lose money
            5% break even
            5% make consistent profits
            ```
            
            The difference? **RISK MANAGEMENT**
            
            ## The Foundation: Risk vs Reward
            
            **Key Principle**: 
            "Risk comes from not knowing what you're doing."
            - Warren Buffett
            
            **Three Types of Risk**:
            
            1. **Market Risk** (Systematic):
               - Affects all investments
               - Economic factors, interest rates, wars
               - Cannot be eliminated, only managed
               
            2. **Specific Risk** (Unsystematic):
               - Company-specific issues
               - Management changes, product failures
               - Can be reduced through diversification
               
            3. **Liquidity Risk**:
               - Cannot buy/sell quickly
               - Large bid-ask spreads
               - Important for large positions
            
            ## The Golden Rule: Position Sizing
            
            **The 1% Rule**:
            ```
            Never risk more than 1% of total capital on a single trade
            
            Example:
            Total Capital: ₹10,00,000
            Max Risk per Trade: ₹10,000 (1%)
            ```
            
            **How to Calculate Position Size**:
            
            ```
            Position Size = (Capital × Risk %) ÷ (Entry - Stop Loss)
            
            Example:
            Capital: ₹10,00,000
            Risk %: 1% = ₹10,000
            Stock Price: ₹1,000
            Stop Loss: ₹950 (5% below)
            Position Size = 10,000 ÷ (1000 - 950) = 200 shares
            Investment = 200 × 1000 = ₹2,00,000
            ```
            
            **Advanced Position Sizing Methods**:
            
            **1. Kelly Criterion**:
            ```
            f* = (bp - q) / b
            Where:
            f* = Fraction of capital to bet
            b = Net odds received (profit/loss ratio)
            p = Probability of winning
            q = Probability of losing (1-p)
            
            Conservative: Use ½ Kelly or ¼ Kelly
            ```
            
            **2. Fixed Fractional**:
            ```
            Risk fixed % of current capital
            Adjusts position size with account growth/decline
            Example: Always risk 1% of current balance
            ```
            
            **3. Fixed Ratio**:
            ```
            Increase size after fixed profit amount
            Example: Add 1 lot after every ₹50,000 profit
            ```
            
            ## Stop Loss Strategies
            
            **Types of Stop Losses**:
            
            **1. Percentage Stop**:
            ```
            Fixed % below entry price
            Example: 5-10% for stocks, 2-3% for futures
            Simple but not adaptive
            ```
            
            **2. Volatility Stop (ATR-based)**:
            ```
            Based on Average True Range
            Example: 2 × ATR below entry
            Adjusts to market volatility
            ```
            
            **3. Technical Stop**:
            ```
            Below support levels
            Below moving averages
            Below trendlines
            Most logical approach
            ```
            
            **4. Time Stop**:
            ```
            Exit if not profitable within X days
            Example: Exit if not up 5% in 10 days
            Prevents dead money
            ```
            
            **5. Trailing Stop**:
            ```
            Moves up as price increases
            Types: Percentage, ATR, Parabolic SAR
            Locks in profits
            ```
            
            **Stop Loss Placement Rules**:
            
            **For Buy Trades**:
            ```
            1. Below recent swing low
            2. Below key support level
            3. Below moving average (20/50 EMA)
            4. 1-2% below entry for day trades
            5. 5-10% below for investments
            ```
            
            **For Short Trades**:
            ```
            1. Above recent swing high
            2. Above key resistance
            3. Above moving average
            ```
            
            **Common Stop Loss Mistakes**:
            ❌ Placing too close (gets stopped often)
            ❌ Placing too far (large losses)
            ❌ Moving stop loss away from price
            ❌ No stop loss (hoping it comes back)
            ❌ Removing stop loss after entry
            
            ## Portfolio Risk Management
            
            **Correlation Matrix**:
            ```
            Avoid highly correlated positions
            Ideal: Mix of negatively/uncorrelated assets
            Example: Tech stocks + Pharma + FMCG
            ```
            
            **Sector Allocation**:
            ```
            Max 25% in one sector
            Ideal: 5-8 sectors
            Rebalance quarterly
            ```
            
            **Market Cap Allocation**:
            ```
            Large Cap: 50-60% (Foundation)
            Mid Cap: 20-30% (Growth)
            Small Cap: 10-20% (Speculation)
            Adjust based on market cycle
            ```
            
            **Geographic Diversification**:
            ```
            India: 70%
            US: 20%
            Other: 10%
            Reduces country-specific risk
            ```
            
            ## Advanced Risk Metrics
            
            **1. Value at Risk (VaR)**:
            ```
            Maximum expected loss over period
            Confidence level: 95% or 99%
            Time horizon: 1 day, 1 week, 1 month
            
            Example: 
            "95% confident won't lose more than 5% in month"
            ```
            
            **2. Maximum Drawdown (MDD)**:
            ```
            Largest peak-to-trough decline
            Measures worst-case historical loss
            Recovery time important
            ```
            
            **3. Sharpe Ratio**:
            ```
            Risk-adjusted return
            = (Return - Risk-free rate) / Standard Deviation
            Higher = Better risk-adjusted returns
            >1 = Good, >2 = Excellent
            ```
            
            **4. Sortino Ratio**:
            ```
            Like Sharpe, but only downside deviation
            Better for asymmetric returns
            = (Return - Risk-free rate) / Downside Deviation
            ```
            
            **5. Calmar Ratio**:
            ```
            = Annual Return / Maximum Drawdown
            Measures return per unit of drawdown
            >1 = Good, >3 = Excellent
            ```
            
            ## Psychological Risk Management
            
            **Emotional Triggers & Solutions**:
            
            **1. Fear of Missing Out (FOMO)**:
            ```
            Trigger: Seeing others make money
            Solution: Have entry checklist, wait for setup
            ```
            
            **2. Revenge Trading**:
            ```
            Trigger: Recent loss
            Solution: Daily loss limit, take break
            ```
            
            **3. Hope Trading**:
            ```
            Trigger: Losing position
            Solution: Pre-defined stop loss, no exceptions
            ```
            
            **4. Overconfidence**:
            ```
            Trigger: Winning streak
            Solution: Reduce position size, review trades
            ```
            
            **Mental Stop Losses**:
            ```
            1. Daily loss limit (2-3% of capital)
            2. Weekly loss limit (5-7%)
            3. Monthly loss limit (10-15%)
            4. Consecutive loss limit (3-5 trades)
            ```
            
            ## Market Condition Adjustments
            
            **Volatility-Based Adjustments**:
            
            **High VIX (>25)**:
            ```
            Reduce position size 50%
            Use wider stop losses
            Avoid leverage
            Focus on hedging
            ```
            
            **Low VIX (<15)**:
            ```
            Normal position sizing
            Tighter stop losses
            Can use modest leverage
            Good for trend following
            ```
            
            **Market Cycle Adjustments**:
            
            **Bull Market**:
            ```
            Increase equity exposure
            Use trailing stops
            Take partial profits
            ```
            
            **Bear Market**:
            ```
            Reduce equity exposure
            Increase cash position
            Use inverse ETFs
            Focus on shorting or puts
            ```
            
            **Sideways Market**:
            ```
            Reduce position size
            Range trading strategies
            Options selling (premium collection)
            Wait for breakout
            ```
            
            ## Leverage Management
            
            **The Dangers of Leverage**:
            ```
            Leverage amplifies both gains AND losses
            Most common cause of blowups
            Requires extreme discipline
            ```
            
            **Safe Leverage Guidelines**:
            
            **For Stocks**:
            ```
            Beginners: No leverage
            Experienced: Max 1:1 (50% margin)
            Pros: Max 2:1 (66% margin)
            ```
            
            **For Futures**:
            ```
            Lot size × Margin < 10% of capital
            Always keep 50% margin buffer
            Never use 100% of available margin
            ```
            
            **For Options**:
            ```
            Selling naked: Very dangerous
            Spreads: Defined risk better
            Buying: Premium = Max loss (safe)
            ```
            
            **Margin Call Prevention**:
            1. Always maintain 30% extra margin
            2. Monitor positions daily
            3. Have emergency fund
            4. Know broker's margin rules
            
            ## Crisis Management Plan
            
            **Black Swan Events**:
            ```
            COVID-19 crash: -40% in weeks
            2008 crisis: -60% over year
            Flash crashes: -10% in minutes
            ```
            
            **Pre-Crisis Preparation**:
            
            1. **Portfolio Hedging**:
               ```
               Always have 10-20% in cash
               Keep some gold/digital gold
               Consider put options for insurance
               ```
            
            2. **Diversification**:
               ```
               Across asset classes
               Across geographies
               Across currencies
               ```
            
            3. **Liquidity Management**:
               ```
               Keep emergency fund (6 months expenses)
               Avoid illiquid investments
               Know what you can sell quickly
               ```
            
            **During Crisis Actions**:
            
            1. **Assessment Phase (Days 1-3)**:
               ```
               Don't panic sell
               Assess damage
               Check margin requirements
               ```
            
            2. **Action Phase (Days 4-10)**:
               ```
               Rebalance if needed
               Add hedges if too late to sell
               Raise cash from strongest positions
               ```
            
            3. **Recovery Phase (Weeks 2-8)**:
               ```
               Look for buying opportunities
               DCA into quality assets
               Rebuild gradually
               ```
            
            ## Risk Management Systems
            
            **Daily Risk Checklist**:
            
            ✅ **Pre-Market**:
               - Check global markets
               - Review news/events
               - Calculate position sizes
               - Set stop losses
            
            ✅ **During Market**:
               - Monitor open positions
               - Check margin usage
               - No new trades after 2% daily loss
               - Take partial profits at targets
            
            ✅ **Post-Market**:
               - Journal all trades
               - Calculate daily P&L
               - Update risk metrics
               - Plan for next day
            
            **Weekly Risk Review**:
            
            1. **Portfolio Analysis**:
               - Check sector allocation
               - Review correlation
               - Calculate VAR
            
            2. **Performance Review**:
               - Win rate
               - Risk-reward ratio
               - Maximum drawdown
            
            3. **Strategy Adjustments**:
               - What worked/didn't work
               - Adjust position sizing if needed
               - Update stop loss methods
            
            **Monthly Risk Report**:
            
            ```
            Section 1: Performance
            - Total return
            - Sharpe/Sortino ratio
            - Maximum drawdown
            
            Section 2: Risk Metrics
            - VAR (95%, 99%)
            - Beta to market
            - Correlation analysis
            
            Section 3: Improvements
            - Best/worst trades
            - Lessons learned
            - Action plan for next month
            ```
            
            ## Common Risk Management Mistakes
            
            **Beginner Mistakes**:
            ❌ No stop loss
            ❌ Position too large
            ❌ Adding to losing positions
            ❌ Trading without plan
            ❌ Ignoring correlation
            
            **Intermediate Mistakes**:
            ❌ Over-diversification
            ❌ Underestimating tail risk
            ❌ Not adjusting for volatility
            ❌ Emotional stop loss moving
            ❌ Ignoring liquidity risk
            
            **Advanced Mistakes**:
            ❌ Over-optimization
            ❌ Strategy drift
            ❌ Ignuring black swans
            ❌ Complacency after success
            ❌ Not having crisis plan
            
            ## Risk Management Tools & Software
            
            **Free Tools**:
            - Portfolio Visualizer (backtesting)
            - Riskalyze (risk assessment)
            - Excel/Google Sheets (custom trackers)
            
            **Paid Tools**:
            - Bloomberg Terminal (professional)
            - Morningstar Direct
            - RiskMetrics
            
            **Broker Tools**:
            - Zerodha Console (risk analytics)
            - Upstox Risk Management
            - ICICI Direct Portfolio Manager
            
            **DIY Spreadsheet Template**:
            ```
            Tabs Needed:
            1. Positions (current holdings)
            2. Trades (historical)
            3. Risk Metrics (VAR, beta, etc.)
            4. Performance (charts)
            5. Journal (lessons)
            ```
            
            ## Case Studies
            
            **Case Study 1: The Conservative Investor**
            ```
            Capital: ₹50,00,000
            Strategy: 1% risk per trade, max 5 positions
            Stop Loss: 10% for investments
            Result: 15% annual return, max drawdown 12%
            Lesson: Consistency beats excitement
            ```
            
            **Case Study 2: The Aggressive Trader**
            ```
            Capital: ₹10,00,000
            Strategy: 5% risk per trade, 10 positions
            Stop Loss: 2% for trades
            Result: 40% return year 1, -60% year 2
            Lesson: High risk can work until it doesn't
            ```
            
            **Case Study 3: The Balanced Approach**
            ```
            Capital: ₹25,00,000
            Strategy: Core (80%) + Satellite (20%)
            Core: 1% risk, Satellite: 3% risk
            Result: 20% return, 15% drawdown
            Lesson: Best of both worlds
            ```
            
            ## Creating Your Risk Management Plan
            
            **Step 1: Risk Tolerance Assessment**
            ```
            Questionnaire:
            1. What % loss would make you uncomfortable?
            2. How long can you stay invested?
            3. Need for liquidity?
            4. Investment experience?
            5. Financial goals?
            ```
            
            **Step 2: Capital Allocation**
            ```
            Based on risk tolerance:
            Conservative: 70% debt, 30% equity
            Moderate: 50% debt, 50% equity
            Aggressive: 30% debt, 70% equity
            ```
            
            **Step 3: Position Sizing Rules**
            ```
            Conservative: 0.5% risk per trade
            Moderate: 1% risk per trade
            Aggressive: 2% risk per trade
            Max positions: 10-20
            ```
            
            **Step 4: Exit Rules**
            ```
            Stop Loss: Technical + % based
            Take Profit: 2:1 or 3:1 risk-reward
            Time Exit: 20-50 days maximum
            ```
            
            **Step 5: Review Schedule**
            ```
            Daily: Check positions, stop losses
            Weekly: Portfolio rebalance
            Monthly: Performance review
            Quarterly: Strategy review
            Yearly: Complete overhaul
            ```
            
            ## Final Wisdom
            
            **10 Commandments of Risk Management**:
            
            1. **Thou shalt preserve capital** above all
            2. **Thou shalt use stop losses** always
            3. **Thou shalt size positions** properly
            4. **Thou shalt diversify** adequately
            5. **Thou shalt know thy risk tolerance**
            6. **Thou shalt have an exit plan** before entry
            7. **Thou shalt keep emotions** in check
            8. **Thou shalt review** performance regularly
            9. **Thou shalt learn** from losses
            10. **Thou shalt be patient** - markets reward discipline
            
            **Remember**: 
            "The first rule of making money is not losing it. The second rule is not forgetting the first rule."
            
            **Final Thought**:
            Risk management is boring. It's not sexy. It doesn't make for exciting stories. But it's what separates the 5% who succeed from the 95% who fail. Master risk management, and you master the markets.
            
            Stay safe, stay disciplined, and may your risks be small and your rewards be large! 🛡️
            """,
            "level": "Advanced",
            "time": "40 min read",
            "icon": "🛡️"
        }
    },
    "Psychology": {
        "Trading Psychology": {
            "content": """
            # 🧠 Trading Psychology: Master Your Mind, Master the Markets
            
            ## The Mental Game of Trading
            
            Trading is 80% psychology, 15% risk management, and 5% strategy. You can have the best strategy in the world, but without the right mindset, you'll still fail.
            
            **Why Psychology Matters**:
            ```
            Same strategy + Different psychology = Different results
            Markets don't change - Your perception does
            Biggest enemy = Yourself
            ```
            
            ## The Trader's Mindset
            
            **Professional vs Amateur Mindset**:
            
            | Aspect | Professional | Amateur |
            |--------|-------------|---------|
            | Focus | Process | Profits |
            | Losses | Learning opportunity | Failure |
            | Wins | Expected outcome | Exciting event |
            | Planning | Detailed plan | No plan |
            | Emotions | Controlled | Controlling |
            | Timeframe | Long-term | Short-term |
            
            **Developing the Right Mindset**:
            
            1. **Process Over Outcome**:
               ```
               Bad: "I need to make money today"
               Good: "I need to follow my plan today"
               ```
            
            2. **Probability Thinking**:
               ```
               Bad: "This trade will work"
               Good: "This trade has 60% probability"
               ```
            
            3. **Abundance Mentality**:
               ```
               Bad: "I missed my chance"
               Good: "There's always another opportunity"
               ```
            
            ## Common Psychological Biases
            
            **1. Confirmation Bias**:
            ```
            Problem: Only see information confirming beliefs
            Example: Ignoring bad news about favorite stock
            Solution: Actively seek contradictory evidence
            ```
            
            **2. Overconfidence Bias**:
            ```
            Problem: After wins, think you can't lose
            Example: Increasing position size after success
            Solution: Stick to position sizing rules always
            ```
            
            **3. Loss Aversion**:
            ```
            Problem: Pain of loss > Joy of equal gain
            Example: Holding losers, selling winners early
            Solution: Pre-defined exit rules, no exceptions
            ```
            
            **4. Recency Bias**:
            ```
            Problem: Overweight recent events
            Example: Buying because stock went up yesterday
            Solution: Look at longer timeframes
            ```
            
            **5. Anchoring**:
            ```
            Problem: Fixating on specific price
            Example: "I'll sell when it gets back to my buy price"
            Solution: Trade current price, not past price
            ```
            
            **6. Herd Mentality**:
            ```
            Problem: Following crowd without thinking
            Example: Buying because everyone is buying
            Solution: Have independent analysis
            ```
            
            **7. Gambler's Fallacy**:
            ```
            Problem: "I've lost 5 times, next must be win"
            Solution: Each trade is independent
            ```
            
            ## Emotional States in Trading
            
            **The Emotional Cycle**:
            
            ```
            1. Optimism (Enter trade)
            2. Excitement (Price moves your way)
            3. Thrill (Big profits)
            4. Euphoria (Overconfidence sets in)
            5. Anxiety (Price reverses slightly)
            6. Denial ("It will come back")
            7. Fear (Losses mounting)
            8. Desperation (Hoping for miracle)
            9. Panic (Selling at bottom)
            10. Relief (Pain stops)
            11. Depression (After loss)
            12. Hope (Looking for next trade)
            ```
            
            **Breaking the Cycle**:
            - Exit before anxiety phase
            - Have profit targets
            - Use trailing stops
            - Take breaks between trades
            
            ## Building Mental Discipline
            
            **Daily Routine for Mental Strength**:
            
            **Morning Preparation (Before Market)**:
            ```
            1. Meditation (10 minutes)
            2. Visualization (See yourself following rules)
            3. Review trading plan
            4. Set intentions ("Today I will...")
            5. Physical exercise (30 minutes)
            ```
            
            **During Trading**:
            ```
            1. Breathing exercises before each trade
            2. Check emotional state (scale 1-10)
            3. If emotional > 6, don't trade
            4. Take breaks every 90 minutes
            5. Hydrate and eat light
            ```
            
            **After Trading**:
            ```
            1. Journal about emotional states
            2. Review trades without judgment
            3. Meditation to clear mind
            4. Disconnect from markets
            5. Physical activity
            ```
            
            **Weekly Mental Maintenance**:
            ```
            1. Complete trade journal review
            2. Identify emotional patterns
            3. Plan improvements
            4. Weekend digital detox
            5. Nature time
            ```
            
            ## Overcoming Fear & Greed
            
            **Managing Fear**:
            
            **Types of Fear**:
            1. **Fear of Missing Out (FOMO)**
            2. **Fear of Losing**
            3. **Fear of Being Wrong**
            4. **Fear of Success**
            
            **Fear Management Techniques**:
            
            **1. Systematic Approach**:
            ```
            Have checklist for every trade
            No checklist = No trade
            Removes emotional decision making
            ```
            
            **2. Position Sizing**:
            ```
            Trade small when fearful
            "This is just a test trade" mentality
            Build confidence gradually
            ```
            
            **3. Visualization**:
            ```
            Visualize worst-case scenario
            Plan your response
            Reduces fear of unknown
            ```
            
            **4. Acceptance**:
            ```
            Accept that losses will happen
            It's part of the business
            Focus on process, not individual outcomes
            ```
            
            **Managing Greed**:
            
            **Greed Warning Signs**:
            - Adding to winning positions beyond plan
            - Moving profit targets further away
            - Overtrading
            - Taking excessive risk
            
            **Greed Management Techniques**:
            
            **1. Profit Taking Rules**:
            ```
            Take partial profits at targets
            "Leave some for the next person"
            Lock in gains systematically
            ```
            
            **2. Position Limits**:
            ```
            Maximum X positions open
            Maximum Y% in one trade
            Hard limits prevent overexposure
            ```
            
            **3. Cooling Off Period**:
            ```
            After big win, take 1-3 days off
            Avoid "hot hand" fallacy
            Let emotions settle
            ```
            
            ## Developing Patience
            
            **The Waiting Game**:
            
            ```
            Professional traders spend:
            70% waiting for setup
            20% managing positions
            10% entering/exiting
            ```
            
            **Patience Exercises**:
            
            **Exercise 1: The 24-Hour Rule**:
            ```
            See a trade setup? Wait 24 hours
            If still valid, take it
            Eliminates impulsive trading
            ```
            
            **Exercise 2: The Empty Chart**:
            ```
            Sit with blank chart for 30 minutes
            Don't take any trades
            Builds tolerance for inaction
            ```
            
            **Exercise 3: The Watchlist Game**:
            ```
            Add 10 stocks to watchlist
            Don't trade any for week
            Observe how many setups actually worked
            ```
            
            **Benefits of Patience**:
            - Better entry prices
            - Higher probability setups
            - Less overtrading
            - Lower brokerage costs
            - Less stress
            
            ## Building Confidence
            
            **Genuine vs False Confidence**:
            
            **False Confidence**:
            - Based on recent wins
            - Leads to over-trading
            - Crashes after losses
            
            **Genuine Confidence**:
            - Based on proven process
            - Survives losing streaks
            - Consistent over time
            
            **Confidence Building Steps**:
            
            **Step 1: Mastery through Repetition**:
            ```
            Practice one strategy 100 times
            Paper trade until consistent
            Build muscle memory
            ```
            
            **Step 2: Track Record**:
            ```
            Keep detailed journal
            Review winning trades
            See evidence of success
            ```
            
            **Step 3: Competence Stacking**:
            ```
            Master risk management first
            Then master entries
            Then master exits
            Build skills systematically
            ```
            
            **Step 4: Positive Self-Talk**:
            ```
            Instead of: "I hope this works"
            Say: "I'm following my plan"
            Instead of: "Don't lose money"
            Say: "Manage risk properly"
            ```
            
            ## Handling Losses Psychologically
            
            **Healthy vs Unhealthy Response to Losses**:
            
            **Unhealthy Response**:
            - Anger and frustration
            - Blaming external factors
            - Revenge trading
            - Hiding losses
            
            **Healthy Response**:
            - Acceptance and analysis
            - Taking responsibility
            - Learning lessons
            - Adjusting strategy if needed
            
            **Loss Recovery Protocol**:
            
            **After a Loss**:
            ```
            1. Close all positions
            2. Take deep breaths
            3. Walk away from screens
            4. Physical activity (walk, exercise)
            5. Return only when calm
            6. Journal the loss objectively
            7. Identify lesson
            8. Plan improvement
            ```
            
            **Consecutive Losses Protocol**:
            ```
            1 loss: Review trade
            2 losses: Reduce position size 50%
            3 losses: Take day off
            4 losses: Take week off
            5 losses: Complete strategy review
            ```
            
            **Reframing Losses**:
            ```
            Instead of: "I lost money"
            Think: "I paid for education"
            Instead of: "I failed"
            Think: "I collected data"
            Instead of: "This sucks"
            Think: "What can I learn?"
            ```
            
            ## Mindfulness in Trading
            
            **Mindfulness Techniques**:
            
            **1. Breathing Awareness**:
            ```
            Before each trade: 3 deep breaths
            Focus on breath, not P&L
            Calms nervous system
            ```
            
            **2. Body Scan**:
            ```
            Check body for tension
            Shoulders, jaw, stomach
            Relax tense areas
            ```
            
            **3. Thought Labeling**:
            ```
            "This is fear thinking"
            "This is greed thinking"
            "This is hope thinking"
            Don't fight thoughts, just label them
            ```
            
            **4. Present Moment Focus**:
            ```
            "Right now, I'm looking at a chart"
            "Right now, I'm breathing"
            "Right now, I'm following my plan"
            Bring attention to present
            ```
            
            **Benefits of Mindfulness**:
            - Better decision making
            - Reduced emotional trading
            - Improved focus
            - Lower stress levels
            - Better risk management
            
            ## Creating Your Psychological Edge
            
            **Personal Trading Constitution**:
            
            Create a written document with:
            
            ```
            1. My Trading Philosophy
               - What kind of trader am I?
               - What are my core beliefs?
               
            2. My Rules (Never Break)
               - Position sizing rules
               - Stop loss rules
               - Entry/exit rules
               
            3. My Process
               - Daily routine
               - Trade checklist
               - Review process
               
            4. My Values
               - Discipline over profits
               - Learning over winning
               - Process over outcome
               
            5. My Identity
               - "I am a disciplined trader"
               - "I follow my rules"
               - "I learn from every trade"
            ```
            
            **Read this constitution daily** until it becomes your identity.
            
            ## Common Psychological Problems & Solutions
            
            **Problem: Can't Pull the Trigger**
            ```
            Symptoms: Seeing setup but not entering
            Cause: Fear of loss, perfectionism
            Solution: 
            1. Trade smaller size
            2. Use "test trade" mentality
            3. Set timer (enter in 60 seconds or skip)
            ```
            
            **Problem: Overtrading**
            ```
            Symptoms: Too many trades, chasing
            Cause: Boredom, need for action
            Solution:
            1. Maximum 2-3 trades per day
            2. Wait 1 hour between trades
            3. Find other activities
            ```
            
            **Problem: Moving Stop Losses**
            ```
            Symptoms: Changing stops after entry
            Cause: Hope, denial
            Solution:
            1. Automated stops only
            2. No manual adjustments allowed
            3. If want to move stop, must close trade first
            ```
            
            **Problem: Taking Profits Too Early**
            ```
            Symptoms: Selling at first sign of profit
            Cause: Fear of giving back gains
            Solution:
            1. Use trailing stops
            2. Take partial profits
            3. Leave runner with stop at breakeven
            ```
            
            **Problem: Revenge Trading**
            ```
            Symptoms: Trading immediately after loss
            Cause: Anger, need to recover
            Solution:
            1. Mandatory break after loss
            2. "Three deep breaths" rule
            3. Loss limit per day/week
            ```
            
            ## Trading Journal for Psychology
            
            **Psychological Journal Template**:
            
            ```
            Date: [Date]
            
            Emotional State (1-10): [Rating]
            Physical State (1-10): [Rating]
            
            Trades Taken:
            1. [Trade details]
               - Emotion at entry: [ ]
               - Emotion during trade: [ ]
               - Emotion at exit: [ ]
               
            Psychological Observations:
            - What triggered emotions?
            - How did emotions affect decisions?
            - What worked well mentally?
            - What needs improvement?
            
            Lessons Learned:
            1. [Psychological lesson]
            2. [Behavioral insight]
            3. [Improvement for next time]
            
            Affirmation for Tomorrow:
            "[Positive statement about trading mindset]"
            ```
            
            **Weekly Psychology Review**:
            
            ```
            1. Emotional patterns (What triggers me?)
            2. Best mental states (When do I trade best?)
            3. Worst mental states (When should I not trade?)
            4. Progress on goals (Am I improving?)
            5. Adjustments needed (What to change?)
            ```
            
            ## Mental Models for Trading
            
            **1. The Chess Master Model**:
            ```
            Think 3-5 moves ahead
            Consider opponent's likely moves
            Have contingency plans
            Stay several steps ahead of market
            ```
            
            **2. The Scientist Model**:
            ```
            Form hypothesis (trade idea)
            Test hypothesis (enter trade)
            Collect data (monitor trade)
            Draw conclusions (win or learn)
            Refine theory (improve strategy)
            ```
            
            **3. The Warrior Model**:
            ```
            Discipline is everything
            Train daily (study, practice)
            Follow strategy without question
            Accept outcomes (win or lose) with honor
            ```
            
            **4. The Gardener Model**:
            ```
            Plant seeds (small positions)
            Water regularly (add to winners)
            Remove weeds (cut losers)
            Be patient (growth takes time)
            Harvest when ready (take profits)
            ```
            
            ## Resources for Mental Improvement
            
            **Books**:
            - "Trading in the Zone" by Mark Douglas (MUST READ)
            - "The Psychology of Trading" by Brett Steenbarger
            - "The Mental Game of Trading" by Jared Tendler
            - "Mind Over Markets" by James Dalton
            
            **Meditation Apps**:
            - Headspace (beginner friendly)
            - Calm (stress reduction)
            - Waking Up (philosophical)
            
            **Tools**:
            - Journaling software (Day One, Journey)
            - Mood tracking apps
            - Biofeedback devices
            
            **Professional Help**:
            - Trading psychologists
            - Performance coaches
            - Mindfulness teachers
            
            ## Final Thoughts
            
            **The Journey**:
            
            Trading psychology isn't something you master overnight. It's a **lifelong journey** of self-discovery and improvement. Some days you'll be the master of your mind, other days your emotions will master you. Both are part of the process.
            
            **Remember**:
            
            "The market is a mirror. It shows you who you are. If you're fearful, you'll see fear. If you're greedy, you'll see greed. If you're disciplined, you'll see opportunity."
            
            **Your Psychological Edge**:
            
            Ultimately, your greatest edge in the markets isn't a special indicator or a secret strategy. It's your **mind**. A disciplined, focused, emotionally balanced mind is worth more than any trading system.
            
            **Daily Commitment**:
            
            Every day, commit to:
            1. Following your process
            2. Managing your emotions
            3. Learning from your experiences
            4. Being kind to yourself
            5. Coming back better tomorrow
            
            **Final Words**:
            
            "Mastering others is strength. Mastering yourself is true power."
            - Lao Tzu
            
            Master your mind, and you'll master the markets. The journey starts with a single breath, a single trade, a single moment of awareness.
            
            Breathe. Focus. Trade well. 🧠
            """,
            "level": "Psychology",
            "time": "45 min read",
            "icon": "🧠"
        }
    },
    "Strategies": {
        "Day Trading Strategies": {
            "content": """
            # 🌅 Day Trading: Complete Strategies Guide
            
            ## What is Day Trading?
            
            Day trading involves buying and selling financial instruments **within the same trading day**. All positions are closed before market close. No overnight risk is carried.
            
            **Indian Market Specifics**:
            ```
            Trading Hours: 9:15 AM - 3:30 PM
            Settlement: T+1
            Intraday Margin: 5-20x leverage available
            Tax: All profits treated as business income
            ```
            
            **Who Should Day Trade?**:
            - Those who can monitor markets full-time
            - Risk-tolerant individuals
            - Disciplined and emotionally controlled
            - With sufficient capital (> ₹5 lakhs recommended)
            
            ## Essential Day Trading Rules
            
            **Golden Rules**:
            
            1. **Never Trade Without Stop Loss**
            2. **Risk Maximum 1% per Trade**
            3. **No Overnight Positions**
            4. **Stick to Your Plan**
            5. **Stop Trading After 2% Daily Loss**
            
            **Position Sizing Formula**:
            ```
            Shares = (Account Risk %) / (Entry - Stop Loss)
            
            Example:
            Account: ₹5,00,000
            Risk per trade: 0.5% = ₹2,500
            Stock: ₹1,000
            Stop Loss: ₹990 (1% risk)
            Shares = 2500 / (1000-990) = 250 shares
            ```
            
            ## Pre-Market Preparation
            
            **Morning Routine (8:00-9:15 AM)**:
            
            ```
            1. Global Markets Check (7:00 AM)
               - US markets close
               - Asian markets open
               - SGX Nifty
               - Dow Futures
               
            2. Economic Calendar (7:15 AM)
               - RBI announcements
               - GDP data
               - Corporate results
               - Global events
               
            3. FII/DII Data (7:30 AM)
               - Net buying/selling
               - Sectoral trends
               - Derivative positions
               
            4. Stock Scanner (7:45 AM)
               - Gap up/down > 2%
               - High volume pre-market
               - News catalysts
               - Breakouts
               
            5. Watchlist Creation (8:15 AM)
               - 5-10 focus stocks
               - Set price alerts
               - Note key levels
               
            6. Trading Plan (8:45 AM)
               - Max trades for day
               - Profit target
               - Loss limit
               - Strategy for the day
               
            7. Mental Preparation (9:00 AM)
               - Meditation
               - Visualization
               - Set intentions
            ```
            
            ## Core Day Trading Strategies
            
            ### 1. Opening Range Breakout (ORB)
            
            **Concept**: First 15-30 minutes sets the range for the day
            
            **Strategy**:
            ```
            Time: 9:15-9:45 AM
            Identify: High and Low of first 30 minutes
            Entry: Break above high (long) or below low (short)
            Stop Loss: Opposite side of range
            Target: 1:2 or 1:3 risk-reward
            ```
            
            **Rules**:
            - Wait for 9:45 AM confirmation
            - Volume must confirm breakout
            - Avoid first 5 minutes (noise)
            - Best for trending days
            
            ### 2. Moving Average Bounce
            
            **Concept**: Price tends to revert to moving averages
            
            **Setup**:
            ```
            Timeframe: 5-minute chart
            Indicators: 20 EMA, 50 EMA
            Entry: Bounce off EMA with candle confirmation
            Stop Loss: Below EMA (for longs)
            Target: Next resistance or 1:2 R:R
            ```
            
            **Types**:
            
            **a. EMA Pullback**:
            ```
            Price above EMA, pulls back to EMA
            Enter on bullish candle at EMA
            Stop below EMA low
            ```
            
            **b. EMA Crossover**:
            ```
            5 EMA crosses 20 EMA
            Volume confirmation needed
            Enter on retest
            ```
            
            ### 3. Support/Resistance Trading
            
            **Concept**: Price reacts at previous support/resistance
            
            **Strategy**:
            ```
            1. Identify key levels on daily chart
            2. Watch for reaction at these levels on 5-min
            3. Enter on reversal candle pattern
            4. Stop beyond the level
            5. Target next level
            ```
            
            **Key Levels**:
            - Previous day high/low
            - Weekly pivots
            - Round numbers (100, 1000, 5000)
            - VWAP (Volume Weighted Average Price)
            
            ### 4. VWAP Trading Strategies
            
            **VWAP Rules**:
            ```
            Price above VWAP = Bullish bias
            Price below VWAP = Bearish bias
            VWAP acts as dynamic support/resistance
            ```
            
            **Strategies**:
            
            **a. VWAP Bounce**:
            ```
            Price pulls back to VWAP
            Enter on bounce with volume
            Stop below VWAP
            Target: Previous high or 1:2 R:R
            ```
            
            **b. VWAP Fade**:
            ```
            Price far from VWAP (>1.5%)
            Mean reversion likely
            Fade the move toward VWAP
            ```
            
            ### 5. Gap Trading Strategies
            
            **Types of Gaps**:
            
            **a. Gap Fill Strategy**:
            ```
            Stock gaps up/down > 2%
            High probability of filling gap
            Fade the gap direction
            Enter partial, add on confirmation
            Target: Gap fill (opening price)
            ```
            
            **b. Gap and Go**:
            ```
            Stock gaps on high volume + news
            Strong momentum continuation
            Ride the trend
            Enter on pullback
            Use trailing stop
            ```
            
            **Gap Rules**:
            - >5% gaps risky to fade
            - Volume confirms direction
            - Earnings gaps behave differently
            
            ### 6. Scalping Strategies
            
            **For Quick Profits (1-5 minutes)**:
            
            **a. Bid-Ask Scalping**:
            ```
            Capitalize on spread
            Requires Level 2 data
            Very fast execution needed
            High frequency
            ```
            
            **b. Momentum Scalping**:
            ```
            Ride strong moves
            1-5 minute holds
            5:1 win rate needed (small profits)
            Exit at first sign of weakness
            ```
            
            **Scalping Requirements**:
            - Low brokerage
            - Fast internet
            - Multiple monitors
            - Quick decision making
            
            ### 7. News Based Trading
            
            **Types of News**:
            
            **a. Earnings Announcements**:
            ```
            Pre-market or post-market results
            Gap next day
            Trade the reaction (not the news)
            Wait 15 minutes after open
            ```
            
            **b. Corporate Announcements**:
            ```
            Mergers, acquisitions, buybacks
            FDA approvals (for pharma)
            Government contracts
            ```
            
            **c. Economic Data**:
            ```
            RBI policy
            GDP numbers
            Inflation data
            IIP numbers
            ```
            
            **News Trading Rules**:
            - Don't trade before news
            - Wait for volatility to settle
            - Trade the trend, not the initial spike
            - Use wider stops
            
            ## Sector-Specific Strategies
            
            ### Banking Stocks (HDFC, ICICI, SBI)
            ```
            Characteristics: High liquidity, news sensitive
            Best Times: 10 AM - 2 PM
            Key Levels: RBI policy, NPA data
            Strategy: Range trading, news plays
            ```
            
            ### IT Stocks (TCS, Infosys, Wipro)
            ```
            Characteristics: Dollar sensitive, global news
            Best Times: US market overlap (7-9 PM IST next day)
            Strategy: Follow Nasdaq, currency movements
            ```
            
            ### FMCG Stocks (HUL, ITC, Nestle)
            ```
            Characteristics: Low volatility, dividend plays
            Best Times: Anytime, but low intraday moves
            Strategy: Range bound, support/resistance
            ```
            
            ### Auto Stocks (Maruti, M&M, Tata Motors)
            ```
            Characteristics: Cyclical, monthly sales data
            Best Times: Sales announcement days
            Strategy: Trend following, breakout plays
            ```
            
            ## Time-Based Strategies
            
            **Market Opening (9:15-10:00)**:
            ```
            Strategy: Opening range, gap plays
            Risk: High volatility
            Reward: Quick profits
            Tips: Wait for first 15-min range
            ```
            
            **Mid-Morning (10:00-11:30)**:
            ```
            Strategy: Trend continuation
            Risk: Medium
            Reward: Good moves develop
            Tips: Follow institutional flow
            ```
            
            **Lunch Time (11:30-1:00)**:
            ```
            Strategy: Range trading
            Risk: Low volume, whipsaws
            Reward: Small profits
            Tips: Smaller position size
            ```
            
            **Afternoon (1:00-2:30)**:
            ```
            Strategy: Breakouts from ranges
            Risk: Medium
            Reward: Good directional moves
            Tips: European market open impact
            ```
            
            **Closing (2:30-3:30)**:
            ```
            Strategy: Squaring off, momentum
            Risk: High (last hour volatility)
            Reward: Big moves often
            Tips: Don't hold too close to close
            ```
            
            ## Risk Management for Day Trading
            
            **Daily Loss Limits**:
            ```
            Beginners: 1% of capital
            Intermediate: 2% of capital
            Professionals: 3% of capital
            STOP TRADING when hit daily limit
            ```
            
            **Position Size Adjustments**:
            ```
            After 2 winning trades: Normal size
            After 2 losing trades: Reduce 50%
            After 3 losing trades: Stop trading for day
            ```
            
            **Stop Loss Techniques**:
            
            **1. Fixed Percentage**:
            ```
            Stocks: 0.5-1%
            Futures: 0.25-0.5%
            Options: 50-100% of premium
            ```
            
            **2. Technical Stops**:
            ```
            Below support
            Below moving average
            Below recent low
            ```
            
            **3. Time Stops**:
            ```
            Exit if not profitable in 30 minutes
            Exit before 3:00 PM if losing
            ```
            
            **4. Trailing Stops**:
            ```
            Move stop to breakeven at 1R profit
            Trail by ATR or percentage
            ```
            
            ## Psychology of Day Trading
            
            **Mental Challenges**:
            
            **1. Overtrading**:
            ```
            Cause: Boredom, need for action
            Solution: Max 3-5 trades per day
            ```
            
            **2. Revenge Trading**:
            ```
            Cause: Recent loss
            Solution: Daily loss limit, mandatory break
            ```
            
            **3. Fear of Pulling Trigger**:
            ```
            Cause: Previous losses
            Solution: Smaller position size, practice
            ```
            
            **4. Holding Losers**:
            ```
            Cause: Hope, denial
            Solution: Automated stop losses
            ```
            
            **Daily Mental Routine**:
            ```
            Pre-market: Visualization, meditation
            During: Breathing exercises, breaks
            Post-market: Journaling, reflection
            Evening: Disconnect, recharge
            ```
            
            ## Tools & Setup Requirements
            
            **Hardware Requirements**:
            ```
            Computer: Fast processor, 16GB+ RAM
            Monitors: 2-4 monitors recommended
            Internet: Fiber optic, backup connection
            UPS: Essential for power backup
            ```
            
            **Software Requirements**:
            ```
            Charting: TradingView, MetaTrader, Amibroker
            Scanner: Chartink, TradingView scanner
            News: Moneycontrol, Economic Times alerts
            Broker Platform: Zerodha Kite, Upstox Pro
            ```
            
            **Data Requirements**:
            ```
            Real-time data: Essential
            Level 2 data: For serious traders
            Historical data: For backtesting
            News feed: Real-time news
            ```
            
            ## Backtesting & Optimization
            
            **Backtesting Process**:
            
            ```
            Step 1: Define strategy rules
            Step 2: Get historical data
            Step 3: Test on 2+ years data
            Step 4: Analyze results
            Step 5: Optimize parameters
            Step 6: Forward test (paper trade)
            Step 7: Live trade small
            Step 8: Scale up
            ```
            
            **Key Metrics to Track**:
            ```
            Win Rate: >40% acceptable
            Profit Factor: >1.5 good
            Max Drawdown: <20% acceptable
            Average Win/Loss: >1:1.5
            Sharpe Ratio: >1 good
            ```
            
            **Common Optimization Mistakes**:
            ❌ Overfitting (curve fitting)
            ❌ Too many parameters
            ❌ Ignoring transaction costs
            ❌ Not testing different market conditions
            
            ## Tax Implications in India
            
            **Day Trading Taxation**:
            ```
            Tax Treatment: Business Income
            ITR Form: ITR-3 or ITR-4
            Audit Required: If turnover > ₹2 crores
            Expenses Deductible: Internet, software, etc.
            ```
            
            **Records to Maintain**:
            ```
            1. Trade-wise profit/loss statement
            2. Bank statements
            3. Brokerage statements
            4. Expense receipts
            5. Home office details (if applicable)
            ```
            
            **Advance Tax**:
            ```
            Payable if tax liability > ₹10,000
            Due dates: June 15, Sept 15, Dec 15, Mar 15
            Calculate quarterly
            ```
            
            ## Common Day Trading Mistakes
            
            **Beginner Mistakes**:
            ❌ No stop loss
            ❌ Overtrading
            ❌ Chasing stocks
            ❌ Trading too large
            ❌ Ignoring trends
            
            **Intermediate Mistakes**:
            ❌ Switching strategies often
            ❌ Not keeping journal
            ❌ Ignoring sector strength
            ❌ Trading against trend
            ❌ Revenge trading
            
            **Advanced Mistakes**:
            ❌ Overconfidence after wins
            ❌ Underestimating black swans
            ❌ Not adapting to changing markets
            ❌ Ignoring liquidity
            ❌ Complacency
            
            ## Success Blueprint
            
            **Phase 1: Learning (Months 1-3)**:
            ```
            - Paper trade only
            - Learn one strategy thoroughly
            - Study market structure
            - Read books, watch tutorials
            ```
            
            **Phase 2: Practice (Months 4-6)**:
            ```
            - Small live trading (₹25,000 capital)
            - Focus on consistency, not profits
            - Keep detailed journal
            - Review daily
            ```
            
            **Phase 3: Refinement (Months 7-12)**:
            ```
            - Scale up capital gradually
            - Add second strategy
            - Improve risk management
            - Work on psychology
            ```
            
            **Phase 4: Mastery (Year 2+)**:
            ```
            - Full-time if profitable
            - Multiple strategies
            - Teach others (reinforces learning)
            - Continuous improvement
            ```
            
            ## Daily Checklist
            
            **Before Market Opens**:
            ✅ Global markets checked
            ✅ Economic calendar reviewed
            ✅ Watchlist prepared
            ✅ Trading plan set
            ✅ Mental state prepared
            
            **During Trading**:
            ✅ Follow trading plan
            ✅ Use stop losses
            ✅ Monitor position size
            ✅ Take breaks
            ✅ No emotional decisions
            
            **After Market Close**:
            ✅ All positions closed
            ✅ Journal completed
            ✅ Performance reviewed
            ✅ Lessons noted
            ✅ Plan for tomorrow
            
            **Weekly Review**:
            ✅ Win rate calculation
            ✅ Profit factor check
            ✅ Drawdown analysis
            ✅ Strategy review
            ✅ Plan improvements
            
            ## Resources
            
            **Books**:
            - "A Complete Guide to Volume Price Analysis" by Anna Coulling
            - "Day Trading for Dummies" by Ann Logue
            - "The New Trading for a Living" by Alexander Elder
            
            **Courses**:
            - NSE Academy Certification
            - Zerodha Varsity (free)
            - Price Action Trading by Al Brooks
            
            **YouTube Channels**:
            - Rayner Teo
            - The Trading Channel
            - Adam Khoo
            
            **Forums & Communities**:
            - TradingQnA
            - Traderji
            - Reddit r/Daytrading
            
            ## Final Words of Wisdom
            
            **The Reality**:
            ```
            90% of day traders fail
            It takes 1-3 years to become profitable
            It's a skill, not a gift
            Consistency beats brilliance
            ```
            
            **Success Mindset**:
            ```
            Focus on process, not profits
            Small consistent gains compound
            Every loss is tuition fee
            The market is always right
            Patience is the ultimate edge
            ```
            
            **Remember**:
            "The goal of a successful trader is to make the best trades. Money is secondary."
            
            Trade well, stay disciplined, and may your edges be sharp and your stops be tight! 🌅
            """,
            "level": "Strategies",
            "time": "50 min read",
            "icon": "🌅"
        }
    }
}

STOCKS_DATABASE = {
    
    "Indian Stocks": {
        "Reliance Industries Ltd.": "RELIANCE.NS",
        "Tata Consultancy Services Ltd.": "TCS.NS",
        "HDFC Bank Ltd.": "HDFCBANK.NS",
        "Infosys Ltd.": "INFY.NS",
        "ICICI Bank Ltd.": "ICICIBANK.NS",
        "Hindustan Unilever Ltd.": "HINDUNILVR.NS",
        "State Bank of India": "SBIN.NS",
        "Bharti Airtel Ltd.": "BHARTIARTL.NS",
        "ITC Ltd.": "ITC.NS",
        "Larsen & Toubro Ltd.": "LT.NS",
        "Kotak Mahindra Bank Ltd.": "KOTAKBANK.NS",
        "Axis Bank Ltd.": "AXISBANK.NS",
        "Asian Paints Ltd.": "ASIANPAINT.NS",
        "Maruti Suzuki India Ltd.": "MARUTI.NS",
        "Sun Pharmaceutical Industries Ltd.": "SUNPHARMA.NS",
        "Mahindra & Mahindra Ltd.": "M&M.NS",
        "Titan Company Ltd.": "TITAN.NS",
        "Bajaj Finance Ltd.": "BAJFINANCE.NS",
        "Wipro Ltd.": "WIPRO.NS",
        "UltraTech Cement Ltd.": "ULTRACEMCO.NS"
    },

}

# Load Indian stocks
try:
    all_indian_stocks = pd.read_csv('stocks.csv')
except:
    all_indian_stocks = pd.DataFrame({
        'NAME OF COMPANY': ['Dummy Company'],
        'SYMBOL': ['DUMMY.NS']
    })

# Initialize database tables
initialize_database()

# Initialize session states
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'username' not in st.session_state:
    st.session_state.username = None
if 'current_page' not in st.session_state:
    st.session_state.current_page = "login"
if 'search_results' not in st.session_state:
    st.session_state.search_results = None
if 'selected_company' not in st.session_state:
    st.session_state.selected_company = None
if 'search_performed' not in st.session_state:
    st.session_state.search_performed = False
if 'view_holdings' not in st.session_state:
    st.session_state.view_holdings = False
if 'selected_holding_symbol' not in st.session_state:
    st.session_state.selected_holding_symbol = None
if 'show_watchlist' not in st.session_state:
    st.session_state.show_watchlist = False
if 'show_learning' not in st.session_state:
    st.session_state.show_learning = False
if 'selected_course' not in st.session_state:
    st.session_state.selected_course = None
if 'selected_lesson' not in st.session_state:
    st.session_state.selected_lesson = None
if 'current_user' not in st.session_state:
    st.session_state.current_user = None
# state initialization
if 'lesson_completed' not in st.session_state:
    st.session_state.lesson_completed = {}

# Initialize random trading simulator states
if 'random_stock_index' not in st.session_state:
    st.session_state.random_stock_index = random.randint(0, len(all_indian_stocks) - 1) if 'all_indian_stocks' in locals() else 0
if 'current_minute' not in st.session_state:
    st.session_state.current_minute = 0
if 'trading_data' not in st.session_state:
    st.session_state.trading_data = None
if 'day_complete' not in st.session_state:
    st.session_state.day_complete = False
if 'trade_history' not in st.session_state:
    st.session_state.trade_history = []
if 'random_portfolio' not in st.session_state:
    st.session_state.random_portfolio = {
        'cash': 100000.00,
        'shares': 0,
        'buy_price': 0.00,
        'buy_transactions': []
    }
if 'auto_advance' not in st.session_state:
    st.session_state.auto_advance = False
if 'last_update' not in st.session_state:
    st.session_state.last_update = datetime.now()
if 'graph_updated' not in st.session_state:
    st.session_state.graph_updated = False
if 'current_trading_date' not in st.session_state:
    st.session_state.current_trading_date = None
if 'trading_dates' not in st.session_state:
    st.session_state.trading_dates = []
if 'chart_type' not in st.session_state:
    st.session_state.chart_type = "Candlestick"

st.set_page_config(page_title="Learn2Trade",page_icon="📈" ,layout="wide")

# Authentication Pages
if not st.session_state.authenticated:
    st.title("Learn2Trade - Login")
    
    tab1, tab2 = st.tabs(["Login", "Register"])
    
    with tab1:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            login_button = st.form_submit_button("Login")
            
            if login_button:
                if username and password:
                    success, message, user_id = login_user(username, password)
                    if success:
                        st.session_state.authenticated = True
                        st.session_state.user_id = user_id
                        st.session_state.username = username
                        st.session_state.current_user = User(user_id, username)  # Create User object
                        st.session_state.current_page = "main"
                        st.success("Login successful! Redirecting...")
                        st.rerun()
                    else:
                        st.error(message)
                else:
                    st.error("Please fill in all fields")
    
    with tab2:
    
        st.subheader("Create New Account")
        
        # Use columns for better layout
        col1, col2 = st.columns(2)
        
        with col1:
            new_username = st.text_input(
                "Username *", 
                placeholder="john_doe123",
                key="reg_username",
                help="3-20 characters: letters, numbers, and underscores only"
            )
            
            email = st.text_input(
                "Email *", 
                placeholder="john@example.com",
                key="reg_email",
                help="Enter a valid email address"
            )
        
        with col2:
            new_password = st.text_input(
                "Password *", 
                type="password",
                placeholder="Create a strong password",
                key="reg_password",
                help="8+ chars, with uppercase, lowercase, number & special char"
            )
            
            confirm_password = st.text_input(
                "Confirm Password *", 
                type="password",
                placeholder="Re-enter your password",
                key="reg_confirm_password"
            )
        
        # Real-time password strength indicator (only shows if password is entered)
        if new_password:
            # Calculate password strength
            strength_score = 0
            if len(new_password) >= 8:
                strength_score += 1
            if any(c.isupper() for c in new_password):
                strength_score += 1
            if any(c.islower() for c in new_password):
                strength_score += 1
            if any(c.isdigit() for c in new_password):
                strength_score += 1
            if any(c in '!@#$%^&*()_+-=[]{};\':"\\|,.<>/?~`' for c in new_password):
                strength_score += 1
            
            if strength_score <= 2:
                strength_text = "Weak"
                strength_color = "red"
            elif strength_score <= 4:
                strength_text = "Medium"
                strength_color = "orange"
            else:
                strength_text = "Strong"
                strength_color = "green"
            
            st.markdown(f"**Password Strength:** <span style='color:{strength_color}'>{strength_text}</span>", unsafe_allow_html=True)
            
            # Show password requirements in an expander
            with st.expander("Password Requirements", expanded=False):
                col_req1, col_req2 = st.columns(2)
                with col_req1:
                    st.write("✅" if len(new_password) >= 8 else "❌", " At least 8 characters")
                    st.write("✅" if any(c.isupper() for c in new_password) else "❌", " At least 1 uppercase letter")
                    st.write("✅" if any(c.islower() for c in new_password) else "❌", " At least 1 lowercase letter")
                with col_req2:
                    st.write("✅" if any(c.isdigit() for c in new_password) else "❌", " At least 1 number")
                    st.write("✅" if any(c in '!@#$%^&*()_+-=[]{};\':"\\|,.<>/?~`' for c in new_password) else "❌", " At least 1 special character")
                    st.write("✅" if ' ' not in new_password else "❌", " No spaces allowed")
        
        st.markdown("---")
        
        # Terms and conditions
        agree_terms = st.checkbox("I agree to the Terms of Service and Privacy Policy")
        
        # Register button
        if st.button("Create Account", type="primary", use_container_width=True):
            # Validation functions (defined inside to avoid any scope issues)
            def validate_username_input(username):
                import re
                if not username:
                    return False, "Username is required"
                if len(username) < 3:
                    return False, "Username must be at least 3 characters long"
                if len(username) > 20:
                    return False, "Username cannot exceed 20 characters"
                if not re.match(r'^[a-zA-Z0-9_]+$', username):
                    return False, "Username can only contain letters, numbers, and underscores"
                if username.startswith('_') or username.endswith('_'):
                    return False, "Username cannot start or end with underscore"
                if '__' in username:
                    return False, "Username cannot contain consecutive underscores"
                return True, "Username is valid"
            
            def validate_email_input(email):
                import re
                if not email:
                    return False, "Email is required"
                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                if not re.match(email_pattern, email):
                    return False, "Please enter a valid email address (e.g., name@example.com)"
                if ' ' in email:
                    return False, "Email cannot contain spaces"
                if email.count('@') != 1:
                    return False, "Email must contain exactly one @ symbol"
                return True, "Email is valid"
            
            def validate_password_input(password):
                if not password:
                    return False, "Password is required"
                if len(password) < 8:
                    return False, "Password must be at least 8 characters long"
                if len(password) > 50:
                    return False, "Password cannot exceed 50 characters"
                if ' ' in password:
                    return False, "Password cannot contain spaces"
                if not any(c.isupper() for c in password):
                    return False, "Password must contain at least one uppercase letter"
                if not any(c.islower() for c in password):
                    return False, "Password must contain at least one lowercase letter"
                if not any(c.isdigit() for c in password):
                    return False, "Password must contain at least one number"
                if not any(c in '!@#$%^&*()_+-=[]{};\':"\\|,.<>/?~`' for c in password):
                    return False, "Password must contain at least one special character (!@#$%^&* etc.)"
                return True, "Password is valid"
            
            # Perform all validations
            errors = []
            
            # Validate username
            username_valid, username_msg = validate_username_input(new_username)
            if not username_valid:
                errors.append(f"{username_msg}")
            
            # Validate email
            if not errors:  # Only proceed if previous validations passed
                email_valid, email_msg = validate_email_input(email)
                if not email_valid:
                    errors.append(f"{email_msg}")
            
            # Validate password
            if not errors:
                password_valid, password_msg = validate_password_input(new_password)
                if not password_valid:
                    errors.append(f"{password_msg}")
            
            # Validate password match
            if not errors and new_password != confirm_password:
                errors.append("Passwords do not match")
            
            # Validate terms agreement
            if not errors and not agree_terms:
                errors.append("You must agree to the Terms of Service and Privacy Policy")
            
            # Check if username/email already exists in database
            if not errors:
                conn = None
                try:
                    conn = get_db_connection()
                    if conn:
                        cur = conn.cursor()
                        # Check if username exists
                        cur.execute("SELECT id FROM users WHERE username = %s", (new_username,))
                        if cur.fetchone():
                            errors.append("Username already taken")
                        
                        # Check if email exists
                        if not errors:
                            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
                            if cur.fetchone():
                                errors.append("Email already registered")
                        
                        cur.close()
                except Exception as e:
                    errors.append(f"Database error: {str(e)}")
                finally:
                    if conn:
                        conn.close()
            
            # If no errors, proceed with registration
            if not errors:
                with st.spinner("Creating your account..."):
                    success, message, user_id = register_user(new_username, email, new_password)
                    
                    if success:
                        st.success("Account created successfully!")
                        
                        # AUTO-LOGIN after successful registration
                        st.session_state.authenticated = True
                        st.session_state.user_id = user_id
                        st.session_state.username = new_username
                        st.session_state.current_user = User(user_id, new_username)
                        st.session_state.current_page = "main"
                        
                        st.success("Auto-login successful! Redirecting...")
                        time_module.sleep(2)
                        st.rerun()
                    else:
                        st.error(f"{message}")
            else:
                # Display all errors
                for error in errors:
                    st.error(error)
    
else:
    # Main Application
    st.title(f"📈 Learn2Trade - Welcome {st.session_state.username}!")
    
        # Sidebar with logout option
    with st.sidebar:
        st.header(f"  {st.session_state.username}")
        
        # Show learning progress if user exists
        if st.session_state.current_user:
            try:
                # Calculate total lessons directly
                total_lessons = 0
                for category in STOCK_MARKET_COURSES:
                    total_lessons += len(STOCK_MARKET_COURSES[category])
                
                # Get completed lessons
                learning_progress = st.session_state.current_user.get_learning_progress()
                completed_lessons = 0
                for category in learning_progress:
                    completed_lessons += learning_progress[category].get('completed', 0)
                
                if total_lessons > 0:
                    progress_percent = (completed_lessons / total_lessons) * 100
                    st.metric("Learning Progress", f"{completed_lessons}/{total_lessons}", f"{progress_percent:.1f}%")
            except Exception as e:
                st.error(f"Error loading learning progress: {e}")
        
        if st.button("Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.user_id = None
            st.session_state.username = None
            st.session_state.current_user = None
            st.session_state.current_page = "login"
            st.rerun()
        
        st.markdown("---")
        
        # Navigation - UPDATED (removed Learn Concepts from here)
        st.header("Navigation")
        nav_options = ["Trading", "Portfolio", "Watchlist"]
        selected_nav = st.radio("Go to:", nav_options, label_visibility="collapsed")
        
        if selected_nav == "Trading":
            st.session_state.view_holdings = False
            st.session_state.show_watchlist = False
            st.session_state.show_learning = False
        elif selected_nav == "Portfolio":
            st.session_state.view_holdings = True
            st.session_state.show_watchlist = False
            st.session_state.show_learning = False
        elif selected_nav == "Watchlist":
            st.session_state.view_holdings = False
            st.session_state.show_watchlist = True
            st.session_state.show_learning = False
        
        st.markdown("---")
        
        # Trading Mode Selection - UPDATED with Learn Concepts
        method_trading = st.selectbox("Select Trading Mode:", 
                                     ["Live Trading", "Practice Mode", "Learn Concepts"])
        
        # Set learning mode if selected
        if method_trading == "Learn Concepts":
            st.session_state.show_learning = True
        else:
            st.session_state.show_learning = False
        
        st.markdown("---")
        
        # Portfolio Summary (only show in trading mode)
        if selected_nav == "Trading" and method_trading == "Live Trading":
            st.subheader("Portfolio Summary")
            total_portfolio_value = calculate_portfolio_value(st.session_state.user_id)
            portfolio = get_user_portfolio(st.session_state.user_id)
            
            if portfolio:
                st.metric("Total Value", f"₹{total_portfolio_value:,.2f}")
                st.metric("Cash Balance", f"₹{portfolio['cash']:,.2f}")
                
                # Quick holdings view
                if portfolio['holdings']:
                    st.markdown("**Current Holdings:**")
                    for symbol, holding in list(portfolio['holdings'].items())[:3]:
                        company_name = holding.get('company_name', symbol)[:20]
                        shares = holding['shares']
                        st.write(f"• {company_name}: {shares} shares")
                    
                    if len(portfolio['holdings']) > 3:
                        st.caption(f"+ {len(portfolio['holdings']) - 3} more holdings")
    # Main Content Area
    if method_trading == "Learn Concepts" or st.session_state.show_learning:
        # Learning Mode - Comprehensive Stock Market Education
        st.header("Learn Stock Market Concepts & Tricks")
        
        # Get user progress from database
        if st.session_state.current_user:
            learning_progress = st.session_state.current_user.get_learning_progress()
        else:
            learning_progress = {}
        
        # Sidebar for course selection
        with st.sidebar:
            st.header("Course Progress")
            
            for category in STOCK_MARKET_COURSES.keys():
                if category in learning_progress:
                    progress = learning_progress[category]
                    total_lessons = len(STOCK_MARKET_COURSES[category])
                    completed_lessons = progress['completed']
                else:
                    total_lessons = len(STOCK_MARKET_COURSES[category])
                    completed_lessons = 0
                
                completion_rate = (completed_lessons / total_lessons) * 100 if total_lessons > 0 else 0
                st.progress(completion_rate/100, text=f"{category}: {completed_lessons}/{total_lessons}")
            
            st.markdown("---")
            st.header("Quick Navigation")
            
            # Category selection
            selected_category = st.selectbox(
                "Select Category:",
                list(STOCK_MARKET_COURSES.keys()),
                index=0
            )
            
            # Lesson selection within category
            if selected_category in STOCK_MARKET_COURSES:
                lessons = list(STOCK_MARKET_COURSES[selected_category].keys())
                selected_lesson = st.selectbox(
                    "Select Lesson:",
                    lessons,
                    index=0
                )
                
                if st.button("Start Lesson", use_container_width=True):
                    st.session_state.selected_course = selected_category
                    st.session_state.selected_lesson = selected_lesson
                    st.rerun()
        
        # Main learning content area
        if st.session_state.selected_course and st.session_state.selected_lesson:
            lesson_data = STOCK_MARKET_COURSES[st.session_state.selected_course][st.session_state.selected_lesson]
            
            # Header with lesson info
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.title(f"{lesson_data['icon']} {st.session_state.selected_lesson}")
            with col2:
                st.info(f"**Level:** {lesson_data['level']}")
            with col3:
                st.info(f"**Time:** {lesson_data['time']}")
            
            # Check if already completed
            is_completed = False
            if st.session_state.current_user and st.session_state.selected_course in learning_progress:
                if st.session_state.selected_lesson in learning_progress[st.session_state.selected_course]['lessons']:
                    is_completed = learning_progress[st.session_state.selected_course]['lessons'][st.session_state.selected_lesson]
            
            # Mark complete button with prevention for multiple clicks
            if not is_completed:
                if st.button("Mark as Complete", type="primary", key=f"complete_{st.session_state.selected_lesson}"):
                    if st.session_state.current_user:
                        success = st.session_state.current_user.mark_lesson_complete(
                            st.session_state.selected_course,
                            st.session_state.selected_lesson
                        )
                        if success:
                            st.success("Lesson marked as complete! 🎉")
                            # Refresh progress
                            learning_progress = st.session_state.current_user.get_learning_progress()
                            st.rerun()
                        else:
                            st.warning("This lesson is already marked as complete!")
                    else:
                        st.error("User not found. Please log in again.")
            else:
                st.success("This lesson is already marked as complete!")

            st.markdown("---")
            
            # Display lesson content
            st.markdown(lesson_data['content'])
            
            # Interactive elements
            st.markdown("---")
            st.subheader("Quick Quiz")
            
            # Simple quiz based on lesson
            if st.session_state.selected_lesson == "What is Stock Market?":
                quiz_question = "What does buying a stock mean?"
                options = [
                    "You're lending money to the company",
                    "You own a small piece of the company",
                    "You're betting against the company",
                    "You're becoming an employee"
                ]
                correct_answer = "You own a small piece of the company"
                
            elif st.session_state.selected_lesson == "Stock Market Basics":
                quiz_question = "What is a 'Blue-chip' stock?"
                options = [
                    "A new, risky company",
                    "A large, established, stable company",
                    "A company that only deals in technology",
                    "A company that pays no dividends"
                ]
                correct_answer = "A large, established, stable company"
                
            else:
                quiz_question = "What is the most important rule for beginners?"
                options = [
                    "Invest all your money at once",
                    "Follow hot tips from friends",
                    "Never invest money you can't afford to lose",
                    "Only trade in penny stocks"
                ]
                correct_answer = "Never invest money you can't afford to lose"
            
            # Display quiz
            st.write(f"**{quiz_question}**")
            selected_option = st.radio("Select your answer:", options, index=None, key=f"quiz_{st.session_state.selected_lesson}")
            
            if selected_option:
                if selected_option == correct_answer:
                    st.success("Correct! Well done!")
                else:
                    st.error(f"Incorrect. The correct answer is: {correct_answer}")
            
            # Practice exercise
            st.markdown("---")
            st.subheader("Practice Exercise")
            
            if st.session_state.selected_lesson == "What is Stock Market?":
                st.write("""
                **Exercise**: 
                1. Go to Moneycontrol.com
                2. Find 3 companies from different sectors
                3. Note their current stock prices
                4. Calculate how many shares you could buy with ₹10,000
                5. Imagine you bought them - track for 1 week
                """)
            
            elif st.session_state.selected_lesson == "Technical Analysis Basics":
                st.write("""
                **Exercise**:
                1. Open TradingView.com
                2. Find NIFTY 50 chart
                3. Identify:
                   - Current trend (uptrend/downtrend/sideways)
                   - Key support and resistance levels
                   - Any candlestick patterns
                4. Take screenshot and label your findings
                """)
            
            else:
                st.write("""
                **Exercise**:
                1. Pick one concept from this lesson
                2. Research it more deeply
                3. Write a 100-word summary
                4. Share with a friend or in trading community
                """)
            
    
        else:
            # Welcome to learning module
            st.markdown("""
            # 🎓 Welcome to Stock Market Learning Center!
            
            ## Your Journey to Financial Literacy Starts Here
            
            This comprehensive learning module will take you from **zero to hero** in stock market investing and trading. 
            Whether you're a complete beginner or looking to advance your skills, we have something for everyone.
            
            ### 🏆 What You'll Learn:
            
            **📚 Basics (Beginner)**
            - What is Stock Market?
            - How to start investing
            - Basic terminology
            - Common mistakes to avoid
            
            **📊 Intermediate**
            - Technical analysis fundamentals
            - Fundamental analysis
            - Reading financial statements
            - Building your first portfolio
            
            **🎯 Advanced**
            - Options trading strategies
            - Risk management mastery
            - Advanced chart patterns
            - Algorithmic trading basics
            
            **🧠 Psychology**
            - Trading mindset development
            - Emotional control
            - Overcoming fear and greed
            - Building discipline
            
            **🌅 Strategies**
            - Day trading techniques
            - Swing trading strategies
            - Position trading
            - Seasonal patterns
            
            ### 🚀 How to Use This Module:
            
            1. **Start with Basics** if you're new to investing
            2. **Complete lessons in order** for best results
            3. **Take notes** and do the practice exercises
            4. **Mark lessons complete** to track progress
            5. **Apply knowledge** in Practice Mode
            
            ### 📈 Track Your Progress
            
            Your progress is automatically tracked in the database. Aim to complete all lessons to become a well-rounded investor/trader.
            
            ### 🎯 Quick Start Tips:
            
            - Spend 30 minutes daily on learning
            - Practice with paper trading first
            - Start small when you begin real trading
            - Never stop learning - markets evolve!
            
            **Ready to begin? Select a category and lesson from the sidebar!** 🚀
            """)
            
            # Quick stats
            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            
            total_lessons = sum([len(STOCK_MARKET_COURSES[cat]) for cat in STOCK_MARKET_COURSES])
            completed_lessons = 0
            if st.session_state.current_user:
                completed_lessons = st.session_state.current_user.get_completed_lesson_count()
            
            with col1:
                st.metric("Total Lessons", total_lessons)
            with col2:
                st.metric("Completed", completed_lessons)
            with col3:
                completion_percent = (completed_lessons / total_lessons) * 100 if total_lessons > 0 else 0
                st.metric("Completion", f"{completion_percent:.1f}%")
    
    elif st.session_state.show_watchlist:
        # Watchlist Page - ENHANCED with graphs and details
        st.header("My Watchlist")
        
        # Display watchlist
        watchlist = get_watchlist(st.session_state.user_id)
        
        if watchlist:
            st.subheader(f"Your Watchlist ({len(watchlist)} items)")
            
            for i, item in enumerate(watchlist):
                with st.expander(f"{item['company_name']} ({item['symbol']})", expanded=False):
                    col1, col2 = st.columns([4, 1])
                    
                    with col1:
                        st.caption(f"Added: {item['added_at'].strftime('%Y-%m-%d %H:%M')}")
                    
                    with col2:
                        # Remove button
                        if st.button("Remove", key=f"remove_{i}"):
                            success, message = remove_from_watchlist(st.session_state.user_id, item['symbol'])
                            if success:
                                st.success(message)
                                st.rerun()
                            else:
                                st.error(message)
                    
                    # Show current price and details
                    try:
                        stock = Stock(item['symbol'], item['company_name'])
                        current_price = stock.get_current_price()
                        
                        if current_price:
                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                st.metric("Current Price", 
                                         f"₹{current_price:.2f}" if item['symbol'].endswith('.NS') else f"${current_price:.2f}")
                            
                            # Get historical data for mini chart
                            st.subheader("Price Chart")
                            try:
                                data = stock.get_historical_data(period="1mo", interval="1d")
                                if not data.empty and 'Close' in data.columns:
                                    fig = go.Figure()
                                    fig.add_trace(go.Scatter(
                                        x=data.index,
                                        y=data['Close'],
                                        mode='lines',
                                        name='Price',
                                        line=dict(color='blue', width=2)
                                    ))
                                    
                                    fig.update_layout(
                                        title=f"{item['company_name']} - Last 30 Days",
                                        xaxis_title="Date",
                                        yaxis_title="Price",
                                        height=300
                                    )
                                    
                                    st.plotly_chart(fig, use_container_width=True)
                            except:
                                st.info("Chart data not available")
                    except:
                        st.info("Price data not available")
            
            # Clear all button
            if st.button("🗑️ Clear All Watchlist", type="secondary"):
                conn = get_db_connection()
                if conn:
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            "DELETE FROM watchlists WHERE user_id = %s",
                            (st.session_state.user_id,)
                        )
                        conn.commit()
                        cur.close()
                        conn.close()
                        st.success("Watchlist cleared!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error clearing watchlist: {e}")
        else:
            st.info("Your watchlist is empty. Add stocks to track them here!")
    
    elif st.session_state.view_holdings:
        # Portfolio Page - SIMPLIFIED (no graphs, no buy/sell)
        st.header("Portfolio Summary")
        
        portfolio = get_user_portfolio(st.session_state.user_id)
        total_portfolio_value = calculate_portfolio_value(st.session_state.user_id)
        
        if portfolio:
            # Portfolio Summary
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Value", f"₹{total_portfolio_value:,.2f}")
            with col2:
                st.metric("Cash Balance", f"₹{portfolio['cash']:,.2f}")
            with col3:
                holdings_value = total_portfolio_value - portfolio['cash']
                st.metric("Holdings Value", f"₹{holdings_value:,.2f}")
            with col4:
                total_invested = sum([h['total_invested'] for h in portfolio['holdings'].values()])
                total_pnl = holdings_value - total_invested
                st.metric("Total P&L", f"₹{total_pnl:,.2f}")
            
            st.markdown("---")
            
            # Holdings Table (no graphs)
            if portfolio['holdings']:
                st.subheader("Current Holdings")
                
                holdings_data = []
                total_invested = 0
                total_current = 0
                
                for symbol, holding in portfolio['holdings'].items():
                    company_name = holding.get('company_name', symbol)
                    shares = holding['shares']
                    avg_price = holding['avg_price']
                    
                    stock = Stock(symbol, company_name)
                    current_price = stock.get_current_price()
                    if current_price is None:
                        current_price = avg_price
                    
                    invested = shares * avg_price
                    current_value = shares * current_price
                    pnl = current_value - invested
                    pnl_percent = (pnl / invested * 100) if invested > 0 else 0
                    
                    holdings_data.append({
                        'Symbol': symbol,
                        'Company': company_name,
                        'Shares': shares,
                        'Avg Price': f"₹{avg_price:.2f}",
                        'Current Price': f"₹{current_price:.2f}",
                        'Invested': f"₹{invested:,.2f}",
                        'Current Value': f"₹{current_value:,.2f}",
                        'P&L': f"₹{pnl:,.2f}",
                        'P&L %': f"{pnl_percent:.1f}%"
                    })
                    
                    total_invested += invested
                    total_current += current_value
                
                if holdings_data:
                    df = pd.DataFrame(holdings_data)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    
                    # Summary
                    st.markdown("---")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Invested", f"₹{total_invested:,.2f}")
                    with col2:
                        st.metric("Current Value", f"₹{total_current:,.2f}")
                    with col3:
                        total_pnl = total_current - total_invested
                        total_pnl_percent = (total_pnl / total_invested * 100) if total_invested > 0 else 0
                        st.metric("Total P&L", f"₹{total_pnl:,.2f}", f"{total_pnl_percent:.1f}%")
            else:
                st.info("No holdings yet. Start trading to build your portfolio!")
        else:
            st.info("Portfolio data not available")
    
    elif method_trading == "Live Trading":
        # Live Trading interface
        st.subheader("Search Stocks")
        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            search_query = st.text_input("Search stock (by company name or symbol)", 
                                        placeholder="Enter company name or symbol...",
                                        key="search_input")
        with col2:
            searching = st.button("Search", use_container_width=True)
        with col3:
            if st.button("Clear", use_container_width=True):
                st.session_state.search_results = None
                st.session_state.selected_company = None
                st.session_state.search_performed = False
                st.rerun()
        
        # Perform search
        if searching and search_query:
            st.session_state.search_results = []
            st.session_state.search_performed = True
            
            for stock_type, stocks in STOCKS_DATABASE.items():
                for company_name, symbol in stocks.items():
                    if (search_query.lower() in company_name.lower() or 
                        search_query.lower() in symbol.lower()):
                        st.session_state.search_results.append({
                            "type": stock_type,
                            "company_name": company_name,
                            "symbol": symbol
                        })
            
            if all_indian_stocks is not None and not all_indian_stocks.empty:
                try:
                    mask = (
                        all_indian_stocks['NAME OF COMPANY'].astype(str).str.contains(search_query, case=False, na=False) |
                        all_indian_stocks['SYMBOL'].astype(str).str.contains(search_query, case=False, na=False)
                    )
                    csv_search_results = all_indian_stocks[mask]
                        
                    for _, row in csv_search_results.iterrows():
                        temp = {
                            "type": "Indian Stocks",
                            "company_name": str(row['NAME OF COMPANY']) if pd.notna(row['NAME OF COMPANY']) else "Unknown",
                            "symbol": str(row['SYMBOL']) if pd.notna(row['SYMBOL']) else "UNKNOWN.NS"
                        }
                        if not any(r['symbol'] == temp['symbol'] for r in st.session_state.search_results):
                            st.session_state.search_results.append(temp)
                except Exception as e:
                    st.warning(f"Error searching Indian stocks: {str(e)}")
            
            if not st.session_state.search_results:
                st.warning(f"No stocks found matching '{search_query}'")
            else:
                st.success(f"Found {len(st.session_state.search_results)} results")
        
        # Display search results or normal selection
        if st.session_state.search_results and st.session_state.search_performed:
            st.subheader("Search Results")
            
            display_options = []
            for result in st.session_state.search_results:
                if result and 'company_name' in result and 'symbol' in result:
                    display_text = f"{result['company_name']} ({result['symbol']}) - {result.get('type', 'Unknown')}"
                    display_options.append((display_text, result))
            
            if display_options:
                selected_display = st.selectbox(
                    "Select from search results:",
                    options=[opt[0] for opt in display_options],
                    index=None,
                    placeholder="Choose a stock from search results..."
                )
                
                if selected_display:
                    try:
                        selected_index = [opt[0] for opt in display_options].index(selected_display)
                        selected_result = display_options[selected_index][1]
                        st.session_state.selected_company = selected_result
                        
                        catagory = selected_result.get('type', 'Unknown')
                        full_company_name = selected_result.get('company_name', 'Unknown')
                        company = selected_result.get('symbol', '')
                        
                        if company:
                            st.success(f"Selected: {full_company_name} ({company})")
                        else:
                            st.error("Invalid stock symbol")
                    except (ValueError, IndexError) as e:
                        st.error(f"Error selecting stock: {str(e)}")
                        catagory = st.selectbox("Select category of the stock:", list(STOCKS_DATABASE.keys()))
                        full_company_name = ""
                        company = ""
                else:
                    catagory = st.selectbox("Select category of the stock:", list(STOCKS_DATABASE.keys()))
                    full_company_name = ""
                    company = ""
        else:
            catagory = "Indian Stocks"
            
            if catagory == "Indian Stocks":
                if all_indian_stocks is not None and not all_indian_stocks.empty and 'NAME OF COMPANY' in all_indian_stocks.columns:
                    companies = all_indian_stocks['NAME OF COMPANY'].dropna().unique().tolist()
                    if companies:
                        full_company_name = st.selectbox("Select company for stock:", companies)
                        if 'SYMBOL' in all_indian_stocks.columns:
                            try:
                                symbol_data = all_indian_stocks[all_indian_stocks['NAME OF COMPANY'] == full_company_name]['SYMBOL']
                                if not symbol_data.empty and pd.notna(symbol_data.iloc[0]):
                                    company = str(symbol_data.iloc[0])
                                else:
                                    st.error("Symbol not found for selected company")
                                    company = ""
                            except Exception as e:
                                st.error(f"Error getting symbol: {str(e)}")
                                company = ""
                        else:
                            st.error("CSV file doesn't have 'SYMBOL' column")
                            company = ""
                    else:
                        st.error("No companies available in Indian stocks database")
                        full_company_name = ""
                        company = ""
                else:
                    st.error("Indian stocks data not available or improperly loaded")
                    full_company_name = ""
                    company = ""
            else:
                company_items = list(STOCKS_DATABASE.get(catagory, {}).items())
                if company_items:
                    display_options = [f"{name} ({symbol})" for name, symbol in company_items]
                    selected_display = st.selectbox("Select company for stock:", display_options)
                    
                    if selected_display:
                        try:
                            full_company_name, company_with_parenthesis = selected_display.split(" (", 1)
                            company = company_with_parenthesis.rstrip(")")
                        except ValueError:
                            st.error("Error parsing stock selection")
                            full_company_name = ""
                            company = ""
                    else:
                        full_company_name = ""
                        company = ""
                else:
                    st.warning(f"No stocks available in category: {catagory}")
                    full_company_name = ""
                    company = ""
        
        # Display stock data and graph
        if 'full_company_name' in locals() and full_company_name and company:
            st.header(f"{full_company_name} ({company})")
            
            # Watchlist button at top
            col1, col2 = st.columns([3, 1])
            with col2:
                if st.button("⭐ Add to Watchlist", use_container_width=True):
                    success, message = add_to_watchlist(st.session_state.user_id, company, full_company_name)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
            
            try:
                # Use OOP Stock class
                stock = Stock(company, full_company_name)
                
                # Get live price
                live_price = stock.get_current_price()
                
                # Get recent history for graph
                st.subheader("Recent Price Chart")
                
                period_options = {
                    "Live": "live",
                    "1 Day": ("1d", "1m"),
                    "1 Week": ("7d", "15m"),
                    "1 Month": ("1mo", "1h"),
                    "3 Months": ("3mo", "1d"),
                    "6 Months": ("6mo", "1d"),
                    "1 Year": ("1y", "1wk")
                }
                
                selected_period = st.selectbox("Select time period:", list(period_options.keys()))
                
                if stock.ticker is not None:
                    try:
                        if selected_period == "Live":
                            try:
                                market_open = is_market_open_now()
                            except:
                                market_open = False
                            
                            if company.endswith('.NS') and not market_open:
                                st.warning("Indian Market is currently closed. Showing last available data.")
                            
                            try:
                                start_time, end_time = get_live_data_period()
                                data = stock.ticker.history(start=start_time.strftime("%Y-%m-%d %H:%M:%S"), 
                                                          end=end_time.strftime("%Y-%m-%d %H:%M:%S"), 
                                                          interval="1m")
                            except:
                                data = pd.DataFrame()
                            
                            if data.empty:
                                try:
                                    data = stock.ticker.history(period="1d", interval="1m")
                                    if len(data) > 30:
                                        data = data.tail(30)
                                except:
                                    data = pd.DataFrame()
                            
                        else:
                            period, interval = period_options[selected_period]
                            try:
                                data = stock.ticker.history(period=period, interval=interval)
                            except:
                                data = pd.DataFrame()
                        
                    except Exception as e:
                        st.error(f"Error fetching historical data: {str(e)}")
                        data = pd.DataFrame()
                
                if data is None or data.empty or not isinstance(data, pd.DataFrame):
                    st.warning(f"No historical data available for {full_company_name} ({company})")
                    data = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume'])
                
                # Live trading interface for Live period
                if selected_period == "Live" and stock.ticker is not None:
                    try:
                        current_price = "N/A"
                        if not data.empty and 'Close' in data.columns and len(data) > 0:
                            try:
                                current_price = float(data["Close"].iloc[-1])
                            except:
                                current_price = live_price if isinstance(live_price, (int, float)) else 0
                        else:
                            current_price = live_price if isinstance(live_price, (int, float)) else 0
                        
                        if isinstance(current_price, (int, float)) and current_price > 0:
                            st.subheader(f"Current Price: ₹{current_price:.2f}" if company.endswith('.NS') else f"${current_price:.2f}")
                            
                            portfolio = get_user_portfolio(st.session_state.user_id)
                            
                            st.markdown("### Live Portfolio")
                            
                            col1, col2, col3 = st.columns(3)
                            
                            with col1:
                                st.metric("Cash Balance", 
                                         f"₹{portfolio['cash']:,.2f}" if company.endswith('.NS') else f"${portfolio['cash']:,.2f}")
                            
                            with col2:
                                holdings_value = 0
                                shares_held = 0
                                if company in portfolio['holdings']:
                                    holdings = portfolio['holdings'][company]
                                    shares_held = holdings['shares']
                                    holdings_value = holdings['shares'] * current_price
                                    st.metric("Current Holdings", 
                                             f"{holdings['shares']} shares",
                                             f"Value: ₹{holdings_value:,.2f}" if company.endswith('.NS') else f"Value: ${holdings_value:,.2f}")
                                else:
                                    st.metric("Current Holdings", "0 shares")
                            
                            with col3:
                                total_value = portfolio['cash'] + holdings_value
                                st.metric("Total Portfolio Value", 
                                         f"₹{total_value:,.2f}" if company.endswith('.NS') else f"${total_value:,.2f}")
                            
                            # Check if market is open for Indian stocks
                            is_market_open = True
                            market_status_message = ""
                            
                            if company.endswith('.NS'):  # Indian stock
                                is_market_open = is_market_open_now()
                                if not is_market_open:
                                    market_status_message = "⚠️ Indian Stock Market is currently CLOSED"
                            
                            st.markdown("### Live Trading")
                            
                            # Show market status
                            if market_status_message:
                                st.warning(market_status_message)
                            
                            trading_col1, trading_col2 = st.columns(2)
                            
                            with trading_col1:
                                st.markdown("#### 📥 Buy Stocks")
                                
                                # Only show buy options if market is open (for Indian stocks)
                                if company.endswith('.NS') and not is_market_open:
                                    st.info("Buy options are only available when market is open")
                                    st.info("Market Hours: 9:15 AM - 3:30 PM (Monday-Friday)")
                                else:
                                    max_shares = int(portfolio['cash'] // current_price) if current_price > 0 else 0
                                    max_shares = min(max_shares, 100)
                                    
                                    if max_shares > 0:
                                        quick_buy_cols = st.columns(3)
                                        with quick_buy_cols[0]:
                                            if st.button("Buy 5", use_container_width=True, key="live_buy_5"):
                                                shares_to_buy = min(5, max_shares)
                                                if shares_to_buy > 0:
                                                    success, message = update_portfolio_db(st.session_state.user_id, company, 'buy', shares_to_buy, current_price, full_company_name)
                                                    if success:
                                                        st.success(f"{message}: {shares_to_buy} shares at ₹{current_price:.2f}")
                                                        st.rerun()
                                                    else:
                                                        st.error(f"{message}")
                                        
                                        with quick_buy_cols[1]:
                                            if st.button("Buy 10", use_container_width=True, key="live_buy_10"):
                                                shares_to_buy = min(10, max_shares)
                                                if shares_to_buy > 0:
                                                    success, message = update_portfolio_db(st.session_state.user_id, company, 'buy', shares_to_buy, current_price, full_company_name)
                                                    if success:
                                                        st.success(f"{message}: {shares_to_buy} shares at ₹{current_price:.2f}")
                                                        st.rerun()
                                                    else:
                                                        st.error(f"{message}")
                                        
                                        with quick_buy_cols[2]:
                                            if st.button("Buy 25", use_container_width=True, key="live_buy_25"):
                                                shares_to_buy = min(25, max_shares)
                                                if shares_to_buy > 0:
                                                    success, message = update_portfolio_db(st.session_state.user_id, company, 'buy', shares_to_buy, current_price, full_company_name)
                                                    if success:
                                                        st.success(f"{message}: {shares_to_buy} shares at ₹{current_price:.2f}")
                                                        st.rerun()
                                                    else:
                                                        st.error(f"{message}")
                                        
                                        st.markdown("---")
                                        shares_to_buy = st.number_input(
                                            "Custom Buy Amount", 
                                            min_value=1, 
                                            max_value=max_shares, 
                                            value=1,
                                            key="live_buy_shares"
                                        )
                                        buy_cost = shares_to_buy * current_price
                                        
                                        if st.button(f"Buy {shares_to_buy} Shares", type="primary", use_container_width=True, key="live_buy_custom"):
                                            success, message = update_portfolio_db(st.session_state.user_id, company, 'buy', shares_to_buy, current_price, full_company_name)
                                            if success:
                                                st.success(f"{message}: {shares_to_buy} shares at ₹{current_price:.2f}")
                                                st.rerun()
                                            else:
                                                st.error(f"{message}")
                                        
                                        st.caption(f"Max {max_shares} shares | Cost: ₹{buy_cost:,.2f}")
                                    else:
                                        st.warning("Insufficient cash to buy shares")
                                        st.caption(f"Need at least ₹{current_price:.2f} | Have: ₹{portfolio['cash']:.2f}")
                            
                            with trading_col2:
                                st.markdown("#### Sell Stocks")
                                
                                # Only show sell options if market is open (for Indian stocks)
                                if company.endswith('.NS') and not is_market_open:
                                    st.info("Sell options are only available when market is open")
                                    st.info("Market Hours: 9:15 AM - 3:30 PM (Monday-Friday)")
                                else:
                                    if shares_held > 0:
                                        current_value = shares_held * current_price
                                        avg_price = portfolio['holdings'][company]['avg_price']
                                        total_pnl = (current_price - avg_price) * shares_held
                                        
                                        quick_sell_cols = st.columns(3)
                                        with quick_sell_cols[0]:
                                            if st.button("Sell 25%", use_container_width=True, key="live_sell_25"):
                                                shares_to_sell = int(shares_held * 0.25)
                                                if shares_to_sell > 0:
                                                    success, message = update_portfolio_db(st.session_state.user_id, company, 'sell', shares_to_sell, current_price)
                                                    if success:
                                                        st.success(f"{message}")
                                                        st.rerun()
                                                    else:
                                                        st.error(f"{message}")
                                        
                                        with quick_sell_cols[1]:
                                            if st.button("Sell 50%", use_container_width=True, key="live_sell_50"):
                                                shares_to_sell = int(shares_held * 0.5)
                                                if shares_to_sell > 0:
                                                    success, message = update_portfolio_db(st.session_state.user_id, company, 'sell', shares_to_sell, current_price)
                                                    if success:
                                                        st.success(f"{message}")
                                                        st.rerun()
                                                    else:
                                                        st.error(f"{message}")
                                        
                                        with quick_sell_cols[2]:
                                            if st.button("Sell All", type="secondary", use_container_width=True, key="live_sell_all"):
                                                success, message = update_portfolio_db(st.session_state.user_id, company, 'sell', shares_held, current_price)
                                                if success:
                                                    st.success(f"{message}")
                                                    st.rerun()
                                                else:
                                                    st.error(f"{message}")
                                        
                                        st.markdown("---")
                                        shares_to_sell = st.number_input(
                                            "Custom Sell Amount", 
                                            min_value=1, 
                                            max_value=shares_held, 
                                            value=1,
                                            key="live_sell_shares"
                                        )
                                        sell_value = shares_to_sell * current_price
                                        
                                        if st.button(f"Sell {shares_to_sell} Shares", type="secondary", use_container_width=True, key="live_sell_custom"):
                                            success, message = update_portfolio_db(st.session_state.user_id, company, 'sell', shares_to_sell, current_price)
                                            if success:
                                                st.success(f"{message}")
                                                st.rerun()
                                            else:
                                                st.error(f"{message}")
                                        
                                        st.caption(f"Selling {shares_to_sell} shares = ₹{sell_value:,.2f}")
                                        st.info(f"Average Buy Price: ₹{avg_price:.2f} | Current P&L: ₹{total_pnl:,.2f}")
                                    else:
                                        st.info("No shares to sell")
                            
                            # Only show recent orders if market is open
                            if portfolio['orders'] and (not company.endswith('.NS') or is_market_open):
                                st.markdown("#### Recent Orders")
                                recent_orders = [o for o in portfolio['orders'] if o['symbol'] == company][-5:]
                                for order in reversed(recent_orders):
                                    emoji = "🟢" if order['action'] == 'buy' else "🔴"
                                    time_str = order['timestamp'].strftime('%H:%M:%S')
                                    st.write(f"{emoji} {order['action'].upper()} {order['shares']} shares @ ₹{order['price']:.2f} ({time_str})")
                            
                            st.markdown("---")
                            st.markdown("#### Auto Refresh")
                            
                            # Only show auto-refresh if market is open
                            if not company.endswith('.NS') or is_market_open:
                                refresh_col1, refresh_col2 = st.columns([2, 1])
                                with refresh_col1:
                                    refresh_rate = st.slider("Auto-refresh rate (seconds):", 10, 60, 30)
                                with refresh_col2:
                                    auto_refresh = st.checkbox("Enable auto-refresh", value=False)
                                
                                if st.button("Refresh Now", key="live_refresh"):
                                    st.rerun()
                                
                                if auto_refresh:
                                    time_module.sleep(refresh_rate)
                                    st.rerun()
                            else:
                                st.info("Auto-refresh is only available during market hours")
                            
                            if not data.empty and len(data) > 0:
                                try:
                                    st.info(f"Live Data: {data.index[0].strftime('%H:%M')} to {data.index[-1].strftime('%H:%M')}")
                                except:
                                    st.info("Live Data available")
                        else:
                            st.warning("Current price not available for live trading")
                    except Exception as e:
                        st.error(f"Error in live trading interface: {str(e)}")

                # Display price metrics
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    if isinstance(live_price, (int, float)):
                        st.metric(label="Current Price", 
                                 value=f"₹{live_price:.2f}" if company.endswith('.NS') else f"${live_price:.2f}")
                    else:
                        st.metric(label="Current Price", value=str(live_price))
                
                with col2:
                    day_high = "N/A"
                    if stock.ticker is not None:
                        try:
                            high_info = stock.ticker.fast_info.get("day_high", None)
                            if high_info is not None:
                                day_high = float(high_info)
                            else:
                                hist_data = stock.ticker.history(period="1d")
                                if not hist_data.empty and 'High' in hist_data.columns:
                                    day_high = float(hist_data['High'].max())
                        except:
                            day_high = "N/A"
                    
                    if isinstance(day_high, (int, float)):
                        st.metric(label="Day High", 
                                 value=f"₹{day_high:.2f}" if company.endswith('.NS') else f"${day_high:.2f}")
                    else:
                        st.metric(label="Day High", value=str(day_high))
                
                with col3:
                    day_low = "N/A"
                    if stock.ticker is not None:
                        try:
                            low_info = stock.ticker.fast_info.get("day_low", None)
                            if low_info is not None:
                                day_low = float(low_info)
                            else:
                                hist_data = stock.ticker.history(period="1d")
                                if not hist_data.empty and 'Low' in hist_data.columns:
                                    day_low = float(hist_data['Low'].min())
                        except:
                            day_low = "N/A"
                    
                    if isinstance(day_low, (int, float)):
                        st.metric(label="Day Low", 
                                 value=f"₹{day_low:.2f}" if company.endswith('.NS') else f"${day_low:.2f}")
                    else:
                        st.metric(label="Day Low", value=str(day_low))
                
                # Display charts
                if not data.empty and isinstance(data, pd.DataFrame) and len(data) > 0:
                    col1, col2, col3 = st.columns([1, 1, 1])
                    with col1:
                        area_chart = st.button("Area Chart", key="area_btn")
                    with col2:
                        line_chart = st.button("Line Chart", key="line_btn")
                    with col3:
                        candlestick_chart = st.button("Candlestick Chart", key="candle_btn")
                    
                    chart_displayed = False
                    
                    required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                    if all(col in data.columns for col in required_columns):
                        if area_chart or (not line_chart and not candlestick_chart and not chart_displayed):
                            try:
                                x_labels = data.index
                                if selected_period == "Live" or selected_period == "1 Day":
                                    x_labels = [dt.time() for dt in data.index]
                                
                                x = np.arange(len(data))
                                
                                fig, (ax_price, ax_vol) = plt.subplots(
                                    2, 1,
                                    figsize=(15, 12),
                                    sharex=True,
                                    gridspec_kw={"height_ratios": [5, 4]}
                                )
                                
                                ax_price.plot(x, data["Close"], linewidth=2, label="Close Price")
                                ax_price.fill_between(x, data["Close"], alpha=0.25)
                                
                                price_min = data["Close"].min()
                                price_max = data["Close"].max()
                                padding = (price_max - price_min) * 0.15
                                ax_price.set_ylim(price_min - padding, price_max + padding)
                                
                                ax_price.set_ylabel("Price (Real Value)")
                                ax_price.set_title(f"{full_company_name} - {selected_period} Price Chart")
                                ax_price.legend()
                                ax_price.grid(True, alpha=0.2)
                                
                                colors = np.where(data["Close"].diff() >= 0, "#2ecc71", "#e74c3c")
                                
                                ax_vol.bar(x, data["Volume"], width=0.8, color=colors, edgecolor="black", linewidth=0.3)
                                ax_vol.set_ylabel("Volume")
                                ax_vol.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1e6:.1f}M"))
                                ax_vol.grid(False)
                                
                                step = max(len(x) // 10, 1)
                                ax_vol.set_xticks(x[::step])
                                
                                if selected_period == "Live":
                                    time_labels = [t.strftime('%H:%M') for t in x_labels[::step]]
                                    ax_vol.set_xticklabels(time_labels, rotation=45, ha="right")
                                else:
                                    ax_vol.set_xticklabels(x_labels[::step], rotation=45, ha="right")
                                
                                plt.xlabel("Time" if selected_period == "Live" else "Date")
                                plt.tight_layout()
                                
                                st.pyplot(fig)
                                plt.close(fig)
                                chart_displayed = True
                            except Exception as e:
                                st.error(f"Error displaying area chart: {str(e)}")
                        
                        if line_chart and not chart_displayed:
                            try:
                                x = np.arange(len(data))
                                plt.figure(figsize=(10, 6))
                                plt.plot(x, data["Close"], label="Close Price", linewidth=2)
                                plt.title(f"{full_company_name} - {selected_period} Price Chart")
                                plt.xlabel("Time" if selected_period == "Live" else "Date")
                                plt.ylabel("Price")
                                plt.legend()
                                plt.grid(True, alpha=0.3)
                                
                                if selected_period == "Live":
                                    x_labels = [dt.strftime('%H:%M') for dt in data.index]
                                else:
                                    x_labels = [dt.date() for dt in data.index]
                                
                                step = max(len(x) // 14, 1)
                                plt.xticks(x[::step], x_labels[::step], rotation=70)
                                plt.tight_layout()
                                st.pyplot(plt)
                                plt.clf()
                                chart_displayed = True
                            except Exception as e:
                                st.error(f"Error displaying line chart: {str(e)}")
                        
                        if candlestick_chart and not chart_displayed:
                            try:
                                x_values = list(range(len(data)))
                                
                                fig = go.Figure(data=[go.Candlestick(
                                    x=x_values,
                                    open=data['Open'],
                                    high=data['High'],
                                    low=data['Low'],
                                    close=data['Close'],
                                    name="Candlestick",
                                    increasing=dict(line=dict(color="#00C853"), fillcolor="#00C853"),
                                    decreasing=dict(line=dict(color="#D50000"), fillcolor="#D50000")
                                )])
                                
                                if selected_period == "Live":
                                    date_strings = [dt.strftime('%H:%M') for dt in data.index]
                                else:
                                    date_strings = [dt.strftime('%Y-%m-%d') for dt in data.index]
                                
                                fig.update_layout(
                                    title=f"{full_company_name} - {selected_period} Candlestick Chart",
                                    xaxis_title="Time" if selected_period == "Live" else "Date",
                                    yaxis_title="Price",
                                    xaxis_rangeslider_visible=False,
                                    height=600,
                                    xaxis=dict(
                                        tickmode='array',
                                        tickvals=x_values[::max(1, len(x_values)//10)],
                                        ticktext=[date_strings[i] for i in x_values[::max(1, len(x_values)//10)]],
                                        tickangle=45
                                    )
                                )
                                
                                st.plotly_chart(fig, use_container_width=True)
                                chart_displayed = True
                            except Exception as e:
                                st.error(f"Error displaying candlestick chart: {str(e)}")
                        
                        st.subheader("Historical Data")
                        try:
                            st.dataframe(data.tail(20).style.format({
                                'Open': '{:.2f}',
                                'High': '{:.2f}', 
                                'Low': '{:.2f}',
                                'Close': '{:.2f}',
                                'Volume': '{:,.0f}'
                            }))
                        except Exception as e:
                            st.error(f"Error displaying data table: {str(e)}")
                        
                            with info_col2:
                                st.write("**Price Info:**")
                                try:
                                    prev_close = stock.ticker.fast_info.get("previous_close", "N/A") if stock.ticker else "N/A"
                                    if isinstance(prev_close, (int, float)):
                                        st.write(f"Previous Close: ${prev_close:.2f}")
                                    else:
                                        st.write(f"Previous Close: {prev_close}")
                                    
                                    if (isinstance(live_price, (int, float)) and 
                                        isinstance(prev_close, (int, float)) and 
                                        prev_close != 0):
                                        change = ((live_price - prev_close) / prev_close) * 100
                                        st.write(f"Daily Change: {change:+.2f}%")
                                except:
                                    st.write("Previous Close: N/A")
                    else:
                        st.warning("Incomplete data available for charts")
                else:
                    st.warning("No data available for the selected period.")
                    
            except Exception as e:
                st.error(f"Error fetching data: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
                st.info("Please check if the stock symbol is correct and try again.")
        
        elif st.session_state.search_performed and not st.session_state.search_results:
            st.info("Try searching for a different stock or use the category selection above.")
        
        else:
            st.info("Please select or search for a stock to view its data.")
    
    else:
        # Practice Mode (formerly "Learn with random graph") - REMOVED navigation options
        st.header("💰 Practice Mode")
        
        # Auto-advance timer
        if 'day_complete' in st.session_state and not st.session_state.day_complete:
            time_diff = (datetime.now() - st.session_state.last_update).seconds
            
            if st.session_state.auto_advance:
                if time_diff >= 5:
                    if st.session_state.current_minute < 389:
                        st.session_state.current_minute += 1
                        st.session_state.last_update = datetime.now()
                        st.session_state.graph_updated = True
                        st.rerun()
                    else:
                        st.session_state.day_complete = True
                        st.session_state.auto_advance = False
                        st.rerun()
        
        # Get stock details
        idx = st.session_state.random_stock_index
        symbol = all_indian_stocks.iloc[idx, 0]
        
        st.subheader(f"Trading: {symbol}")
        
        def get_trading_dates(symbol, days_back=60):
            """Get historical trading dates"""
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            try:
                data = yf.download(
                    symbol,
                    start=start_date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                    progress=False
                )
                
                if data.empty:
                    dates = []
                    current = start_date
                    while current <= end_date:
                        if current.weekday() < 5:
                            dates.append(current)
                        current += timedelta(days=1)
                    return dates[-10:]
                else:
                    return data.index.tolist()
            except:
                dates = []
                current = start_date
                while current <= end_date:
                    if current.weekday() < 5:
                        dates.append(current)
                    current += timedelta(days=1)
                return dates[-10:]
        
        def generate_trading_data_for_date(symbol, date=None):
            """Generate minute-by-minute trading data for a specific date"""
            if date is None:
                date = datetime.now()
            
            try:
                end_date = date + timedelta(days=1)
                data = yf.download(
                    symbol,
                    start=date.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                    progress=False
                )
                
                if not data.empty:
                    base_price = float(data['Close'].iloc[-1])
                else:
                    base_price = 100 + (hash(symbol) % 9900)
            except:
                base_price = 100 + (hash(symbol) % 9900)
            
            minutes = 390
            seed_value = int(date.timestamp()) + hash(symbol)
            np.random.seed(seed_value % 10000)
            
            returns = np.random.normal(0.0001, 0.001, minutes)
            cumulative_returns = np.cumsum(returns)
            minute_prices = base_price * (1 + cumulative_returns)
            
            min_price = base_price * 0.9
            max_price = base_price * 1.1
            minute_prices = np.clip(minute_prices, min_price, max_price)
            
            base_volume = random.randint(10000, 1000000)
            x = np.linspace(0, 2*np.pi, minutes)
            volume_pattern = (np.sin(x - np.pi/2) + 1) * 0.5
            minute_volumes = (volume_pattern * base_volume / volume_pattern.mean()).astype(int)
            
            minute_data = []
            for i in range(minutes):
                if i == 0:
                    minute_open = minute_prices[i]
                else:
                    minute_open = minute_prices[i-1]
                
                minute_close = minute_prices[i]
                price_range = abs(minute_close - minute_open)
                minute_high = max(minute_open, minute_close) + random.random() * price_range * 0.1
                minute_low = min(minute_open, minute_close) - random.random() * price_range * 0.1
                
                minute_data.append({
                    'minute': i,
                    'open': float(minute_open),
                    'high': float(minute_high),
                    'low': float(minute_low),
                    'close': float(minute_close),
                    'volume': int(minute_volumes[i])
                })
            
            return minute_data
        
        def get_next_trading_date(current_date, trading_dates):
            """Get the next valid trading date"""
            if not trading_dates:
                return None
            
            sorted_dates = sorted(trading_dates)
            current_date_str = current_date.strftime("%Y-%m-%d")
            sorted_date_strs = [d.strftime("%Y-%m-%d") for d in sorted_dates]
            
            try:
                current_idx = sorted_date_strs.index(current_date_str)
                
                if current_idx + 1 < len(sorted_dates):
                    return sorted_dates[current_idx + 1]
                else:
                    return random.choice(sorted_dates[:-1])
            except ValueError:
                return sorted_dates[0]
        
        # Initialize trading data if not set
        if st.session_state.trading_data is None:
            with st.spinner("Initializing trading session..."):
                st.session_state.trading_dates = get_trading_dates(symbol, days_back=90)
                
                if not st.session_state.trading_dates:
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=30)
                    dates = []
                    current = start_date
                    while current <= end_date:
                        if current.weekday() < 5:
                            dates.append(current)
                        current += timedelta(days=1)
                    st.session_state.trading_dates = dates
                
                if len(st.session_state.trading_dates) > 1:
                    st.session_state.current_trading_date = random.choice(st.session_state.trading_dates[:-1])
                else:
                    st.session_state.current_trading_date = st.session_state.trading_dates[0]
                
                st.session_state.minute_data = generate_trading_data_for_date(
                    symbol, 
                    st.session_state.current_trading_date
                )
                
                st.session_state.trading_data = True
                st.session_state.current_minute = 0
                st.session_state.day_complete = False
                st.session_state.graph_updated = True
                st.rerun()
        
        if st.session_state.current_trading_date:
            st.info(f"**Trading Date:** {st.session_state.current_trading_date.strftime('%A, %d %B %Y')}")
        
        # Portfolio display
        st.markdown("---")
        st.subheader("Portfolio Dashboard")
        
        portfolio_cols = st.columns(4)
        with portfolio_cols[0]:
            st.metric("Cash", f"₹{st.session_state.random_portfolio['cash']:,.2f}")
        with portfolio_cols[1]:
            shares_held = st.session_state.random_portfolio['shares']
            avg_price = st.session_state.random_portfolio['buy_price']
            st.metric("Shares Held", f"{shares_held} @ ₹{avg_price:.2f}")
        with portfolio_cols[2]:
            if hasattr(st.session_state, 'minute_data') and st.session_state.minute_data and shares_held > 0:
                current_price = st.session_state.minute_data[st.session_state.current_minute]['close']
                pnl = (current_price - avg_price) * shares_held
                pnl_percent = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0
                st.metric("Current P&L", f"₹{pnl:,.2f}", f"{pnl_percent:.2f}%")
            else:
                st.metric("Current P&L", "₹0.00", "0%")
        with portfolio_cols[3]:
            total_value = st.session_state.random_portfolio['cash']
            if hasattr(st.session_state, 'minute_data') and st.session_state.minute_data and shares_held > 0:
                current_price = st.session_state.minute_data[st.session_state.current_minute]['close']
                total_value += current_price * shares_held
            st.metric("Total Value", f"₹{total_value:,.2f}")
        
        # Trading actions
        st.markdown("---")
        st.subheader("Trading Actions")
        
        if hasattr(st.session_state, 'minute_data') and st.session_state.minute_data:
            current_data = st.session_state.minute_data[st.session_state.current_minute]
            current_price = current_data['close']
            
            st.info(f"## 💰 Current Stock Price: ₹{current_price:.2f}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("### Buy Stocks")
                max_shares = int(st.session_state.random_portfolio['cash'] // current_price)
                max_shares = min(max_shares, 50)
                
                if max_shares > 0:
                    quick_buy_cols = st.columns(3)
                    with quick_buy_cols[0]:
                        if st.button("Buy 5", use_container_width=True):
                            shares_to_buy = min(5, max_shares)
                            if shares_to_buy > 0:
                                buy_cost = shares_to_buy * current_price
                                st.session_state.random_portfolio['cash'] -= buy_cost
                                st.session_state.random_portfolio['shares'] += shares_to_buy
                                
                                if len(st.session_state.random_portfolio['buy_transactions']) == 0:
                                    st.session_state.random_portfolio['buy_price'] = current_price
                                else:
                                    total_cost = sum([t['shares'] * t['price'] for t in st.session_state.random_portfolio['buy_transactions']]) + buy_cost
                                    total_shares = sum([t['shares'] for t in st.session_state.random_portfolio['buy_transactions']]) + shares_to_buy
                                    st.session_state.random_portfolio['buy_price'] = total_cost / total_shares
                                
                                st.session_state.random_portfolio['buy_transactions'].append({
                                    'shares': shares_to_buy,
                                    'price': current_price,
                                    'total': buy_cost
                                })
                                
                                st.session_state.trade_history.append({
                                    'type': 'BUY',
                                    'date': st.session_state.current_trading_date.strftime('%Y-%m-%d'),
                                    'time': f"{9 + st.session_state.current_minute // 60}:{st.session_state.current_minute % 60:02d}",
                                    'price': current_price,
                                    'shares': shares_to_buy,
                                    'total': buy_cost
                                })
                                st.success(f"Bought {shares_to_buy} shares at ₹{current_price:.2f}")
                                st.rerun()
                    
                    with quick_buy_cols[1]:
                        if st.button("Buy 10", use_container_width=True):
                            shares_to_buy = min(10, max_shares)
                            if shares_to_buy > 0:
                                buy_cost = shares_to_buy * current_price
                                st.session_state.random_portfolio['cash'] -= buy_cost
                                st.session_state.random_portfolio['shares'] += shares_to_buy
                                
                                if len(st.session_state.random_portfolio['buy_transactions']) == 0:
                                    st.session_state.random_portfolio['buy_price'] = current_price
                                else:
                                    total_cost = sum([t['shares'] * t['price'] for t in st.session_state.random_portfolio['buy_transactions']]) + buy_cost
                                    total_shares = sum([t['shares'] for t in st.session_state.random_portfolio['buy_transactions']]) + shares_to_buy
                                    st.session_state.random_portfolio['buy_price'] = total_cost / total_shares
                                
                                st.session_state.random_portfolio['buy_transactions'].append({
                                    'shares': shares_to_buy,
                                    'price': current_price,
                                    'total': buy_cost
                                })
                                
                                st.session_state.trade_history.append({
                                    'type': 'BUY',
                                    'date': st.session_state.current_trading_date.strftime('%Y-%m-%d'),
                                    'time': f"{9 + st.session_state.current_minute // 60}:{st.session_state.current_minute % 60:02d}",
                                    'price': current_price,
                                    'shares': shares_to_buy,
                                    'total': buy_cost
                                })
                                st.success(f"✅ Bought {shares_to_buy} shares at ₹{current_price:.2f}")
                                st.rerun()
                    
                    with quick_buy_cols[2]:
                        if st.button("Buy 25", use_container_width=True):
                            shares_to_buy = min(25, max_shares)
                            if shares_to_buy > 0:
                                buy_cost = shares_to_buy * current_price
                                st.session_state.random_portfolio['cash'] -= buy_cost
                                st.session_state.random_portfolio['shares'] += shares_to_buy
                                
                                if len(st.session_state.random_portfolio['buy_transactions']) == 0:
                                    st.session_state.random_portfolio['buy_price'] = current_price
                                else:
                                    total_cost = sum([t['shares'] * t['price'] for t in st.session_state.random_portfolio['buy_transactions']]) + buy_cost
                                    total_shares = sum([t['shares'] for t in st.session_state.random_portfolio['buy_transactions']]) + shares_to_buy
                                    st.session_state.random_portfolio['buy_price'] = total_cost / total_shares
                                
                                st.session_state.random_portfolio['buy_transactions'].append({
                                    'shares': shares_to_buy,
                                    'price': current_price,
                                    'total': buy_cost
                                })
                                
                                st.session_state.trade_history.append({
                                    'type': 'BUY',
                                    'date': st.session_state.current_trading_date.strftime('%Y-%m-%d'),
                                    'time': f"{9 + st.session_state.current_minute // 60}:{st.session_state.current_minute % 60:02d}",
                                    'price': current_price,
                                    'shares': shares_to_buy,
                                    'total': buy_cost
                                })
                                st.success(f"✅ Bought {shares_to_buy} shares at ₹{current_price:.2f}")
                                st.rerun()
                    
                    st.markdown("---")
                    shares_to_buy = st.number_input(
                        "Custom Buy Amount", 
                        min_value=1, 
                        max_value=max_shares, 
                        value=1,
                        key="buy_shares"
                    )
                    buy_cost = shares_to_buy * current_price
                    
                    if st.button(f"Buy {shares_to_buy} Shares", type="primary", use_container_width=True):
                        st.session_state.random_portfolio['cash'] -= buy_cost
                        st.session_state.random_portfolio['shares'] += shares_to_buy
                        
                        if len(st.session_state.random_portfolio['buy_transactions']) == 0:
                            st.session_state.random_portfolio['buy_price'] = current_price
                        else:
                            total_cost = sum([t['shares'] * t['price'] for t in st.session_state.random_portfolio['buy_transactions']]) + buy_cost
                            total_shares = sum([t['shares'] for t in st.session_state.random_portfolio['buy_transactions']]) + shares_to_buy
                            st.session_state.random_portfolio['buy_price'] = total_cost / total_shares
                        
                        st.session_state.random_portfolio['buy_transactions'].append({
                            'shares': shares_to_buy,
                            'price': current_price,
                            'total': buy_cost
                        })
                        
                        st.session_state.trade_history.append({
                            'type': 'BUY',
                            'date': st.session_state.current_trading_date.strftime('%Y-%m-%d'),
                            'time': f"{9 + st.session_state.current_minute // 60}:{st.session_state.current_minute % 60:02d}",
                            'price': current_price,
                            'shares': shares_to_buy,
                            'total': buy_cost
                        })
                        st.success(f"✅ Bought {shares_to_buy} shares at ₹{current_price:.2f}")
                        st.rerun()
                    
                    st.caption(f"Max {max_shares} shares | Cost: ₹{buy_cost:,.2f}")
                else:
                    st.warning("Insufficient cash to buy shares")
                    st.caption(f"Need at least ₹{current_price:.2f} | Have: ₹{st.session_state.random_portfolio['cash']:.2f}")
            
            with col2:
                st.markdown("### Sell Stocks")
                shares_held = st.session_state.random_portfolio['shares']
                
                if shares_held > 0:
                    current_value = shares_held * current_price
                    avg_price = st.session_state.random_portfolio['buy_price']
                    total_pnl = (current_price - avg_price) * shares_held
                    
                    quick_sell_cols = st.columns(3)
                    with quick_sell_cols[0]:
                        if st.button("Sell 25%", use_container_width=True):
                            shares_to_sell = int(shares_held * 0.25)
                            if shares_to_sell > 0:
                                sell_value = shares_to_sell * current_price
                                sell_pnl = (current_price - avg_price) * shares_to_sell
                                
                                st.session_state.random_portfolio['cash'] += sell_value
                                st.session_state.random_portfolio['shares'] -= shares_to_sell
                                
                                st.session_state.trade_history.append({
                                    'type': 'PARTIAL_SELL',
                                    'date': st.session_state.current_trading_date.strftime('%Y-%m-%d'),
                                    'time': f"{9 + st.session_state.current_minute // 60}:{st.session_state.current_minute % 60:02d}",
                                    'price': current_price,
                                    'shares': shares_to_sell,
                                    'total': sell_value,
                                    'profit_loss': sell_pnl
                                })
                                
                                profit_color = "🟢" if sell_pnl >= 0 else "🔴"
                                st.success(f"{profit_color} Sold {shares_to_sell} shares at ₹{current_price:.2f} "
                                          f"(P&L: ₹{sell_pnl:,.2f})")
                                st.rerun()
                    
                    with quick_sell_cols[1]:
                        if st.button("Sell 50%", use_container_width=True):
                            shares_to_sell = int(shares_held * 0.5)
                            if shares_to_sell > 0:
                                sell_value = shares_to_sell * current_price
                                sell_pnl = (current_price - avg_price) * shares_to_sell
                                
                                st.session_state.random_portfolio['cash'] += sell_value
                                st.session_state.random_portfolio['shares'] -= shares_to_sell
                                
                                st.session_state.trade_history.append({
                                    'type': 'PARTIAL_SELL',
                                    'date': st.session_state.current_trading_date.strftime('%Y-%m-%d'),
                                    'time': f"{9 + st.session_state.current_minute // 60}:{st.session_state.current_minute % 60:02d}",
                                    'price': current_price,
                                    'shares': shares_to_sell,
                                    'total': sell_value,
                                    'profit_loss': sell_pnl
                                })
                                
                                profit_color = "🟢" if sell_pnl >= 0 else "🔴"
                                st.success(f"{profit_color} Sold {shares_to_sell} shares at ₹{current_price:.2f} "
                                          f"(P&L: ₹{sell_pnl:,.2f})")
                                st.rerun()
                    
                    with quick_sell_cols[2]:
                        if st.button("Sell All", type="secondary", use_container_width=True):
                            sell_value = shares_held * current_price
                            sell_pnl = (current_price - avg_price) * shares_held
                            
                            st.session_state.random_portfolio['cash'] += sell_value
                            st.session_state.random_portfolio['shares'] = 0
                            st.session_state.random_portfolio['buy_price'] = 0.00
                            st.session_state.random_portfolio['buy_transactions'] = []
                            
                            st.session_state.trade_history.append({
                                'type': 'FULL_SELL',
                                'date': st.session_state.current_trading_date.strftime('%Y-%m-%d'),
                                'time': f"{9 + st.session_state.current_minute // 60}:{st.session_state.current_minute % 60:02d}",
                                'price': current_price,
                                'shares': shares_held,
                                'total': sell_value,
                                'profit_loss': sell_pnl
                            })
                            
                            profit_color = "🟢" if sell_pnl >= 0 else "🔴"
                            st.success(f"{profit_color} Sold all {shares_held} shares at ₹{current_price:.2f} "
                                      f"(P&L: ₹{sell_pnl:,.2f})")
                            st.rerun()
                    
                    st.markdown("---")
                    shares_to_sell = st.number_input(
                        "Custom Sell Amount", 
                        min_value=1, 
                        max_value=shares_held, 
                        value=1,
                        key="sell_shares"
                    )
                    sell_value = shares_to_sell * current_price
                    sell_pnl = (current_price - avg_price) * shares_to_sell
                    
                    if st.button(f"Sell {shares_to_sell} Shares", type="secondary", use_container_width=True):
                        st.session_state.random_portfolio['cash'] += sell_value
                        st.session_state.random_portfolio['shares'] -= shares_to_sell
                        
                        st.session_state.trade_history.append({
                            'type': 'PARTIAL_SELL',
                            'date': st.session_state.current_trading_date.strftime('%Y-%m-%d'),
                            'time': f"{9 + st.session_state.current_minute // 60}:{st.session_state.current_minute % 60:02d}",
                            'price': current_price,
                            'shares': shares_to_sell,
                            'total': sell_value,
                            'profit_loss': sell_pnl
                        })
                        
                        profit_color = "🟢" if sell_pnl >= 0 else "🔴"
                        st.success(f"{profit_color} Sold {shares_to_sell} shares at ₹{current_price:.2f} "
                                  f"(P&L: ₹{sell_pnl:,.2f})")
                        st.rerun()
                    
                    st.caption(f"Selling {shares_to_sell} shares = ₹{sell_value:,.2f}")
                    st.info(f"Average Buy Price: ₹{avg_price:.2f} | Current P&L: ₹{total_pnl:,.2f}")
                else:
                    st.info("No shares to sell")
        
        # Chart selection
        st.markdown("---")
        st.subheader("Chart Analysis")
        
        st.markdown("---")
        st.subheader("Time Controls")
        
        if 'day_complete' in st.session_state and not st.session_state.day_complete:
            time_control_cols = st.columns(7)
            
            with time_control_cols[0]:
                if not st.session_state.auto_advance:
                    if st.button("Start Auto", use_container_width=True, type="primary"):
                        st.session_state.auto_advance = True
                        st.session_state.last_update = datetime.now()
                        st.rerun()
                else:
                    if st.button("Pause Auto", use_container_width=True):
                        st.session_state.auto_advance = False
                        st.rerun()
            
            with time_control_cols[1]:
                if st.button(" +1 Min", use_container_width=True):
                    if st.session_state.current_minute < 389:
                        st.session_state.current_minute += 1
                        st.session_state.auto_advance = False
                        st.session_state.graph_updated = True
                        st.rerun()
                    else:
                        st.session_state.day_complete = True
                        st.rerun()
            
            with time_control_cols[2]:
                if st.button("⏭️ +5 Min", use_container_width=True):
                    if st.session_state.current_minute < 385:
                        st.session_state.current_minute += 5
                        st.session_state.auto_advance = False
                        st.session_state.graph_updated = True
                        st.rerun()
                    else:
                        st.session_state.current_minute = 389
                        st.session_state.day_complete = True
                        st.rerun()
            
            with time_control_cols[3]:
                if st.button("⏭️ +15 Min", use_container_width=True):
                    if st.session_state.current_minute < 375:
                        st.session_state.current_minute += 15
                        st.session_state.auto_advance = False
                        st.session_state.graph_updated = True
                        st.rerun()
                    else:
                        st.session_state.current_minute = 389
                        st.session_state.day_complete = True
                        st.rerun()
            
            with time_control_cols[4]:
                if st.button("⏭️ +30 Min", use_container_width=True):
                    if st.session_state.current_minute < 360:
                        st.session_state.current_minute += 30
                        st.session_state.auto_advance = False
                        st.session_state.graph_updated = True
                        st.rerun()
                    else:
                        st.session_state.current_minute = 389
                        st.session_state.day_complete = True
                        st.rerun()
            
            with time_control_cols[5]:
                if st.button("⏭️ +60 Min", use_container_width=True):
                    if st.session_state.current_minute < 330:
                        st.session_state.current_minute += 60
                        st.session_state.auto_advance = False
                        st.session_state.graph_updated = True
                        st.rerun()
                    else:
                        st.session_state.current_minute = 389
                        st.session_state.day_complete = True
                        st.rerun()
            
            with time_control_cols[6]:
                if st.button("To End", use_container_width=True):
                    st.session_state.current_minute = 389
                    st.session_state.day_complete = True
                    st.session_state.auto_advance = False
                    st.rerun()
        
        chart_options = ["Candlestick", "Line Chart", "OHLC Chart", "Area Chart", "Renko"]
        chart_type = st.radio(
            "Select Chart Type:",
            chart_options,
            index=chart_options.index(st.session_state.chart_type) if st.session_state.chart_type in chart_options else 0,
            horizontal=True,
            key="chart_selector"
        )
        
        if chart_type != st.session_state.chart_type:
            st.session_state.chart_type = chart_type
            st.session_state.graph_updated = True
            st.rerun()
        
        if hasattr(st.session_state, 'minute_data') and st.session_state.minute_data:
            current_minute_idx = min(st.session_state.current_minute, len(st.session_state.minute_data) - 1)
            current_data = st.session_state.minute_data[:current_minute_idx + 1]
            
            if current_data:
                minutes = [d['minute'] for d in current_data]
                prices = [d['close'] for d in current_data]
                opens = [d['open'] for d in current_data]
                highs = [d['high'] for d in current_data]
                lows = [d['low'] for d in current_data]
                volumes = [d['volume'] for d in current_data]
                
                market_times = [f"{9 + m//60}:{m%60:02d}" for m in minutes]
                
                if st.session_state.chart_type == "Candlestick":
                    fig = go.Figure(data=[go.Candlestick(
                        x=minutes,
                        open=opens,
                        high=highs,
                        low=lows,
                        close=prices,
                        increasing=dict(line=dict(color='#00C853')),
                        decreasing=dict(line=dict(color='#D50000'))
                    )])
                    
                    fig.update_layout(
                        title=f"{symbol} - {st.session_state.current_trading_date.strftime('%d %b %Y')} (Minute {current_minute_idx})",
                        xaxis_title="Trading Minute",
                        yaxis_title="Price (₹)",
                        height=500,
                        xaxis=dict(
                            tickmode='array',
                            tickvals=minutes[::max(1, len(minutes)//10)],
                            ticktext=market_times[::max(1, len(minutes)//10)],
                            tickangle=45
                        )
                    )
                    
                elif st.session_state.chart_type == "Line Chart":
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=minutes,
                        y=prices,
                        mode='lines',
                        name='Price',
                        line=dict(color='blue', width=2)
                    ))
                    
                    if len(prices) > 20:
                        ma20 = pd.Series(prices).rolling(window=20).mean()
                        fig.add_trace(go.Scatter(
                            x=minutes,
                            y=ma20,
                            mode='lines',
                            name='MA20',
                            line=dict(color='orange', width=1, dash='dash'),
                            opacity=0.7
                        ))
                    
                    if len(prices) > 50:
                        ma50 = pd.Series(prices).rolling(window=50).mean()
                        fig.add_trace(go.Scatter(
                            x=minutes,
                            y=ma50,
                            mode='lines',
                            name='MA50',
                            line=dict(color='red', width=1, dash='dash'),
                            opacity=0.5
                        ))
                    
                    fig.update_layout(
                        title=f"{symbol} - {st.session_state.current_trading_date.strftime('%d %b %Y')} (Minute {current_minute_idx})",
                        xaxis_title="Trading Minute",
                        yaxis_title="Price (₹)",
                        height=500,
                        xaxis=dict(
                            tickmode='array',
                            tickvals=minutes[::max(1, len(minutes)//10)],
                            ticktext=market_times[::max(1, len(minutes)//10)],
                            tickangle=45
                        )
                    )
                    
                elif st.session_state.chart_type == "OHLC Chart":
                    fig = go.Figure(data=[go.Ohlc(
                        x=minutes,
                        open=opens,
                        high=highs,
                        low=lows,
                        close=prices,
                        increasing=dict(line=dict(color='#00C853')),
                        decreasing=dict(line=dict(color='#D50000'))
                    )])
                    
                    fig.update_layout(
                        title=f"{symbol} - {st.session_state.current_trading_date.strftime('%d %b %Y')} (Minute {current_minute_idx})",
                        xaxis_title="Trading Minute",
                        yaxis_title="Price (₹)",
                        height=500,
                        xaxis=dict(
                            tickmode='array',
                            tickvals=minutes[::max(1, len(minutes)//10)],
                            ticktext=market_times[::max(1, len(minutes)//10)],
                            tickangle=45
                        )
                    )
                    
                elif st.session_state.chart_type == "Area Chart":
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=minutes,
                        y=prices,
                        fill='tozeroy',
                        mode='lines',
                        name='Price',
                        line=dict(color='blue', width=2),
                        fillcolor='rgba(0, 123, 255, 0.3)'
                    ))
                    
                    fig.update_layout(
                        title=f"{symbol} - {st.session_state.current_trading_date.strftime('%d %b %Y')} (Minute {current_minute_idx})",
                        xaxis_title="Trading Minute",
                        yaxis_title="Price (₹)",
                        height=500,
                        xaxis=dict(
                            tickmode='array',
                            tickvals=minutes[::max(1, len(minutes)//10)],
                            ticktext=market_times[::max(1, len(minutes)//10)],
                            tickangle=45
                        )
                    )
                    
                else:
                    brick_size = (max(prices) - min(prices)) / 20
                    renko_bricks = []
                    last_close = opens[0] if opens else prices[0]
                    
                    for i in range(len(prices)):
                        close_price = prices[i]
                        diff = close_price - last_close
                        
                        if abs(diff) >= brick_size:
                            bricks_count = int(abs(diff) / brick_size)
                            for j in range(bricks_count):
                                if diff > 0:
                                    renko_bricks.append({
                                        'x': minutes[i],
                                        'open': last_close + (j * brick_size),
                                        'close': last_close + ((j + 1) * brick_size),
                                        'color': 'green'
                                    })
                                else:
                                    renko_bricks.append({
                                        'x': minutes[i],
                                        'open': last_close - (j * brick_size),
                                        'close': last_close - ((j + 1) * brick_size),
                                        'color': 'red'
                                    })
                            last_close = renko_bricks[-1]['close'] if renko_bricks else last_close
                    
                    if renko_bricks:
                        fig = go.Figure()
                        for brick in renko_bricks:
                            fig.add_trace(go.Scatter(
                                x=[brick['x'], brick['x']],
                                y=[brick['open'], brick['close']],
                                mode='lines',
                                line=dict(color=brick['color'], width=15),
                                showlegend=False
                            ))
                        
                        fig.update_layout(
                            title=f"{symbol} - {st.session_state.current_trading_date.strftime('%d %b %Y')} (Renko, Brick: ₹{brick_size:.2f})",
                            xaxis_title="Trading Minute",
                            yaxis_title="Price (₹)",
                            height=500,
                            xaxis=dict(
                                tickmode='array',
                                tickvals=minutes[::max(1, len(minutes)//10)],
                                ticktext=market_times[::max(1, len(minutes)//10)],
                                tickangle=45
                            )
                        )
                    else:
                        st.info("Not enough price movement for Renko chart")
                        fig = go.Figure()
                
                st.plotly_chart(fig, use_container_width=True)
                
                fig_vol = go.Figure()
                colors = ['green' if prices[i] >= opens[i] else 'red' for i in range(len(prices))]
                
                fig_vol.add_trace(go.Bar(
                    x=minutes,
                    y=volumes,
                    marker_color=colors,
                    name='Volume'
                ))
                
                fig_vol.update_layout(
                    title="Volume",
                    xaxis_title="Trading Minute",
                    yaxis_title="Volume",
                    height=300,
                    xaxis=dict(
                        tickmode='array',
                        tickvals=minutes[::max(1, len(minutes)//10)],
                        ticktext=market_times[::max(1, len(minutes)//10)],
                        tickangle=45
                    )
                )
                
                st.plotly_chart(fig_vol, use_container_width=True)
        
        if 'day_complete' in st.session_state and not st.session_state.day_complete:
            st.markdown("---")
            current_hour = 9 + st.session_state.current_minute // 60
            current_minute_time = st.session_state.current_minute % 60
            progress = st.session_state.current_minute / 389
            
            speed_status = "Auto" if st.session_state.auto_advance else "Manual"
            st.progress(
                progress, 
                text=f" **Market Time:** {current_hour}:{current_minute_time:02d} | "
                     f"**Progress:** {st.session_state.current_minute}/389 minutes | "
                     f"**Mode:** {speed_status}"
            )
        
        if st.session_state.trade_history:
            st.markdown("---")
            st.subheader("Recent Trades")
            
            for trade in reversed(st.session_state.trade_history[-8:]):
                if trade['type'] in ['BUY', 'PARTIAL_SELL']:
                    emoji = "🟢" if trade['type'] == 'BUY' else "🟡"
                    trade_type = "BUY" if trade['type'] == 'BUY' else "PARTIAL SELL"
                    st.write(f"{emoji} **{trade_type}** - {trade['date']} {trade['time']} - {trade['shares']} shares @ ₹{trade['price']:.2f}")
                else:
                    profit_loss = trade.get('profit_loss', 0)
                    profit_color = "🟢" if profit_loss >= 0 else "🔴"
                    trade_type = trade.get('type', 'SELL').replace('_', ' ').title()
                    st.write(f"{profit_color} **{trade_type}** - {trade['date']} {trade['time']} - {trade['shares']} shares @ ₹{trade['price']:.2f} "
                            f"(P&L: ₹{profit_loss:,.2f})")
        
        st.markdown("---")
        st.subheader("Trade Management")
        
        change_trade_cols = st.columns(3)
        
        with change_trade_cols[0]:
            if st.button("Start New Trade", use_container_width=True, type="primary"):
                shares_held = st.session_state.random_portfolio['shares']
                
                if shares_held > 0:
                    st.warning("You currently hold shares!")
                    option = st.radio(
                        "What would you like to do with your shares?",
                        ["Sell All Shares & Start New Trade", 
                         "Keep Shares & Start New Trade"],
                        key="new_trade_option"
                    )
                    
                    if option == "Sell All Shares & Start New Trade":
                        current_price = st.session_state.minute_data[st.session_state.current_minute]['close']
                        sale_value = shares_held * current_price
                        avg_price = st.session_state.random_portfolio['buy_price']
                        profit_loss = (current_price - avg_price) * shares_held
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("Confirm Sell & Start", type="primary"):
                                st.session_state.random_portfolio['cash'] += sale_value
                                st.session_state.trade_history.append({
                                    'type': 'NEW_TRADE_SELL',
                                    'date': st.session_state.current_trading_date.strftime('%Y-%m-%d'),
                                    'time': f"{9 + st.session_state.current_minute // 60}:{st.session_state.current_minute % 60:02d}",
                                    'price': current_price,
                                    'shares': shares_held,
                                    'total': sale_value,
                                    'profit_loss': profit_loss
                                })
                                
                                st.session_state.random_portfolio['shares'] = 0
                                st.session_state.random_portfolio['buy_price'] = 0.00
                                st.session_state.random_portfolio['buy_transactions'] = []
                                
                                st.session_state.random_stock_index = random.randint(0, len(all_indian_stocks) - 1)
                                st.session_state.trading_data = None
                                st.session_state.current_trading_date = None
                                st.session_state.trading_dates = []
                                st.session_state.current_minute = 0
                                st.session_state.day_complete = False
                                st.session_state.auto_advance = False
                                st.success("Sold all shares and starting new trade!")
                                st.rerun()
                        
                        with col2:
                            if st.button("Cancel"):
                                st.info("Action cancelled")
                    
                    else:
                        if st.button("Keep & Start New", type="primary"):
                            st.session_state.random_stock_index = random.randint(0, len(all_indian_stocks) - 1)
                            st.session_state.trading_data = None
                            st.session_state.current_trading_date = None
                            st.session_state.trading_dates = []
                            st.session_state.current_minute = 0
                            st.session_state.day_complete = False
                            st.session_state.auto_advance = False
                            st.success("Starting new trade (keeping shares)!")
                            st.rerun()
                
                else:
                    st.session_state.random_stock_index = random.randint(0, len(all_indian_stocks) - 1)
                    st.session_state.trading_data = None
                    st.session_state.current_trading_date = None
                    st.session_state.trading_dates = []
                    st.session_state.current_minute = 0
                    st.session_state.day_complete = False
                    st.session_state.auto_advance = False
                    st.success("Starting new trade...")
                    st.rerun()
        
        with change_trade_cols[1]:
            if st.button("Reset Portfolio", use_container_width=True):
                st.session_state.random_portfolio = {
                    'cash': 100000.00,
                    'shares': 0,
                    'buy_price': 0.00,
                    'buy_transactions': []
                }
                st.success("Portfolio reset to ₹1,00,000")
                st.rerun()
        
        with change_trade_cols[2]:
            if 'day_complete' in st.session_state and not st.session_state.day_complete:
                if st.button("Reset Day", use_container_width=True):
                    st.session_state.current_minute = 0
                    st.session_state.auto_advance = False
                    st.success("Trading day reset to start")
                    st.rerun()
        
        if 'day_complete' in st.session_state and st.session_state.day_complete:
            st.markdown("---")
            st.success("**Trading Day Complete!**")
            
            if hasattr(st.session_state, 'minute_data') and st.session_state.minute_data:
                prices = [d['close'] for d in st.session_state.minute_data]
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Opening Price", f"₹{prices[0]:.2f}")
                with col2:
                    st.metric("Closing Price", f"₹{prices[-1]:.2f}")
                with col3:
                    day_change = prices[-1] - prices[0]
                    day_change_pct = (day_change / prices[0]) * 100 if prices[0] > 0 else 0
                    st.metric("Day Change", f"₹{day_change:.2f}", f"{day_change_pct:.2f}%")
                with col4:
                    st.metric("High/Low", f"₹{max(prices):.2f}/₹{min(prices):.2f}")

# Footer
st.markdown("---")
st.markdown("©Learn2Trade - Educational Trading Platform")