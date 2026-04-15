import asyncio
from dataclasses import dataclass
from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .agent import SandboxedReactAgent
from .authz import AuthorizationPolicyService
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
    authorization_service: AuthorizationPolicyService


def create_app_runtime() -> AppRuntime:
    authorization_service = AuthorizationPolicyService.from_env()
    agent = SandboxedReactAgent(authorization_service=authorization_service)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        raw_reaper_interval = os.getenv(
            "SANDBOX_LEASE_REAPER_INTERVAL_SECONDS",
            os.getenv("SANDBOX_LEASE_JANITOR_INTERVAL_SECONDS", "15"),
        )
        try:
            reaper_interval = max(5, int(raw_reaper_interval))
        except (TypeError, ValueError):
            reaper_interval = 15
        reaper_enabled = _as_bool(
            os.getenv(
                "SANDBOX_LEASE_REAPER_ENABLED",
                os.getenv("SANDBOX_LEASE_JANITOR_ENABLED"),
            ),
            default=True,
        )
        raw_pending_ttl = os.getenv("SANDBOX_PENDING_LEASE_REAPER_TTL_SECONDS")
        try:
            pending_ttl_override = (
                int(raw_pending_ttl) if raw_pending_ttl is not None else None
            )
        except (TypeError, ValueError):
            pending_ttl_override = None
        reaper_task: asyncio.Task[None] | None = None
        authz_refresh_task: asyncio.Task[None] | None = None
        authz_refresh_interval_raw = os.getenv("AUTHZ_REFRESH_INTERVAL_SECONDS", "30")
        try:
            authz_refresh_interval = max(5, int(authz_refresh_interval_raw))
        except (TypeError, ValueError):
            authz_refresh_interval = 30

        async def _lease_reaper_loop() -> None:
            while True:
                try:
                    counts = await asyncio.to_thread(
                        agent.sandbox_lifecycle.run_reaper_cycle,
                        pending_lease_ttl_seconds=pending_ttl_override,
                    )
                    if counts.get("released_total", 0) > 0:
                        logger.info(
                            "sandbox.lease_reaper.reaped",
                            extra={
                                "event": "sandbox.lease_reaper.reaped",
                                "released_total": counts.get("released_total", 0),
                                "expired_released": counts.get("expired", 0),
                                "pending_released": counts.get("pending", 0),
                            },
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("sandbox.lease_reaper.error")
                await asyncio.sleep(reaper_interval)

        app.state.agent = agent
        app.state.authorization_service = authorization_service
        agent.frontend_library_cache.ensure_libraries()

        async def _authz_refresh_loop() -> None:
            while True:
                try:
                    await asyncio.to_thread(authorization_service.refresh_from_remote)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("authz.policy.refresh_loop_error")
                await asyncio.sleep(authz_refresh_interval)

        if reaper_enabled:
            reaper_task = asyncio.create_task(_lease_reaper_loop())
        if authorization_service.remote_policy_url:
            try:
                await asyncio.to_thread(authorization_service.refresh_from_remote)
            except Exception:
                logger.exception("authz.policy.initial_refresh_failed")
            authz_refresh_task = asyncio.create_task(_authz_refresh_loop())
        try:
            yield
        finally:
            if authz_refresh_task is not None:
                authz_refresh_task.cancel()
                try:
                    await authz_refresh_task
                except asyncio.CancelledError:
                    pass
            if reaper_task is not None:
                reaper_task.cancel()
                try:
                    await reaper_task
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
        authorization_service=authorization_service,
    )
