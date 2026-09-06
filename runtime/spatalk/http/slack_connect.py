"""The Slack door for a clinic's own workspace: connect and callback (onboarding roadmap §3).

Button clicks and thread replies keep their own routes (:mod:`spatalk.http.slack`,
:mod:`spatalk.http.slack_events`) and the one signing secret: it is one Slack app, installed
in many workspaces. What these two routes add is the install itself, finished by
:mod:`spatalk.social.slack_oauth`. Shape copied from :mod:`spatalk.social.instagram`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from spatalk.social.meta_oauth import sign_state
from spatalk.social.slack_oauth import build_slack_start_url, complete_slack_connect

router = APIRouter()

# Who the audit trail credits a connection to. The link is opened by a signed-in portal
# owner, but the runtime sees only the signed state, so it records the door used.
CONNECTED_BY = "slack connect link"


@router.get("/slack/connect")
async def connect(request: Request, tenant: str, return_to: str | None = None):
    """Send the owner to Slack's install page with a 15-minute signed state."""
    ctx = request.app.state.ctx
    state = sign_state(ctx.settings.secret_key, tenant, return_to)
    return RedirectResponse(build_slack_start_url(ctx.settings, state), status_code=302)


@router.get("/slack/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    """Slack sends the owner back here with a code. A bad state is a 400 and stores nothing."""
    ctx = request.app.state.ctx
    if not code:
        raise HTTPException(status_code=400, detail="missing code")
    result = await complete_slack_connect(
        ctx.sf,
        ctx.settings,
        ctx.clock,
        code=code,
        state=state,
        connected_by=CONNECTED_BY,
        client=getattr(ctx, "graph", None),
    )
    if result.return_to:
        return RedirectResponse(result.return_to, status_code=302)
    return PlainTextResponse(
        f"Connected: {result.display_name}. Requests will arrive there from now on. "
        "You can close this tab."
    )
