"""FastAPI application assembly: create app, include routers, setup middleware."""

import logging

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI 토론 시뮬레이터 Final", version="4.0")

# Middleware (order matters: security headers wrap CORS)
from api.middleware import setup_cors, setup_security_headers

setup_security_headers(app)
setup_cors(app)

# Routers
from api.routes.debate import router as debate_router
from api.routes.health import router as health_router
from api.routes.models import router as models_router
from api.ws import router as ws_router

app.include_router(debate_router)
app.include_router(health_router)
app.include_router(models_router)
app.include_router(ws_router)
