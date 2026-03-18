# -*- coding: utf-8 -*-
"""
Serial scale reader with:
- EMA smoothing for the main display
- numeric stability detection
- database write only when the value is stable
- configuration through environment variables
"""

import os
import re
import time
import threading
import logging
import tkinter as tk

import serial
import pyodbc


# ---------------- Configuration ----------------
SERIAL_PORT = os.getenv("SERIAL_PORT", "COM5")
BAUD_RATE = int(os.getenv("BAUD_RATE", "9600"))

DB_DSN = os.getenv("DB_DSN", "FMDNS")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "Production")

CURRENT_RECORD_ID = os.getenv("CURRENT_RECORD_ID", "M 1")

# Stability settings
STABLE_THRESHOLD = int(os.getenv("STABLE_THRESHOLD", "5"))
STABLE_TOLERANCE = float(os.getenv("STABLE_TOLERANCE", "0.01"))

# EMA smoothing
EMA_ALPHA = float(os.getenv("EMA_ALPHA", "0.25"))

# Display debounce
DISPLAY_CHANGE_THRESHOLD = float(os.getenv("DISPLAY_CHANGE_THRESHOLD", "0.005"))

LOG_FILE = os.getenv("LOG_FILE", "weight_scale.log")


# ---------------- Logging ----------------
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# ---------------- Global state ----------------
running = True
recent_values = []
last_committed_value = None
ema_value = None
last_displayed_value = None
last_stable_state = False

conn = None
cursor = None
root = None
text = None


# ---------------- Database ----------------
def connect_database():
    """Create database connection and cursor."""
    global conn, cursor
    try:
        conn = pyodbc.connect(
            f"DSN={DB_DSN};UID={DB_USER};PWD={DB_PASSWORD};DATABASE={DB_NAME}"
        )
        cursor = conn.cursor()
        logging.info("Database connection established.")
    except Exception as exc:
        logging.error(f"Database connection error: {exc}")
        raise SystemExit(1)


# ---------------- Utility functions ----------------
def parse_scale_line(line: str):
    """
    Extract (value_in_kg, display_text) from a serial line.
    Supports numeric value + optional unit: kg, g, lb, lbs.
    Converts everything to kg.
    """
    s = line.strip()
    if not s:
        return None, None

    match = re.search(r"([-+]?\d+(?:[.,]\d+)?)\s*(kg|g|lb|lbs)?\b", s, flags=re.I)
    if not match:
        return None, None

    num_text = match.group(1).replace(",", ".")
    unit = (match.group(2) or "kg").lower()

    try:
        value = float(num_text)
    except ValueError:
        return None, None

    if unit == "g":
        value_kg = value / 1000.0
    elif unit in ("lb", "lbs"):
        value_kg = value * 0.45359237
    else:
        value_kg = value

    display_text = f"{value_kg:.2f} kg"
    return value_kg, display_text


def values_stable(values, threshold, tolerance):
    """
    Return True if the last `threshold` values are all within ±tolerance
    of the most recent value.
    """
    if len(values) < threshold:
        return False

    reference = values[-1]
    window = values[-threshold:]
    return all(abs(v - reference) <= tolerance for v in window)


def update_database_weight(value_kg: float):
    """Write the formatted weight value to the database."""
    global cursor, conn

    try:
        value_text = f"{value_kg:.2f}"
        sql = 'UPDATE Greutate SET "WeightT" = ? WHERE ID = ?'
        cursor.execute(sql, (value_text, CURRENT_RECORD_ID))
        conn.commit()
        logging.info(
            f"Weight {value_text} kg written to DB for ID={CURRENT_RECORD_ID}."
        )
    except Exception as exc:
        logging.error(f"Database write error: {exc}")


# ---------------- GUI helpers ----------------
def update_big_display(display_text: str, stable: bool):
    """Update the large display text and color."""
    text.config(state=tk.NORMAL)
    text.delete(1.0, tk.END)
    text.insert(tk.END, display_text, "centered")
    text.config(fg=("chartreuse2" if stable else "gold1"))
    text.config(state=tk.DISABLED)


def stop_script():
    """Stop the application and close the GUI."""
    global running, conn
    running = False

    try:
        if conn is not None:
            conn.close()
            logging.info("Database connection closed.")
    except Exception as exc:
        logging.error(f"Error while closing database connection: {exc}")

    try:
        root.destroy()
    except Exception:
        pass


def reset_weight():
    """Reset internal smoothing/stability state and clear display."""
    global ema_value, recent_values, last_displayed_value, last_stable_state, last_committed_value

    ema_value = None
    recent_values.clear()
    last_displayed_value = None
    last_stable_state = False
    last_committed_value = None

    root.after(0, update_big_display, "---", False)
    logging.info("Weight state reset.")


# ---------------- Serial communication thread ----------------
def serial_communication():
    """
    Continuously:
    - read from serial
    - parse value in kg
    - apply EMA smoothing
    - detect stability
    - write to DB only when stable
    - update GUI with debounce
    """
    global running
    global recent_values
    global last_committed_value
    global ema_value
    global last_displayed_value
    global last_stable_state

    while running:
        try:
            with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
                logging.info(f"Connected to scale on {SERIAL_PORT}.")

                while running:
                    raw = ser.readline().decode("utf-8", errors="ignore")
                    if not raw:
                        continue

                    value_kg, _ = parse_scale_line(raw)
                    if value_kg is None:
                        continue

                    # Keep a recent history for stability detection
                    recent_values.append(value_kg)
                    if len(recent_values) > 100:
                        recent_values = recent_values[-50:]

                    # EMA smoothing for display
                    if ema_value is None:
                        ema_value = value_kg
                    else:
                        ema_value = EMA_ALPHA * value_kg + (1 - EMA_ALPHA) * ema_value

                    stable = values_stable(
                        recent_values,
                        STABLE_THRESHOLD,
                        STABLE_TOLERANCE
                    )

                    # Write to database only when stable and sufficiently different
                    if stable:
                        if (
                            last_committed_value is None
                            or abs(value_kg - last_committed_value) > (STABLE_TOLERANCE / 2)
                        ):
                            update_database_weight(value_kg)
                            last_committed_value = value_kg

                    # Update display only when needed
                    show_value = ema_value
                    need_update_display = False

                    if last_displayed_value is None:
                        need_update_display = True
                    elif abs(show_value - last_displayed_value) >= DISPLAY_CHANGE_THRESHOLD:
                        need_update_display = True
                    elif stable != last_stable_state:
                        need_update_display = True

                    if need_update_display:
                        display_text = f"{show_value:.2f} kg"
                        root.after(0, update_big_display, display_text, stable)
                        last_displayed_value = show_value
                        last_stable_state = stable

                    time.sleep(0.02)

        except serial.SerialException:
            logging.warning("Scale not connected. Retrying in 2 seconds...")
            time.sleep(2)
        except Exception as exc:
            logging.error(f"Serial read error: {exc}")
            time.sleep(2)


# ---------------- GUI setup ----------------
def build_gui():
    """Create and configure the Tkinter GUI."""
    global root, text

    root = tk.Tk()
    root.title("Weight Scale")
    root.configure(bg="royalblue3")

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    desired_width = screen_width // 3
    desired_height = screen_height // 7

    root.geometry(f"{desired_width}x{desired_height}+0+23")
    root.overrideredirect(True)
    root.wm_attributes("-topmost", 1)

    font_size = 60
    text = tk.Text(
        root,
        wrap=tk.WORD,
        font=("Arial Bold", font_size),
        bg="royalblue3",
        fg="royalblue3",
        borderwidth=0,
        highlightthickness=0
    )
    text.pack(fill=tk.BOTH, expand=True)
    text.tag_configure("centered", justify="center")

    button_frame = tk.Frame(root, bg="royalblue3")
    button_frame.pack(side=tk.BOTTOM, fill=tk.X)

    stop_button = tk.Button(
        button_frame,
        text="STOP",
        command=stop_script,
        bg="red",
        fg="white",
        font=("Arial", 14)
    )
    stop_button.pack(side=tk.LEFT, padx=5, pady=5)

    reset_button = tk.Button(
        button_frame,
        text="RESET",
        command=reset_weight,
        bg="orange",
        fg="white",
        font=("Arial", 14)
    )
    reset_button.pack(side=tk.LEFT, padx=5, pady=5)


# ---------------- Main ----------------
def main():
    connect_database()
    build_gui()

    serial_thread = threading.Thread(target=serial_communication, daemon=True)
    serial_thread.start()

    try:
        root.mainloop()
    except KeyboardInterrupt:
        logging.info("Stopped by KeyboardInterrupt.")
    finally:
        stop_script()


if __name__ == "__main__":
    main()