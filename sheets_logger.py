"""
sheets_logger.py
Handles all Google Sheets interactions for the Viana Data Checker.

SETUP:
1. Place your service account credentials.json in the same folder as this file.
2. Set SHEET_ID below to your Google Sheet's ID.
3. Share the Google Sheet with the service account email (client_email in credentials.json).
"""

import gspread
from gspread_formatting import CellFormat, Color, TextFormat, format_cell_range
from google.oauth2.service_account import Credentials
from datetime import datetime
import os

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
SHEET_ID         = "1tUOvu0Wntzmcj6fN8N5XWSbNwv2cI2JZSh5rUK8SgZg"
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = ["Site", "Zone", "Date", "Output"]

# ── Cell formats ──────────────────────────────────────────────────────────────
FMT_RED_ROW = CellFormat(
    backgroundColor=Color(1, 0.8, 0.8),        # light red background
    textFormat=TextFormat(bold=True, foregroundColor=Color(0.6, 0, 0))  # dark red bold text
)
FMT_HEADER = CellFormat(
    backgroundColor=Color(0.2, 0.2, 0.2),      # dark grey background
    textFormat=TextFormat(bold=True, foregroundColor=Color(1, 1, 1))    # white bold text
)


class SheetsLogger:

    def __init__(self):
        creds        = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        client       = gspread.authorize(creds)
        self.sheet   = client.open_by_key(SHEET_ID).sheet1
        self._ensure_headers()

    def _ensure_headers(self):
        """Write + format header row if the sheet is empty."""
        first_row = self.sheet.row_values(1)
        if first_row != HEADERS:
            self.sheet.clear()
            self.sheet.append_row(HEADERS, value_input_option="RAW")
        # Always re-apply header formatting so it looks right after a clear
        format_cell_range(self.sheet, "A1:D1", FMT_HEADER)

    def _next_row(self):
        """Return the 1-based index of the next empty row."""
        return len(self.sheet.get_all_values()) + 1

    def append_result(self, site: str, zone: str, has_data: bool):
        """
        Append one result row. If output is 'No data', colour the entire row red.
        """
        date_str = datetime.now().strftime("%B %d, %Y")
        output   = "Has data" if has_data else "No data"

        self.sheet.append_row(
            [site, zone, date_str, output],
            value_input_option="RAW"
        )

        if not has_data:
            # Find the row we just wrote and colour it red
            row_idx  = self._next_row() - 1          # row we just appended
            cell_range = f"A{row_idx}:D{row_idx}"
            format_cell_range(self.sheet, cell_range, FMT_RED_ROW)

    def append_site_separator(self, site: str):
        """Insert a blank separator row between sites."""
        self.sheet.append_row(["", "", "", ""], value_input_option="RAW")