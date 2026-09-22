from greennode_agentbase import GreenNodeAgentBaseApp, RequestContext, PingStatus
from dotenv import load_dotenv

load_dotenv()

app = GreenNodeAgentBaseApp()

from app.api.server import create_app
fastapi_app = create_app()
app.mount("/", fastapi_app)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    """POST /invocations — non-streaming gateway for Zalo/external APIs."""
    from app.agent.orchestrator import Orchestrator
    orch = Orchestrator.from_env()
    result = orch.answer(
        payload.get("message", ""),
        history=payload.get("history", []),
        user_id=context.user_id,
        session_id=context.session_id,
    )
    return result.to_invocation_response()


@app.ping
def health_check() -> PingStatus:
    """GET /health — only checks process is alive, NEVER touches DB."""
    return PingStatus.HEALTHY


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
