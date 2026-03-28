"""
Task 1 (Easy): Database Connection Pool Exhaustion

Scenario: order-service deployed a new version with a connection leak.
Connections to database-primary grow unbounded. Once the pool (max 200)
is saturated, order-service and user-service start failing.

Root cause: order-service deployment v2.4.1 has a connection leak.
Fix: Rollback order-service, then restart database-primary to clear stale connections.
"""

from __future__ import annotations
from typing import List
from .base import BaseScenario
from models import (
    Alert, AlertSeverity, LogEntry, MetricSeries, MetricDatapoint, ActionResult,
)


class DbConnectionOutage(BaseScenario):
    task_id = "task1_db_outage"
    task_description = (
        "A database connection pool exhaustion incident. The order-service "
        "deployed 45 minutes ago and database connections are saturated. "
        "Order creation and user lookups are failing. Diagnose the root cause, "
        "apply the correct remediation, and resolve the incident."
    )
    difficulty = "easy"
    incident_title = "Database connection pool exhausted — order and user failures"
    initial_severity = "SEV2"
    max_steps = 25

    root_cause_service = "order-service"
    root_cause_description = "Connection leak in order-service v2.4.1 deployment"
    root_cause_keywords = ["connection", "leak", "order-service", "v2.4.1"]
    relevant_services = [
        "order-service", "database-primary", "user-service", "api-gateway"
    ]
    correct_remediations = [
        ("order-service", "rollback"),
        ("database-primary", "restart"),
        ("order-service", "rollback_deployment"),
    ]
    required_diagnostics = [
        ("database-primary", "connection_pool_status"),
        ("order-service", "connection_pool_status"),
    ]

    def setup(self):
        # order-service: degraded, leaking connections
        self._service_states["order-service"].update({
            "health": "degraded",
            "cpu_percent": 55.0,
            "memory_percent": 72.0,
            "error_rate_percent": 35.0,
            "request_latency_p99_ms": 8500.0,
            "active_connections": 195,
            "recent_deployments": ["v2.4.1 deployed 45 min ago"],
        })

        # database-primary: strained, near connection limit
        self._service_states["database-primary"].update({
            "health": "degraded",
            "cpu_percent": 78.0,
            "memory_percent": 82.0,
            "error_rate_percent": 5.0,
            "request_latency_p99_ms": 450.0,
            "active_connections": 198,
        })

        # user-service: intermittent failures from DB contention
        self._service_states["user-service"].update({
            "health": "degraded",
            "error_rate_percent": 12.0,
            "request_latency_p99_ms": 2200.0,
        })

        # api-gateway: elevated errors due to downstream
        self._service_states["api-gateway"].update({
            "error_rate_percent": 15.0,
            "request_latency_p99_ms": 3500.0,
        })

        # Initial alerts
        self._active_alerts = [
            Alert(
                alert_id="ALT-001",
                service="database-primary",
                severity=AlertSeverity.CRITICAL,
                message="Connection pool utilization at 99% (198/200). Approaching limit.",
                fired_at="14:22 UTC",
            ),
            Alert(
                alert_id="ALT-002",
                service="order-service",
                severity=AlertSeverity.CRITICAL,
                message="Error rate exceeded 30% threshold. Order creation failing.",
                fired_at="14:23 UTC",
            ),
            Alert(
                alert_id="ALT-003",
                service="user-service",
                severity=AlertSeverity.WARNING,
                message="Elevated error rate (12%). Profile lookups intermittently failing.",
                fired_at="14:25 UTC",
            ),
        ]

        # Delayed alerts (escalation if unresolved)
        self._alert_timeline = [
            (8, Alert(
                alert_id="ALT-004",
                service="api-gateway",
                severity=AlertSeverity.CRITICAL,
                message="Overall API error rate exceeded 20%. Customer impact confirmed.",
                fired_at="14:46 UTC",
            )),
            (15, Alert(
                alert_id="ALT-005",
                service="database-primary",
                severity=AlertSeverity.CRITICAL,
                message="Connection pool FULL (200/200). All new connections rejected.",
                fired_at="15:07 UTC",
            )),
            # Red herring
            (5, Alert(
                alert_id="ALT-006",
                service="redis-cache",
                severity=AlertSeverity.INFO,
                message="Cache eviction rate slightly elevated. Memory at 75%.",
                fired_at="14:37 UTC",
                is_red_herring=True,
            )),
        ]

    def get_logs(self, service: str, query: str = "", time_range: str = "1h") -> List[LogEntry]:
        logs_db = {
            "order-service": [
                LogEntry(timestamp="14:15:03", level="INFO", service="order-service",
                         message="Deployment v2.4.1 started. Rolling update in progress."),
                LogEntry(timestamp="14:16:22", level="INFO", service="order-service",
                         message="Deployment v2.4.1 complete. All pods healthy."),
                LogEntry(timestamp="14:20:45", level="WARN", service="order-service",
                         message="DB connection pool utilization at 80%. Acquired=160, Released=45."),
                LogEntry(timestamp="14:22:11", level="ERROR", service="order-service",
                         message="Failed to acquire DB connection: pool exhausted. Timeout after 30s."),
                LogEntry(timestamp="14:22:15", level="ERROR", service="order-service",
                         message="Order creation failed: DBConnectionError - no available connections."),
                LogEntry(timestamp="14:23:01", level="ERROR", service="order-service",
                         message="Connection leak detected: 195 connections acquired, only 12 released in last 30 min."),
                LogEntry(timestamp="14:24:30", level="ERROR", service="order-service",
                         message="Repeated: Failed to acquire DB connection. Requests queuing."),
                LogEntry(timestamp="14:25:00", level="WARN", service="order-service",
                         message="Health check degraded: dependency database-primary returning errors."),
            ],
            "database-primary": [
                LogEntry(timestamp="14:18:00", level="INFO", service="database-primary",
                         message="Active connections: 150/200. Normal range."),
                LogEntry(timestamp="14:20:30", level="WARN", service="database-primary",
                         message="Active connections: 180/200. Approaching limit."),
                LogEntry(timestamp="14:22:00", level="WARN", service="database-primary",
                         message="Active connections: 198/200. CRITICAL threshold exceeded."),
                LogEntry(timestamp="14:22:30", level="ERROR", service="database-primary",
                         message="Connection rejected: max_connections (200) reached. Source: order-service (185 conns)."),
                LogEntry(timestamp="14:23:00", level="ERROR", service="database-primary",
                         message="Rejecting new connections. Top consumers: order-service=185, user-service=10, auth-service=3."),
                LogEntry(timestamp="14:24:00", level="WARN", service="database-primary",
                         message="Long-running idle connections detected: 140 connections idle >5 min from order-service."),
            ],
            "user-service": [
                LogEntry(timestamp="14:23:30", level="WARN", service="user-service",
                         message="Database query timeout: connection acquisition took 28s (limit 30s)."),
                LogEntry(timestamp="14:24:00", level="ERROR", service="user-service",
                         message="Profile lookup failed: unable to get DB connection."),
                LogEntry(timestamp="14:25:00", level="WARN", service="user-service",
                         message="Falling back to cache for user profiles. Cache hit rate: 60%."),
            ],
            "api-gateway": [
                LogEntry(timestamp="14:23:00", level="WARN", service="api-gateway",
                         message="Elevated 5xx responses on /api/orders/* routes. Rate: 35%."),
                LogEntry(timestamp="14:25:00", level="WARN", service="api-gateway",
                         message="Elevated 5xx responses on /api/users/* routes. Rate: 12%."),
            ],
            "redis-cache": [
                LogEntry(timestamp="14:20:00", level="INFO", service="redis-cache",
                         message="Memory usage: 75%. Eviction policy: allkeys-lru. Normal operation."),
            ],
        }
        entries = logs_db.get(service, [
            LogEntry(timestamp="14:00:00", level="INFO", service=service,
                     message="All systems nominal. No issues detected."),
        ])
        if query:
            entries = [e for e in entries if query.lower() in e.message.lower()]
        return entries

    def get_metrics(self, service: str, metric: str) -> List[MetricSeries]:
        metrics_db = {
            "database-primary": {
                "active_connections": MetricSeries(
                    metric_name="active_connections", service="database-primary", unit="count",
                    datapoints=[
                        MetricDatapoint(timestamp="14:00", value=120),
                        MetricDatapoint(timestamp="14:05", value=125),
                        MetricDatapoint(timestamp="14:10", value=130),
                        MetricDatapoint(timestamp="14:15", value=140),
                        MetricDatapoint(timestamp="14:17", value=155),
                        MetricDatapoint(timestamp="14:19", value=170),
                        MetricDatapoint(timestamp="14:20", value=180),
                        MetricDatapoint(timestamp="14:21", value=190),
                        MetricDatapoint(timestamp="14:22", value=198),
                        MetricDatapoint(timestamp="14:23", value=200),
                    ],
                ),
                "cpu_usage": MetricSeries(
                    metric_name="cpu_usage", service="database-primary", unit="percent",
                    datapoints=[
                        MetricDatapoint(timestamp="14:00", value=40),
                        MetricDatapoint(timestamp="14:10", value=45),
                        MetricDatapoint(timestamp="14:15", value=55),
                        MetricDatapoint(timestamp="14:20", value=70),
                        MetricDatapoint(timestamp="14:23", value=78),
                    ],
                ),
            },
            "order-service": {
                "error_rate": MetricSeries(
                    metric_name="error_rate", service="order-service", unit="percent",
                    datapoints=[
                        MetricDatapoint(timestamp="14:00", value=0.1),
                        MetricDatapoint(timestamp="14:10", value=0.2),
                        MetricDatapoint(timestamp="14:16", value=0.5),
                        MetricDatapoint(timestamp="14:18", value=5.0),
                        MetricDatapoint(timestamp="14:20", value=15.0),
                        MetricDatapoint(timestamp="14:22", value=35.0),
                    ],
                ),
                "db_connections": MetricSeries(
                    metric_name="db_connections_held", service="order-service", unit="count",
                    datapoints=[
                        MetricDatapoint(timestamp="14:00", value=30),
                        MetricDatapoint(timestamp="14:10", value=50),
                        MetricDatapoint(timestamp="14:15", value=90),
                        MetricDatapoint(timestamp="14:17", value=130),
                        MetricDatapoint(timestamp="14:20", value=170),
                        MetricDatapoint(timestamp="14:22", value=185),
                        MetricDatapoint(timestamp="14:23", value=195),
                    ],
                ),
            },
        }
        svc_metrics = metrics_db.get(service, {})
        if metric == "all":
            return list(svc_metrics.values())
        if metric in svc_metrics:
            return [svc_metrics[metric]]
        return [MetricSeries(metric_name=metric, service=service, unit="unknown", datapoints=[])]

    def run_diagnostic(self, service: str, diagnostic: str) -> ActionResult:
        if service == "database-primary" and diagnostic == "connection_pool_status":
            return ActionResult(
                success=True,
                message="Connection pool diagnostic complete.",
                data={
                    "max_connections": 200,
                    "active_connections": 198,
                    "idle_connections": 140,
                    "waiting_queries": 45,
                    "per_service_breakdown": {
                        "order-service": 185,
                        "user-service": 10,
                        "auth-service": 3,
                    },
                    "finding": "order-service holds 185/198 connections. 140 are idle >5 min. "
                               "Connections are being acquired but NOT released — classic connection leak pattern.",
                },
            )
        if service == "order-service" and diagnostic == "connection_pool_status":
            return ActionResult(
                success=True,
                message="Order service connection diagnostic complete.",
                data={
                    "pool_size": 50,
                    "active_held": 50,
                    "released_last_30m": 12,
                    "acquired_last_30m": 195,
                    "leak_detected": True,
                    "finding": "Connection leak confirmed. Acquired 195 connections in 30 min, "
                               "released only 12. Started after deployment v2.4.1.",
                },
            )
        if service == "order-service" and diagnostic == "health_check":
            return ActionResult(
                success=True,
                message="Health check: DEGRADED.",
                data={
                    "status": "degraded",
                    "checks": {
                        "database": "FAILING — cannot acquire connection",
                        "payment-service": "OK",
                        "message-queue": "OK",
                    },
                    "last_deployment": "v2.4.1, 45 min ago",
                },
            )
        return ActionResult(
            success=True,
            message=f"Diagnostic '{diagnostic}' on {service}: no specific findings.",
            data={"status": "ok", "finding": "No anomalies detected."},
        )

    def apply_remediation(self, service: str, action: str, params: dict) -> ActionResult:
        if service == "order-service" and action in ("rollback", "rollback_deployment"):
            self._service_states["order-service"].update({
                "health": "healthy",
                "error_rate_percent": 0.5,
                "request_latency_p99_ms": 250.0,
                "active_connections": 40,
                "recent_deployments": ["v2.4.0 (rolled back from v2.4.1)"],
            })
            return ActionResult(
                success=True,
                message="Rolled back order-service from v2.4.1 to v2.4.0. "
                        "Connection leak resolved. Error rate dropping.",
                data={"previous_version": "v2.4.1", "current_version": "v2.4.0"},
            )

        if service == "database-primary" and action in ("restart", "drain_connections",
                                                         "clear_connections"):
            self._service_states["database-primary"].update({
                "health": "healthy",
                "cpu_percent": 42.0,
                "memory_percent": 66.0,
                "error_rate_percent": 0.0,
                "request_latency_p99_ms": 18.0,
                "active_connections": 50,
            })
            self._service_states["user-service"].update({
                "health": "healthy",
                "error_rate_percent": 0.1,
                "request_latency_p99_ms": 85.0,
            })
            return ActionResult(
                success=True,
                message="Database primary restarted. Stale connections cleared. "
                        "Connection count back to normal (50/200). Dependent services recovering.",
                data={"active_connections": 50, "max_connections": 200},
            )

        return ActionResult(
            success=True,
            message=f"Applied '{action}' to {service}.",
            data={"service": service, "action": action},
        )
