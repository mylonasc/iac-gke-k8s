import asyncio
from dataclasses import dataclass
from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .agent import SandboxedReactAgent
from .auth import AnonymousIdentityConfig, AuthConfig, TokenVerifier
from .tracing import init_tracing


logger = logging.getLogger(__name__)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class AppRuntime:
    app: FastAPI
    agent: SandboxedReactAgent
    auth_config: AuthConfig
    token_verifier: TokenVerifier
    anon_identity_config: AnonymousIdentityConfig


def create_app_runtime() -> AppRuntime:
    agent = SandboxedReactAgent()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        raw_janitor_interval = os.getenv("SANDBOX_LEASE_JANITOR_INTERVAL_SECONDS", "45")
        try:
            janitor_interval = max(5, int(raw_janitor_interval))
        except (TypeError, ValueError):
            janitor_interval = 45
        janitor_enabled = _as_bool(
            os.getenv("SANDBOX_LEASE_JANITOR_ENABLED"),
            default=True,
        )
        janitor_task: asyncio.Task[None] | None = None

        async def _lease_janitor_loop() -> None:
            while True:
                await asyncio.sleep(janitor_interval)
                try:
                    released = await asyncio.to_thread(
                        agent.sandbox_lifecycle.reap_expired_leases
                    )
                    if released > 0:
                        logger.info(
                            "sandbox.lease_janitor.reaped",
                            extra={
                                "event": "sandbox.lease_janitor.reaped",
                                "released_count": released,
                            },
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("sandbox.lease_janitor.error")

        app.state.agent = agent
        agent.frontend_library_cache.ensure_libraries()
        if janitor_enabled:
            janitor_task = asyncio.create_task(_lease_janitor_loop())
        try:
            yield
        finally:
            if janitor_task is not None:
                janitor_task.cancel()
                try:
                    await janitor_task
                except asyncio.CancelledError:
                    pass
            agent.close()

    app = FastAPI(
        title="sandboxed-react-agent-backend",
        version="0.5.0",
        lifespan=lifespan,
    )
    app.mount(
        "/static/vendor",
        StaticFiles(directory=str(agent.frontend_library_cache.cache_dir)),
        name="vendor-static",
    )
    init_tracing(app)
    auth_config = AuthConfig.from_env()
    token_verifier = TokenVerifier(auth_config)
    anon_identity_config = AnonymousIdentityConfig.from_env()
    return AppRuntime(
        app=app,
        agent=agent,
        auth_config=auth_config,
        token_verifier=token_verifier,
        anon_identity_config=anon_identity_config,
    )
