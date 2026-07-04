from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from layoverlab.api.routes import router
from layoverlab.connectors.base import load_default_connectors
from layoverlab.settings import get_settings

app = FastAPI(title="LayoverLab API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().api_cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.on_event("startup")
def _startup() -> None:
    load_default_connectors()
