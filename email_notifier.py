"""
email_notifier.py
Sends a summary email when the Viana Daily Data Checker finishes.

SETUP (one-time):
  1. Enable 2-Step Verification on your Gmail account.
  2. Go to myaccount.google.com → Security → App passwords.
  3. Create an app password named "Viana Checker".
  4. Paste the 16-character password into SMTP_PASSWORD below.
  5. Set SENDER_EMAIL to the Gmail address you used above.
  6. Add your team's addresses to RECIPIENTS.
"""

import smtplib
import traceback
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
SENDER_EMAIL  = "coco@skunkworks.ai"       # Gmail address that sends the email
SMTP_PASSWORD = "ermu dugq vtnv tqas"        # 16-character app password (spaces OK)

RECIPIENTS = [
    "coco@skunkworks.ai",
    # "teammate1@example.com",
    # "teammate2@example.com",
]

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
# ──────────────────────────────────────────────────────────────────────────────


def send_summary(no_data_locations: list, total_zones_checked: int):
    """
    Send the daily summary email.

    Parameters
    ----------
    no_data_locations : list of dicts with keys: site, zone, timestamp
    total_zones_checked : total number of zones that were checked (including skipped)
    """
    now         = datetime.now()
    date_str    = f"{now.strftime('%B')} {now.day}, {now.year}"   # e.g. "April 22, 2026"
    time_str    = now.strftime("%H:%M")
    issue_count = len(no_data_locations)

    # ── Subject ───────────────────────────────────────────────────────────────
    if issue_count == 0:
        subject = f"✅ Viana Daily Check — All clear [{date_str}]"
    else:
        subject = f"🚨 Viana Daily Check — {issue_count} zone(s) missing data [{date_str}]"

    # ── Plain-text body ───────────────────────────────────────────────────────
    divider = "─" * 50

    lines = [
        "VIANA DAILY DATA CHECK — SUMMARY",
        divider,
        f"Run completed : {date_str} at {time_str}",
        f"Zones checked : {total_zones_checked}",
        f"Issues found  : {issue_count}",
        "",
    ]

    if issue_count == 0:
        lines += [
            "✅ All zones are reporting data normally.",
            "No action required.",
        ]
    else:
        lines += [
            "🚨 The following zones reported NO DATA:",
            "",
            f"  {'SITE':<30}  {'ZONE':<30}  TIME",
            f"  {'─'*30}  {'─'*30}  {'─'*8}",
        ]

        # Group by site for readability
        sites_seen = []
        by_site: dict[str, list] = {}
        for loc in no_data_locations:
            s = loc["site"]
            if s not in by_site:
                by_site[s] = []
                sites_seen.append(s)
            by_site[s].append(loc)

        for site in sites_seen:
            for loc in by_site[site]:
                t = loc["timestamp"].split(" ")[-1][:5]   # "HH:MM"
                lines.append(f"  {loc['site']:<30}  {loc['zone']:<30}  {t}")
            lines.append("")   # blank line between sites

        lines += [
            divider,
            "Please check these zones in the Viana Portal.",
        ]

    lines += [
        "",
        divider,
        "This message was sent automatically by the Viana Data Checker.",
    ]

    body_plain = "\n".join(lines)

    # ── HTML body ─────────────────────────────────────────────────────────────
    if issue_count == 0:
        status_banner = (
            '<div style="background:#d4edda;color:#155724;padding:12px 16px;'
            'border-radius:4px;font-weight:bold;margin-bottom:16px;">'
            '✅ All zones are reporting data normally. No action required.'
            '</div>'
        )
        table_html = ""
    else:
        status_banner = (
            '<div style="background:#f8d7da;color:#721c24;padding:12px 16px;'
            'border-radius:4px;font-weight:bold;margin-bottom:16px;">'
            f'🚨 {issue_count} zone(s) reported NO DATA — please investigate.'
            '</div>'
        )

        rows_html = ""
        prev_site = None
        for loc in no_data_locations:
            t         = loc["timestamp"].split(" ")[-1][:5]
            site_cell = ""
            if loc["site"] != prev_site:
                # Count how many rows this site spans
                span      = sum(1 for l in no_data_locations if l["site"] == loc["site"])
                site_cell = (
                    f'<td rowspan="{span}" style="padding:8px 12px;border:1px solid #dee2e6;'
                    f'font-weight:bold;vertical-align:top;background:#fff3cd;">'
                    f'{loc["site"]}</td>'
                )
                prev_site = loc["site"]

            rows_html += (
                f'<tr>'
                f'{site_cell}'
                f'<td style="padding:8px 12px;border:1px solid #dee2e6;">{loc["zone"]}</td>'
                f'<td style="padding:8px 12px;border:1px solid #dee2e6;color:#666;">{t}</td>'
                f'</tr>'
            )

        table_html = f"""
        <table style="border-collapse:collapse;width:100%;margin-top:8px;font-size:14px;">
          <thead>
            <tr style="background:#343a40;color:#fff;">
              <th style="padding:10px 12px;text-align:left;border:1px solid #dee2e6;">Site</th>
              <th style="padding:10px 12px;text-align:left;border:1px solid #dee2e6;">Zone</th>
              <th style="padding:10px 12px;text-align:left;border:1px solid #dee2e6;">Time</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
        <p style="margin-top:12px;color:#555;font-size:13px;">
          Please check these zones in the Viana Portal.
        </p>
        """

    body_html = f"""
    <html><body style="font-family:Arial,sans-serif;font-size:14px;color:#212529;max-width:700px;">
      <h2 style="border-bottom:2px solid #dee2e6;padding-bottom:8px;">
        Viana Daily Data Check
      </h2>
      <table style="margin-bottom:16px;">
        <tr><td style="color:#666;padding-right:16px;">Run completed</td>
            <td><strong>{date_str} at {time_str}</strong></td></tr>
        <tr><td style="color:#666;padding-right:16px;">Zones checked</td>
            <td><strong>{total_zones_checked}</strong></td></tr>
        <tr><td style="color:#666;padding-right:16px;">Issues found</td>
            <td><strong>{issue_count}</strong></td></tr>
      </table>
      {status_banner}
      {table_html}
      <hr style="margin-top:32px;border:none;border-top:1px solid #dee2e6;">
      <p style="color:#aaa;font-size:12px;">
        Sent automatically by the Viana Data Checker.
      </p>
    </body></html>
    """

    # ── Assemble & send ───────────────────────────────────────────────────────
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = ", ".join(RECIPIENTS)

    msg.attach(MIMEText(body_plain, "plain", "utf-8"))
    msg.attach(MIMEText(body_html,  "html",  "utf-8"))

    try:
        print("\n  📧 Sending summary email …")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SENDER_EMAIL, SMTP_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())
        print(f"  ✅ Email sent to: {', '.join(RECIPIENTS)}")
    except Exception:
        print("  ⚠️  Email failed (run continues) — check SMTP credentials:")
        traceback.print_exc()