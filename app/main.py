from fastapi import FastAPI

from app.api import evaluation, health, sessions
from app.core.config import settings

app = FastAPI(title=settings.PROJECT_NAME)

app.include_router(health.router)
app.include_router(sessions.router)
app.include_router(evaluation.router)
