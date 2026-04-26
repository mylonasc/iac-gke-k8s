from fastapi import FastAPI

from onboarding_client.database import Base, engine
from onboarding_client.routers.admin_api import router as admin_api_router
from onboarding_client.routers.public import router as public_router
from onboarding_client.routers.runtime_api import router as runtime_api_router

app = FastAPI(title="Onboarding Client", version="0.1.0")
app.include_router(public_router)
app.include_router(admin_api_router)
app.include_router(runtime_api_router)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
