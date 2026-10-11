from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from app.core.config import settings
from app.core.db import engine, init_db
from app.api.routes import accounts, projects, workspace, entry
from app.runtime_identity import health_identity

@asynccontextmanager
async def lifespan(app):
    with Session(engine) as session:
        init_db(session)
    yield

app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.FRONTEND_HOST], allow_credentials=False, allow_methods=["GET","POST","PATCH","PUT","DELETE"], allow_headers=["Authorization","Content-Type"])
app.include_router(accounts.router, prefix=settings.API_V1_STR)
app.include_router(projects.router, prefix=settings.API_V1_STR)
app.include_router(workspace.router, prefix=settings.API_V1_STR)
app.include_router(entry.router, prefix=settings.API_V1_STR)

@app.get("/api/v1/health")
def health():
    return health_identity()

FRONTEND = Path(__file__).parent / "frontend"
app.mount("/assets", StaticFiles(directory=FRONTEND / "assets", check_dir=False), name="assets")

@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("api/") or not (FRONTEND / "index.html").exists():
        raise HTTPException(404, "页面不存在；请先构建前端")
    return FileResponse(FRONTEND / "index.html")
