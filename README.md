# Serial Weight Scale Reader

A Python application that reads weight data from a serial-connected scale, smooths the display using EMA, detects stable values, and writes the final stable weight to a database.

## Features

- Reads weight data from a serial port
- Supports `kg`, `g`, `lb`, and `lbs`
- Converts all values to kilograms
- Applies EMA smoothing for a more stable on-screen display
- Detects numeric stability over consecutive readings
- Writes to the database only when the weight is stable
- Simple Tkinter GUI with:
  - large live weight display
  - color indication for stable / unstable state
  - STOP and RESET buttons

## How it works

1. The application reads lines from the configured serial port.
2. It extracts the numeric weight and unit from each line.
3. The value is converted to kilograms.
4. An EMA filter smooths the displayed value.
5. The script checks whether the latest readings are stable within a tolerance window.
6. Once stable, the value is written to the database.
7. The GUI updates only when the displayed value changes enough, reducing flicker.

## Configuration

The application uses environment variables for configuration.

Copy `.env.example` to `.env` and adjust the values for your system.

## Environment variables

- `SERIAL_PORT` - serial port name, for example `COM5`
- `BAUD_RATE` - serial baud rate
- `DB_DSN` - ODBC DSN name
- `DB_USER` - database username
- `DB_PASSWORD` - database password
- `DB_NAME` - database name
- `CURRENT_RECORD_ID` - record ID to update in the database
- `STABLE_THRESHOLD` - number of consecutive readings required for stability
- `STABLE_TOLERANCE` - allowed variation in kg for stability detection
- `EMA_ALPHA` - EMA smoothing factor
- `DISPLAY_CHANGE_THRESHOLD` - minimum change required to refresh the display
- `LOG_FILE` - log file name

## Installation

```bash
pip install -r requirements.txt