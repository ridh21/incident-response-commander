"""
Base class for incident scenarios.

Each scenario defines the simulated infrastructure state, alert timeline,
expected investigation path, correct root cause, and valid remediations.
"""

from __future__ import annotations
import json
import os
import copy
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Set, Tuple

from models import (
    Action, ActionType, Observation, Reward, RewardBreakdown, State,
    Alert, AlertSeverity, ServiceStatus, ServiceHealth,
    LogEntry, MetricDatapoint, MetricSeries, ActionResult,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


def _load_json(filename: str) -> dict:
    with open(os.path.join(DATA_DIR, filename)) as f:
        return json.load(f)


class BaseScenario(ABC):
    """Abstract base for an incident scenario."""

    # ── Subclass must define ────────────────────────
    task_id: str = ""
    task_description: str = ""
    difficulty: str = ""  # easy, medium, hard
    incident_title: str = ""
    initial_severity: str = "SEV2"
    max_steps: int = 30

    # Expected investigation & resolution
    root_cause_service: str = ""
    root_cause_description: str = ""
    root_cause_keywords: List[str] = []
    relevant_services: List[str] = []
    correct_remediations: List[Tuple[str, str]] = []  # (service, action_type)
    required_diagnostics: List[Tuple[str, str]] = []  # (service, diagnostic)

    def __init__(self):
        self.service_graph = _load_json("service_graph.json")
        self.runbooks = _load_json("runbooks.json")

        # Episode state
        self.step_count = 0
        self.elapsed_minutes = 0
        self.done = False

        # Tracking
        self.services_investigated: Set[str] = set()
        self.diagnostics_run: List[Tuple[str, str]] = []
        self.remediations_applied: List[Tuple[str, str]] = []
        self.status_updates: List[str] = []
        self.root_cause_declared: Optional[str] = None
        self.root_cause_correct = False
        self.incident_resolved = False
        self.destructive_on_healthy: int = 0
        self.alerts_acknowledged: Set[str] = set()

        # Reward accumulation
        self.cumulative_reward = 0.0
        self.reward_breakdown = RewardBreakdown()

        # Service states (will be overridden by subclasses)
        self._service_states: Dict[str, Dict[str, Any]] = {}
        self._active_alerts: List[Alert] = []
        self._alert_timeline: List[Tuple[int, Alert]] = []  # (step, alert)

        # Initialize service states from graph baseline
        for svc_name, svc_info in self.service_graph["services"].items():
            self._service_states[svc_name] = {
                **svc_info["baseline_metrics"],
                "health": "healthy",
                "recent_deployments": [],
            }

    # ── Subclass hooks ──────────────────────────────

    @abstractmethod
    def setup(self):
        """Set up the incident: override service states, create alerts, etc."""
        ...

    @abstractmethod
    def get_logs(self, service: str, query: str = "", time_range: str = "1h") -> List[LogEntry]:
        """Return simulated logs for a service."""
        ...

    @abstractmethod
    def get_metrics(self, service: str, metric: str) -> List[MetricSeries]:
        """Return simulated metric time series."""
        ...

    @abstractmethod
    def run_diagnostic(self, service: str, diagnostic: str) -> ActionResult:
        """Run a specific diagnostic on a service."""
        ...

    @abstractmethod
    def apply_remediation(self, service: str, remediation: str, params: dict) -> ActionResult:
        """Apply a remediation action to a service."""
        ...

    def on_step(self, step: int):
        """Called each step — subclass can inject new alerts or escalate."""
        for trigger_step, alert in self._alert_timeline:
            if trigger_step == step and alert.alert_id not in {a.alert_id for a in self._active_alerts}:
                self._active_alerts.append(alert)

    # ── Core API ────────────────────────────────────

    def reset(self) -> Observation:
        self.__init__()
        self.setup()
        return self._make_observation(None)

    def step(self, action: Action) -> Tuple[Observation, Reward, bool, Dict[str, Any]]:
        if self.done:
            return (
                self._make_observation(ActionResult(success=False, message="Incident already resolved.")),
                self._make_reward(0.0, "Incident already resolved."),
                True,
                {"reason": "already_done"},
            )

        self.step_count += 1
        self.elapsed_minutes += 3  # each step ~3 minutes of simulated time
        self.on_step(self.step_count)

        result = self._execute_action(action)
        step_reward = self._compute_step_reward(action, result)
        self.cumulative_reward = min(1.0, self.cumulative_reward + step_reward)

        if self.step_count >= self.max_steps and not self.done:
            self.done = True

        obs = self._make_observation(result)
        reward = self._make_reward(step_reward, result.message)
        info = {
            "step": self.step_count,
            "action_type": action.action_type.value,
            "action_success": result.success,
        }

        return obs, reward, self.done, info

    def get_state(self) -> State:
        return State(
            episode_id=f"{self.task_id}_ep",
            task_id=self.task_id,
            step_count=self.step_count,
            max_steps=self.max_steps,
            elapsed_minutes=self.elapsed_minutes,
            incident_severity=self.initial_severity,
            incident_resolved=self.incident_resolved,
            root_cause_declared=self.root_cause_declared is not None,
            root_cause_correct=self.root_cause_correct,
            services_investigated=list(self.services_investigated),
            remediations_applied=[f"{s}:{a}" for s, a in self.remediations_applied],
            status_updates_sent=len(self.status_updates),
            cumulative_reward=round(self.cumulative_reward, 4),
            done=self.done,
        )

    # ── Action dispatch ─────────────────────────────

    def _execute_action(self, action: Action) -> ActionResult:
        t = action.action_type
        svc = action.target_service
        params = action.parameters

        if t == ActionType.CHECK_ALERTS:
            return self._handle_check_alerts()
        elif t == ActionType.INVESTIGATE_SERVICE:
            return self._handle_investigate(svc)
        elif t == ActionType.QUERY_LOGS:
            return self._handle_query_logs(svc, params.get("query", ""), params.get("time_range", "1h"))
        elif t == ActionType.CHECK_METRICS:
            return self._handle_check_metrics(svc, params.get("metric", "all"))
        elif t == ActionType.VIEW_DEPENDENCY_GRAPH:
            return self._handle_view_deps(svc)
        elif t == ActionType.RUN_DIAGNOSTIC:
            return self._handle_diagnostic(svc, params.get("diagnostic", "health_check"))
        elif t == ActionType.CONSULT_RUNBOOK:
            return self._handle_runbook(svc)
        elif t == ActionType.APPLY_REMEDIATION:
            return self._handle_remediation(svc, params.get("action", ""), params.get("params", {}))
        elif t == ActionType.ROLLBACK_DEPLOYMENT:
            return self._handle_rollback(svc)
        elif t == ActionType.SCALE_SERVICE:
            return self._handle_scale(svc, params.get("replicas", 3))
        elif t == ActionType.RESTART_SERVICE:
            return self._handle_restart(svc)
        elif t == ActionType.UPDATE_STATUS:
            return self._handle_status_update(params.get("severity", "SEV2"), params.get("message", ""))
        elif t == ActionType.DECLARE_ROOT_CAUSE:
            return self._handle_declare_root_cause(params.get("root_cause", ""))
        elif t == ActionType.RESOLVE_INCIDENT:
            return self._handle_resolve(params.get("summary", ""), params.get("resolution", ""))
        else:
            return ActionResult(success=False, message=f"Unknown action type: {t}")

    def _valid_service(self, svc: Optional[str]) -> bool:
        return svc is not None and svc in self.service_graph["services"]

    def _handle_check_alerts(self) -> ActionResult:
        visible_alerts = [a.model_dump(exclude={"is_red_herring"}) for a in self._active_alerts]
        return ActionResult(
            success=True,
            message=f"{len(self._active_alerts)} active alert(s).",
            data={"alerts": visible_alerts},
        )

    def _handle_investigate(self, svc: Optional[str]) -> ActionResult:
        if not self._valid_service(svc):
            return ActionResult(success=False, message=f"Unknown service: {svc}")
        self.services_investigated.add(svc)
        state = self._service_states[svc]
        info = self.service_graph["services"][svc]
        status = ServiceStatus(
            name=svc,
            health=ServiceHealth(state["health"]),
            cpu_percent=state["cpu_percent"],
            memory_percent=state["memory_percent"],
            error_rate_percent=state["error_rate_percent"],
            request_latency_p99_ms=state["request_latency_p99_ms"],
            active_connections=state.get("active_connections", 0),
            recent_deployments=state.get("recent_deployments", []),
        )
        return ActionResult(
            success=True,
            message=f"Service {svc}: {state['health']}",
            data={
                "description": info["description"],
                "team": info["team"],
                "tier": info["tier"],
                "dependencies": info["dependencies"],
            },
            services=[status],
        )

    def _handle_query_logs(self, svc: Optional[str], query: str, time_range: str) -> ActionResult:
        if not self._valid_service(svc):
            return ActionResult(success=False, message=f"Unknown service: {svc}")
        self.services_investigated.add(svc)
        logs = self.get_logs(svc, query, time_range)
        return ActionResult(
            success=True,
            message=f"Retrieved {len(logs)} log entries from {svc}.",
            logs=logs,
        )

    def _handle_check_metrics(self, svc: Optional[str], metric: str) -> ActionResult:
        if not self._valid_service(svc):
            return ActionResult(success=False, message=f"Unknown service: {svc}")
        self.services_investigated.add(svc)
        series = self.get_metrics(svc, metric)
        return ActionResult(
            success=True,
            message=f"Retrieved {len(series)} metric series for {svc}.",
            metrics=series,
        )

    def _handle_view_deps(self, svc: Optional[str]) -> ActionResult:
        if svc and not self._valid_service(svc):
            return ActionResult(success=False, message=f"Unknown service: {svc}")
        if svc:
            deps = self.service_graph["services"][svc]["dependencies"]
            edges = [e for e in self.service_graph["dependency_edges"] if e["from"] == svc or e["to"] == svc]
        else:
            deps = list(self.service_graph["services"].keys())
            edges = self.service_graph["dependency_edges"]
        return ActionResult(
            success=True,
            message=f"Dependency graph{'  for ' + svc if svc else ''}.",
            data={"services": deps, "edges": edges},
        )

    def _handle_diagnostic(self, svc: Optional[str], diagnostic: str) -> ActionResult:
        if not self._valid_service(svc):
            return ActionResult(success=False, message=f"Unknown service: {svc}")
        self.services_investigated.add(svc)
        self.diagnostics_run.append((svc, diagnostic))
        return self.run_diagnostic(svc, diagnostic)

    def _handle_runbook(self, svc: Optional[str]) -> ActionResult:
        if svc and svc not in self.runbooks:
            return ActionResult(success=False, message=f"No runbook found for: {svc}")
        if svc:
            rb = self.runbooks[svc]
        else:
            rb = {k: v["title"] for k, v in self.runbooks.items()}
        return ActionResult(
            success=True,
            message=f"Runbook for {svc}." if svc else "Available runbooks.",
            data={"runbook": rb},
        )

    def _handle_remediation(self, svc: Optional[str], action_name: str, params: dict) -> ActionResult:
        if not self._valid_service(svc):
            return ActionResult(success=False, message=f"Unknown service: {svc}")
        self.remediations_applied.append((svc, action_name))
        if self._service_states[svc]["health"] == "healthy" and svc not in self.relevant_services:
            self.destructive_on_healthy += 1
        return self.apply_remediation(svc, action_name, params)

    def _handle_rollback(self, svc: Optional[str]) -> ActionResult:
        if not self._valid_service(svc):
            return ActionResult(success=False, message=f"Unknown service: {svc}")
        self.remediations_applied.append((svc, "rollback"))
        if self._service_states[svc]["health"] == "healthy" and svc not in self.relevant_services:
            self.destructive_on_healthy += 1
        return self.apply_remediation(svc, "rollback", {})

    def _handle_scale(self, svc: Optional[str], replicas: int) -> ActionResult:
        if not self._valid_service(svc):
            return ActionResult(success=False, message=f"Unknown service: {svc}")
        self.remediations_applied.append((svc, "scale"))
        return ActionResult(
            success=True,
            message=f"Scaled {svc} to {replicas} replicas.",
            data={"service": svc, "replicas": replicas},
        )

    def _handle_restart(self, svc: Optional[str]) -> ActionResult:
        if not self._valid_service(svc):
            return ActionResult(success=False, message=f"Unknown service: {svc}")
        self.remediations_applied.append((svc, "restart"))
        if self._service_states[svc]["health"] == "healthy" and svc not in self.relevant_services:
            self.destructive_on_healthy += 1
        return ActionResult(
            success=True,
            message=f"Restarted {svc}. Service coming back online.",
            data={"service": svc, "status": "restarting"},
        )

    def _handle_status_update(self, severity: str, message: str) -> ActionResult:
        if not message.strip():
            return ActionResult(success=False, message="Status update must include a message.")
        self.status_updates.append(message)
        return ActionResult(
            success=True,
            message=f"Status update posted (severity: {severity}).",
            data={"severity": severity, "update": message},
        )

    def _handle_declare_root_cause(self, root_cause: str) -> ActionResult:
        if not root_cause.strip():
            return ActionResult(success=False, message="Root cause description cannot be empty.")
        self.root_cause_declared = root_cause
        rc_lower = root_cause.lower()
        matched = sum(1 for kw in self.root_cause_keywords if kw.lower() in rc_lower)
        self.root_cause_correct = matched >= max(1, len(self.root_cause_keywords) // 2)
        if self.root_cause_correct:
            msg = "Root cause declared and matches known cause."
        else:
            msg = "Root cause declared but does not match known cause."
        return ActionResult(success=True, message=msg, data={"correct": self.root_cause_correct})

    def _handle_resolve(self, summary: str, resolution: str) -> ActionResult:
        has_root_cause = self.root_cause_declared is not None
        has_remediation = len(self.remediations_applied) > 0
        if not has_root_cause:
            return ActionResult(
                success=False,
                message="Cannot resolve incident without declaring root cause first."
            )
        if not has_remediation:
            return ActionResult(
                success=False,
                message="Cannot resolve incident without applying at least one remediation."
            )
        self.incident_resolved = True
        self.done = True
        return ActionResult(
            success=True,
            message="Incident resolved.",
            data={"summary": summary, "resolution": resolution},
        )

    # ── Reward computation ──────────────────────────

    def _compute_step_reward(self, action: Action, result: ActionResult) -> float:
        reward = 0.0
        t = action.action_type
        svc = action.target_service

        # Investigation of a relevant service
        if t in (ActionType.INVESTIGATE_SERVICE, ActionType.QUERY_LOGS,
                 ActionType.CHECK_METRICS, ActionType.RUN_DIAGNOSTIC):
            if svc in self.relevant_services:
                reward += 0.02
                self.reward_breakdown.investigation_efficiency = min(
                    0.20, self.reward_breakdown.investigation_efficiency + 0.02
                )
            else:
                reward += 0.005  # small reward for any investigation

        # Checking alerts is always useful early
        if t == ActionType.CHECK_ALERTS and self.step_count <= 3:
            reward += 0.01

        # Correct root cause declaration
        if t == ActionType.DECLARE_ROOT_CAUSE and self.root_cause_correct:
            reward += 0.25
            self.reward_breakdown.root_cause_accuracy = 0.30
        elif t == ActionType.DECLARE_ROOT_CAUSE and not self.root_cause_correct:
            reward += 0.05  # partial credit for attempting
            self.reward_breakdown.root_cause_accuracy = max(
                self.reward_breakdown.root_cause_accuracy, 0.05
            )

        # Correct remediation
        if t in (ActionType.APPLY_REMEDIATION, ActionType.ROLLBACK_DEPLOYMENT,
                 ActionType.RESTART_SERVICE, ActionType.SCALE_SERVICE):
            remediation_key = (svc, t.value if t != ActionType.APPLY_REMEDIATION
                               else action.parameters.get("action", ""))
            if any(svc == cs and (t.value == ca or action.parameters.get("action", "") == ca)
                   for cs, ca in self.correct_remediations):
                reward += 0.10
                self.reward_breakdown.remediation_correctness = min(
                    0.25, self.reward_breakdown.remediation_correctness + 0.10
                )

        # Status updates
        if t == ActionType.UPDATE_STATUS:
            reward += 0.02
            self.reward_breakdown.communication_quality = min(
                0.10, self.reward_breakdown.communication_quality + 0.02
            )

        # Incident resolution
        if t == ActionType.RESOLVE_INCIDENT and self.incident_resolved:
            # Time efficiency bonus
            steps_used_ratio = self.step_count / self.max_steps
            if steps_used_ratio < 0.4:
                time_bonus = 0.10
            elif steps_used_ratio < 0.6:
                time_bonus = 0.07
            elif steps_used_ratio < 0.8:
                time_bonus = 0.04
            else:
                time_bonus = 0.01
            self.reward_breakdown.time_efficiency = time_bonus
            reward += time_bonus

        # Safety penalty
        if self.destructive_on_healthy > 0:
            penalty = min(0.10, self.destructive_on_healthy * 0.03)
            self.reward_breakdown.safety_bonus = max(-0.10, 0.05 - penalty)

        return round(reward, 4)

    # ── Observation construction ────────────────────

    def _make_observation(self, result: Optional[ActionResult]) -> Observation:
        visible_alerts = [
            Alert(**{k: v for k, v in a.model_dump().items() if k != "is_red_herring"})
            for a in self._active_alerts
        ]
        return Observation(
            incident_id=f"INC-{self.task_id.upper().replace('_', '-')}",
            task_id=self.task_id,
            task_description=self.task_description,
            severity=self.initial_severity,
            title=self.incident_title,
            elapsed_minutes=self.elapsed_minutes,
            step_number=self.step_count,
            max_steps=self.max_steps,
            active_alerts=visible_alerts,
            affected_services=[s for s, st in self._service_states.items() if st["health"] != "healthy"],
            services_investigated=list(self.services_investigated),
            action_result=result,
            available_actions=[a.value for a in ActionType],
            done=self.done,
            info={"elapsed_minutes": self.elapsed_minutes},
        )

    def _make_reward(self, step_reward: float, feedback: str) -> Reward:
        return Reward(
            value=round(self.cumulative_reward, 4),
            breakdown=self.reward_breakdown.model_copy(),
            step_reward=round(step_reward, 4),
            cumulative=round(self.cumulative_reward, 4),
            feedback=feedback,
        )
