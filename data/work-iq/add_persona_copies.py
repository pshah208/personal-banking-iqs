"""Give one more persona Work IQ access to every seeded email by importing inbox copies.

Work IQ only grounds on mail the signed-in user can see. The seeders cc the demo driver (Raj), so another
persona (for example Derek Fontaine) sees only the threads he was party to. This adds an Inbox copy of every
other seeded message to that persona's mailbox. Nobody else's mailbox is touched, the original sender, recipients
and dates are preserved, and the import is idempotent: a subject already in the Inbox is skipped.

    $env:WORKIQ_TENANT_ID=...; $env:WORKIQ_CLIENT_ID=...; $env:WORKIQ_CLIENT_SECRET=...
    python add_persona_copies.py derek.fontaine [--dry-run]
"""
import argparse
import json
import urllib.parse

import seed_work_iq as s

FILES = ["emails.json", "book_emails.json", "card_emails.json", "mission_emails.json"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("alias")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    g = s.Graph("app", dry_run=a.dry_run)
    box = s.upn(a.alias)
    added = skipped = party = 0
    for f in FILES:
        data = json.loads((s.HERE / f).read_text(encoding="utf-8"))
        people = {p["alias"]: p for p in data["people"]}

        def rcpt(alias: str) -> dict:
            return {"emailAddress": {"address": s.upn(alias), "name": people.get(alias, {}).get("displayName", alias)}}

        for em in data["emails"]:
            cc = list(em.get("cc", []))
            if s.DRIVER_ALIAS and s.DRIVER_ALIAS not in [em["from"]] + em["to"] + cc:
                cc.append(s.DRIVER_ALIAS)
            if a.alias in [em["from"]] + em["to"] + cc:
                party += 1
                continue
            subj = em["subject"].replace("'", "''")
            q = urllib.parse.quote(f"subject eq '{subj}'")
            hit = g.call("GET", f"/users/{box}/mailFolders/inbox/messages?$filter={q}&$select=id&$top=1")
            if hit and hit.get("value"):
                skipped += 1
                continue
            when = em["sentDateTime"]
            g.call("POST", f"/users/{box}/mailFolders/inbox/messages", json_body={
                "subject": em["subject"], "importance": em.get("importance", "normal"),
                "body": {"contentType": "HTML", "content": s.html_body(em["body"])},
                "from": rcpt(em["from"]), "sender": rcpt(em["from"]),
                "toRecipients": [rcpt(x) for x in em["to"]], "ccRecipients": [rcpt(x) for x in cc],
                "sentDateTime": when, "receivedDateTime": when, "isRead": False,
                "singleValueExtendedProperties": [{"id": "Integer 0x0E07", "value": "1"},
                                                  {"id": "SystemTime 0x0039", "value": when},
                                                  {"id": "SystemTime 0x0E06", "value": when}]})
            added += 1
            print(f"  + {f:20} {when[:10]} {em['subject'][:70]}")
    print(f"\n{box}: {added} added, {skipped} already present, {party} already party to the thread")


if __name__ == "__main__":
    main()
