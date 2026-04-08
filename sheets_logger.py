"""
sheets_logger.py
Handles all Google Sheets interactions for the Viana Data Checker.

LAYOUT:
  Col A = Site
  Col B = Zone
  Col C onwards = one column per date (e.g. "April 1, 2026", "April 2, 2026", ...)

Each Site+Zone pair gets exactly one row.
Each day's run fills in the next available date column.
"""

import time
import os
from datetime import datetime

import gspread
from gspread_formatting import CellFormat, Color, TextFormat, format_cell_range
from google.oauth2.service_account import Credentials

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
SHEET_ID         = "1tUOvu0Wntzmcj6fN8N5XWSbNwv2cI2JZSh5rUK8SgZg"
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Cell formats ──────────────────────────────────────────────────────────────
FMT_NO_DATA = CellFormat(
    backgroundColor=Color(1, 0.8, 0.8),
    textFormat=TextFormat(bold=True, foregroundColor=Color(0.6, 0, 0))
)
FMT_HAS_DATA = CellFormat(
    backgroundColor=Color(0.85, 1, 0.85),
    textFormat=TextFormat(bold=False, foregroundColor=Color(0, 0.4, 0))
)
FMT_HEADER = CellFormat(
    backgroundColor=Color(0.2, 0.2, 0.2),
    textFormat=TextFormat(bold=True, foregroundColor=Color(1, 1, 1))
)
FMT_DATE_HEADER = CellFormat(
    backgroundColor=Color(0.3, 0.3, 0.6),
    textFormat=TextFormat(bold=True, foregroundColor=Color(1, 1, 1))
)


def _col_letter(col_index: int) -> str:
    """Convert 1-based column index to letter(s). 1→A, 27→AA, etc."""
    result = ""
    while col_index > 0:
        col_index, remainder = divmod(col_index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _retry(fn, retries=4, delay=15):
    """
    Call fn(), retrying up to `retries` times on any exception.
    Waits `delay` seconds between attempts (handles 502 / rate-limit errors).
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < retries:
                print(f"    ⚠️  Sheets API error (attempt {attempt}/{retries}), "
                      f"retrying in {delay}s … ({e})")
                time.sleep(delay)
    raise last_err


class SheetsLogger:

    def __init__(self):
        creds      = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        client     = gspread.authorize(creds)
        self.sheet = client.open_by_key(SHEET_ID).sheet1

        # Build today's date string without leading zero (works on Windows too)
        now = datetime.now()
        self.today = f"{now.strftime('%B')} {now.day}, {now.year}"

        self._ensure_headers()
        self.date_col = self._get_or_create_date_column(self.today)
        self._row_cache = self._build_row_cache()

        # Buffer: list of (site, zone, has_data) accumulated per site
        # Flushed in one batch call to minimise API round-trips
        self._pending: list[tuple[str, str, bool]] = []

    # ── Header setup ──────────────────────────────────────────────────────────

    def _ensure_headers(self):
        row1 = _retry(lambda: self.sheet.row_values(1))
        if len(row1) < 2 or row1[0] != "Site" or row1[1] != "Zone":
            _retry(lambda: self.sheet.clear())
            _retry(lambda: self.sheet.update("A1:B1", [["Site", "Zone"]]))
            _retry(lambda: format_cell_range(self.sheet, "A1:B1", FMT_HEADER))

    # ── Date column ───────────────────────────────────────────────────────────

    def _get_or_create_date_column(self, date_str: str) -> int:
        row1 = _retry(lambda: self.sheet.row_values(1))
        for i, val in enumerate(row1):
            if val.strip() == date_str:
                return i + 1
        new_col    = len(row1) + 1
        col_letter = _col_letter(new_col)
        _retry(lambda: self.sheet.update(f"{col_letter}1", [[date_str]]))
        _retry(lambda: format_cell_range(self.sheet, f"{col_letter}1", FMT_DATE_HEADER))
        return new_col

    # ── Row cache ─────────────────────────────────────────────────────────────

    def _build_row_cache(self) -> dict:
        all_rows = _retry(lambda: self.sheet.get_all_values())
        cache = {}
        for i, row in enumerate(all_rows[1:], start=2):
            if len(row) >= 2 and (row[0].strip() or row[1].strip()):
                key = f"{row[0].strip()}||{row[1].strip()}"
                cache[key] = i
        return cache

    def _get_or_create_row(self, site: str, zone: str) -> int:
        key = f"{site}||{zone}"
        if key in self._row_cache:
            return self._row_cache[key]
        _retry(lambda: self.sheet.append_row([site, zone], value_input_option="RAW"))
        new_row = len(_retry(lambda: self.sheet.get_all_values()))
        self._row_cache[key] = new_row
        return new_row

    # ── Public API ────────────────────────────────────────────────────────────

    def queue_result(self, site: str, zone: str, has_data: bool):
        """
        Buffer one result. Call flush_site() after all zones for a site are done.
        Nothing is written to Sheets until flush_site() is called.
        """
        self._pending.append((site, zone, has_data))

    def flush_site(self):
        """
        Write all buffered results to Sheets in as few API calls as possible,
        then clear the buffer.

        Strategy:
          1. Ensure all Site+Zone rows exist (batch append if needed).
          2. Build a single batch_update payload for all cell values.
          3. Apply formatting in two bulk calls (one for No data, one for Has data).
        """
        if not self._pending:
            return

        col_letter = _col_letter(self.date_col)

        # ── Step 1: resolve row indices (creates missing rows) ────────────
        row_indices = []
        for site, zone, _ in self._pending:
            row_indices.append(self._get_or_create_row(site, zone))

        # ── Step 2: batch-write all values in one API call ────────────────
        cell_updates = []
        for (site, zone, has_data), row_idx in zip(self._pending, row_indices):
            output = "Has data" if has_data else "No data"
            cell_updates.append({
                "range": f"{col_letter}{row_idx}",
                "values": [[output]]
            })

        _retry(lambda: self.sheet.batch_update(
            cell_updates, value_input_option="RAW"
        ))

        # ── Step 3: bulk-format — two calls total (no_data + has_data) ────
        no_data_ranges  = []
        has_data_ranges = []
        for (_, __, has_data), row_idx in zip(self._pending, row_indices):
            addr = f"{col_letter}{row_idx}"
            if has_data:
                has_data_ranges.append(addr)
            else:
                no_data_ranges.append(addr)

        if no_data_ranges:
            combined = ",".join(no_data_ranges)
            _retry(lambda: format_cell_range(self.sheet, combined, FMT_NO_DATA))

        if has_data_ranges:
            combined = ",".join(has_data_ranges)
            _retry(lambda: format_cell_range(self.sheet, combined, FMT_HAS_DATA))

        self._pending.clear()

    def append_result(self, site: str, zone: str, has_data: bool):
        """Compatibility shim — just queues the result."""
        self.queue_result(site, zone, has_data)

    def append_site_separator(self, site: str):
        """No-op — not needed in matrix layout."""
        pass