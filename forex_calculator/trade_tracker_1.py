import tkinter as tk
from tkinter import ttk, messagebox
from tkcalendar import DateEntry
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime, timedelta
import threading
import logging
from typing import Optional, Dict, List, Tuple
from ttkthemes import ThemedTk

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
INSTRUMENTS = {
    "XAUUSD":    {"pip": 0.01,   "contract": 100.0,   "quote_usd": True,  "desc":"Gold (pip=0.01)"},
    "BTCUSD":    {"pip": 1.0,    "contract": 1.0,     "quote_usd": True,  "desc":"Bitcoin (pip=1)"},
    "US30":      {"pip": 1.0,    "contract": 1.0,     "quote_usd": True,  "desc":"US30 index (point=1)"},
    "NASDAQ100": {"pip": 1.0,    "contract": 1.0,     "quote_usd": True,  "desc":"NASDAQ100 (point=1)"},
    "USDJPY":    {"pip": 0.01,   "contract": 100000.0,"quote_usd": False, "desc":"USD/JPY (pip=0.01, quote JPY)"},
    "GBPJPY":    {"pip": 0.01,   "contract": 100000.0,"quote_usd": False, "desc":"GBP/JPY (pip=0.01, quote JPY)"},
    "AUDUSD":    {"pip": 0.0001, "contract": 100000.0,"quote_usd": True,  "desc":"AUD/USD (pip=0.0001)"},
}

class TradeDB:
    """Database layer for trade storage and retrieval"""
    def __init__(self, db_path: str = 'trades.db'):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.create_tables()
        self._cache = {}
        self._cache_expiry = timedelta(minutes=5)
        
    def create_tables(self):
        """Initialize database tables"""
        with self.conn:
            self.conn.execute('''CREATE TABLE IF NOT EXISTS trades
                               (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                timestamp TEXT, instrument TEXT, 
                                direction TEXT, entry REAL, stop REAL,
                                target REAL, exit REAL, lots REAL,
                                contract_size REAL, pip_size REAL,
                                quote_to_usd REAL, pips_to_sl REAL,
                                usd_to_sl REAL, pips_to_tp REAL,
                                usd_to_tp REAL, realized_pips REAL,
                                realized_usd REAL, notes TEXT)''')
            
            self.conn.execute('''CREATE TABLE IF NOT EXISTS tags
                               (trade_id INTEGER, tag TEXT,
                                FOREIGN KEY(trade_id) REFERENCES trades(id))''')
    
    def add_trade(self, trade_data: Dict) -> int:
        """Add a new trade to the database"""
        with self.conn:
            cur = self.conn.cursor()
            cur.execute('''INSERT INTO trades VALUES 
                         (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       list(trade_data.values()))
            trade_id = cur.lastrowid
            self._clear_cache()
            return trade_id
    
    def get_trades(self, limit: int = 200, filters: Optional[Dict] = None) -> List[Dict]:
        """Retrieve trades with optional filters"""
        cache_key = f"trades_{limit}_{filters}"
        if cache_key in self._cache:
            if datetime.now() - self._cache[cache_key]['timestamp'] < self._cache_expiry:
                return self._cache[cache_key]['data']
        
        query = "SELECT * FROM trades"
        params = []
        
        if filters:
            conditions = []
            for k, v in filters.items():
                if v is not None:
                    conditions.append(f"{k} = ?")
                    params.append(v)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(query, params)
            columns = [col[0] for col in cur.description]
            results = [dict(zip(columns, row)) for row in cur.fetchall()]
            
        self._cache[cache_key] = {
            'timestamp': datetime.now(),
            'data': results
        }
        return results
    
    def delete_trade(self, trade_id: int) -> bool:
        """Delete a trade by ID"""
        with self.conn:
            self.conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
            self._clear_cache()
            return self.conn.total_changes > 0
    
    def _clear_cache(self):
        """Clear the cache"""
        self._cache = {}

class TradeCalculator:
    """Business logic for trade calculations"""
    @staticmethod
    def calc_pips(entry: float, price: float, pip_size: float, direction: str) -> float:
        """Calculate pips between entry and price"""
        return (price - entry) / pip_size if direction == "Long" else (entry - price) / pip_size
    
    @staticmethod
    def pip_value_usd(pip_size: float, contract_size: float, quote_usd: bool = True, 
                     quote_to_usd_rate: float = 1.0) -> float:
        """Calculate pip value in USD"""
        base = pip_size * contract_size
        return base if quote_usd else base / quote_to_usd_rate
    
    @staticmethod
    def usd_from_pips(pips: float, pip_value_per_lot: float, lots: float) -> float:
        """Calculate USD value from pips"""
        return pips * pip_value_per_lot * lots
    
    @staticmethod
    def price_from_usd_target(entry: float, direction: str, usd_target: float, 
                             pip_size: float, contract_size: float, quote_usd: bool,
                             quote_rate: float, lots: float) -> Optional[float]:
        """Calculate price target for specific USD amount"""
        pip_val = TradeCalculator.pip_value_usd(pip_size, contract_size, quote_usd, quote_rate)
        if pip_val == 0 or lots == 0:
            return None
        pips_needed = usd_target / (pip_val * lots)
        price_diff = pips_needed * pip_size
        return entry + price_diff if direction == "Long" else entry - price_diff

class TradeTrackerApp(ttk.Frame):
    """Main application GUI"""
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.db = TradeDB()
        self.calculator = TradeCalculator()
        self.setup_ui()
        self.load_trades_async()
        
    def setup_ui(self):
        """Initialize the user interface"""
        self.master.title("Advanced Trade Tracker")
        self.master.geometry("1200x800")
        self.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Configure styles
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.configure_styles()
        
        # Create main layout
        self.create_dashboard()
        self.create_input_panel()
        self.create_results_display()
        self.create_trade_table()
        self.create_chart_controls()
        
    def configure_styles(self):
        """Configure ttk styles"""
        self.style.configure("TFrame", background="#f5f5f5")
        self.style.configure("TLabel", background="#f5f5f5", font=("Segoe UI", 10))
        self.style.configure("TButton", font=("Segoe UI", 10), padding=5)
        self.style.configure("Card.TFrame", background="#ffffff", relief="raised", borderwidth=1)
        self.style.configure("Card.TLabel", background="#ffffff", font=("Segoe UI", 9))
        self.style.configure("Positive.TLabel", foreground="#4CAF50")
        self.style.configure("Negative.TLabel", foreground="#F44336")
        
    def create_dashboard(self):
        """Create the summary dashboard"""
        dashboard = ttk.Frame(self)
        dashboard.pack(fill="x", pady=(0, 10))
        
        # Dashboard cards
        self.total_profit_card = self.create_dashboard_card(dashboard, "Total Profit", "$0.00", 0)
        self.win_rate_card = self.create_dashboard_card(dashboard, "Win Rate", "0%", 1)
        self.avg_win_card = self.create_dashboard_card(dashboard, "Avg Win", "$0.00", 2)
        self.avg_loss_card = self.create_dashboard_card(dashboard, "Avg Loss", "$0.00", 3)
        
    def create_dashboard_card(self, parent, title: str, value: str, column: int) -> ttk.Frame:
        """Create a dashboard summary card"""
        card = ttk.Frame(parent, style="Card.TFrame")
        card.grid(row=0, column=column, padx=5, sticky="nsew")
        parent.grid_columnconfigure(column, weight=1)
        
        ttk.Label(card, text=title, style="Card.TLabel").pack(pady=(5,0))
        value_label = ttk.Label(card, text=value, font=("Segoe UI", 14, "bold"))
        value_label.pack(pady=(0,5))
        
        return value_label
    
    def create_input_panel(self):
        """Create the trade input panel"""
        input_frame = ttk.LabelFrame(self, text="Trade Input", padding=10)
        input_frame.pack(side="left", fill="y", padx=(0,10))
        
        # Instrument selection
        ttk.Label(input_frame, text="Instrument:").grid(row=0, column=0, sticky="w", pady=2)
        self.instrument_var = tk.StringVar(value="XAUUSD")
        inst_combo = ttk.Combobox(input_frame, values=list(INSTRUMENTS.keys()), 
                                 textvariable=self.instrument_var, state="readonly")
        inst_combo.grid(row=1, column=0, sticky="ew", pady=(0,10))
        inst_combo.bind("<<ComboboxSelected>>", lambda e: self.on_instrument_change())
        
        # Trade direction
        ttk.Label(input_frame, text="Direction:").grid(row=2, column=0, sticky="w", pady=2)
        self.direction_var = tk.StringVar(value="Long")
        ttk.Combobox(input_frame, values=["Long","Short"], 
                     textvariable=self.direction_var, state="readonly").grid(row=3, column=0, sticky="ew", pady=(0,10))
        
        # Price inputs
        price_fields = [
            ("Entry Price:", "entry_var"),
            ("Stop Loss Price:", "stop_var"),
            ("Take Profit Price:", "tp_var"),
            ("Exit Price:", "exit_var")
        ]
        
        for i, (label, var_name) in enumerate(price_fields, start=4):
            ttk.Label(input_frame, text=label).grid(row=i, column=0, sticky="w", pady=2)
            setattr(self, var_name, tk.StringVar())
            ttk.Entry(input_frame, textvariable=getattr(self, var_name)).grid(row=i+1, column=0, sticky="ew", pady=(0,10))
        
        # Size inputs
        ttk.Label(input_frame, text="Lots (size):").grid(row=10, column=0, sticky="w", pady=2)
        self.lots_var = tk.StringVar(value="1.0")
        ttk.Entry(input_frame, textvariable=self.lots_var).grid(row=11, column=0, sticky="ew", pady=(0,10))
        
        # Advanced inputs
        ttk.Label(input_frame, text="Contract size per lot:").grid(row=12, column=0, sticky="w", pady=2)
        self.contract_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.contract_var).grid(row=13, column=0, sticky="ew", pady=(0,10))
        
        ttk.Label(input_frame, text="Quote rate (e.g., USDJPY=150):").grid(row=14, column=0, sticky="w", pady=2)
        self.quote_rate_var = tk.StringVar()
        self.quote_entry = ttk.Entry(input_frame, textvariable=self.quote_rate_var)
        self.quote_entry.grid(row=15, column=0, sticky="ew", pady=(0,10))
        
        # Notes
        ttk.Label(input_frame, text="Notes:").grid(row=16, column=0, sticky="w", pady=2)
        self.notes_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.notes_var).grid(row=17, column=0, sticky="ew", pady=(0,10))
        
        # Action buttons
        btn_frame = ttk.Frame(input_frame)
        btn_frame.grid(row=18, column=0, pady=10, sticky="ew")
        
        ttk.Button(btn_frame, text="Calculate", command=self.calculate).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(btn_frame, text="Save Trade", command=self.save_trade).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(btn_frame, text="Clear", command=self.clear_inputs).pack(side="left", fill="x", expand=True, padx=2)
        
        self.on_instrument_change()
    
    def create_results_display(self):
        """Create the results display area"""
        results_frame = ttk.LabelFrame(self, text="Calculation Results", padding=10)
        results_frame.pack(fill="x", pady=(0,10))
        
        self.results_text = tk.Text(results_frame, height=8, wrap="word", font=("Consolas", 10))
        self.results_text.pack(fill="x", padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=self.results_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.results_text.configure(yscrollcommand=scrollbar.set)
    
    def create_trade_table(self):
        """Create the trade history table"""
        table_frame = ttk.LabelFrame(self, text="Trade History", padding=10)
        table_frame.pack(fill="both", expand=True, pady=(0,10))
        
        columns = ("ID", "Timestamp", "Instrument", "Direction", "Entry", "Stop", "Target", 
                  "Exit", "Lots", "P/L (USD)")
        
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=80, anchor="center")
        
        self.tree.column("Timestamp", width=150)
        self.tree.column("Instrument", width=80)
        self.tree.column("P/L (USD)", width=100)
        
        self.tree.pack(fill="both", expand=True, side="left")
        
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        # Context menu
        self.tree_menu = tk.Menu(self.master, tearoff=0)
        self.tree_menu.add_command(label="Edit Trade", command=self.edit_selected)
        self.tree_menu.add_command(label="Delete Trade", command=self.delete_selected)
        self.tree.bind("<Button-3>", self.show_tree_menu)
    
    def create_chart_controls(self):
        """Create chart controls"""
        chart_frame = ttk.Frame(self)
        chart_frame.pack(fill="x", pady=(0,5))
        
        ttk.Button(chart_frame, text="Profit Chart", command=self.show_profit_chart).pack(side="left", padx=2)
        ttk.Button(chart_frame, text="Instrument Distribution", command=self.show_instrument_chart).pack(side="left", padx=2)
        ttk.Button(chart_frame, text="Refresh", command=self.load_trades_async).pack(side="right", padx=2)
    
    def on_instrument_change(self):
        """Update UI when instrument changes"""
        inst = self.instrument_var.get()
        if inst not in INSTRUMENTS:
            return
        
        info = INSTRUMENTS[inst]
        if not self.contract_var.get():
            self.contract_var.set(str(info["contract"]))
        
        if info["quote_usd"]:
            self.quote_entry.configure(state="disabled")
            self.quote_rate_var.set("")
        else:
            self.quote_entry.configure(state="normal")
            if not self.quote_rate_var.get():
                self.quote_rate_var.set("150" if inst == "USDJPY" else "190" if inst == "GBPJPY" else "1")
    
    def calculate(self):
        """Calculate trade metrics"""
        try:
            # Validate inputs and get values
            inst = self.instrument_var.get()
            info = INSTRUMENTS[inst]
            
            entry = self._validate_float(self.entry_var.get(), "Entry price")
            stop = self._validate_float(self.stop_var.get(), "Stop loss", required=False)
            tp = self._validate_float(self.tp_var.get(), "Take profit", required=False)
            exit_price = self._validate_float(self.exit_var.get(), "Exit price", required=False)
            lots = self._validate_float(self.lots_var.get(), "Lots")
            contract_size = self._validate_float(self.contract_var.get(), "Contract size", default=info["contract"])
            quote_rate = self._validate_float(self.quote_rate_var.get(), "Quote rate", required=not info["quote_usd"], default=1.0)
            
            direction = self.direction_var.get()
            pip_size = info["pip"]
            quote_usd = info["quote_usd"]
            
            # Perform calculations
            pip_value = self.calculator.pip_value_usd(pip_size, contract_size, quote_usd, quote_rate)
            
            results = [
                f"Instrument: {inst} - {info['desc']}",
                f"Direction: {direction}, Lots: {lots}, Contract Size: {contract_size}",
                f"Pip Size: {pip_size}, Pip Value: ${pip_value:.4f}/lot"
            ]
            
            if stop is not None:
                pips_sl = self.calculator.calc_pips(entry, stop, pip_size, direction)
                usd_sl = self.calculator.usd_from_pips(pips_sl, pip_value, lots)
                results.extend([
                    f"\nStop Loss: {stop}",
                    f"Pips to SL: {pips_sl:.2f}",
                    f"USD at SL: ${usd_sl:.2f}"
                ])
            
            if tp is not None:
                pips_tp = self.calculator.calc_pips(entry, tp, pip_size, direction)
                usd_tp = self.calculator.usd_from_pips(pips_tp, pip_value, lots)
                results.extend([
                    f"\nTake Profit: {tp}",
                    f"Pips to TP: {pips_tp:.2f}",
                    f"USD at TP: ${usd_tp:.2f}"
                ])
            
            if exit_price is not None:
                pips_real = self.calculator.calc_pips(entry, exit_price, pip_size, direction)
                usd_real = self.calculator.usd_from_pips(pips_real, pip_value, lots)
                results.extend([
                    f"\nExit Price: {exit_price}",
                    f"Realized Pips: {pips_real:.2f}",
                    f"Realized USD: ${usd_real:.2f}"
                ])
            
            # Display results
            self.results_text.delete("1.0", tk.END)
            self.results_text.insert(tk.END, "\n".join(results))
            
        except ValueError as e:
            messagebox.showerror("Input Error", str(e))
    
    def save_trade(self):
        """Save trade to database"""
        try:
            # Validate inputs
            inst = self.instrument_var.get()
            info = INSTRUMENTS[inst]
            
            entry = self._validate_float(self.entry_var.get(), "Entry price")
            stop = self._validate_float(self.stop_var.get(), "Stop loss", required=False)
            tp = self._validate_float(self.tp_var.get(), "Take profit", required=False)
            exit_price = self._validate_float(self.exit_var.get(), "Exit price", required=False)
            lots = self._validate_float(self.lots_var.get(), "Lots")
            contract_size = self._validate_float(self.contract_var.get(), "Contract size", default=info["contract"])
            quote_rate = self._validate_float(self.quote_rate_var.get(), "Quote rate", required=not info["quote_usd"], default=1.0)
            
            direction = self.direction_var.get()
            pip_size = info["pip"]
            quote_usd = info["quote_usd"]
            notes = self.notes_var.get()
            
            # Calculate trade metrics
            pip_value = self.calculator.pip_value_usd(pip_size, contract_size, quote_usd, quote_rate)
            pips_sl = self.calculator.calc_pips(entry, stop, pip_size, direction) if stop else None
            usd_sl = self.calculator.usd_from_pips(pips_sl, pip_value, lots) if pips_sl else None
            pips_tp = self.calculator.calc_pips(entry, tp, pip_size, direction) if tp else None
            usd_tp = self.calculator.usd_from_pips(pips_tp, pip_value, lots) if pips_tp else None
            realized_pips = self.calculator.calc_pips(entry, exit_price, pip_size, direction) if exit_price else None
            realized_usd = self.calculator.usd_from_pips(realized_pips, pip_value, lots) if realized_pips else None
            
            # Prepare trade data
            trade_data = {
                "timestamp": datetime.now().isoformat(),
                "instrument": inst,
                "direction": direction,
                "entry": entry,
                "stop": stop,
                "target": tp,
                "exit": exit_price,
                "lots": lots,
                "contract_size": contract_size,
                "pip_size": pip_size,
                "quote_to_usd": quote_rate,
                "pips_to_sl": pips_sl,
                "usd_to_sl": usd_sl,
                "pips_to_tp": pips_tp,
                "usd_to_tp": usd_tp,
                "realized_pips": realized_pips,
                "realized_usd": realized_usd,
                "notes": notes
            }
            
            # Save to database
            trade_id = self.db.add_trade(trade_data)
            logging.info(f"Saved trade ID {trade_id}")
            
            messagebox.showinfo("Success", "Trade saved successfully")
            self.load_trades_async()
            self.clear_inputs()
            
        except ValueError as e:
            messagebox.showerror("Input Error", str(e))
    
    def load_trades_async(self):
        """Load trades in background thread"""
        def _load():
            try:
                trades = self.db.get_trades(limit=200)
                self.update_trade_table(trades)
                self.update_dashboard(trades)
            except Exception as e:
                logging.error(f"Error loading trades: {e}")
                messagebox.showerror("Error", f"Failed to load trades: {e}")
        
        threading.Thread(target=_load, daemon=True).start()
    
    def update_trade_table(self, trades: List[Dict]):
        """Update the trade table with new data"""
        self.tree.delete(*self.tree.get_children())
        
        for trade in trades:
            pl_usd = trade.get("realized_usd", 0)
            pl_text = f"${pl_usd:.2f}" if pl_usd is not None else ""
            
            self.tree.insert("", "end", values=(
                trade.get("id"),
                trade.get("timestamp"),
                trade.get("instrument"),
                trade.get("direction"),
                trade.get("entry"),
                trade.get("stop"),
                trade.get("target"),
                trade.get("exit"),
                trade.get("lots"),
                pl_text
            ))
    
    def update_dashboard(self, trades: List[Dict]):
        """Update dashboard with summary metrics"""
        if not trades:
            return
        
        df = pd.DataFrame(trades)
        df['realized_usd'] = pd.to_numeric(df['realized_usd'], errors='coerce').fillna(0)
        
        # Total profit
        total_profit = df['realized_usd'].sum()
        self.total_profit_card.config(
            text=f"${total_profit:.2f}",
            style="Positive.TLabel" if total_profit >= 0 else "Negative.TLabel"
        )
        
        # Win rate
        winning_trades = len(df[df['realized_usd'] > 0])
        total_trades = len(df)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        self.win_rate_card.config(text=f"{win_rate:.1%}")
        
        # Avg win/loss
        avg_win = df[df['realized_usd'] > 0]['realized_usd'].mean() or 0
        avg_loss = df[df['realized_usd'] < 0]['realized_usd'].mean() or 0
        self.avg_win_card.config(text=f"${avg_win:.2f}")
        self.avg_loss_card.config(text=f"${abs(avg_loss):.2f}", style="Negative.TLabel")
    
    def show_profit_chart(self):
        """Show profit/loss chart"""
        def _generate_chart():
            try:
                trades = self.db.get_trades(limit=50)
                if not trades:
                    messagebox.showwarning("No Data", "No trades to display")
                    return
                
                df = pd.DataFrame(trades)
                df['realized_usd'] = pd.to_numeric(df['realized_usd'], errors='coerce').fillna(0)
                df = df.sort_values('timestamp')
                
                plt.figure(figsize=(10, 5))
                bars = plt.bar(range(len(df)), df['realized_usd'], 
                              color=['#4CAF50' if x >= 0 else '#F44336' for x in df['realized_usd']])
                plt.axhline(0, color='black', linewidth=0.8)
                plt.title("Profit/Loss per Trade (Last 50 Trades)")
                plt.xlabel("Trade Sequence")
                plt.ylabel("USD")
                plt.tight_layout()
                plt.show()
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to generate chart: {e}")
        
        threading.Thread(target=_generate_chart, daemon=True).start()
    
    def show_instrument_chart(self):
        """Show instrument distribution chart"""
        def _generate_chart():
            try:
                trades = self.db.get_trades(limit=200)
                if not trades:
                    messagebox.showwarning("No Data", "No trades to display")
                    return
                
                df = pd.DataFrame(trades)
                instrument_counts = df['instrument'].value_counts()
                
                plt.figure(figsize=(6, 6))
                plt.pie(instrument_counts, labels=instrument_counts.index, autopct='%1.1f%%')
                plt.title("Trade Distribution by Instrument")
                plt.tight_layout()
                plt.show()
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to generate chart: {e}")
        
        threading.Thread(target=_generate_chart, daemon=True).start()
    
    def delete_selected(self):
        """Delete selected trades"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select trades to delete")
            return
        
        trade_ids = [self.tree.item(item)['values'][0] for item in selected]
        confirm = messagebox.askyesno(
            "Confirm Delete",
            f"Delete {len(trade_ids)} selected trades? This cannot be undone."
        )
        
        if confirm:
            try:
                for trade_id in trade_ids:
                    self.db.delete_trade(trade_id)
                messagebox.showinfo("Success", f"Deleted {len(trade_ids)} trades")
                self.load_trades_async()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete trades: {e}")
    
    def edit_selected(self):
        """Edit selected trade"""
        selected = self.tree.selection()
        if not selected or len(selected) > 1:
            messagebox.showwarning("Selection Error", "Please select exactly one trade to edit")
            return
        
        trade_id = self.tree.item(selected[0])['values'][0]
        messagebox.showinfo("Edit", f"Would edit trade ID {trade_id} (implementation omitted for brevity)")
    
    def show_tree_menu(self, event):
        """Show context menu for treeview"""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.tree_menu.post(event.x_root, event.y_root)
    
    def clear_inputs(self):
        """Clear all input fields"""
        self.entry_var.set("")
        self.stop_var.set("")
        self.tp_var.set("")
        self.exit_var.set("")
        self.lots_var.set("1.0")
        self.contract_var.set("")
        self.quote_rate_var.set("")
        self.notes_var.set("")
        self.results_text.delete("1.0", tk.END)
    
    def _validate_float(self, value: str, field_name: str, required: bool = True, 
                       default: Optional[float] = None) -> Optional[float]:
        """Validate and convert a string to float"""
        if not value:
            if required:
                raise ValueError(f"{field_name} is required")
            return default
        
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"Invalid value for {field_name}. Please enter a number.")

def main():
    """Main application entry point"""
    root = ThemedTk(theme="arc")
    app = TradeTrackerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()