"""
sheets_logger.py
Handles all Google Sheets interactions for the Viana Data Checker.

SETUP:
1. Place your service account credentials.json in the same folder as this file.
2. Set SHEET_ID below to your Google Sheet's ID.
3. Share the Google Sheet with the service account email (client_email in credentials.json).
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import os

# ── CONFIGURATION ────────────────────────────────────────────────────────────
SHEET_ID         = "1tUOvu0Wntzmcj6fN8N5XWSbNwv2cI2JZSh5rUK8SgZg"   # ← paste your Sheet ID here
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Column headers (row 1)
HEADERS = ["Site", "Zone", "Date", "Output"]


class SheetsLogger:

    def __init__(self):
        creds  = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        self.sheet = client.open_by_key(SHEET_ID).sheet1
        self._ensure_headers()

    def _ensure_headers(self):
        """Write header row if the sheet is empty."""
        first_row = self.sheet.row_values(1)
        if first_row != HEADERS:
            self.sheet.clear()
            self.sheet.append_row(HEADERS, value_input_option="RAW")

    def append_result(self, site: str, zone: str, has_data: bool):
        """
        Append one result row.
        Called after each zone is checked.
        """
        date_str = datetime.now().strftime("%B %d, %Y")   # e.g. March 31, 2026
        output   = "Has data" if has_data else "No data"
        self.sheet.append_row(
            [site, zone, date_str, output],
            value_input_option="RAW"
        )

    def append_site_separator(self, site: str):
        """
        Insert a blank row then a bold-ish site header row between sites.
        Makes the sheet easier to read at a glance.
        """
        self.sheet.append_row(["", "", "", ""], value_input_option="RAW")