from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from telegram_service.auth import hash_password
from telegram_service.config import get_settings
from telegram_service.database import Base, SessionLocal, engine
from telegram_service.models import User
from telegram_service.routers.admin_api import router as admin_api_router
from telegram_service.routers.admin_ui import router as admin_ui_router
from telegram_service.routers.config_api import router as config_api_router
from telegram_service.routers.runtime_gateway import router as runtime_router
from telegram_service.routers.self_service_api import router as self_service_router

settings = get_settings()

app = FastAPI(title="Telegram Service Gateway", version="0.1.0")
app.include_router(admin_api_router)
app.include_router(admin_ui_router)
app.include_router(config_api_router)
app.include_router(runtime_router)
app.include_router(self_service_router)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == settings.admin_username).first()
        if not admin:
            db.add(
                User(
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                    is_admin=True,
                    is_active=True,
                )
            )
            db.commit()
    finally:
        db.close()


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/admin")


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
