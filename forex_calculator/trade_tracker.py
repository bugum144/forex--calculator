import os
import csv
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt

CSV_FILE = "trades.csv"

INSTRUMENTS = {
    "XAUUSD":    {"pip": 0.01,   "contract": 100.0,   "quote_usd": True,  "desc":"Gold (pip=0.01)"},
    "BTCUSD":    {"pip": 1.0,    "contract": 1.0,     "quote_usd": True,  "desc":"Bitcoin (pip=1)"},
    "US30":      {"pip": 1.0,    "contract": 1.0,     "quote_usd": True,  "desc":"US30 index (point=1)"},
    "NASDAQ100": {"pip": 1.0,    "contract": 1.0,     "quote_usd": True,  "desc":"NASDAQ100 (point=1)"},
    "USDJPY":    {"pip": 0.01,   "contract": 100000.0,"quote_usd": False, "desc":"USD/JPY (pip=0.01, quote JPY)"},
    "GBPJPY":    {"pip": 0.01,   "contract": 100000.0,"quote_usd": False, "desc":"GBP/JPY (pip=0.01, quote JPY)"},
    "AUDUSD":    {"pip": 0.0001, "contract": 100000.0,"quote_usd": True,  "desc":"AUD/USD (pip=0.0001)"},
}

def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp","instrument","direction","entry","stop","target","exit","lots",
                "contract_size","pip_size","quote_to_usd","pips_to_sl","usd_to_sl",
                "pips_to_tp","usd_to_tp","realized_pips","realized_usd","notes"
            ])
ensure_csv()

def calc_pips(entry, price, pip_size, direction):
    try:
        entry = float(entry); price = float(price); pip_size = float(pip_size)
    except Exception:
        return None
    return (price - entry) / pip_size if direction == "Long" else (entry - price) / pip_size

def pip_value_usd(pip_size, contract_size, quote_usd=True, quote_to_usd_rate=1.0):
    base = float(pip_size) * float(contract_size)
    if quote_usd:
        return base
    try:
        qr = float(quote_to_usd_rate)
        return base if qr == 0 else base / qr
    except Exception:
        return base

def usd_from_pips(pips, pip_value_per_lot, lots):
    return pips * pip_value_per_lot * lots

def price_from_usd_target(entry, direction, usd_target, pip_size, contract_size, quote_usd, quote_rate, lots):
    pip_val = pip_value_usd(pip_size, contract_size, quote_usd, quote_rate)
    if pip_val == 0 or lots == 0:
        return None
    pips_needed = usd_target / (pip_val * lots)
    price_diff = pips_needed * pip_size
    return entry + price_diff if direction == "Long" else entry - price_diff

def parse_money_field(val):
    if not val: return None
    v = str(val).strip()
    if v.startswith("$"):
        try:
            return float(v.replace("$",""))
        except:
            return None
    return None

class TradeTrackerApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        master.title("Forex/Markets Trade Calculator & Tracker")
        master.geometry("980x620")
        self.pack(fill="both", expand=True, padx=8, pady=8)
        self.create_styles()
        self.create_widgets()
        self.load_trades()

    def create_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f0f4fc")
        style.configure("TLabel", background="#f0f4fc", font=("Segoe UI", 11))
        style.configure("TButton", font=("Segoe UI", 11, "bold"), padding=6)
        style.map("TButton",
            background=[("active", "#4a90e2"), ("!active", "#357ab7")],
            foreground=[("active", "#ffffff"), ("!active", "#ffffff")]
        )
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=28, fieldbackground="#eaf1fb", background="#eaf1fb")
        style.configure("Treeview.Heading", font=("Segoe UI", 11, "bold"), background="#357ab7", foreground="#ffffff")
        style.configure("TLabelframe", background="#eaf1fb", font=("Segoe UI", 12, "bold"))
        style.configure("TLabelframe.Label", background="#357ab7", foreground="#ffffff", font=("Segoe UI", 12, "bold"))

    def create_widgets(self):
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="ns", padx=(0,10), pady=4)
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        # Instrument
        ttk.Label(left, text="Instrument:").grid(row=0, column=0, sticky="w", pady=(0,2))
        self.instrument_var = tk.StringVar(value="XAUUSD")
        inst_combo = ttk.Combobox(left, values=list(INSTRUMENTS.keys()), textvariable=self.instrument_var, state="readonly")
        inst_combo.grid(row=1, column=0, sticky="ew", pady=(0,6))
        inst_combo.bind("<<ComboboxSelected>>", lambda e: self.on_instrument_change())
        inst_combo.bind("<<ComboboxSelected>>", lambda _: self.on_instrument_change())
        # Direction
        ttk.Label(left, text="Direction:").grid(row=2, column=0, sticky="w", pady=(0,2))
        self.direction_var = tk.StringVar(value="Long")
        dir_combo = ttk.Combobox(left, values=["Long","Short"], textvariable=self.direction_var, state="readonly")
        dir_combo.grid(row=3, column=0, sticky="ew", pady=(0,6))

        # Entry / Stop / Target / Exit
        ttk.Label(left, text="Entry Price:").grid(row=4, column=0, sticky="w", pady=(0,2))
        self.entry_var = tk.StringVar()
        ttk.Entry(left, textvariable=self.entry_var).grid(row=5, column=0, sticky="ew", pady=(0,6))

        ttk.Label(left, text="Stop Loss Price:").grid(row=6, column=0, sticky="w", pady=(0,2))
        self.stop_var = tk.StringVar()
        ttk.Entry(left, textvariable=self.stop_var).grid(row=7, column=0, sticky="ew", pady=(0,6))

        ttk.Label(left, text="Take Profit Price (optional):").grid(row=8, column=0, sticky="w", pady=(0,2))
        self.tp_var = tk.StringVar()
        ttk.Entry(left, textvariable=self.tp_var).grid(row=9, column=0, sticky="ew", pady=(0,6))

        ttk.Label(left, text="Exit Price (to record realized P/L, optional):").grid(row=10, column=0, sticky="w", pady=(0,2))
        self.exit_var = tk.StringVar()
        ttk.Entry(left, textvariable=self.exit_var).grid(row=11, column=0, sticky="ew", pady=(0,6))

        # Lots
        ttk.Label(left, text="Lots (size):").grid(row=12, column=0, sticky="w", pady=(0,2))
        self.lots_var = tk.StringVar(value="1.0")
        ttk.Entry(left, textvariable=self.lots_var).grid(row=13, column=0, sticky="ew", pady=(0,6))

        # Contract size override
        ttk.Label(left, text="Contract size per lot (override):").grid(row=14, column=0, sticky="w", pady=(0,2))
        self.contract_var = tk.StringVar(value="")
        ttk.Entry(left, textvariable=self.contract_var).grid(row=15, column=0, sticky="ew", pady=(0,2))
        ttk.Label(left, text="(leave empty to use instrument default)").grid(row=16, column=0, sticky="w", pady=(0,6))

        # Quote to USD rate (for JPY-quoted instruments)
        ttk.Label(left, text="Quote rate (e.g., USDJPY=150):").grid(row=17, column=0, sticky="w", pady=(0,2))
        self.quote_rate_var = tk.StringVar(value="")
        self.quote_entry = ttk.Entry(left, textvariable=self.quote_rate_var)
        self.quote_entry.grid(row=18, column=0, sticky="ew", pady=(0,2))
        ttk.Label(left, text="(needed for JPY quote conversion; leave if instrument quote is USD)").grid(row=19, column=0, sticky="w", pady=(0,6))

        # Notes
        ttk.Label(left, text="Notes:").grid(row=20, column=0, sticky="w", pady=(0,2))
        self.notes_var = tk.StringVar()
        ttk.Entry(left, textvariable=self.notes_var).grid(row=21, column=0, sticky="ew", pady=(0,6))

        # Buttons
        btn_frame = ttk.Frame(left)
        btn_frame.grid(row=22, column=0, pady=10, sticky="ew")
        btn_frame.grid_columnconfigure((0,1,2), weight=1)
        self.create_button(btn_frame, "Calculate", self.calculate, 0)
        self.create_button(btn_frame, "Save Trade", self.save_trade, 1)
        self.create_button(btn_frame, "Clear Inputs", self.clear_inputs, 2)

        # RHS: results, table, charts
        results_frame = ttk.LabelFrame(right, text="Calculation Results")
        results_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        results_scrollbar = ttk.Scrollbar(results_frame, orient="vertical")
        self.results_text = tk.Text(results_frame, height=9, wrap="word", bg="#eaf1fb", font=("Segoe UI", 11), yscrollcommand=results_scrollbar.set)
        self.results_text.pack(fill="x", padx=4, pady=4, side="left")
        results_scrollbar.config(command=self.results_text.yview)
        results_scrollbar.pack(fill="y", side="right")

        table_frame = ttk.LabelFrame(right, text="Saved Trades")
        table_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        right.grid_rowconfigure(1, weight=1)

        columns = ("timestamp","instrument","dir","entry","stop","target","exit","lots","realized_usd")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", style="Treeview")
        for c in columns:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=100, anchor="center")
        self.tree.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscroll=scrollbar.set)

        chart_frame = ttk.Frame(right)
        chart_frame.grid(row=2, column=0, sticky="ew", padx=4, pady=6)
        chart_frame.grid_columnconfigure((0,1,2,3), weight=1)
        self.create_button(chart_frame, "Show Profit Bar Chart", self.show_bar_chart, 0)
        self.create_button(chart_frame, "Show Pie Chart by Instrument", self.show_pie_chart, 1)
        self.create_button(chart_frame, "Reload Table", self.load_trades, 2)
        self.create_button(chart_frame, "Delete Selected", self.delete_selected, 3)

        self.on_instrument_change()

    def create_button(self, parent, text, command, col):
        btn = ttk.Button(parent, text=text, command=command)
        btn.grid(row=0, column=col, sticky="ew", padx=2)
        btn.bind("<Enter>", lambda e: btn.state(["active"]))
        btn.bind("<Enter>", lambda _: btn.state(["active"]))
        btn.bind("<Leave>", lambda _: btn.state(["!active"]))
    def on_instrument_change(self):
        inst = self.instrument_var.get()
        if inst not in INSTRUMENTS:
            return
        info = INSTRUMENTS[inst]
        default_contract = str(info["contract"])
        if not self.contract_var.get():
            self.contract_var.set(default_contract)
        if info["quote_usd"]:
            self.quote_entry.configure(state="disabled")
            self.quote_rate_var.set("")
        else:
            self.quote_entry.configure(state="normal")
            if not self.quote_rate_var.get():
                self.quote_rate_var.set("150" if inst == "USDJPY" else "190" if inst == "GBPJPY" else "1")

    def calculate(self):
        inst = self.instrument_var.get()
        info = INSTRUMENTS[inst]
        try:
            contract_override = float(self.contract_var.get()) if self.contract_var.get() else info["contract"]
        except Exception:
            messagebox.showerror("Input error", "Invalid contract size")
            return
        pip_size = info["pip"]
        entry = self._float_or_error(self.entry_var.get(), "Entry")
        if entry is None: return
        stop = self._float_or_none(self.stop_var.get())
        tp = self._float_or_none(self.tp_var.get())
        exit_price = self._float_or_none(self.exit_var.get())
        lots = self._float_or_error(self.lots_var.get(), "Lots")
        if lots is None: return
        quote_rate = self._float_or_none(self.quote_rate_var.get()) or 1.0
        pip_val = pip_value_usd(pip_size, contract_override, info["quote_usd"], quote_rate)
        direction = self.direction_var.get()
        results = [
            f"Instrument: {inst} — {info['desc']}",
            f"Entry: {entry}, Direction: {direction}, Lots: {lots}",
            f"Pip size: {pip_size}, Contract per lot: {contract_override}",
            f"Estimated pip value per lot (USD): {pip_val:.6f}"
        ]
        if stop is not None:
            pips_sl = calc_pips(entry, stop, pip_size, direction)
            usd_sl = usd_from_pips(pips_sl, pip_val, lots)
            results.append(f"Pips to Stop Loss: {pips_sl:.2f}")
            results.append(f"USD at Stop Loss (for {lots} lots): {usd_sl:.2f}")
        else:
            results.append("Stop Loss: (not provided)")
        if tp is not None:
            pips_tp = calc_pips(entry, tp, pip_size, direction)
            usd_tp = usd_from_pips(pips_tp, pip_val, lots)
            results.append(f"Pips to Take Profit: {pips_tp:.2f}")
            results.append(f"USD at Take Profit (for {lots} lots): {usd_tp:.2f}")
        else:
            results.append("Take Profit: (not provided)")
        if exit_price is not None:
            pips_real = calc_pips(entry, exit_price, pip_size, direction)
            usd_real = usd_from_pips(pips_real, pip_val, lots)
            results.append(f"Exit: {exit_price}")
            results.append(f"Realized pips: {pips_real:.2f}")
            results.append(f"Realized USD: {usd_real:.2f}")
        else:
            results.append("Exit: (not provided)")
        desired_usd_tp = parse_money_field(self.tp_var.get())
        desired_usd_sl = parse_money_field(self.stop_var.get())
        if desired_usd_tp is not None:
            target_price = price_from_usd_target(entry, direction, desired_usd_tp, pip_size, contract_override, info["quote_usd"], quote_rate, lots)
            results.append(f"Price target for USD profit ${desired_usd_tp:.2f}: {target_price:.6f}")
        if desired_usd_sl is not None:
            target_price = price_from_usd_target(entry, direction, desired_usd_sl, pip_size, contract_override, info["quote_usd"], quote_rate, lots)
            results.append(f"Price target for USD loss ${desired_usd_sl:.2f}: {target_price:.6f}")
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert(tk.END, "\n".join(results))

    def _float_or_error(self, v, name):
        try:
            return float(v)
        except Exception:
            messagebox.showerror("Input error", f"Invalid value for {name}. Please enter a number.")
            return None

    def _float_or_none(self, v):
        if not v:
            return None
        try:
            return float(v)
        except:
            return None

    def save_trade(self):
        inst = self.instrument_var.get(); info = INSTRUMENTS[inst]
        entry = self._float_or_error(self.entry_var.get(), "Entry")
        if entry is None: return
        stop = self._float_or_none(self.stop_var.get())
        tp = self._float_or_none(self.tp_var.get())
        exit_price = self._float_or_none(self.exit_var.get())
        lots = self._float_or_error(self.lots_var.get(), "Lots")
        if lots is None: return
        contract_override = float(self.contract_var.get()) if self.contract_var.get() else info["contract"]
        pip_size = info["pip"]
        quote_rate = self._float_or_none(self.quote_rate_var.get()) or 1.0
        direction = self.direction_var.get()
        notes = self.notes_var.get()
        pip_val = pip_value_usd(pip_size, contract_override, info["quote_usd"], quote_rate)
        pips_to_sl = calc_pips(entry, stop, pip_size, direction) if stop is not None else None
        usd_to_sl = usd_from_pips(pips_to_sl, pip_val, lots) if pips_to_sl is not None else None
        pips_to_tp = calc_pips(entry, tp, pip_size, direction) if tp is not None else None
        usd_to_tp = usd_from_pips(pips_to_tp, pip_val, lots) if pips_to_tp is not None else None
        realized_pips = calc_pips(entry, exit_price, pip_size, direction) if exit_price is not None else None
        realized_usd = usd_from_pips(realized_pips, pip_val, lots) if realized_pips is not None else None
        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "timestamp": datetime.now(datetime.timezone.utc).isoformat(),
            "direction": direction,
            "entry": entry,
            "stop": stop if stop is not None else "",
            "target": tp if tp is not None else "",
            "exit": exit_price if exit_price is not None else "",
            "lots": lots,
            "contract_size": contract_override,
            "pip_size": pip_size,
            "quote_to_usd": quote_rate,
            "pips_to_sl": round(pips_to_sl,4) if pips_to_sl is not None else "",
            "usd_to_sl": round(usd_to_sl,4) if usd_to_sl is not None else "",
            "pips_to_tp": round(pips_to_tp,4) if pips_to_tp is not None else "",
            "usd_to_tp": round(usd_to_tp,4) if usd_to_tp is not None else "",
            "realized_pips": round(realized_pips,4) if realized_pips is not None else "",
            "realized_usd": round(realized_usd,4) if realized_usd is not None else "",
            "notes": notes
        }
        fieldnames = ["timestamp","instrument","direction","entry","stop","target","exit","lots",
                      "contract_size","pip_size","quote_to_usd","pips_to_sl","usd_to_sl",
                      "pips_to_tp","usd_to_tp","realized_pips","realized_usd","notes"]
        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writerow(row)
        messagebox.showinfo("Saved", "Trade saved to trades.csv")
        self.load_trades()

    def load_trades(self):
        self.tree.delete(*self.tree.get_children())
        try:
            df = pd.read_csv(CSV_FILE)
            for _, r in df.tail(200).iterrows():
                self.tree.insert("", "end", values=(
                    r.get("timestamp",""), r.get("instrument",""), r.get("direction",""),
                    r.get("entry",""), r.get("stop",""), r.get("target",""), r.get("exit",""),
                    r.get("lots",""), r.get("realized_usd","")
                ))
        except Exception as e:
            print("Failed to load trades:", e)

    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        confirm = messagebox.askyesno("Delete", "Delete selected trades from CSV? This is permanent.")
        if not confirm:
            return
        timestamps = [self.tree.item(s)["values"][0] for s in sel]
        try:
            df = pd.read_csv(CSV_FILE)
            df = df[~df["timestamp"].isin(timestamps)]
            df.to_csv(CSV_FILE, index=False)
            messagebox.showinfo("Deleted", "Selected trades deleted.")
            self.load_trades()
        except Exception as e:
            messagebox.showerror("Error", f"Could not delete: {e}")

    def show_bar_chart(self):
        try:
            df = pd.read_csv(CSV_FILE)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read trades.csv: {e}")
            return
        if df.empty:
            messagebox.showwarning("No data", "No trades to plot.")
            return
        df["realized_usd"] = pd.to_numeric(df["realized_usd"], errors="coerce").fillna(0)
        sub = df.tail(min(30, len(df)))
        x = range(len(sub))
        plt.figure(figsize=(10,5))
        bars = plt.bar(x, sub["realized_usd"], tick_label=[f"{i+1}" for i in range(len(sub))])
        plt.axhline(0, color="black", linewidth=0.8)
        plt.title("Realized USD per trade (last %d)"%len(sub))
        plt.xlabel("Trade (most recent right)")
        plt.ylabel("Realized USD")
        for b, val in zip(bars, sub["realized_usd"]):
            b.set_color("#4caf50" if val >= 0 else "#e74c3c")
        plt.tight_layout()
        plt.show()

    def show_pie_chart(self):
        try:
            df = pd.read_csv(CSV_FILE)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read trades.csv: {e}")
            return
        if df.empty:
            messagebox.showwarning("No data", "No trades to plot.")
            return
        df["realized_usd"] = pd.to_numeric(df["realized_usd"], errors="coerce").fillna(0)
        grouped = df.groupby("instrument")["realized_usd"].sum().sort_values(ascending=False)
        if grouped.sum() == 0:
            grouped = df["instrument"].value_counts()
            plt.figure(figsize=(6,6))
            plt.pie(grouped, labels=grouped.index, autopct="%1.1f%%")
            plt.title("Trade count by instrument")
            plt.show()
            return
        plt.figure(figsize=(6,6))
        plt.pie(grouped, labels=grouped.index, autopct="%1.1f%%")
        plt.title("Realized USD share by instrument")
        plt.show()

    def clear_inputs(self):
        self.entry_var.set("")
        self.stop_var.set("")
        self.tp_var.set("")
        self.exit_var.set("")
        self.lots_var.set("1.0")
        self.contract_var.set("")
        self.quote_rate_var.set("")
        self.notes_var.set("")
        self.results_text.delete("1.0", tk.END)

def main():
    root = tk.Tk()
    app = TradeTrackerApp(root)
    TradeTrackerApp(root)
    root.mainloop()
if __name__ == "__main__":
    main()
