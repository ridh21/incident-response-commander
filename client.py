"""
Client for the Incident Response Commander environment.

Provides both sync and async interfaces for interacting with the
environment server over HTTP.
"""

from __future__ import annotations
import requests
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

from models import Action, Observation, Reward, State


@dataclass
class StepResult:
    """Result from a single environment step."""
    observation: Observation
    reward: Reward
    done: bool
    info: Dict[str, Any]


class IncidentResponseClient:
    """Synchronous HTTP client for the Incident Response Commander environment.

    Usage:
        client = IncidentResponseClient("http://localhost:7860")
        obs = client.reset(task_id="task1_db_outage")
        result = client.step(Action(action_type="check_alerts"))
        state = client.state()
    """

    def __init__(self, base_url: str = "http://localhost:7860"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def health(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/health")
        resp.raise_for_status()
        return resp.json()

    def metadata(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/metadata")
        resp.raise_for_status()
        return resp.json()

    def schema(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.base_url}/schema")
        resp.raise_for_status()
        return resp.json()

    def reset(self, task_id: Optional[str] = None) -> Observation:
        payload = {}
        if task_id:
            payload["task_id"] = task_id
        resp = self.session.post(f"{self.base_url}/reset", json=payload)
        resp.raise_for_status()
        return Observation(**resp.json())

    def step(self, action: Action) -> StepResult:
        resp = self.session.post(
            f"{self.base_url}/step",
            json={"action": action.model_dump()},
        )
        resp.raise_for_status()
        data = resp.json()
        return StepResult(
            observation=Observation(**data["observation"]),
            reward=Reward(**data["reward"]),
            done=data["done"],
            info=data["info"],
        )

    def state(self) -> State:
        resp = self.session.get(f"{self.base_url}/state")
        resp.raise_for_status()
        return State(**resp.json())

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
