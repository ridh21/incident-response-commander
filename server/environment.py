"""
Main Environment class for the Incident Response Commander.

Implements the OpenEnv interface: reset(), step(), state().
Delegates to scenario instances for task-specific logic.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, Tuple

from openenv.core.env_server import Environment

from models import Action, Observation, Reward, State
from server.scenarios import SCENARIOS, BaseScenario
from server.grader import compute_final_grade


class IncidentResponseEnv(Environment):
    """OpenEnv-compatible environment for incident response training.

    Supports 3 tasks with increasing difficulty:
      - task1_db_outage (easy): Database connection pool exhaustion
      - task2_cascade_failure (medium): Multi-service cascading failure
      - task3_data_corruption (hard): Data inconsistency from deployment race condition
    """

    AVAILABLE_TASKS = list(SCENARIOS.keys())

    def __init__(self):
        self._scenario: Optional[BaseScenario] = None
        self._current_task: Optional[str] = None
        self._episode_count = 0

    def reset(self, task_id: Optional[str] = None) -> Observation:
        """Reset the environment and start a new incident.

        Args:
            task_id: Which task to load. Defaults to task1_db_outage.
                     One of: task1_db_outage, task2_cascade_failure, task3_data_corruption.

        Returns:
            Initial observation with incident context and active alerts.
        """
        if task_id is None:
            task_id = self.AVAILABLE_TASKS[0]

        if task_id not in SCENARIOS:
            raise ValueError(
                f"Unknown task: {task_id}. Available: {self.AVAILABLE_TASKS}"
            )

        self._current_task = task_id
        self._scenario = SCENARIOS[task_id]()
        self._episode_count += 1
        return self._scenario.reset()

    def step(self, action: Action) -> Tuple[Observation, Reward, bool, Dict[str, Any]]:
        """Execute an action and return the result.

        Args:
            action: The agent's action (see Action model for available types).

        Returns:
            Tuple of (observation, reward, done, info).
        """
        if self._scenario is None:
            raise RuntimeError("Environment not initialized. Call reset() first.")

        obs, reward, done, info = self._scenario.step(action)

        # Compute final grade when episode ends
        if done:
            final_reward = compute_final_grade(self._scenario)
            reward = final_reward
            info["final_score"] = final_reward.value
            info["score_breakdown"] = final_reward.breakdown.model_dump()

        return obs, reward, done, info

    @property
    def state(self) -> State:
        """Return the current environment state."""
        if self._scenario is None:
            return State(
                episode_id="none",
                task_id="none",
                step_count=0,
                max_steps=0,
                elapsed_minutes=0,
                incident_severity="NONE",
                incident_resolved=False,
                root_cause_declared=False,
                root_cause_correct=False,
                services_investigated=[],
                remediations_applied=[],
                status_updates_sent=0,
                cumulative_reward=0.0,
                done=False,
            )
        return self._scenario.get_state()

    def metadata(self) -> Dict[str, Any]:
        """Return environment metadata."""
        return {
            "name": "incident-response-commander",
            "version": "1.0.0",
            "description": (
                "Production incident response environment. An AI agent acts as an "
                "on-call SRE, diagnosing and resolving infrastructure incidents "
                "across a realistic microservice architecture."
            ),
            "author": "Ridham Patel",
            "tasks": [
                {
                    "id": "task1_db_outage",
                    "name": "Database Connection Pool Exhaustion",
                    "difficulty": "easy",
                    "max_steps": 25,
                    "description": "Diagnose and fix a connection leak causing DB pool exhaustion.",
                },
                {
                    "id": "task2_cascade_failure",
                    "name": "Cascading Service Failure",
                    "difficulty": "medium",
                    "max_steps": 30,
                    "description": "Trace a cascading failure across 4+ services to the root cause.",
                },
                {
                    "id": "task3_data_corruption",
                    "name": "Data Inconsistency from Deployment",
                    "difficulty": "hard",
                    "max_steps": 35,
                    "description": "Identify and remediate data corruption from a deployment race condition.",
                },
            ],
            "action_space": {
                "type": "IncidentAction",
                "action_types": [at.value for at in __import__("models").ActionType],
            },
            "observation_space": {
                "type": "IncidentObservation",
                "includes": [
                    "incident_context", "active_alerts", "affected_services",
                    "action_result", "step_progress",
                ],
            },
            "reward_range": [0.0, 1.0],
            "reward_dimensions": [
                "investigation_efficiency", "root_cause_accuracy",
                "remediation_correctness", "time_efficiency",
                "communication_quality", "safety_bonus",
            ],
        }

    def schema(self) -> Dict[str, Any]:
        """Return JSON schemas for Action and Observation."""
        return {
            "action": Action.model_json_schema(),
            "observation": Observation.model_json_schema(),
            "reward": Reward.model_json_schema(),
            "state": State.model_json_schema(),
        }
