"""
FastAPI server for the Incident Response Commander environment.

Exposes the OpenEnv-compliant HTTP API:
  GET  /health    → health check
  GET  /metadata  → environment metadata
  GET  /schema    → JSON schemas for Action/Observation/Reward
  POST /reset     → reset environment (start new incident)
  POST /step      → execute an action
  GET  /state     → get current state
"""

import sys
import os

# Ensure project root is on the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any

from models import Action, Observation, Reward, State
from server.environment import IncidentResponseEnv

app = FastAPI(
    title="Incident Response Commander",
    description=(
        "An OpenEnv environment simulating production incident response. "
        "AI agents act as on-call SREs diagnosing and resolving infrastructure incidents."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single environment instance (stateful per session)
env = IncidentResponseEnv()


# ── Request/Response models ─────────────────────

class ResetRequest(BaseModel):
    task_id: Optional[str] = None


class StepRequest(BaseModel):
    action: Action


class StepResponse(BaseModel):
    observation: Observation
    reward: Reward
    done: bool
    info: Dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str


# ── Endpoints ───────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        environment="incident-response-commander",
        version="1.0.0",
    )


@app.get("/")
async def root():
    return {
        "status": "ok",
        "environment": "incident-response-commander",
        "version": "1.0.0",
        "endpoints": ["/health", "/metadata", "/schema", "/reset", "/step", "/state"],
    }


@app.get("/metadata")
async def metadata():
    return env.metadata()


@app.get("/schema")
async def schema():
    return env.schema()


@app.post("/reset", response_model=Observation)
async def reset(request: ResetRequest = ResetRequest()):
    try:
        obs = env.reset(task_id=request.task_id)
        return obs
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/step", response_model=StepResponse)
async def step(request: StepRequest):
    try:
        obs, reward, done, info = env.step(request.action)
        return StepResponse(
            observation=obs,
            reward=reward,
            done=done,
            info=info,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/state", response_model=State)
async def state():
    return env.state()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)
