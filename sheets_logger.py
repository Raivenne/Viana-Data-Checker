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
from google.oauth2.service_account import Credentials

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
SHEET_ID         = "1tUOvu0Wntzmcj6fN8N5XWSbNwv2cI2JZSh5rUK8SgZg"
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _col_letter(col_index: int) -> str:
    """Convert 1-based column index to letter(s). 1→A, 27→AA, etc."""
    result = ""
    while col_index > 0:
        col_index, remainder = divmod(col_index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _col_letter_to_index(col_str: str) -> int:
    """Convert column letter(s) to 0-based index. A→0, B→1, AA→26, etc."""
    idx = 0
    for ch in col_str.upper():
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx - 1


def _parse_cell(cell_addr: str):
    """Parse 'C5' into (row_0based=4, col_0based=2)."""
    col_str, row_str = "", ""
    for ch in cell_addr:
        if ch.isalpha():
            col_str += ch
        else:
            row_str += ch
    return int(row_str) - 1, _col_letter_to_index(col_str)


def _retry(fn, retries=4, delay=15):
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

    # ── Colours (RGB 0-1 scale) ───────────────────────────────────────────────
    _RED_BG   = {"red": 1.0,  "green": 0.8,  "blue": 0.8}   # light red
    _RED_FG   = {"red": 0.6,  "green": 0.0,  "blue": 0.0}   # dark red
    _WHITE_BG = {"red": 1.0,  "green": 1.0,  "blue": 1.0}   # white
    _BLACK_FG = {"red": 0.0,  "green": 0.0,  "blue": 0.0}   # black
    _DGREY_BG = {"red": 0.2,  "green": 0.2,  "blue": 0.2}   # dark grey (header)
    _BLUE_BG  = {"red": 0.3,  "green": 0.3,  "blue": 0.6}   # blue (date header)

    def __init__(self):
        creds           = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        self.client     = gspread.authorize(creds)
        self.spreadsheet= self.client.open_by_key(SHEET_ID)
        self.sheet      = self.spreadsheet.sheet1
        self.sheet_id   = self.sheet.id

        now = datetime.now()
        self.today = f"{now.strftime('%B')} {now.day}, {now.year}"

        self._ensure_headers()
        self.date_col   = self._get_or_create_date_column(self.today)
        self._row_cache = self._build_row_cache()
        self._pending: list[tuple[str, str, bool]] = []

    # ── Low-level: single batchUpdate call ───────────────────────────────────

    def _batch_update(self, requests: list):
        """Send a batchUpdate with retry."""
        _retry(lambda: self.spreadsheet.batch_update({"requests": requests}))

    # ── Cell format helpers (all via raw API — no gspread_formatting) ─────────

    def _fmt_request(self, row_0: int, col_0: int, bg: dict, fg: dict, bold: bool) -> dict:
        """Build a single repeatCell format request."""
        return {
            "repeatCell": {
                "range": {
                    "sheetId":          self.sheet_id,
                    "startRowIndex":    row_0,
                    "endRowIndex":      row_0 + 1,
                    "startColumnIndex": col_0,
                    "endColumnIndex":   col_0 + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": bg,
                        "textFormat": {
                            "foregroundColor": fg,
                            "bold": bold,
                        }
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)"
            }
        }

    def _note_request(self, row_0: int, col_0: int, note: str) -> dict:
        """Build a single updateCells note request."""
        return {
            "updateCells": {
                "rows": [{"values": [{"note": note}]}],
                "fields": "note",
                "range": {
                    "sheetId":          self.sheet_id,
                    "startRowIndex":    row_0,
                    "endRowIndex":      row_0 + 1,
                    "startColumnIndex": col_0,
                    "endColumnIndex":   col_0 + 1,
                }
            }
        }

    def _header_fmt_request(self, row_0: int, col_0: int, bg: dict) -> dict:
        """Bold white text on coloured background for headers."""
        return self._fmt_request(
            row_0, col_0, bg,
            fg={"red": 1.0, "green": 1.0, "blue": 1.0},
            bold=True
        )

    # ── Header setup ──────────────────────────────────────────────────────────

    def _ensure_headers(self):
        row1 = _retry(lambda: self.sheet.row_values(1))
        if len(row1) < 2 or row1[0] != "Site" or row1[1] != "Zone":
            _retry(lambda: self.sheet.clear())
            _retry(lambda: self.sheet.update("A1:B1", [["Site", "Zone"]]))
        # Always re-apply header formatting
        self._batch_update([
            self._header_fmt_request(0, 0, self._DGREY_BG),
            self._header_fmt_request(0, 1, self._DGREY_BG),
        ])

    # ── Date column ───────────────────────────────────────────────────────────

    def _get_or_create_date_column(self, date_str: str) -> int:
        row1 = _retry(lambda: self.sheet.row_values(1))
        for i, val in enumerate(row1):
            if val.strip() == date_str:
                return i + 1
        new_col    = len(row1) + 1
        col_letter = _col_letter(new_col)
        _retry(lambda: self.sheet.update(f"{col_letter}1", [[date_str]]))
        self._batch_update([self._header_fmt_request(0, new_col - 1, self._BLUE_BG)])
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
        self._pending.append((site, zone, has_data))

    def flush_site(self):
        """
        Write all buffered results in as few API calls as possible:
          1. Resolve / create row for each Site+Zone.
          2. batch_update all cell values in one call.
          3. One batchUpdate with all format + note requests combined.
        """
        if not self._pending:
            return

        col_letter = _col_letter(self.date_col)
        col_0      = self.date_col - 1   # 0-based

        # ── Step 1: resolve rows ──────────────────────────────────────────
        row_indices = [self._get_or_create_row(s, z) for s, z, _ in self._pending]

        # ── Step 2: write values (one batch call) ─────────────────────────
        cell_updates = [
            {
                "range":  f"{col_letter}{row_idx}",
                "values": [["Has data" if has_data else "No data"]]
            }
            for (_, __, has_data), row_idx in zip(self._pending, row_indices)
        ]
        _retry(lambda: self.sheet.batch_update(cell_updates, value_input_option="RAW"))

        # ── Step 3: format + notes in ONE batchUpdate call ────────────────
        requests = []
        note_text = (
            f"⚠️ No data detected on {self.today}.\n"
            f"Please check this zone in the Viana Portal."
        )

        for (site, zone, has_data), row_idx in zip(self._pending, row_indices):
            row_0 = row_idx - 1   # 0-based

            if has_data:
                # Plain: white background, black text, not bold
                requests.append(self._fmt_request(
                    row_0, col_0, self._WHITE_BG, self._BLACK_FG, bold=False
                ))
            else:
                # Alert: light red background, dark red bold text
                requests.append(self._fmt_request(
                    row_0, col_0, self._RED_BG, self._RED_FG, bold=True
                ))
                # Note on the cell
                requests.append(self._note_request(row_0, col_0, note_text))

        self._batch_update(requests)
        self._pending.clear()

    def append_result(self, site: str, zone: str, has_data: bool):
        """Compatibility shim."""
        self.queue_result(site, zone, has_data)

    def append_site_separator(self, site: str):
        """No-op."""
        pass