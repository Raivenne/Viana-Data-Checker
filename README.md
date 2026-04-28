# VIANA DAILY DATA CHECKER — SETUP & HANDOVER GUIDE

## WHAT IT DOES

Checks all sites and zones in portal.viana.ai for missing data each day.
Updates a Google Sheet with results and sends a summary email to the team.

## FILES

data_checker.py — main script
sheets_logger.py — handles Google Sheets updates
email_notifier.py — handles summary email
credentials.json — Google service account key (DO NOT SHARE PUBLICLY)
progress.json — auto-generated, tracks daily progress (safe to delete)

## REQUIREMENTS

Python 3.10+
Chrome browser installed
Run once: pip install selenium gspread google-auth

## HOW TO RUN MANUALLY

1. Double-click run_checker.bat
2. Log in to portal.viana.ai
3. Switch to QIC network
4. Go to X-Ray → Audience Measurement → click Explore
5. Wait for 3 dropdowns to appear
6. Press ENTER in the terminal

## TASK SCHEDULER (automatic daily run)

Already configured to run at 2PM but can be revised.
The browser will open automatically — someone must log in within 60 seconds.
To change the time: search Task Scheduler → Viana Daily Checker → right-click → Properties.

## IF IT CRASHES

Just run it again. It resumes from where it stopped.

## EMAIL NOTIFICATIONS

Sent to: [list your recipients]
To add/remove recipients: open email_notifier.py and edit the RECIPIENTS list.
SMTP password is the app password for [sender email] — stored in email_notifier.py.

## GOOGLE SHEET

Link: https://docs.google.com/spreadsheets/d/1tUOvu0Wntzmcj6fN8N5XWSbNwv2cI2JZSh5rUK8SgZg
The sheet auto-adds a new column for each day's run.

## CREDENTIALS

credentials.json is the Google service account key.
If it expires or breaks, a new one needs to be generated from:
Google Cloud Console → IAM → Service Accounts → [account name] → Keys

## CONTACT

Built by: Nicole Raiv Hernandez
Date: April 2026
Questions: nicoleraivh@gmail.com
