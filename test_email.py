# test_email.py
from email_notifier import send_summary

fake_no_data = [
    {"site": "Test Mall",        "zone": "Entrance A",   "timestamp": "2026-04-27 09:15:00"},
    {"site": "Test Mall",        "zone": "Food Court",   "timestamp": "2026-04-27 09:22:00"},
    {"site": "Another Site",     "zone": "Main Atrium",  "timestamp": "2026-04-27 09:35:00"},
]

send_summary(fake_no_data, total_zones_checked=47)