"""Write mission_emails.json - colleague correspondence that the agent missions need (Work IQ).

Each email is about a named client case on a mission's case list and carries something no Fabric table holds:
a client's own words, a committee ruling, a privacy preference, a campaign mistake, a scam red flag.
Seed with the same importer as the other book mail:

    python make_mission_emails.py
    $env:SEED_FILE="mission_emails.json"; python seed_card_mail.py [--dry-run]

Every message is also cc'd to `admin` (the tenant admin used for end-to-end testing) in addition to the demo
driver (Raj) that the importer adds. Facts match the governed tables as of 2026-08-03. SYNTHETIC.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
src = json.loads((HERE / "book_emails.json").read_text(encoding="utf-8"))
people = src["people"] + [{"alias": "admin", "displayName": "PB Operations (demo)", "title": "Demo operator", "role": "ops"}]

E = []


def em(i, frm, to, cc, when, subject, body, importance="normal", category="mission_case"):
    E.append({"id": f"EM-M{i:02d}", "category": category, "from": frm, "to": to, "cc": cc + ["admin"],
              "sentDateTime": when, "importance": importance, "subject": subject, "body": body})


em(1, "marcus.delaney", ["priya.raghavan"], ["karen.whitfield"], "2026-08-01T14:10:00Z",
   "Clara Thibault (DA-1040 / RNW-5040) - hold the renewal retention call",
   "Priya,\n\nClara Thibault is on this week's retention list as 'Retain - match 30 bps' for RNW-5040, which matures on 2026-08-14. "
   "Please do not make that call yet.\n\nShe phoned the branch this morning on her verified number. She does not recognise the new "
   "device login and the payee added on 31 July (security case SE-9017 is open), and she says she never set up the transfers to "
   "another institution that started in June - about $1,430 in June and $1,770 in July. The deposit-flow report reads that as "
   "payroll moving away. It may be someone moving her money.\n\nSo: fraud team first, verified phone only, no emails. Once the case "
   "is closed we owe her a calm renewal conversation - her payment roughly doubles at renewal. If the case is still open on the 10th, "
   "escalate under the renewal escalation procedure so she is not forced to choose a term in the middle of a fraud case.\n\nMarcus",
   "high")

em(2, "sophie.tremblay", ["wei.zhang"], ["diane.lafleur"], "2026-07-29T16:25:00Z",
   "Tariq Marchetti (DA-1044) - payroll split to his new employer's bank",
   "Wei,\n\nThanks for the note on Tariq Marchetti. To confirm what he told you on the phone: he started a new job in June and his "
   "employer pays part of his salary into an account at their bank - that is the transfers-out the book is flagging. He is not "
   "unhappy with us.\n\nWhat worries me more is the rest of the picture: his renewal (RNW-5044) is on 29 August, he has asked whether "
   "we can match a competitor quote, and his card has been at the limit for months. I do not want him getting a retention offer, a "
   "card note and a package email in the same week. One relationship conversation, support first, and do not make the payroll a "
   "condition of anything.\n\nSophie")

em(3, "nadia.osei", ["fatima.haddad"], ["raj.balakrishnan"], "2026-07-30T13:05:00Z",
   "Nikhil Petrov - consolidation offer queued while his card fraud case is open",
   "Fatima,\n\nThe lending campaign batch for 4 August has queued a debt-consolidation email to Nikhil Petrov (move his card balance "
   "to his unsecured line). The candidate table says 'Offer' because the numbers work. But his card fraud dispute from 7 July "
   "(SE-9009, card blocked and reissued) is still open, and we have never captured his email marketing consent.\n\nPlease pull him "
   "from the batch. No offers in any book while a security case is open. When it closes, if he wants to talk about the card balance, "
   "he can - as a conversation, not a campaign.\n\nNadia")

em(4, "wei.zhang", ["sophie.tremblay"], ["fatima.haddad"], "2026-07-31T15:45:00Z",
   "Simone Fitzgerald - wants to use her TFSA GIC to pay down the mortgage at renewal",
   "Sophie,\n\nSimone Fitzgerald came in about RNW-5008 (renews 25 August). Her payment more than doubles at renewal and she asked "
   "whether she can take the TFSA GIC that matures the next day and put it against the mortgage to bring the payment down.\n\n"
   "I did not give advice - she needs the licensed advisor for the GIC side. Open points: the prepayment limit on a straight "
   "renewal, the one-day gap between the renewal and the GIC maturity, the fact that TFSA room only comes back the next calendar "
   "year, and whether she wants to keep an emergency cushion. Can we get her one joint appointment rather than two?\n\nWei")

em(5, "sophie.tremblay", ["wei.zhang"], ["karen.whitfield"], "2026-08-02T11:20:00Z",
   "Caleb Yusuf - asked to move both GICs at maturity to an 'investment platform'",
   "Wei,\n\nCaleb Yusuf called about his two GICs maturing in early September (TFSA and RRSP). He wants both paid out to an online "
   "'investment platform' that a friend from a messaging group recommended - he said it pays 2% a month and they help you open the "
   "account over a screen-share.\n\nEvery part of that matches the investment-scam warnings. He is not Vulnerable and it is his "
   "money, so we do not refuse - but the maturity conversation starts with scam coaching, hold-and-verify on any large transfer to "
   "a new payee, and no screen-sharing with anyone. The licensed advisor should be in the room. Nothing about our own products "
   "until that is done.\n\nSophie", "high")

em(6, "priya.raghavan", ["marcus.delaney"], [], "2026-07-28T17:05:00Z",
   "RE: Mortgage client maxing her card - it is Sana Moreau (CA-1049)",
   "Marcus,\n\nFollowing up on my note from last week - the client is Sana Moreau. Two NSF items in the last two months, the card "
   "at the limit, and her renewal (RNW-5049) in December with a much higher payment. She asked me about skipping a payment.\n\n"
   "One more thing: she asked us to phone her and NOT email. Her partner reads the shared email account and she does not want the "
   "money conversation to happen that way. I have noted it on the file. So no email from any book, please - card, mortgage or "
   "insurance.\n\nPriya", "high")

em(7, "sophie.tremblay", ["karen.whitfield"], ["wei.zhang"], "2026-07-21T10:30:00Z",
   "Jun Pelletier (SC-2010) - email changed + new device, and he is still in the student card campaign",
   "Karen,\n\nJun Pelletier (20) had a new-device login and a payee added on 15 July (SE-9024, payees frozen) and the email address "
   "on his profile was changed the same week. We reached him on the verified mobile number; he did not change the email.\n\n"
   "Problem: he is still on the student card campaign list, which would email the NEW address. Please make sure every book's "
   "outreach to him is stopped until the case closes, and that nothing goes to the changed email at all.\n\nSophie", "high")

em(8, "derek.fontaine", ["nadia.osei"], ["raj.balakrishnan", "fatima.haddad"], "2026-07-27T19:00:00Z",
   "Pricing Committee ruling - screenshot evidence, and RNW-5033",
   "Nadia,\n\nThe committee has answered the screenshot question so advisors stop deciding it one by one:\n\n"
   "1. A screenshot of a competitor quote is acceptable for a discount of up to 15 bps, with the advisor's written attestation of "
   "what they saw.\n2. Beyond 15 bps we need a dated commitment letter or PDF that names the client.\n\nFor Mateo Bergeron "
   "(RNW-5033) the gap is 22 bps, so we need the letter before anything beyond 15. Before you get there, though: his file shows the "
   "household above the affordability guideline at the renewal payment. The amortization relief fast path may do more for his "
   "payment than any rate match - run that conversation first.\n\nDerek")

em(9, "raj.balakrishnan", ["nadia.osei"], ["karen.whitfield"], "2026-08-02T09:40:00Z",
   "Henrik Thibault (CV-1025) - complaint routed, no insurance contact until Complaints replies",
   "Nadia,\n\nHenrik Thibault's complaint that he was told mortgage life cover was required is now with the Complaints team "
   "(ref CMP-2207). They are reviewing whether the premiums he paid since origination should be refunded.\n\nUntil they reply: no "
   "insurance contact of any kind - no reinstatement, no gap conversation. The renewal conversation (RNW-5025) goes ahead, support "
   "first: his card is at the limit and the household is above the affordability guideline. If he raises the insurance himself, "
   "acknowledge the complaint and say Complaints will contact him.\n\nRaj")

em(10, "fatima.haddad", ["sophie.tremblay"], ["karen.whitfield"], "2026-08-01T12:15:00Z",
   "Quinn Singh - GIC maturing 29 Aug, KYC out of date, card fraud case open",
   "Sophie,\n\nQuinn Singh's TFSA GIC matures on 29 August. Before anyone calls about it: the KYC on file is out of date, the card "
   "fraud case from 28 July (SE-9030) is still open, and the chequing account went into overdraft twice this summer.\n\nI suggest "
   "the GIC simply rolls to the default term (no recommendation), the fraud team closes the card case first, and then Client "
   "Assistance gets in touch about the card balance. The KYC refresh can follow when Quinn is ready. Agree?\n\nFatima")

out = {"$schema_note": "Agent-mission correspondence for Work IQ - one thread per mission case. Same schema as emails.json; "
                       "seed with seed_card_mail.py and SEED_FILE=mission_emails.json.",
       "scenario": "Agent missions FY26", "as_of": "2026-08-03", "people": people, "emails": E}
(HERE / "mission_emails.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {len(E)} emails")
