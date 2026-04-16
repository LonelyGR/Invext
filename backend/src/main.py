"""
Точка входа FastAPI. Подключение роутеров и логирование.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.core.config import get_settings
from src.core.logging_config import setup_logging
from src.api.routers import (
    auth,
    wallet,
    user_wallets,
    withdrawals,
    admin,
    invest,
    admin_balance,
    admin_dashboard,
    payments,
    settings,
)
from src.core.admin_middleware import admin_jwt_middleware
from src.db.session import async_session_maker
from src.services.deal_scheduler import init_deal_scheduler

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализация планировщика сделок.
    scheduler = AsyncIOScheduler()
    init_deal_scheduler(scheduler, async_session_maker)
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title=get_settings().project_name,
    description="API для бота-кошелька Invext",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JWT + IP-защита для /database/api/*
app.middleware("http")(admin_jwt_middleware)

app.include_router(auth.router)
app.include_router(wallet.router)
app.include_router(user_wallets.router)
app.include_router(withdrawals.router)
app.include_router(admin.router)
app.include_router(invest.router)
app.include_router(payments.router)
app.include_router(admin_balance.router)
app.include_router(admin_dashboard.router)
app.include_router(settings.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
