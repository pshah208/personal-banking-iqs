"""Seed the Work IQ layer for the Mortgage Renewal Concierge into Microsoft 365.

Loads three things into a demo/dev tenant:

  mail    18 renewal-campaign emails, imported into each recipient's Inbox with
          the original sender and timestamp preserved
  teams   the "Retail Mortgage Renewals FY26" team, 3 channels, 12 threads
  files   the 4 meeting notes uploaded to the team's SharePoint document library
          (and optionally a user's OneDrive)

--------------------------------------------------------------------------------
PREREQUISITES
--------------------------------------------------------------------------------
1. A **non-production / demo tenant**. This script writes into user mailboxes and
   renames directory accounts.

2. **Licensed accounts for the 14 personas.** Do NOT create new users unless you
   have spare licences - a user without Exchange Online has no mailbox (mail
   import fails), and without a Microsoft 365 Copilot licence Work IQ cannot
   ground on their content. Instead, map the personas onto existing licensed
   users in `user_mapping.json`, then:

       python seed_work_iq.py --auth cli --check-users
       python seed_work_iq.py --auth cli --map-users --dry-run
       python seed_work_iq.py --auth cli --map-users      # snapshots originals
       python seed_work_iq.py --auth cli --restore-users  # undo

   `--map-users` sets displayName / jobTitle / department (mail renders
   displayName, which is what makes the narrative read correctly) and writes the
   originals to user_mapping.restore.json. UPNs and licences are untouched.

3. An Entra ID app registration with a client secret, and these **application**
   permissions granted with admin consent:

     User.Read.All            resolve aliases -> user ids
     User.ReadWrite.All       --map-users (or run that step with --auth cli)
     Mail.ReadWrite           import messages into mailboxes
     Group.ReadWrite.All      create the team's group
     Team.Create              create the team
     Channel.Create           create channels
     ChannelMessage.Send      post channel messages   *see note below*
     Files.ReadWrite.All      upload meeting notes
     Sites.ReadWrite.All      upload to the team's SharePoint library

   NOTE on ChannelMessage.Send with *application* permissions: this is a
   Microsoft "protected API" and requires a separate request to Microsoft
   (https://aka.ms/teamsgraph/requestaccess). If you do not have that approval,
   run the teams step with delegated auth instead:

       python seed_work_iq.py --only teams --auth device

   Delegated device-code auth posts every message as the signed-in user; the
   script prefixes each post with the original author so the narrative survives.

4. **The demo driver.** Work IQ grounds only on content the signed-in user can
   access, so `driver_alias` in user_mapping.json (Raj Balakrishnan by default) is
   cc'd on every email the persona is not already party to.

--------------------------------------------------------------------------------
CONFIGURE
--------------------------------------------------------------------------------
    $env:WORKIQ_TENANT_ID     = "<tenant-guid>"
    $env:WORKIQ_CLIENT_ID     = "<app-registration-client-id>"
    $env:WORKIQ_CLIENT_SECRET = "<client-secret>"     # app auth only
    # only needed when there is no user_mapping.json:
    $env:WORKIQ_TENANT_DOMAIN = "contoso.onmicrosoft.com"

    pip install azure-identity requests

--------------------------------------------------------------------------------
RUN
--------------------------------------------------------------------------------
    python seed_work_iq.py --auth cli --check-users
    python seed_work_iq.py --only mail
    python seed_work_iq.py --only teams --auth device
    python seed_work_iq.py --only files
    python seed_work_iq.py --all --dry-run        # print what would happen
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
from azure.identity import AzureCliCredential, ClientSecretCredential, DeviceCodeCredential

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_BETA = "https://graph.microsoft.com/beta"
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "tools" / "brand"))
from bank_profile import rebrand, rebrand_text  # noqa: E402  - names the deployed bank

TENANT_ID = os.getenv("WORKIQ_TENANT_ID", "")
CLIENT_ID = os.getenv("WORKIQ_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("WORKIQ_CLIENT_SECRET", "")
DOMAIN = os.getenv("WORKIQ_TENANT_DOMAIN", "")

LIBRARY_FOLDER = "Renewal Campaign"
MAPPING_FILE = HERE / "user_mapping.json"
RESTORE_FILE = HERE / "user_mapping.restore.json"


# --------------------------------------------------------------------------- #
# persona -> real account mapping
# --------------------------------------------------------------------------- #
def mapping() -> dict:
    """Persona alias -> {upn, displayName, jobTitle, department}.

    Demo tenants rarely have spare licences, so personas are mapped onto existing
    licensed accounts rather than newly created users. Falls back to
    <alias>@WORKIQ_TENANT_DOMAIN when no mapping file is present.
    """
    if MAPPING_FILE.exists():
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    return {"mapping": {}, "driver_alias": ""}


_MAP = mapping()
DRIVER_ALIAS = os.getenv("WORKIQ_DRIVER_ALIAS", _MAP.get("driver_alias", ""))


# --------------------------------------------------------------------------- #
# auth + http
# --------------------------------------------------------------------------- #
class Graph:
    def __init__(self, mode: str, dry_run: bool = False):
        self.dry_run = dry_run
        if mode == "app":
            if not (TENANT_ID and CLIENT_ID and CLIENT_SECRET):
                sys.exit("Set WORKIQ_TENANT_ID / WORKIQ_CLIENT_ID / WORKIQ_CLIENT_SECRET.")
            self._cred = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
            self._scopes = ["https://graph.microsoft.com/.default"]
        elif mode == "cli":
            # Uses `az login`. Enough for --check-users / --map-users / --restore-users,
            # which only read and patch directory objects as an admin.
            self._cred = AzureCliCredential()
            self._scopes = ["https://graph.microsoft.com/.default"]
        else:
            if not (TENANT_ID and CLIENT_ID):
                sys.exit("Set WORKIQ_TENANT_ID / WORKIQ_CLIENT_ID.")
            self._cred = DeviceCodeCredential(client_id=CLIENT_ID, tenant_id=TENANT_ID)
            self._scopes = [
                "https://graph.microsoft.com/ChannelMessage.Send",
                "https://graph.microsoft.com/Group.ReadWrite.All",
                "https://graph.microsoft.com/Files.ReadWrite.All",
                "https://graph.microsoft.com/User.Read.All",
            ]
        self.mode = mode
        self._token: str | None = None
        self._expires = 0.0

    def _headers(self) -> dict[str, str]:
        if not self._token or time.time() > self._expires - 120:
            tok = self._cred.get_token(*self._scopes)
            self._token, self._expires = tok.token, tok.expires_on
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def call(self, method: str, url: str, *, json_body: Any = None,
             raw: bytes | None = None, content_type: str | None = None,
             ok_404: bool = False) -> Any:
        if not url.startswith("http"):
            url = f"{GRAPH}{url}"
        if self.dry_run and method.upper() != "GET":
            print(f"    [dry-run] {method.upper()} {url}")
            return {"id": "dry-run-id"}

        for attempt in range(6):
            headers = self._headers()
            if content_type:
                headers["Content-Type"] = content_type
            resp = requests.request(
                method, url, headers=headers,
                json=json_body if raw is None else None,
                data=raw, timeout=60,
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = int(resp.headers.get("Retry-After", 2 ** attempt))
                print(f"    throttled ({resp.status_code}), retrying in {wait}s")
                time.sleep(wait)
                continue
            if resp.status_code == 404 and ok_404:
                return None
            if resp.status_code >= 400:
                raise RuntimeError(f"{method} {url} -> {resp.status_code}: {resp.text[:600]}")
            if not resp.content:
                return None
            return resp.json()
        raise RuntimeError(f"{method} {url} failed after retries")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def upn(alias: str) -> str:
    entry = _MAP.get("mapping", {}).get(alias)
    if entry:
        return entry["upn"]
    if not DOMAIN:
        sys.exit(f"No mapping for '{alias}' and WORKIQ_TENANT_DOMAIN is unset.")
    return f"{alias}@{DOMAIN}"


def map_users(g: Graph) -> None:
    """Rename the mapped accounts to the persona identities, snapshotting first.

    Mail renders displayName, so this is what makes the narrative read correctly
    without creating new (unlicensable) users. Reversible via --restore-users.
    """
    entries = _MAP.get("mapping", {})
    if not entries:
        sys.exit(f"No mapping in {MAPPING_FILE.name}")

    snapshot: dict[str, dict] = {}
    if RESTORE_FILE.exists():
        snapshot = json.loads(RESTORE_FILE.read_text(encoding="utf-8"))
        print(f"  (existing snapshot found - originals already captured for "
              f"{len(snapshot)} account(s), not overwriting)")

    for alias, e in entries.items():
        current = g.call("GET", f"/users/{e['upn']}"
                                "?$select=id,displayName,jobTitle,department,mail",
                         ok_404=True)
        if not current:
            print(f"  !! not found: {e['upn']}")
            continue
        if e["upn"] not in snapshot:
            snapshot[e["upn"]] = {
                "displayName": current.get("displayName"),
                "jobTitle": current.get("jobTitle"),
                "department": current.get("department"),
            }
        g.call("PATCH", f"/users/{e['upn']}", json_body={
            "displayName": e["displayName"],
            "jobTitle": e["jobTitle"],
            "department": e["department"],
        })
        print(f"  {current.get('displayName','?'):<20} -> {e['displayName']:<20} "
              f"({e['upn'].split('@')[0]})")

    if not g.dry_run:
        RESTORE_FILE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(f"\noriginals snapshotted to {RESTORE_FILE.name} - keep this file, "
              f"it is how you undo the rename")


def restore_users(g: Graph) -> None:
    if not RESTORE_FILE.exists():
        sys.exit(f"No snapshot at {RESTORE_FILE.name} - nothing to restore")
    snapshot = json.loads(RESTORE_FILE.read_text(encoding="utf-8"))
    for target, original in snapshot.items():
        g.call("PATCH", f"/users/{target}",
               json_body={k: v for k, v in original.items()})
        print(f"  restored {target.split('@')[0]:<12} -> {original['displayName']}")
    print(f"\n{len(snapshot)} account(s) restored.")


def load(name: str) -> dict:
    return rebrand(json.loads((HERE / name).read_text(encoding="utf-8")))


def html_body(text: str) -> str:
    paras = "".join(
        f"<p>{p.replace(chr(10), '<br/>')}</p>" for p in text.split("\n\n") if p.strip()
    )
    return f"<html><body style=\"font-family:Segoe UI,Arial,sans-serif;font-size:11pt\">{paras}</body></html>"


def resolve_users(g: Graph, aliases: list[str]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for a in aliases:
        u = g.call("GET", f"/users/{upn(a)}?$select=id,displayName", ok_404=True)
        if u:
            ids[a] = u["id"]
        else:
            print(f"    !! user not found: {upn(a)}")
    return ids


# --------------------------------------------------------------------------- #
# 1. mail
# --------------------------------------------------------------------------- #
def seed_mail(g: Graph, purge: bool = False) -> None:
    data = load("emails.json")
    people = {p["alias"]: p for p in data["people"]}
    print(f"\n== MAIL == {len(data['emails'])} messages")

    if purge:
        purge_mail(g, data)

    def recipient(alias: str) -> dict:
        return {"emailAddress": {"address": upn(alias),
                                 "name": people[alias]["displayName"]}}

    for em in data["emails"]:
        sender = recipient(em["from"])
        cc_aliases = list(em.get("cc", []))
        # Work IQ only grounds on what the signed-in user can see, so the demo
        # driver is cc'd on anything they are not already party to.
        if DRIVER_ALIAS and DRIVER_ALIAS not in (
            [em["from"]] + em["to"] + cc_aliases
        ):
            cc_aliases.append(DRIVER_ALIAS)

        when = em["sentDateTime"]
        payload_base = {
            "subject": em["subject"],
            "importance": em.get("importance", "normal"),
            "body": {"contentType": "HTML", "content": html_body(em["body"])},
            "from": sender,
            "sender": sender,
            "toRecipients": [recipient(a) for a in em["to"]],
            "ccRecipients": [recipient(a) for a in cc_aliases],
            "sentDateTime": when,
            "receivedDateTime": when,
            "isRead": False,
            "singleValueExtendedProperties": [
                # PidTagMessageFlags - mark as sent/submitted so the message is
                # not treated as a draft in the recipient's Inbox.
                {"id": "Integer 0x0E07", "value": "1"},
                # Exchange silently rewrites sentDateTime/receivedDateTime to "now"
                # on create. Setting the underlying MAPI properties preserves the
                # original timeline, which the whole narrative depends on.
                # PR_CLIENT_SUBMIT_TIME / PR_MESSAGE_DELIVERY_TIME
                {"id": "SystemTime 0x0039", "value": when},
                {"id": "SystemTime 0x0E06", "value": when},
            ],
        }

        targets = list(dict.fromkeys(em["to"] + cc_aliases))
        for alias in targets:
            g.call("POST", f"/users/{upn(alias)}/mailFolders/inbox/messages",
                   json_body=payload_base)
        # keep a copy in the author's Sent Items so "what did I send" queries work
        g.call("POST", f"/users/{upn(em['from'])}/mailFolders/sentitems/messages",
               json_body=payload_base)
        print(f"  {em['id']}  {when[:10]}  {em['subject'][:52]:<52} "
              f"-> {len(targets)} inbox(es) + sent")


def purge_mail(g: Graph, data: dict) -> None:
    """Remove previously seeded copies so a re-run does not duplicate them."""
    subjects = {e["subject"] for e in data["emails"]}
    aliases = {p["alias"] for p in data["people"]}
    removed = 0
    for alias in sorted(aliases):
        for folder in ("inbox", "sentitems"):
            page = (f"/users/{upn(alias)}/mailFolders/{folder}/messages"
                    "?$select=subject&$top=100")
            while page:
                res = g.call("GET", page if page.startswith("http") else page)
                if not res:
                    break
                for m in res.get("value", []):
                    if m.get("subject") in subjects:
                        g.call("DELETE", f"/users/{upn(alias)}/messages/{m['id']}")
                        removed += 1
                page = res.get("@odata.nextLink")
    print(f"  purged {removed} previously seeded message(s)")


# --------------------------------------------------------------------------- #
# 2. teams
# --------------------------------------------------------------------------- #
def find_group(g: Graph, display_name: str) -> str | None:
    esc = display_name.replace("'", "''")
    r = g.call("GET", f"/groups?$filter=displayName eq '{esc}'&$select=id,displayName")
    vals = (r or {}).get("value", [])
    return vals[0]["id"] if vals else None


def seed_teams(g: Graph, messages_only: bool = False) -> None:
    data = load("teams_messages.json")
    people = {p["alias"]: p for p in load("emails.json")["people"]}
    team_def = data["team"]
    name = team_def["displayName"]
    print(f"\n== TEAMS == {name}")

    team_id = find_group(g, name)
    if team_id:
        print(f"  team already exists: {team_id}")
    elif messages_only:
        sys.exit("  team does not exist - run --only teams first")
    else:
        # App-only team creation accepts exactly one member (the owner);
        # everyone else is added afterwards via the members collection.
        owner = team_def["ownerAliases"][0]
        g.call("POST", "/teams", json_body={
            "template@odata.bind": "https://graph.microsoft.com/v1.0/teamsTemplates('standard')",
            "displayName": name,
            "description": team_def["description"],
            "visibility": team_def["visibility"],
            "members": [{
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{upn(owner)}')",
            }],
        })
        print("  team creation accepted - Graph provisions asynchronously, waiting…")
        for _ in range(30):
            time.sleep(10)
            team_id = find_group(g, name)
            if team_id:
                break
        if not team_id:
            sys.exit("  team did not provision in time; re-run --only teams in a few minutes")
        print(f"  team provisioned: {team_id}")

    # Membership is ensured on every run - adding an existing member is a no-op
    # error we swallow, so this is safe to repeat.
    if not messages_only:
        current = {
            m.get("userId")
            for m in (g.call("GET", f"/teams/{team_id}/members") or {}).get("value", [])
        }
        added, skipped = 0, 0
        for a in team_def["ownerAliases"] + team_def["memberAliases"]:
            user = g.call("GET", f"/users/{upn(a)}?$select=id", ok_404=True)
            if not user or user["id"] in current:
                skipped += 1
                continue
            try:
                g.call("POST", f"/teams/{team_id}/members", json_body={
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"] if a in team_def["ownerAliases"] else [],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{user['id']}')",
                })
                added += 1
            except Exception as exc:  # noqa: BLE001
                print(f"    !! could not add {a}: {str(exc)[:200]}")
        print(f"  members: +{added} added, {skipped} already present")

    existing = {c["displayName"]: c["id"]
                for c in (g.call("GET", f"/teams/{team_id}/channels") or {}).get("value", [])}

    posted, failed, first_error = 0, 0, ""

    for ch in data["channels"]:
        ch_id = existing.get(ch["displayName"])
        if not ch_id:
            created = g.call("POST", f"/teams/{team_id}/channels", json_body={
                "displayName": ch["displayName"],
                "description": ch["description"],
                "membershipType": "standard",
            })
            ch_id = created["id"]
            print(f"  + channel {ch['displayName']}")
            time.sleep(3)
        else:
            print(f"  = channel {ch['displayName']} (exists)")

        for conv in ch["conversations"]:
            try:
                root = post_message(g, team_id, ch_id, conv["from"], people,
                                    subject=conv.get("subject"), text=conv["message"])
                posted += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                first_error = first_error or str(exc)[:300]
                continue
            for reply in conv.get("replies", []):
                try:
                    post_message(g, team_id, ch_id, reply["from"], people,
                                 text=reply["message"], reply_to=root)
                    posted += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    first_error = first_error or str(exc)[:300]
            print(f"    {conv['id']}  {conv.get('subject','')[:52]:<52} "
                  f"+{len(conv.get('replies', []))} replies")

    print(f"\n  messages posted: {posted}   failed: {failed}")
    if failed:
        print(f"  first error: {first_error}")
        print("\n  ChannelMessage.Send does not exist as an *application* permission on\n"
              "  Microsoft Graph - channel posting is delegated-only. Re-run just the\n"
              "  messages with device-code auth (the team and channels already exist):\n"
              "      python seed_work_iq.py --only teams --messages-only --auth device")


def post_message(g: Graph, team_id: str, ch_id: str, alias: str,
                 people: dict, *, text: str, subject: str | None = None,
                 reply_to: str | None = None) -> str:
    author = people[alias]
    if g.mode == "app":
        # application permissions cannot impersonate; Graph attributes the post to
        # the app. Prefix keeps the narrative attributable to the right persona.
        content = (f"<p><strong>{author['displayName']}</strong> "
                   f"<em>({author['title']})</em></p><p>{text}</p>")
    else:
        content = (f"<p><em>Posting on behalf of {author['displayName']} - "
                   f"{author['title']}</em></p><p>{text}</p>")

    body = {"body": {"contentType": "html", "content": content}}
    if subject and not reply_to:
        body["subject"] = subject

    url = (f"/teams/{team_id}/channels/{ch_id}/messages"
           if not reply_to else
           f"/teams/{team_id}/channels/{ch_id}/messages/{reply_to}/replies")
    res = g.call("POST", url, json_body=body)
    time.sleep(1)
    return res["id"]


# --------------------------------------------------------------------------- #
# 3. files
# --------------------------------------------------------------------------- #
def seed_files(g: Graph, onedrive_alias: str | None) -> None:
    print("\n== FILES ==")
    docs = sorted((HERE / "meetings").glob("*.md"))
    extra = [HERE / "emails.json", HERE / "teams_messages.json"]

    targets: list[tuple[str, str]] = []

    team_name = load("teams_messages.json")["team"]["displayName"]
    group_id = find_group(g, team_name)
    if group_id:
        site = g.call("GET", f"/groups/{group_id}/sites/root?$select=id", ok_404=True)
        if site:
            drive = g.call("GET", f"/sites/{site['id']}/drive?$select=id")
            targets.append((f"/drives/{drive['id']}", f"SharePoint · {team_name}"))
    else:
        print("  !! team not found - run --only teams first to get the SharePoint library")

    if onedrive_alias:
        d = g.call("GET", f"/users/{upn(onedrive_alias)}/drive?$select=id", ok_404=True)
        if d:
            targets.append((f"/drives/{d['id']}", f"OneDrive · {onedrive_alias}"))

    if not targets:
        print("  nothing to upload to")
        return

    for drive_path, label in targets:
        print(f"  -> {label}")
        for f in docs:
            body = rebrand_text(f.read_text(encoding="utf-8")).encode("utf-8")
            upload(g, drive_path, f"{LIBRARY_FOLDER}/Meetings/{f.name}", body)
            print(f"     {LIBRARY_FOLDER}/Meetings/{f.name}")
        for f in extra:
            body = rebrand_text(f.read_text(encoding="utf-8")).encode("utf-8")
            upload(g, drive_path, f"{LIBRARY_FOLDER}/Source/{f.name}", body)
            print(f"     {LIBRARY_FOLDER}/Source/{f.name}")


def upload(g: Graph, drive_path: str, item_path: str, content: bytes) -> None:
    g.call("PUT", f"{drive_path}/root:/{item_path}:/content",
           raw=content, content_type="text/plain")


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["mail", "teams", "files"])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--auth", choices=["app", "device", "cli"], default="app")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check-users", action="store_true")
    ap.add_argument("--map-users", action="store_true",
                    help="rename the mapped accounts to the persona identities "
                         "(snapshots originals to user_mapping.restore.json)")
    ap.add_argument("--restore-users", action="store_true",
                    help="undo --map-users from the snapshot")
    ap.add_argument("--messages-only", action="store_true",
                    help="with --only teams: post channel messages into an existing team")
    ap.add_argument("--purge", action="store_true",
                    help="with --only mail: delete previously seeded messages first")
    ap.add_argument("--onedrive-alias", default="raj.balakrishnan",
                    help="also copy the meeting notes into this user's OneDrive")
    args = ap.parse_args()

    if not (DOMAIN or _MAP.get("mapping")):
        sys.exit("Set WORKIQ_TENANT_DOMAIN, or provide user_mapping.json.")

    g = Graph(args.auth, dry_run=args.dry_run)

    if args.map_users:
        map_users(g)
        return

    if args.restore_users:
        restore_users(g)
        return

    if args.check_users:
        aliases = [p["alias"] for p in load("emails.json")["people"]]
        found = resolve_users(g, aliases)
        print(f"\n{len(found)}/{len(aliases)} personas resolved")
        for a in aliases:
            print(f"  {'OK ' if a in found else 'MISS'}  {a:<18} -> {upn(a)}")
        if DRIVER_ALIAS:
            print(f"\ndemo driver: {DRIVER_ALIAS} -> {upn(DRIVER_ALIAS)}")
        return

    steps = ["mail", "teams", "files"] if (args.all or not args.only) else [args.only]
    for s in steps:
        if s == "mail":
            seed_mail(g, purge=args.purge)
        elif s == "teams":
            seed_teams(g, messages_only=args.messages_only)
        elif s == "files":
            seed_files(g, args.onedrive_alias)

    print("\nDone. Allow 15-30 minutes for Microsoft 365 / Copilot indexing "
          "before querying through Work IQ.")


if __name__ == "__main__":
    main()
