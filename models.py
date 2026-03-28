"""
Typed Pydantic models for the Incident Response Commander environment.

Defines the Action, Observation, and Reward spaces for an AI agent
acting as an on-call SRE responding to production incidents.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
#  Action Space
# ──────────────────────────────────────────────

class ActionType(str, Enum):
    """All actions available to the incident responder agent."""
    CHECK_ALERTS = "check_alerts"
    INVESTIGATE_SERVICE = "investigate_service"
    QUERY_LOGS = "query_logs"
    CHECK_METRICS = "check_metrics"
    VIEW_DEPENDENCY_GRAPH = "view_dependency_graph"
    RUN_DIAGNOSTIC = "run_diagnostic"
    CONSULT_RUNBOOK = "consult_runbook"
    APPLY_REMEDIATION = "apply_remediation"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    SCALE_SERVICE = "scale_service"
    RESTART_SERVICE = "restart_service"
    UPDATE_STATUS = "update_status"
    DECLARE_ROOT_CAUSE = "declare_root_cause"
    RESOLVE_INCIDENT = "resolve_incident"


class Action(BaseModel):
    """An action taken by the incident response agent.

    Attributes:
        action_type: The type of action to perform.
        target_service: The service to act on (required for most actions).
        parameters: Additional parameters depending on action type.

    Example parameters by action type:
        - query_logs: {"query": "error", "time_range": "1h"}
        - check_metrics: {"metric": "cpu_usage"}
        - run_diagnostic: {"diagnostic": "connection_pool_status"}
        - apply_remediation: {"action": "drain_connections", "params": {}}
        - scale_service: {"replicas": 5}
        - update_status: {"severity": "SEV1", "message": "Investigating..."}
        - declare_root_cause: {"root_cause": "connection leak in order-service"}
        - resolve_incident: {"summary": "...", "resolution": "..."}
    """
    action_type: ActionType
    target_service: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────
#  Observation Space
# ──────────────────────────────────────────────

class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class ServiceHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class Alert(BaseModel):
    """A monitoring alert fired by the infrastructure."""
    alert_id: str
    service: str
    severity: AlertSeverity
    message: str
    fired_at: str
    acknowledged: bool = False
    is_red_herring: bool = Field(default=False, exclude=True)


class ServiceStatus(BaseModel):
    """Current status of a service in the infrastructure."""
    name: str
    health: ServiceHealth
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    error_rate_percent: float = 0.0
    request_latency_p99_ms: float = 0.0
    active_connections: int = 0
    recent_deployments: List[str] = Field(default_factory=list)


class LogEntry(BaseModel):
    """A log line from a service."""
    timestamp: str
    level: str
    service: str
    message: str


class MetricDatapoint(BaseModel):
    """A single metric measurement."""
    timestamp: str
    value: float


class MetricSeries(BaseModel):
    """A time series of metric measurements."""
    metric_name: str
    service: str
    unit: str
    datapoints: List[MetricDatapoint]


class ActionResult(BaseModel):
    """Result returned after executing an action."""
    success: bool
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)
    logs: List[LogEntry] = Field(default_factory=list)
    metrics: List[MetricSeries] = Field(default_factory=list)
    services: List[ServiceStatus] = Field(default_factory=list)


class Observation(BaseModel):
    """What the agent sees after each step.

    Contains the current incident state, results of the last action,
    active alerts, and affected services.
    """
    incident_id: str
    task_id: str
    task_description: str
    severity: str
    title: str
    elapsed_minutes: int
    step_number: int
    max_steps: int
    active_alerts: List[Alert]
    affected_services: List[str]
    services_investigated: List[str] = Field(default_factory=list)
    action_result: Optional[ActionResult] = None
    available_actions: List[str] = Field(default_factory=list)
    done: bool = False
    info: Dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────
#  Reward
# ──────────────────────────────────────────────

class RewardBreakdown(BaseModel):
    """Detailed breakdown of how the reward was computed."""
    investigation_efficiency: float = Field(
        default=0.0, ge=0.0, le=0.20,
        description="Reward for investigating relevant services (0-0.20)"
    )
    root_cause_accuracy: float = Field(
        default=0.0, ge=0.0, le=0.30,
        description="Reward for correctly identifying root cause (0-0.30)"
    )
    remediation_correctness: float = Field(
        default=0.0, ge=0.0, le=0.25,
        description="Reward for applying correct fix (0-0.25)"
    )
    time_efficiency: float = Field(
        default=0.0, ge=0.0, le=0.10,
        description="Reward for resolving quickly (0-0.10)"
    )
    communication_quality: float = Field(
        default=0.0, ge=0.0, le=0.10,
        description="Reward for status update quality (0-0.10)"
    )
    safety_bonus: float = Field(
        default=0.05, ge=-0.10, le=0.05,
        description="Bonus for avoiding destructive actions on healthy services (0-0.05)"
    )


class Reward(BaseModel):
    """Reward signal for the agent's performance.

    The total score is in [0.0, 1.0] and is computed from multiple
    dimensions of incident response quality.
    """
    value: float = Field(default=0.0, ge=0.0, le=1.0)
    breakdown: RewardBreakdown = Field(default_factory=RewardBreakdown)
    step_reward: float = Field(
        default=0.0,
        description="Incremental reward earned on this step"
    )
    cumulative: float = Field(
        default=0.0,
        description="Running total reward earned so far"
    )
    feedback: str = Field(
        default="",
        description="Human-readable feedback on the agent's action"
    )


# ──────────────────────────────────────────────
#  State
# ──────────────────────────────────────────────

class State(BaseModel):
    """Full environment state returned by state()."""
    episode_id: str
    task_id: str
    step_count: int
    max_steps: int
    elapsed_minutes: int
    incident_severity: str
    incident_resolved: bool
    root_cause_declared: bool
    root_cause_correct: bool
    services_investigated: List[str]
    remediations_applied: List[str]
    status_updates_sent: int
    cumulative_reward: float
    done: bool
