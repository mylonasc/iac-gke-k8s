from dataclasses import dataclass
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .agent import SandboxedReactAgent
from .auth import AnonymousIdentityConfig, AuthConfig, TokenVerifier
from .tracing import init_tracing


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
        app.state.agent = agent
        agent.frontend_library_cache.ensure_libraries()
        yield

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
