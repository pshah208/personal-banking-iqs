"""Seed extra emails (card_emails.json, or $env:SEED_FILE e.g. book_emails.json) with the same importer as seed_work_iq.py.

    $env:WORKIQ_TENANT_ID=...; $env:WORKIQ_CLIENT_ID=...; $env:WORKIQ_CLIENT_SECRET=...
    python seed_card_mail.py [--dry-run] [--purge]
"""
import argparse
import os
import seed_work_iq as s

_orig = s.load
s.load = lambda name: _orig((os.environ.get("SEED_FILE") or "card_emails.json") if name == "emails.json" else name)

ap = argparse.ArgumentParser()
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--purge", action="store_true")
a = ap.parse_args()
s.seed_mail(s.Graph("app", dry_run=a.dry_run), purge=a.purge)

