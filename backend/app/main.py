from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent import router as agent_router
from app.api.center import router as center_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="HBK Panel API",
        description="提供轻量监控集群的中心节点接口，支持节点注册、Agent 推送、多节点查询与任务下发。",
        version="0.3.0",
    )

    cors_origins = os.getenv(
        "HBK_CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in cors_origins.split(",") if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(center_router)
    app.include_router(agent_router)
    return app


app = create_app()
