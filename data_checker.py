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

    def __init__(self):
        opts = Options()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        self.driver = webdriver.Chrome(options=opts)
        self.wait   = WebDriverWait(self.driver, 20)
        self.no_data_locations = []

    # ── iframe ───────────────────────────────────────────────────────────────

    def _enter_iframe(self):
        self.driver.switch_to.default_content()
        self.wait.until(EC.frame_to_be_available_and_switch_to_it(
            (By.TAG_NAME, "iframe")
        ))
        time.sleep(1)

    # ── find dropdown selector by h4 label ───────────────────────────────────

    def _get_dropdown_by_label(self, h4_text: str):
        """
        Find the .ant-select-selector inside the form item whose <h4> matches.
        e.g. h4_text = 'Site' | 'Zones' | 'Date and Time'
        """
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

    # ── open a dropdown (ActionChains required) ───────────────────────────────

    def _open_dropdown(self, selector_el):
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", selector_el
        )
        time.sleep(0.3)
        ActionChains(self.driver).move_to_element(selector_el).click().perform()
        time.sleep(self.DROPDOWN_WAIT)

    # ── close the open dropdown by clicking its label area (outside list) ────

    def _close_dropdown(self, selector_el):
        """
        Click the label h4 above the dropdown to dismiss the open list,
        or fall back to Escape.
        """
        try:
            # Click somewhere neutral — the form item label
            ActionChains(self.driver).move_to_element(selector_el) \
                .move_by_offset(0, -40).click().perform()
        except Exception:
            pass
        try:
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass
        time.sleep(0.5)

    # ── read options from the currently open dropdown ─────────────────────────

    def _get_open_options(self):
        """
        Return (texts, elements). Works for both multi and single select.
        Uses .ant-select-item-option-content which holds the visible label text.
        """
        for _ in range(15):
            opts = self.driver.find_elements(
                By.CSS_SELECTOR,
                ".ant-select-item-option-content"
            )
            visible = [o for o in opts if o.is_displayed() and o.text.strip()]
            if visible:
                return [o.text.strip() for o in visible], visible
            time.sleep(0.4)
        return [], []

    # ── click exactly one option ──────────────────────────────────────────────

    def _choose_one_option(self, target: str):
        """
        Click the option whose text exactly matches target.
        Falls back to contains-match if exact not found.
        Returns matched text or None.
        """
        texts, els = self._get_open_options()

        # Try exact match first
        for el, txt in zip(els, texts):
            if txt == target:
                ActionChains(self.driver).move_to_element(el).click().perform()
                time.sleep(1.0)
                return txt

        # Fallback: contains match
        for el, txt in zip(els, texts):
            if target.lower() in txt.lower():
                ActionChains(self.driver).move_to_element(el).click().perform()
                time.sleep(1.0)
                return txt

        return None

    def _choose_first_option(self):
        _, els = self._get_open_options()
        if els:
            txt = els[0].text.strip()
            ActionChains(self.driver).move_to_element(els[0]).click().perform()
            time.sleep(1.0)
            return txt
        return None

    # ── clear a multi-select dropdown before use ──────────────────────────────

    def _clear_dropdown(self, selector_el):
        """
        Click the × clear button on a multi-select dropdown if it exists.
        Must hover the selector first to make the × visible.
        """
        try:
            # Hover to reveal the clear button
            ActionChains(self.driver).move_to_element(selector_el).perform()
            time.sleep(0.3)
            # The clear button is a sibling span of the selector
            parent = selector_el.find_element(
                By.XPATH, "./ancestor::div[contains(@class,'ant-select')][1]"
            )
            clear_btn = parent.find_element(By.CSS_SELECTOR, ".ant-select-clear")
            if clear_btn.is_displayed():
                ActionChains(self.driver).move_to_element(clear_btn).click().perform()
                time.sleep(0.5)
        except Exception:
            pass

    # ── Apply Filters button ──────────────────────────────────────────────────

    def _click_apply_filters(self):
        """
        The HTML shows: <span>Apply filters</span> inside a button.
        Find the button that contains that span.
        """
        xpaths = [
            "//button[.//span[normalize-space()='Apply filters']]",
            "//button[.//span[normalize-space()='Apply Filters']]",
            "//button[normalize-space(.)='Apply filters']",
            "//button[normalize-space(.)='Apply Filters']",
            "//*[@data-test='apply-filters-btn']",
        ]
        for xp in xpaths:
            try:
                btn = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, xp))
                )
                ActionChains(self.driver).move_to_element(btn).click().perform()
                print("  ✅ Apply filters clicked")
                time.sleep(self.FILTER_WAIT)
                return True
            except Exception:
                pass

        # Debug: list all visible buttons
        buttons = self.driver.find_elements(By.TAG_NAME, "button")
        visible = [(b.text.strip(), b.get_attribute("class")) for b in buttons
                   if b.is_displayed() and b.text.strip()]
        print(f"  ❌ Apply filters not found. Visible buttons: {visible[:8]}")
        return False

    # ── data check ────────────────────────────────────────────────────────────

    def _has_data(self):
        NO_DATA = ["no data", "no data yet", "no results", "no records", "nothing to show"]
        try:
            body = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            return not any(p in body for p in NO_DATA)
        except Exception:
            return True

    # ── discover all sites ────────────────────────────────────────────────────

    def get_all_sites(self):
        print("\n📋 Fetching site list …")
        self._enter_iframe()

        dd = self._get_dropdown_by_label("Site")
        if dd is None:
            print("  ❌ Site dropdown not found")
            self.driver.switch_to.default_content()
            return []

        self._clear_dropdown(dd)
        self._open_dropdown(dd)
        texts, _ = self._get_open_options()

        # Deduplicate, preserve order
        seen, unique = set(), []
        for t in texts:
            if t not in seen:
                seen.add(t)
                unique.append(t)

        self._close_dropdown(dd)
        print(f"  Found {len(unique)} sites")
        # Leave inside iframe — caller calls default_content()
        return unique

    # ── discover zones for one site ───────────────────────────────────────────

    def get_zones_for_site(self, site_name):
        self._enter_iframe()

        # Clear + open Site dropdown
        dd_site = self._get_dropdown_by_label("Site")
        if dd_site is None:
            self.driver.switch_to.default_content()
            return []

        self._clear_dropdown(dd_site)
        self._open_dropdown(dd_site)
        chosen = self._choose_one_option(site_name)
        if not chosen:
            print(f"  ⚠️  Site '{site_name}' not found")
            self._close_dropdown(dd_site)
            self.driver.switch_to.default_content()
            return []

        # Close Site dropdown before touching Zones
        self._close_dropdown(dd_site)

        print(f"  ⏳ Waiting {self.ZONE_LOAD}s for zones …")
        time.sleep(self.ZONE_LOAD)

        dd_zone = self._get_dropdown_by_label("Zones")
        if dd_zone is None:
            self.driver.switch_to.default_content()
            return []

        self._clear_dropdown(dd_zone)
        self._open_dropdown(dd_zone)
        texts, _ = self._get_open_options()
        self._close_dropdown(dd_zone)

        seen, unique = set(), []
        for t in texts:
            if t not in seen:
                seen.add(t)
                unique.append(t)

        self.driver.switch_to.default_content()
        return unique

    # ── process one site + zone combination ───────────────────────────────────

    def process_site_zone(self, site_name, zone_name):
        print(f"\n  🔄 {site_name}  |  {zone_name}")
        self._enter_iframe()

        # ── 1. Site ───────────────────────────────────────────────────────
        dd_site = self._get_dropdown_by_label("Site")
        if dd_site is None:
            print("  ❌ Site dropdown not found")
            self.driver.switch_to.default_content()
            return None

        self._clear_dropdown(dd_site)
        self._open_dropdown(dd_site)
        chosen_site = self._choose_one_option(site_name)
        if not chosen_site:
            print(f"  ⚠️  Could not select site '{site_name}'")
            self._close_dropdown(dd_site)
            self.driver.switch_to.default_content()
            return None
        print(f"  ✔ Site       : {chosen_site}")
        self._close_dropdown(dd_site)  # ← close before next dropdown

        # ── 2. Wait for zones to load ─────────────────────────────────────
        print(f"  ⏳ Waiting {self.ZONE_LOAD}s for zones …")
        time.sleep(self.ZONE_LOAD)

        # ── 3. Zone ───────────────────────────────────────────────────────
        dd_zone = self._get_dropdown_by_label("Zones")
        if dd_zone is None:
            print("  ❌ Zones dropdown not found")
            self.driver.switch_to.default_content()
            return None

        self._clear_dropdown(dd_zone)
        self._open_dropdown(dd_zone)
        chosen_zone = self._choose_one_option(zone_name)
        if not chosen_zone:
            print(f"  ⚠️  Zone '{zone_name}' not found — skipping")
            self._close_dropdown(dd_zone)
            self.driver.switch_to.default_content()
            return None
        print(f"  ✔ Zone       : {chosen_zone}")
        self._close_dropdown(dd_zone)  # ← close before next dropdown

        # ── 4. Date and Time ──────────────────────────────────────────────
        dd_date = self._get_dropdown_by_label("Date and Time")
        if dd_date is None:
            print("  ❌ Date and Time dropdown not found")
            self.driver.switch_to.default_content()
            return None

        self._open_dropdown(dd_date)
        chosen_date = self._choose_one_option("Today")
        if not chosen_date:
            chosen_date = self._choose_first_option()
        print(f"  ✔ Date       : {chosen_date}")
        # Single-select closes itself on pick — no manual close needed

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

    # ── full automation loop ──────────────────────────────────────────────────

    def run_full_automation(self):
        sites = self.get_all_sites()
        self.driver.switch_to.default_content()

        if not sites:
            print("\n❌ CRITICAL: No sites found.")
            return

        print(f"\n🌐 {len(sites)} site(s) to process")

        for i, site in enumerate(sites):
            print(f"\n{'='*65}")
            print(f"🌐 SITE {i+1}/{len(sites)}: {site}")
            print("="*65)

            zones = self.get_zones_for_site(site)
            if not zones:
                print(f"  ⚠️  No zones found for '{site}'")
                continue

            print(f"  📍 {len(zones)} zone(s)")
            for zone in zones:
                self.process_site_zone(site, zone)
                time.sleep(1)

    # ── save report ───────────────────────────────────────────────────────────

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

    # ── entry point ───────────────────────────────────────────────────────────

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