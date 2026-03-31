"""
Viana Portal - Daily Data Checker
Checks all sites/zones for missing data and saves a report.

HOW TO USE:
1. Run this script
2. Manually log in to portal.viana.ai
3. Switch to QIC network
4. Go to X-Ray → Audience Measurement → click Explore
5. Press ENTER in this terminal
"""

import sys
import os
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

if os.name == "nt":
    sys.stdout.reconfigure(encoding="utf-8")
    os.system("chcp 65001 > nul")


class VianaDataChecker:

    DROPDOWN_WAIT = 2
    ZONE_LOAD     = 5
    FILTER_WAIT   = 8
    DATA_WAIT     = 5

    def __init__(self):
        opts = Options()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        self.driver = webdriver.Chrome(options=opts)
        self.wait   = WebDriverWait(self.driver, 20)
        self.no_data_locations = []

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

    def _collect_all_options(self):
        """Scroll the virtual list top-to-bottom and return every unique option text."""
        # Wait for first options
        for _ in range(15):
            if any(o.is_displayed() and o.text.strip() for o in
                   self.driver.find_elements(By.CSS_SELECTOR, ".ant-select-item-option-content")):
                break
            time.sleep(0.4)

        container = self._get_scroll_container()
        if container:
            self.driver.execute_script("arguments[0].scrollTop = 0;", container)
            time.sleep(0.2)

        seen, ordered = set(), []
        stale_passes = 0

        while stale_passes < 2:
            opts = [o for o in self.driver.find_elements(
                By.CSS_SELECTOR, ".ant-select-item-option-content"
            ) if o.is_displayed() and o.text.strip()]

            new_found = False
            for o in opts:
                txt = o.text.strip()
                if txt not in seen:
                    seen.add(txt)
                    ordered.append(txt)
                    new_found = True

            stale_passes = 0 if new_found else stale_passes + 1

            if container:
                self.driver.execute_script("arguments[0].scrollTop += 200;", container)
                time.sleep(0.3)
            else:
                stale_passes += 1

        # Scroll back to top so subsequent clicks work
        if container:
            self.driver.execute_script("arguments[0].scrollTop = 0;", container)
            time.sleep(0.2)

        return ordered

    def _scroll_and_click(self, target: str):
        """
        Scroll through the virtual list to find and click `target`.
        Returns matched text or None.
        """
        container = self._get_scroll_container()
        if container:
            self.driver.execute_script("arguments[0].scrollTop = 0;", container)
            time.sleep(0.2)

        target_lower = target.lower()
        seen, stale_passes = set(), 0

        while stale_passes < 2:
            opts = [o for o in self.driver.find_elements(
                By.CSS_SELECTOR, ".ant-select-item-option-content"
            ) if o.is_displayed() and o.text.strip()]

            for o in opts:
                txt = o.text.strip()
                if txt == target or target_lower in txt.lower():
                    ActionChains(self.driver).move_to_element(o).click().perform()
                    time.sleep(0.8)
                    self._close_dropdown()
                    return txt

            new_txts = {o.text.strip() for o in opts} - seen
            seen |= new_txts
            stale_passes = 0 if new_txts else stale_passes + 1

            if container:
                self.driver.execute_script("arguments[0].scrollTop += 200;", container)
                time.sleep(0.3)
            else:
                stale_passes += 1

        self._close_dropdown()
        return None

    def _choose_first_option(self):
        opts = [o for o in self.driver.find_elements(
            By.CSS_SELECTOR, ".ant-select-item-option-content"
        ) if o.is_displayed() and o.text.strip()]
        if opts:
            txt = opts[0].text.strip()
            ActionChains(self.driver).move_to_element(opts[0]).click().perform()
            time.sleep(0.8)
            self._close_dropdown()
            return txt
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
    # SELECT SITE  (shared helper — used by both discovery and processing)
    # ════════════════════════════════════════════════════════════════════════

    def _select_site(self, site_name: str):
        """
        Clear all, select exactly one site, verify. Returns True on success.
        Must be called INSIDE the iframe.
        """
        self._click_clear_all()
        time.sleep(0.5)

        dd_site = self._get_dropdown_by_label("Site")
        if dd_site is None:
            print("  ❌ Site dropdown not found")
            return False

        self._open_dropdown(dd_site)
        chosen = self._scroll_and_click(site_name)

        if not chosen:
            # Retry once
            print(f"  ⚠️  Site '{site_name}' not found — retrying …")
            time.sleep(2)
            self._open_dropdown(dd_site)
            chosen = self._scroll_and_click(site_name)
            if not chosen:
                print("  ❌ Could not select site — skipping")
                return False

        # Ensure only one site tag
        tags = self._get_selected_tags(dd_site)
        if len(tags) > 1:
            print(f"  ⚠️  Multiple sites selected — fixing …")
            self._deselect_all_in_dropdown(dd_site)
            time.sleep(0.5)
            self._open_dropdown(dd_site)
            self._scroll_and_click(site_name)

        print(f"  ✔ Site       : {chosen}")
        return True

    # ════════════════════════════════════════════════════════════════════════
    # MAIN AUTOMATION LOOP
    # Single pass: for each site → select it → read zones → process each zone
    # Never leaves the iframe between zone-fetch and zone-use.
    # ════════════════════════════════════════════════════════════════════════

    def run_full_automation(self):
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
        print(f"\n🌐 {len(sites)} site(s) to process")

        # ── Process each site ─────────────────────────────────────────────
        for i, site in enumerate(sites):
            print(f"\n{'='*65}")
            print(f"🌐 SITE {i+1}/{len(sites)}: {site}")
            print("="*65)

            # Enter iframe and select this site
            self._enter_iframe()
            ok = self._select_site(site)
            if not ok:
                self.driver.switch_to.default_content()
                continue

            # Wait for zones to populate for THIS site
            print(f"  ⏳ Waiting {self.ZONE_LOAD}s for zones to load …")
            time.sleep(self.ZONE_LOAD)

            # Read the zone list (still inside iframe, site already selected)
            dd_zone = self._get_dropdown_by_label("Zones")
            if dd_zone is None:
                print("  ❌ Zones dropdown not found")
                self.driver.switch_to.default_content()
                continue

            self._open_dropdown(dd_zone)
            zones = self._collect_all_options()
            self._close_dropdown()

            print(f"  📍 {len(zones)} zone(s) found")

            # Exit iframe between zones — each process_site_zone re-enters cleanly
            self.driver.switch_to.default_content()

            if not zones:
                print(f"  ⚠️  No zones for '{site}'")
                continue

            # ── Process each zone for this site ───────────────────────────
            for zone in zones:
                self._process_site_zone(site, zone)
                time.sleep(1)

    # ════════════════════════════════════════════════════════════════════════
    # PROCESS ONE SITE + ZONE
    # ════════════════════════════════════════════════════════════════════════

    def _process_site_zone(self, site_name: str, zone_name: str):
        print(f"\n  🔄 {site_name}  |  {zone_name}")
        self._enter_iframe()

        # ── 1. Select site ────────────────────────────────────────────────
        if not self._select_site(site_name):
            self.driver.switch_to.default_content()
            return None

        # ── 2. Wait for zones ─────────────────────────────────────────────
        print(f"  ⏳ Waiting {self.ZONE_LOAD}s for zones …")
        time.sleep(self.ZONE_LOAD)

        # ── 3. Select zone ────────────────────────────────────────────────
        dd_zone = self._get_dropdown_by_label("Zones")
        if dd_zone is None:
            print("  ❌ Zones dropdown not found")
            self.driver.switch_to.default_content()
            return None

        self._open_dropdown(dd_zone)
        chosen_zone = self._scroll_and_click(zone_name)

        if not chosen_zone:
            print(f"  ⚠️  Zone '{zone_name}' not found — skipping")
            self.driver.switch_to.default_content()
            return None

        tags = self._get_selected_tags(dd_zone)
        if len(tags) > 1:
            print("  ⚠️  Multiple zones — fixing …")
            self._deselect_all_in_dropdown(dd_zone)
            time.sleep(0.5)
            self._open_dropdown(dd_zone)
            self._scroll_and_click(zone_name)

        print(f"  ✔ Zone       : {chosen_zone}")

        # ── 4. Date and Time ──────────────────────────────────────────────
        dd_date = self._get_dropdown_by_label("Date and Time")
        if dd_date is None:
            print("  ❌ Date and Time dropdown not found")
            self.driver.switch_to.default_content()
            return None

        self._open_dropdown(dd_date)
        chosen_date = self._scroll_and_click("Today") or self._choose_first_option()
        print(f"  ✔ Date       : {chosen_date}")

        # ── 5. Apply Filters ──────────────────────────────────────────────
        self._click_apply_filters()

        # ── 6. Check result ───────────────────────────────────────────────
        has_data = self._has_data()
        if has_data:
            print("  📊 ✓ HAS DATA")
        else:
            print("  🚨 ❌ NO DATA")
            self.no_data_locations.append({
                "site":      site_name,
                "zone":      zone_name,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

        self.driver.switch_to.default_content()
        time.sleep(2)
        return has_data

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
            print("\n⏹️  Cancelled by user")
        finally:
            self.driver.switch_to.default_content()
            input("\nPress ENTER to close the browser … ")
            self.driver.quit()


if __name__ == "__main__":
    checker = VianaDataChecker()
    checker.run()