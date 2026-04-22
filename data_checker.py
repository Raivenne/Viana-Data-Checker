"""
Viana Portal - Daily Data Checker
Checks all sites/zones for missing data and saves a report + updates Google Sheets.

HOW TO USE:
1. Run this script
2. Manually log in to portal.viana.ai
3. Switch to QIC network
4. Go to X-Ray → Audience Measurement → click Explore
5. Press ENTER in this terminal

RESUME AFTER CRASH:
If the script crashes mid-run, just run it again.
It will automatically skip any sites that were already completed today,
and continue from where it left off.
"""

import sys
import os
import json
import time
import traceback
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from sheets_logger import SheetsLogger

if os.name == "nt":
    sys.stdout.reconfigure(encoding="utf-8")
    os.system("chcp 65001 > nul")

# ── Progress file — tracks completed sites for today's run ───────────────────
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), "progress.json")


def _load_progress():
    """
    Load today's progress file.
    Returns a dict: { "date": "YYYY-MM-DD", "completed_sites": [...] }
    If the file doesn't exist or is from a previous day, returns a fresh state.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today:
                return data
        except Exception:
            pass
    # Fresh start for today
    return {"date": today, "completed_sites": []}


def _save_progress(data: dict):
    """Write progress to disk immediately after each site completes."""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _clear_progress():
    """Delete the progress file after a full successful run."""
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)


class VianaDataChecker:

    DROPDOWN_WAIT = 4
    ZONE_LOAD     = 24
    FILTER_WAIT   = 4
    DATA_WAIT     = 6

    def __init__(self):
        opts = Options()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        self.driver  = webdriver.Chrome(options=opts)
        self.wait    = WebDriverWait(self.driver, 20)
        self.no_data_locations = []

        print("  📊 Connecting to Google Sheets …")
        self.sheets = SheetsLogger()
        print("  ✅ Google Sheets connected")

    # ════════════════════════════════════════════════════════════════════════
    # IFRAME
    # ════════════════════════════════════════════════════════════════════════

    def _enter_iframe(self):
        self.driver.switch_to.default_content()
        self.wait.until(EC.frame_to_be_available_and_switch_to_it(
            (By.TAG_NAME, "iframe")
        ))
        time.sleep(1)

    # ════════════════════════════════════════════════════════════════════════
    # CLEAR ALL
    # ════════════════════════════════════════════════════════════════════════

    def _click_clear_all(self):
        for sel in [
            (By.CSS_SELECTOR, "button.filter-clear-all-button"),
            (By.XPATH, "//button[.//span[contains(text(),'CLEAR ALL') or contains(text(),'Clear all')]]"),
        ]:
            try:
                btn = WebDriverWait(self.driver, 4).until(EC.element_to_be_clickable(sel))
                ActionChains(self.driver).move_to_element(btn).click().perform()
                time.sleep(1.5)
                return True
            except Exception:
                pass
        return False

    # ════════════════════════════════════════════════════════════════════════
    # DESELECT ALL TAGS IN ONE MULTI-SELECT
    # ════════════════════════════════════════════════════════════════════════

    def _deselect_all_in_dropdown(self, selector_el):
        for _ in range(50):
            try:
                parent = selector_el.find_element(
                    By.XPATH, "./ancestor::div[contains(@class,'ant-select')][1]"
                )
                btns = [b for b in parent.find_elements(
                    By.CSS_SELECTOR, ".ant-select-selection-item-remove"
                ) if b.is_displayed()]
                if not btns:
                    break
                ActionChains(self.driver).move_to_element(btns[0]).click().perform()
                time.sleep(0.25)
            except Exception:
                break

    # ════════════════════════════════════════════════════════════════════════
    # FIND DROPDOWN BY H4 LABEL
    # ════════════════════════════════════════════════════════════════════════

    def _get_dropdown_by_label(self, h4_text: str):
        xpath = (
            f"//div[contains(@class,'ant-form-item')]"
            f"[.//h4[normalize-space()='{h4_text}']]"
            f"//div[contains(@class,'ant-select-selector')]"
        )
        try:
            return WebDriverWait(self.driver, 8).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except Exception:
            return None

    # ════════════════════════════════════════════════════════════════════════
    # OPEN / CLOSE DROPDOWN
    # ════════════════════════════════════════════════════════════════════════

    def _open_dropdown(self, selector_el):
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", selector_el
        )
        time.sleep(0.3)
        ActionChains(self.driver).move_to_element(selector_el).click().perform()
        time.sleep(self.DROPDOWN_WAIT)

    def _close_dropdown(self):
        try:
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass
        time.sleep(0.5)

    # ════════════════════════════════════════════════════════════════════════
    # VIRTUAL LIST HELPERS
    # ════════════════════════════════════════════════════════════════════════

    def _get_scroll_container(self):
        containers = self.driver.find_elements(By.CSS_SELECTOR, ".rc-virtual-list-holder")
        return next((c for c in containers if c.is_displayed()), None)

    def _safe_text(self, element):
        """Read element text, returning None if the element has gone stale."""
        try:
            return element.text.strip()
        except Exception:
            return None

    def _collect_all_options(self):
        """
        Scroll the virtual list and collect every unique option text.
        Re-queries the DOM on every pass to avoid StaleElementReferenceException.
        """
        for _ in range(15):
            els = self.driver.find_elements(
                By.CSS_SELECTOR, ".ant-select-item-option-content"
            )
            if any(self._safe_text(o) for o in els):
                break
            time.sleep(0.4)

        container = self._get_scroll_container()
        if container:
            self.driver.execute_script("arguments[0].scrollTop = 0;", container)
            time.sleep(0.2)

        seen, ordered = set(), []
        stale_passes = 0

        while stale_passes < 2:
            els = self.driver.find_elements(
                By.CSS_SELECTOR, ".ant-select-item-option-content"
            )
            new_found = False
            for o in els:
                txt = self._safe_text(o)
                if txt and o.is_displayed() and txt not in seen:
                    seen.add(txt)
                    ordered.append(txt)
                    new_found = True

            stale_passes = 0 if new_found else stale_passes + 1

            if container:
                self.driver.execute_script("arguments[0].scrollTop += 200;", container)
                time.sleep(0.35)
            else:
                stale_passes += 1

        if container:
            self.driver.execute_script("arguments[0].scrollTop = 0;", container)
            time.sleep(0.2)

        return ordered

    def _scroll_and_click(self, target: str):
        """
        Scroll through the virtual list to find and click `target`.
        Re-queries the DOM on every pass to avoid StaleElementReferenceException.
        """
        container = self._get_scroll_container()
        if container:
            self.driver.execute_script("arguments[0].scrollTop = 0;", container)
            time.sleep(0.2)

        target_lower = target.lower()
        seen, stale_passes = set(), 0

        while stale_passes < 2:
            els = self.driver.find_elements(
                By.CSS_SELECTOR, ".ant-select-item-option-content"
            )
            new_txts = set()
            for o in els:
                txt = self._safe_text(o)
                if not txt:
                    continue
                new_txts.add(txt)
                if not o.is_displayed():
                    continue
                if txt == target or target_lower in txt.lower():
                    try:
                        ActionChains(self.driver).move_to_element(o).click().perform()
                        time.sleep(0.8)
                        self._close_dropdown()
                        return txt
                    except Exception:
                        break  # element went stale on click — re-scroll and retry

            added = new_txts - seen
            seen |= new_txts
            stale_passes = 0 if added else stale_passes + 1

            if container:
                self.driver.execute_script("arguments[0].scrollTop += 200;", container)
                time.sleep(0.35)
            else:
                stale_passes += 1

        self._close_dropdown()
        return None

    def _choose_first_option(self):
        els = self.driver.find_elements(
            By.CSS_SELECTOR, ".ant-select-item-option-content"
        )
        for o in els:
            txt = self._safe_text(o)
            if txt and o.is_displayed():
                try:
                    ActionChains(self.driver).move_to_element(o).click().perform()
                    time.sleep(0.8)
                    self._close_dropdown()
                    return txt
                except Exception:
                    continue
        return None

    # ════════════════════════════════════════════════════════════════════════
    # VERIFY SELECTED COUNT
    # ════════════════════════════════════════════════════════════════════════

    def _get_selected_tags(self, selector_el):
        try:
            parent = selector_el.find_element(
                By.XPATH, "./ancestor::div[contains(@class,'ant-select')][1]"
            )
            return [t.text.strip() for t in parent.find_elements(
                By.CSS_SELECTOR, ".ant-select-selection-item-content"
            ) if t.text.strip()]
        except Exception:
            return []

    # ════════════════════════════════════════════════════════════════════════
    # APPLY FILTERS
    # ════════════════════════════════════════════════════════════════════════

    def _click_apply_filters(self):
        for by, sel in [
            (By.CSS_SELECTOR, "button.filter-apply-button"),
            (By.XPATH, "//button[contains(@class,'filter-apply-button')]"),
            (By.XPATH, "//button[.//span[normalize-space()='Apply filters']]"),
            (By.XPATH, "//button[.//span[normalize-space()='APPLY FILTERS']]"),
            (By.XPATH, "//*[@data-test='apply-filters-btn']"),
        ]:
            try:
                btn = WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((by, sel)))
                ActionChains(self.driver).move_to_element(btn).click().perform()
                print("  ✅ Apply filters clicked")
                time.sleep(self.FILTER_WAIT)
                return True
            except Exception:
                pass
        buttons = [(b.text.strip(), b.get_attribute("class"))
                   for b in self.driver.find_elements(By.TAG_NAME, "button")
                   if b.is_displayed() and b.text.strip()]
        print(f"  ❌ Apply filters not found. Buttons: {buttons[:6]}")
        return False

    # ════════════════════════════════════════════════════════════════════════
    # DATA CHECK
    # ════════════════════════════════════════════════════════════════════════

    def _has_data(self):
        print(f"  ⏳ Waiting {self.DATA_WAIT}s for dashboard to load …")
        time.sleep(self.DATA_WAIT)
        NO_DATA = ["no data yet", "no data", "no results", "no records", "nothing to show"]
        try:
            for el in self.driver.find_elements(By.CSS_SELECTOR, "p.css-19zvg03"):
                if el.is_displayed() and el.text.strip().lower() in NO_DATA:
                    return False
            if any(e.is_displayed() for e in self.driver.find_elements(By.CSS_SELECTOR, ".ant-empty")):
                return False
            if any(p in self.driver.find_element(By.TAG_NAME, "body").text.lower() for p in NO_DATA):
                return False
            return True
        except Exception:
            return True

    # ════════════════════════════════════════════════════════════════════════
    # SELECT SITE
    # ════════════════════════════════════════════════════════════════════════

    def _select_site(self, site_name: str):
        self._click_clear_all()
        time.sleep(0.5)

        dd_site = self._get_dropdown_by_label("Site")
        if dd_site is None:
            print("  ❌ Site dropdown not found")
            return False

        self._open_dropdown(dd_site)
        chosen = self._scroll_and_click(site_name)

        if not chosen:
            print(f"  ⚠️  Site '{site_name}' not found — retrying …")
            time.sleep(2)
            self._open_dropdown(dd_site)
            chosen = self._scroll_and_click(site_name)
            if not chosen:
                print("  ❌ Could not select site — skipping")
                return False

        tags = self._get_selected_tags(dd_site)
        if len(tags) > 1:
            print("  ⚠️  Multiple sites selected — fixing …")
            self._deselect_all_in_dropdown(dd_site)
            time.sleep(0.5)
            self._open_dropdown(dd_site)
            self._scroll_and_click(site_name)

        print(f"  ✔ Site       : {chosen}")
        return True

    # ════════════════════════════════════════════════════════════════════════
    # PROCESS ONE ZONE  (site is already selected — do NOT reselect it)
    # ════════════════════════════════════════════════════════════════════════

    def _process_zone(self, site_name: str, zone_name: str,
                      date_already_set: bool = False) -> bool | None:
        """
        Check one zone. The site MUST already be selected before calling this.
        Pass date_already_set=True for every zone after the first so the
        Date and Time dropdown is left untouched — it stays on "Today".
        Returns True (has data), False (no data), or None (skipped).
        """
        print(f"\n  🔄 {zone_name}")

        # ── Swap zone only (do NOT touch site) ───────────────────────────
        dd_zone = self._get_dropdown_by_label("Zones")
        if dd_zone is None:
            print("  ❌ Zones dropdown not found")
            return None

        self._deselect_all_in_dropdown(dd_zone)
        self._open_dropdown(dd_zone)
        chosen_zone = self._scroll_and_click(zone_name)

        if not chosen_zone:
            print(f"  ⚠️  Zone '{zone_name}' not found — skipping")
            self._close_dropdown()
            return None

        tags = self._get_selected_tags(dd_zone)
        if len(tags) > 1:
            print("  ⚠️  Multiple zones — fixing …")
            self._deselect_all_in_dropdown(dd_zone)
            time.sleep(0.5)
            self._open_dropdown(dd_zone)
            self._scroll_and_click(zone_name)

        print(f"  ✔ Zone       : {chosen_zone}")

        # ── Date — set only on the first zone, leave untouched after ─────
        if not date_already_set:
            dd_date = self._get_dropdown_by_label("Date and Time")
            if dd_date is None:
                print("  ❌ Date and Time dropdown not found")
                return None
            self._open_dropdown(dd_date)
            chosen_date = self._scroll_and_click("Today") or self._choose_first_option()
            print(f"  ✔ Date       : {chosen_date} (set once — stays for all zones)")
        else:
            print("  ✔ Date       : Today (unchanged)")

        # ── Apply & check ─────────────────────────────────────────────────
        self._click_apply_filters()
        has_data = self._has_data()

        # Always exit iframe before returning so the next call starts clean
        self.driver.switch_to.default_content()

        if has_data:
            print("  📊 ✓ HAS DATA")
        else:
            print("  🚨 ❌ NO DATA")
            self.no_data_locations.append({
                "site":      site_name,
                "zone":      zone_name,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

        return has_data

    # ════════════════════════════════════════════════════════════════════════
    # MAIN AUTOMATION LOOP
    # ════════════════════════════════════════════════════════════════════════

    def run_full_automation(self):
        # ── Load today's progress ─────────────────────────────────────────
        progress = _load_progress()
        completed_sites = set(progress["completed_sites"])

        if completed_sites:
            print(f"\n  ⏭️  Resuming — {len(completed_sites)} site(s) already done today:")
            for s in completed_sites:
                print(f"     ✓ {s}")

        # ── Fetch site list ───────────────────────────────────────────────
        print("\n📋 Fetching site list …")
        self._enter_iframe()

        dd = self._get_dropdown_by_label("Site")
        if dd is None:
            print("  ❌ Site dropdown not found")
            self.driver.switch_to.default_content()
            return

        self._open_dropdown(dd)
        sites = self._collect_all_options()
        self._close_dropdown()
        self.driver.switch_to.default_content()

        if not sites:
            print("  ❌ CRITICAL: No sites found.")
            return

        print(f"  Found {len(sites)} sites")

        # Filter out already-completed sites
        remaining = [s for s in sites if s not in completed_sites]
        print(f"\n🌐 {len(remaining)}/{len(sites)} site(s) remaining to process")

        # ── Process each remaining site ───────────────────────────────────
        for i, site in enumerate(remaining):
            print(f"\n{'='*65}")
            print(f"🌐 SITE {sites.index(site)+1}/{len(sites)}: {site}")
            print("="*65)

            # Select site and read its zones
            self._enter_iframe()
            ok = self._select_site(site)
            if not ok:
                self.driver.switch_to.default_content()
                continue

            print(f"  ⏳ Waiting {self.ZONE_LOAD}s for zones to load …")
            time.sleep(self.ZONE_LOAD)

            dd_zone = self._get_dropdown_by_label("Zones")
            if dd_zone is None:
                print("  ❌ Zones dropdown not found")
                self.driver.switch_to.default_content()
                continue

            self._open_dropdown(dd_zone)
            zones = self._collect_all_options()
            self._close_dropdown()
            self.driver.switch_to.default_content()

            print(f"  📍 {len(zones)} zone(s) found")

            if not zones:
                print(f"  ⚠️  No zones for '{site}'")
                continue

            # ── Check each zone (site + date stay selected throughout) ──
            print(f"\n  ✔ Site       : {site}")
            site_results = []
            for z_idx, zone in enumerate(zones):
                # Re-enter iframe for each zone (we exit after each _has_data check)
                self._enter_iframe()
                # date_already_set=True for every zone after the first
                result = self._process_zone(site, zone, date_already_set=(z_idx > 0))
                site_results.append((zone, result))
                if result is not None:
                    self.sheets.queue_result(site, zone, result)
                time.sleep(0.5)

            # ── Flush all results for this site to Sheets in one batch ────
            # Driver is now in default_content (exited after last zone)
            print(f"\n  📊 Updating Google Sheet for {site} …")
            try:
                self.sheets.flush_site()
                written = len([r for r in site_results if r[1] is not None])
                print(f"  ✅ Sheet updated — {written} rows written")
            except Exception as sheet_err:
                import traceback
                print(f"  ⚠️  Sheet update failed (run continues):")
                traceback.print_exc()

            # ── Mark site as done and save progress immediately ───────────
            progress["completed_sites"].append(site)
            _save_progress(progress)
            print(f"  💾 Progress saved — '{site}' marked complete")

        # ── Full run finished — clean up progress file ────────────────────
        _clear_progress()
        print("\n✅ All sites processed — progress file cleared")

    # ════════════════════════════════════════════════════════════════════════
    # REPORT
    # ════════════════════════════════════════════════════════════════════════

    def save_report(self):
        ts       = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"NO_DATA_REPORT_{ts}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("VIANA DAILY NO-DATA REPORT\n")
            f.write("=" * 50 + "\n")
            f.write(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Issues    : {len(self.no_data_locations)}\n\n")
            if self.no_data_locations:
                for loc in self.no_data_locations:
                    f.write(f"[NO DATA]  {loc['site']}  —  {loc['zone']}\n")
                    f.write(f"           {loc['timestamp']}\n\n")
            else:
                f.write("All zones are reporting data.\n")
        print(f"\n💾 Report saved: {filename}")

    # ════════════════════════════════════════════════════════════════════════
    # ENTRY POINT
    # ════════════════════════════════════════════════════════════════════════

    def run(self):
        try:
            self.driver.get("https://portal.viana.ai/")
            print("="*65)
            print("  VIANA PORTAL — DAILY DATA CHECKER")
            print("="*65)
            print("  1. Log in to the portal")
            print("  2. Switch to the QIC network")
            print("  3. X-Ray → Audience Measurement → click Explore")
            print("  4. Wait for the page to FULLY load (3 dropdowns visible)")
            print("  5. Come back here and press ENTER")
            print("="*65)
            input("\n  ▶  Press ENTER when ready … ")
            time.sleep(2)

            self.run_full_automation()
            self.save_report()

        except KeyboardInterrupt:
            print("\n⏹️  Cancelled by user — progress saved, run again to resume")
            self.save_report()
        except Exception:
            print("\n" + "!"*65)
            print("  💥 UNEXPECTED CRASH — full error below:")
            print("!"*65)
            traceback.print_exc()
            print("!"*65)
            print("  Progress saved up to last completed site.")
            print("  Run the script again to resume from where it stopped.")
            self.save_report()
        finally:
            self.driver.switch_to.default_content()
            input("\nPress ENTER to close the browser … ")
            self.driver.quit()


if __name__ == "__main__":
    checker = VianaDataChecker()
    checker.run()
