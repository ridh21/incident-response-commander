"""
Client for the Incident Response Commander environment.

Extends openenv-core's EnvClient, providing both async and sync interfaces
for interacting with the environment server.

Usage (async, recommended):
    async with IncidentResponseEnv(base_url="http://localhost:7860") as client:
        result = await client.reset(task_id="task1_db_outage")
        print(result.observation.title)

        result = await client.step(Action(action_type="check_alerts"))
        print(result.reward)

        state = await client.state()
        print(state.step_count)

Usage (sync via .sync() wrapper):
    with IncidentResponseEnv(base_url="http://localhost:7860").sync() as client:
        result = client.reset(task_id="task1_db_outage")
        result = client.step(Action(action_type="check_alerts"))
"""

from openenv.core import EnvClient, StepResult

from models import Action, Observation, State


class IncidentResponseEnv(EnvClient[Action, Observation, State]):
    """OpenEnv client for the Incident Response Commander environment.

    Inherits async context manager and .sync() wrapper from EnvClient.
    Implement the three protocol methods to handle this environment's
    action/observation/state wire format.
    """

    def _step_payload(self, action: Action) -> dict:
        """Serialize an Action into the POST /step request body."""
        return {"action": action.model_dump()}

    def _parse_result(self, payload: dict) -> StepResult[Observation]:
        """Parse the POST /step (or POST /reset) response into a StepResult.

        The server returns:
            {"observation": {...}, "reward": {"value": float, ...}, "done": bool, "info": {...}}
        """
        reward_raw = payload.get("reward", {})
        if isinstance(reward_raw, dict):
            reward_value = reward_raw.get("value", 0.0)
        else:
            reward_value = float(reward_raw or 0.0)

        return StepResult(
            observation=Observation(**payload["observation"]),
            reward=reward_value,
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: dict) -> State:
        """Parse the GET /state response into a State object."""
        return State(**payload)
