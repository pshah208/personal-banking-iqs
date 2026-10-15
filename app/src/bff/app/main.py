"""Mortgage Renewal Concierge — BFF.

Endpoints
    GET  /health          liveness + configuration summary
    GET  /api/config      what the SPA needs to bootstrap (no secrets)
    GET  /api/me          the signed-in user, as the BFF sees them
    GET  /api/iqs         the IQ catalogue
    GET  /api/story       the guided demo chapters
    POST /api/chat        SSE: iq_active / status / message / error / done
    GET  /api/diag        auth + OBO + agent reachability, for troubleshooting
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from .agent_client import run_agent
from .auth import User, current_user, exchange_obo
from .config import settings
from .iq import iq_catalogue
from .offers import catalogue as offer_catalogue
from . import evergreen, fabric_capacity, pb_books, pb_card_market, pb_cards, pb_customers, pb_missions, pb_scenarios, pb_world
from .books_data import BOOKS
from .cards_data import CARDS
from .pb_data import PB

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("bff")

# Keep the synthetic snapshot on the current week (see evergreen.py). The bundles
# and the one derived table that copies dates out of them are rewritten in place;
# the module-level as-of constants are re-read after each shift.
for _data in (PB, BOOKS, CARDS, pb_books._INV_ROWS):
    evergreen.track(_data)


def _sync_as_of() -> None:
    pb_books.AS_OF = BOOKS["as_of"]
    pb_missions.AS_OF = BOOKS["as_of"]
    pb_customers.AS_OF = date.fromisoformat(PB["as_of"])
    logger.info("evergreen: data as of %s (+%s days)", BOOKS["as_of"], evergreen.offset_days())


evergreen.on_refresh(_sync_as_of)
evergreen.ensure_current()

app = FastAPI(title="Mortgage Renewal Concierge BFF", version="1.0.0")


@app.middleware("http")
async def _evergreen(request: Request, call_next):
    evergreen.ensure_current()
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORY_FILE = Path(__file__).with_name("story.json")


class ChatRequest(BaseModel):
    question: str
    threadId: str | None = None


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "mockMode": settings.mock_mode,
        "authConfigured": settings.configured(),
        "agentConfigured": bool(settings.project_endpoint),
        "agent": settings.agent_name,
        "dataAsOf": evergreen.as_of().isoformat(),
    }


@app.get("/api/config")
async def config() -> dict:
    """Bootstrap values for the SPA. Deliberately contains no secrets."""
    return {
        "tenantId": settings.tenant_id,
        "apiScope": settings.api_scope,
        "agentName": settings.agent_name,
        "mockMode": settings.mock_mode,
        "bank": settings.bank_name,
        "disclaimer": (
            "SYNTHETIC DEMO DATA. CFC Bank is used as a branding label only. "
            "No customer, balance, rate or policy shown here reflects real "
            "CFC Bank information."
        ),
    }


@app.get("/api/me")
async def me(user: User = Depends(current_user)) -> dict:
    """The signed-in user, enriched from Microsoft Graph.

    The token carries name and roles but not jobTitle or department, so those are
    fetched from Graph on the user's behalf. The 14 demo personas already have
    those fields set in Entra, which is what lets the persona card show the real
    person rather than a hardcoded one.
    """
    roles = user.claims.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]

    profile = {
        "name": user.name,
        "upn": user.upn,
        "oid": user.oid,
        "roles": roles,
        "role": roles[0] if roles else "",
        "jobTitle": "",
        "department": "",
    }

    if settings.mock_mode:
        profile.update({"jobTitle": "VP, Real Estate Secured Lending",
                        "department": "Real Estate Secured Lending"})
        return profile

    # Graph enrichment is best-effort: a failure here must not block the app.
    try:
        import httpx

        token = await exchange_obo(user, "https://graph.microsoft.com/.default")
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://graph.microsoft.com/v1.0/me"
                "?$select=displayName,jobTitle,department,mail",
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code == 200:
            g = r.json()
            profile["jobTitle"] = g.get("jobTitle") or ""
            profile["department"] = g.get("department") or ""
            if g.get("displayName"):
                profile["name"] = g["displayName"]
        else:
            logger.info("graph /me returned %s", r.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.info("graph enrichment skipped: %s", str(exc)[:200])

    return profile


@app.get("/api/iqs")
async def iqs() -> list[dict]:
    return iq_catalogue()


@app.get("/api/offers")
async def offers() -> list[dict]:
    """The RP-003 approved offer catalogue.

    Served so the client can refuse to render a flyer that breaches policy. The
    check has to be deterministic, so it is done against this list rather than by
    asking the model whether its own offer was allowed.
    """
    return offer_catalogue()


@app.get("/api/story")
async def story() -> dict:
    if not STORY_FILE.exists():
        return {"chapters": []}
    return json.loads(STORY_FILE.read_text(encoding="utf-8"))


@app.post("/api/chat")
async def chat(req: ChatRequest, user: User = Depends(current_user)) -> StreamingResponse:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    logger.info("chat from %s: %s", user.upn, req.question[:120])
    return StreamingResponse(
        run_agent(user, req.question, req.threadId),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # stop nginx buffering the stream
        },
    )


@app.get("/api/fabric-capacity")
async def fabric_capacity_status(user: User = Depends(current_user)) -> dict:
    """State of the Fabric capacity behind Fabric IQ (Active / Paused / ...)."""
    return await fabric_capacity.status(user.upn)


@app.post("/api/fabric-capacity/{action}")
async def fabric_capacity_change(action: str, user: User = Depends(current_user)) -> dict:
    """Pause (suspend) or resume the capacity. Logged with the caller's UPN."""
    try:
        return await fabric_capacity.change(action, user.upn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


# --------------------------------------------------------------------------- #
# Scenarios - deterministic renewal engine + Web IQ world events + analyst
# --------------------------------------------------------------------------- #
class ScenarioRequest(BaseModel):
    factors: dict[str, float] = {}
    name: str = "Custom"
    worldId: str | None = None


@app.get("/api/scenarios/library")
async def scenarios_library(user: User = Depends(current_user)) -> dict:
    return pb_scenarios.library()


@app.post("/api/scenarios/run")
async def scenarios_run(req: ScenarioRequest, user: User = Depends(current_user)) -> dict:
    return pb_scenarios.run(req.factors, req.name[:80])


@app.get("/api/scenarios/world")
async def scenarios_world(refresh: bool = False, cached: bool = False, user: User = Depends(current_user)) -> dict:
    """World-event presets scaled by today's Web IQ severity (cached; ?refresh=true re-queries)."""
    return pb_world.cached() if cached else await pb_world.world(user, refresh=refresh)


def _world_context(world_id: str | None) -> str:
    if not world_id:
        return ""
    w = pb_world.cached()
    if world_id.startswith("emerging:"):
        e = next((x for x in w.get("emerging") or [] if f"emerging:{x['title']}" == world_id), None)
        if not e:
            return ""
        return (f"Emerging risk (live Web IQ, public web, {e['date'] or 'recent'}, {e['source'] or 'web'}): {e['title']} - {e['headline']} "
                f"NOT a governed scenario: approximated with the governed '{e['closest_name']}' shock at '{e['severity']}' severity. "
                "Say so plainly and recommend whether the Retail Risk Committee should add it to the library (RP-015).")
    t = next((x for x in w["themes"] if x["id"] == world_id), None)
    if not t:
        return ""
    if not t["live"]:
        return f"Household signal: {t['name']} at governed baseline strength (live Web IQ not available)."
    return (f"Household signal: {t['name']}. Live Web IQ (public web, {t['date'] or 'recent'}, {t['source'] or 'web'}): {t['headline']} "
            f"Assessed strength '{t['severity']}', so the governed preset is scaled x{t['intensity']}. Transmission: {t['channels']}")


@app.post("/api/scenarios/narrate")
async def scenarios_narrate(req: ScenarioRequest, user: User = Depends(current_user)) -> StreamingResponse:
    result = pb_scenarios.run(req.factors, req.name[:80])
    logger.info("AUDIT scenario narrate by %s: %s %s", user.upn, result["name"], result["factors"])
    return StreamingResponse(run_agent(user, pb_scenarios.narrative_prompt(result, _world_context(req.worldId)), None,
                                       settings.scenario_agent_name), media_type="text/event-stream", headers=SSE_HEADERS)


# --------------------------------------------------------------------------- #
# Customers - 360, wellness, next-best action, outreach, compliance review
# --------------------------------------------------------------------------- #
def _cust_or_404(cid: str) -> dict:
    c = pb_customers.customer(cid)
    if not c:
        raise HTTPException(status_code=404, detail=f"Unknown customer {cid}")
    return c


@app.get("/api/pb/overview")
async def pb_overview(user: User = Depends(current_user)) -> dict:
    return pb_customers.overview()


@app.get("/api/pb/customers")
async def pb_customer_list(user: User = Depends(current_user)) -> dict:
    return pb_customers.customers()


@app.get("/api/pb/wellness")
async def pb_wellness(user: User = Depends(current_user)) -> dict:
    return pb_customers.wellness()


@app.get("/api/pb/customer/{cid}")
async def pb_customer(cid: str, user: User = Depends(current_user)) -> dict:
    return _cust_or_404(cid)


class DraftRequest(BaseModel):
    actionIndex: int = 0
    channel: str = "Email"


class OutreachDraft(BaseModel):
    channel: str = "Email"
    purpose: str = "Service"
    subject: str = ""
    body: str = ""
    action: dict = {}
    notes: str = ""


@app.post("/api/pb/customer/{cid}/draft")
async def pb_draft(cid: str, req: DraftRequest, user: User = Depends(current_user)) -> dict:
    _cust_or_404(cid)
    d = pb_customers.draft(cid, req.actionIndex, req.channel if req.channel in ("Email", "SMS", "Phone") else "Email")
    return {**d, "verdict": pb_customers.verdict(d["checks"])}


@app.post("/api/pb/customer/{cid}/checks")
async def pb_checks(cid: str, req: OutreachDraft, user: User = Depends(current_user)) -> dict:
    _cust_or_404(cid)
    cks = pb_customers.checks(cid, req.model_dump())
    return {"checks": cks, "verdict": pb_customers.verdict(cks)}


@app.post("/api/pb/customer/{cid}/review")
async def pb_review(cid: str, req: OutreachDraft, user: User = Depends(current_user)) -> StreamingResponse:
    """Stream the Compliance Reviewer agent over a draft (deterministic checks passed in as authoritative)."""
    _cust_or_404(cid)
    d = req.model_dump()
    cks = pb_customers.checks(cid, d)
    logger.info("AUDIT compliance review by %s for %s: %s", user.upn, cid, pb_customers.verdict(cks))
    return StreamingResponse(run_agent(user, pb_customers.review_prompt(cid, d, cks), None, settings.compliance_agent_name),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/pb/customer/{cid}/memo")
async def pb_memo(cid: str, req: OutreachDraft, user: User = Depends(current_user)) -> Response:
    _cust_or_404(cid)
    d = req.model_dump()
    if not d.get("action"):
        d["action"] = {"action_type": "Service", "product_name": "Renewal conversation"}
    data = pb_customers.memo_docx(cid, d, req.notes, user.upn)
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="conversation-note-{cid}.docx"'})


@app.post("/api/pb/customer/{cid}/outlook-draft")
async def pb_outlook_draft(cid: str, req: OutreachDraft, user: User = Depends(current_user)) -> dict:
    """Save the reviewed email as a DRAFT in the signed-in user's own Outlook (delegated, no recipient, never sent)."""
    import html

    import httpx

    _cust_or_404(cid)
    d = req.model_dump()
    cks = pb_customers.checks(cid, d)
    if pb_customers.verdict(cks) == "blocked":
        raise HTTPException(status_code=409, detail="Draft is blocked by compliance checks - fix it before saving.")
    body = "".join(f"<p>{html.escape(par).replace(chr(10), '<br/>')}</p>" for par in d["body"].split("\n\n"))
    try:
        token = await exchange_obo(user, "https://graph.microsoft.com/.default")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post("https://graph.microsoft.com/v1.0/me/messages",
                                  headers={"Authorization": f"Bearer {token}"},
                                  json={"subject": d["subject"], "isDraft": True,
                                        "body": {"contentType": "HTML", "content": body}, "toRecipients": []})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Graph call failed: {str(exc)[:200]}") from exc
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"Graph {r.status_code}: {r.text[:200]}")
    logger.info("AUDIT outlook draft created by %s for %s", user.upn, cid)
    return {"saved": True, "webLink": r.json().get("webLink", ""), "note": "Saved to your Outlook Drafts - no recipient set, nothing sent."}


# --------------------------------------------------------------------------- #
# Cards book
# --------------------------------------------------------------------------- #
@app.get("/api/cards/overview")
async def cards_overview(user: User = Depends(current_user)) -> dict:
    return pb_cards.overview()


@app.get("/api/cards/market")
async def cards_market(refresh: bool = False, cached: bool = False, user: User = Depends(current_user)) -> dict:
    """Web IQ: current competitor card offers (public web, cached, internal market context only)."""
    return pb_card_market.cached() if cached else await pb_card_market.market(user, refresh=refresh)


@app.get("/api/cards/accounts")
async def cards_accounts(user: User = Depends(current_user)) -> dict:
    return pb_cards.accounts()


@app.get("/api/cards/account/{aid}")
async def cards_account(aid: str, user: User = Depends(current_user)) -> dict:
    a = pb_cards.account(aid)
    if not a:
        raise HTTPException(status_code=404, detail=f"Unknown card account {aid}")
    return a


class CardDraftRequest(BaseModel):
    playIndex: int = 0


class CardDraft(BaseModel):
    channel: str = "Email"
    purpose: str = "Service"
    subject: str = ""
    body: str = ""
    play: dict = {}


@app.post("/api/cards/account/{aid}/draft")
async def cards_draft(aid: str, req: CardDraftRequest, user: User = Depends(current_user)) -> dict:
    d = pb_cards.draft(aid, req.playIndex)
    if not d:
        raise HTTPException(status_code=404, detail=f"No plays for {aid}")
    return {**d, "verdict": pb_cards.verdict(d["checks"])}


@app.post("/api/cards/account/{aid}/checks")
async def cards_checks(aid: str, req: CardDraft, user: User = Depends(current_user)) -> dict:
    if aid not in pb_cards.ACC:
        raise HTTPException(status_code=404, detail=aid)
    cks = pb_cards.checks(aid, req.model_dump())
    return {"checks": cks, "verdict": pb_cards.verdict(cks)}


@app.post("/api/cards/account/{aid}/review")
async def cards_review(aid: str, req: CardDraft, user: User = Depends(current_user)) -> StreamingResponse:
    if aid not in pb_cards.ACC:
        raise HTTPException(status_code=404, detail=aid)
    d = req.model_dump()
    cks = pb_cards.checks(aid, d)
    logger.info("AUDIT card compliance review by %s for %s: %s", user.upn, aid, pb_cards.verdict(cks))
    return StreamingResponse(run_agent(user, pb_cards.review_prompt(aid, d, cks), None, settings.compliance_agent_name),
                             media_type="text/event-stream", headers=SSE_HEADERS)


# --------------------------------------------------------------------------- #
# Product books - Everyday banking, Borrowing, Investing, Newcomers, Insurance, Security (one contract)
# --------------------------------------------------------------------------- #
def _book_account_or_404(book: str, aid: str) -> str:
    if book not in pb_books.BOOK:
        raise HTTPException(status_code=404, detail=f"Unknown book {book}")
    resolved = pb_books.resolve(book, aid)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Unknown {book} account {aid}")
    return resolved


@app.get("/api/books")
async def books_list(user: User = Depends(current_user)) -> list:
    return pb_books.books()


@app.get("/api/books/{book}/overview")
async def books_overview(book: str, user: User = Depends(current_user)) -> dict:
    o = pb_books.overview(book)
    if not o:
        raise HTTPException(status_code=404, detail=f"Unknown book {book}")
    return o


@app.get("/api/books/{book}/accounts")
async def books_accounts(book: str, user: User = Depends(current_user)) -> dict:
    a = pb_books.accounts(book)
    if not a:
        raise HTTPException(status_code=404, detail=f"Unknown book {book}")
    return a


@app.get("/api/books/{book}/account/{aid}")
async def books_account(book: str, aid: str, user: User = Depends(current_user)) -> dict:
    return pb_books.account(book, _book_account_or_404(book, aid))


class BookDraftRequest(BaseModel):
    playIndex: int = 0


class BookDraft(BaseModel):
    channel: str = "Email"
    purpose: str = "Service"
    subject: str = ""
    body: str = ""
    play: dict = {}


@app.post("/api/books/{book}/account/{aid}/draft")
async def books_draft(book: str, aid: str, req: BookDraftRequest, user: User = Depends(current_user)) -> dict:
    d = pb_books.draft(book, _book_account_or_404(book, aid), req.playIndex)
    if not d:
        raise HTTPException(status_code=404, detail=f"No plays for {aid}")
    return d


@app.post("/api/books/{book}/account/{aid}/checks")
async def books_checks(book: str, aid: str, req: BookDraft, user: User = Depends(current_user)) -> dict:
    cks = pb_books.checks(book, _book_account_or_404(book, aid), req.model_dump())
    return {"checks": cks, "verdict": pb_books.verdict(cks)}


@app.post("/api/books/{book}/account/{aid}/review")
async def books_review(book: str, aid: str, req: BookDraft, user: User = Depends(current_user)) -> StreamingResponse:
    aid = _book_account_or_404(book, aid)
    d = req.model_dump()
    cks = pb_books.checks(book, aid, d)
    logger.info("AUDIT %s compliance review by %s for %s: %s", book, user.upn, aid, pb_books.verdict(cks))
    return StreamingResponse(run_agent(user, pb_books.review_prompt(book, aid, d, cks), None, settings.compliance_agent_name),
                             media_type="text/event-stream", headers=SSE_HEADERS)


# --------------------------------------------------------------------------- #
# Agent missions - one job per book that needs an agent, run through a visible harness
# --------------------------------------------------------------------------- #
def _mission_or_404(book: str) -> None:
    if book not in pb_missions.MISSIONS:
        raise HTTPException(status_code=404, detail=f"Unknown mission book {book}")


class MissionRun(BaseModel):
    caseId: str


class MissionDecision(BaseModel):
    runId: str
    caseId: str
    decision: str
    note: str = ""


@app.get("/api/missions")
async def missions_list(user: User = Depends(current_user)) -> list:
    return pb_missions.catalogue()


@app.get("/api/missions/{book}")
async def missions_get(book: str, user: User = Depends(current_user)) -> dict:
    _mission_or_404(book)
    return pb_missions.mission(book)


@app.post("/api/missions/{book}/run")
async def missions_run(book: str, req: MissionRun, user: User = Depends(current_user)) -> StreamingResponse:
    _mission_or_404(book)
    if not pb_missions.book_accounts(req.caseId):
        raise HTTPException(status_code=404, detail=f"Unknown client {req.caseId}")
    return StreamingResponse(pb_missions.run(user, book, req.caseId), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/missions/{book}/decision")
async def missions_decide(book: str, req: MissionDecision, user: User = Depends(current_user)) -> dict:
    _mission_or_404(book)
    if req.decision not in ("approve", "send_back", "escalate"):
        raise HTTPException(status_code=400, detail="decision must be approve, send_back or escalate")
    try:
        return pb_missions.decide(user, book, req.runId, req.caseId, req.decision, req.note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/missions/{book}/audit")
async def missions_audit(book: str, user: User = Depends(current_user)) -> list:
    _mission_or_404(book)
    return pb_missions.audit(book)


@app.get("/api/diag")
async def diag(user: User = Depends(current_user)) -> dict:
    """Walk the chain end to end and report exactly where it breaks.

    Ordered so the first failure is the actionable one: token -> OBO -> agent.
    """
    out: dict = {
        "user": {"name": user.name, "upn": user.upn},
        "settings": {
            "tenantConfigured": bool(settings.tenant_id),
            "secretConfigured": bool(settings.client_secret),
            "projectEndpoint": settings.project_endpoint or "(unset)",
            "agentName": settings.agent_name,
            "mockMode": settings.mock_mode,
        },
        "checks": [],
    }

    def add(name: str, ok: bool, detail: str = "") -> None:
        out["checks"].append({"check": name, "ok": ok, "detail": detail})

    add("token validated", True, f"scopes: {user.claims.get('scp', '')}")

    if settings.mock_mode:
        add("mock mode", True, "Azure calls are bypassed.")
        return out

    try:
        token = await exchange_obo(user)
        add("on-behalf-of exchange", True, f"scope {settings.foundry_scope}")
    except Exception as exc:  # noqa: BLE001
        add("on-behalf-of exchange", False, str(getattr(exc, "detail", exc))[:500])
        return out

    # Confirm the agent exists on the v2 (prompt agent) surface. The older
    # assistants API does not list portal-created agents at all.
    try:
        import httpx

        base = settings.project_endpoint.rstrip("/")
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.get(
                f"{base}/agents/{settings.agent_name}?api-version=v1",
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code == 200:
            body = r.json()
            ver = body.get("versions", {}).get("latest", {})
            tools = [t.get("type") for t in ver.get("definition", {}).get("tools", [])]
            add("agent found", True,
                f"version {ver.get('version', '?')} · model "
                f"{ver.get('definition', {}).get('model', '?')} · tools: "
                f"{', '.join(t for t in tools if t) or 'none listed'}")
        else:
            add("agent found", False, f"{r.status_code}: {r.text[:400]}")
    except Exception as exc:  # noqa: BLE001
        add("agent found", False, str(exc)[:400])

    return out


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):  # noqa: ANN201
    logger.exception("unhandled error on %s", request.url.path)
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=500, content={"detail": str(exc)[:500]})
