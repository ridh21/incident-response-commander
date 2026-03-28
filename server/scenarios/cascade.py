"""
Task 2 (Medium): Cascading Service Failure

Scenario: auth-service deployed v2.3.2 with a known memory leak 2 hours ago.
Memory grew until auth-service became slow, causing api-gateway to timeout and retry,
which overwhelmed user-service, which caused notification-service queue to back up.

The agent must trace the dependency chain back to auth-service as the root cause,
not just fix the visible symptoms.

Root cause: auth-service v2.3.2 memory leak in JWT token cache.
Fix: Rollback auth-service, scale api-gateway temporarily, drain notification queue.
"""

from __future__ import annotations
from typing import List
from .base import BaseScenario
from models import (
    Alert, AlertSeverity, LogEntry, MetricSeries, MetricDatapoint, ActionResult,
)


class CascadingFailure(BaseScenario):
    task_id = "task2_cascade_failure"
    task_description = (
        "A cascading failure across multiple services. Several services are degraded "
        "or down. Multiple alerts are firing. You must trace the failure chain to "
        "identify the original root cause and apply targeted fixes — not just "
        "treat symptoms."
    )
    difficulty = "medium"
    incident_title = "Multi-service degradation — auth timeouts cascading to gateway, users, and notifications"
    initial_severity = "SEV1"
    max_steps = 30

    root_cause_service = "auth-service"
    root_cause_description = "Memory leak in auth-service v2.3.2 JWT token cache"
    root_cause_keywords = ["memory", "leak", "auth-service", "jwt", "v2.3"]
    relevant_services = [
        "auth-service", "api-gateway", "user-service",
        "notification-service", "message-queue", "redis-cache",
    ]
    correct_remediations = [
        ("auth-service", "rollback"),
        ("auth-service", "rollback_deployment"),
        ("auth-service", "restart"),
        ("api-gateway", "scale"),
        ("notification-service", "drain_queue"),
    ]
    required_diagnostics = [
        ("auth-service", "memory_profile"),
        ("auth-service", "health_check"),
    ]

    def setup(self):
        # auth-service: memory leak, very slow
        self._service_states["auth-service"].update({
            "health": "degraded",
            "cpu_percent": 85.0,
            "memory_percent": 96.0,
            "error_rate_percent": 40.0,
            "request_latency_p99_ms": 12000.0,
            "active_connections": 800,
            "recent_deployments": ["v2.3.2 deployed 2 hours ago"],
        })

        # api-gateway: retrying auth calls, overwhelming downstream
        self._service_states["api-gateway"].update({
            "health": "degraded",
            "cpu_percent": 72.0,
            "memory_percent": 60.0,
            "error_rate_percent": 25.0,
            "request_latency_p99_ms": 15000.0,
            "active_connections": 4800,
        })

        # user-service: overwhelmed by retried requests from gateway
        self._service_states["user-service"].update({
            "health": "degraded",
            "cpu_percent": 90.0,
            "memory_percent": 78.0,
            "error_rate_percent": 18.0,
            "request_latency_p99_ms": 5000.0,
            "active_connections": 2500,
        })

        # notification-service: queue backing up
        self._service_states["notification-service"].update({
            "health": "degraded",
            "cpu_percent": 45.0,
            "memory_percent": 55.0,
            "error_rate_percent": 5.0,
            "request_latency_p99_ms": 8000.0,
        })

        # message-queue: filling up
        self._service_states["message-queue"].update({
            "cpu_percent": 55.0,
            "memory_percent": 70.0,
        })

        # Initial alerts — many firing, making it harder to pinpoint root cause
        self._active_alerts = [
            Alert(
                alert_id="ALT-101",
                service="api-gateway",
                severity=AlertSeverity.CRITICAL,
                message="Overall error rate 25%. P99 latency >15s. Multiple routes affected.",
                fired_at="13:05 UTC",
            ),
            Alert(
                alert_id="ALT-102",
                service="user-service",
                severity=AlertSeverity.CRITICAL,
                message="CPU at 90%. Request queue growing. Latency >5s.",
                fired_at="13:08 UTC",
            ),
            Alert(
                alert_id="ALT-103",
                service="auth-service",
                severity=AlertSeverity.WARNING,
                message="Memory usage at 96%. Approaching OOM threshold.",
                fired_at="13:02 UTC",
            ),
            Alert(
                alert_id="ALT-104",
                service="notification-service",
                severity=AlertSeverity.WARNING,
                message="Notification processing backlog. Queue depth: 45,000 messages.",
                fired_at="13:10 UTC",
            ),
        ]

        self._alert_timeline = [
            (5, Alert(
                alert_id="ALT-105",
                service="auth-service",
                severity=AlertSeverity.CRITICAL,
                message="OOM killer triggered! auth-service pod restarted. Memory leaked to 98%.",
                fired_at="13:27 UTC",
            )),
            (10, Alert(
                alert_id="ALT-106",
                service="api-gateway",
                severity=AlertSeverity.CRITICAL,
                message="Connection pool exhausted. Active connections: 4800/5000.",
                fired_at="13:42 UTC",
            )),
            (12, Alert(
                alert_id="ALT-107",
                service="message-queue",
                severity=AlertSeverity.WARNING,
                message="Queue depth: 80,000 messages. Consumer lag increasing.",
                fired_at="13:48 UTC",
            )),
            # Red herrings
            (3, Alert(
                alert_id="ALT-108",
                service="database-replica",
                severity=AlertSeverity.INFO,
                message="Replication lag: 250ms (threshold: 1000ms). Within acceptable range.",
                fired_at="13:21 UTC",
                is_red_herring=True,
            )),
            (7, Alert(
                alert_id="ALT-109",
                service="payment-service",
                severity=AlertSeverity.INFO,
                message="Scheduled batch job completed. 15 refunds processed.",
                fired_at="13:33 UTC",
                is_red_herring=True,
            )),
        ]

    def get_logs(self, service: str, query: str = "", time_range: str = "1h") -> List[LogEntry]:
        logs_db = {
            "auth-service": [
                LogEntry(timestamp="11:00:00", level="INFO", service="auth-service",
                         message="Deployment v2.3.2 started. New JWT caching layer enabled."),
                LogEntry(timestamp="11:01:30", level="INFO", service="auth-service",
                         message="Deployment v2.3.2 complete. All health checks passing."),
                LogEntry(timestamp="12:00:00", level="WARN", service="auth-service",
                         message="Memory usage: 65%. JWT token cache size: 450,000 entries. GC pressure increasing."),
                LogEntry(timestamp="12:30:00", level="WARN", service="auth-service",
                         message="Memory usage: 82%. JWT cache growing unbounded. Cache eviction NOT configured in v2.3.2."),
                LogEntry(timestamp="12:50:00", level="ERROR", service="auth-service",
                         message="GC pause: 4.2s. Request processing stalled. Clients timing out."),
                LogEntry(timestamp="13:00:00", level="ERROR", service="auth-service",
                         message="Memory usage: 94%. JWT cache: 1,200,000 entries. CRITICAL: no eviction policy set."),
                LogEntry(timestamp="13:02:00", level="ERROR", service="auth-service",
                         message="Token validation latency: 12s (normal: 45ms). Memory pressure causing swap."),
                LogEntry(timestamp="13:05:00", level="ERROR", service="auth-service",
                         message="OOMKill warning: memory at 96%. Container will be killed at 98%."),
            ],
            "api-gateway": [
                LogEntry(timestamp="12:55:00", level="WARN", service="api-gateway",
                         message="auth-service response time degraded: 3s avg (normal: 45ms)."),
                LogEntry(timestamp="13:00:00", level="WARN", service="api-gateway",
                         message="Retry storm: auth validation timing out. Retrying 3x per request."),
                LogEntry(timestamp="13:02:00", level="ERROR", service="api-gateway",
                         message="Circuit breaker OPEN for auth-service. Requests failing fast."),
                LogEntry(timestamp="13:03:00", level="WARN", service="api-gateway",
                         message="Retry backoff applied but request volume still 3x normal due to client retries."),
                LogEntry(timestamp="13:05:00", level="ERROR", service="api-gateway",
                         message="Connection pool at 4800/5000. Downstream services overwhelmed by retried requests."),
                LogEntry(timestamp="13:08:00", level="ERROR", service="api-gateway",
                         message="Cascading: user-service and order-service receiving 3x normal traffic from retries."),
            ],
            "user-service": [
                LogEntry(timestamp="13:03:00", level="WARN", service="user-service",
                         message="Incoming request rate 3x normal. Source: api-gateway retry storm."),
                LogEntry(timestamp="13:05:00", level="WARN", service="user-service",
                         message="CPU at 85%. Thread pool nearly exhausted."),
                LogEntry(timestamp="13:08:00", level="ERROR", service="user-service",
                         message="Request queue growing. 2,500 active connections. Latency >5s."),
                LogEntry(timestamp="13:10:00", level="ERROR", service="user-service",
                         message="Dropping requests. Queue depth exceeded max. Some profile lookups failing."),
            ],
            "notification-service": [
                LogEntry(timestamp="13:05:00", level="WARN", service="notification-service",
                         message="Incoming message rate exceeds processing capacity. Queue depth: 30,000."),
                LogEntry(timestamp="13:08:00", level="WARN", service="notification-service",
                         message="Queue depth: 45,000. Consumer lag increasing. Some notifications delayed >10 min."),
                LogEntry(timestamp="13:12:00", level="ERROR", service="notification-service",
                         message="Queue depth: 60,000. Many messages are retry notifications from failed requests upstream."),
            ],
            "message-queue": [
                LogEntry(timestamp="13:05:00", level="WARN", service="message-queue",
                         message="Queue depth growing: notification queue at 30,000. Producer rate 5x normal."),
                LogEntry(timestamp="13:10:00", level="WARN", service="message-queue",
                         message="Memory at 70%. Queue depth: 55,000. Mostly retry/failure notification messages."),
            ],
        }
        entries = logs_db.get(service, [
            LogEntry(timestamp="13:00:00", level="INFO", service=service,
                     message="All systems nominal. No issues detected."),
        ])
        if query:
            entries = [e for e in entries if query.lower() in e.message.lower()]
        return entries

    def get_metrics(self, service: str, metric: str) -> List[MetricSeries]:
        metrics_db = {
            "auth-service": {
                "memory_usage": MetricSeries(
                    metric_name="memory_usage_percent", service="auth-service", unit="percent",
                    datapoints=[
                        MetricDatapoint(timestamp="11:00", value=30),
                        MetricDatapoint(timestamp="11:30", value=38),
                        MetricDatapoint(timestamp="12:00", value=52),
                        MetricDatapoint(timestamp="12:15", value=65),
                        MetricDatapoint(timestamp="12:30", value=78),
                        MetricDatapoint(timestamp="12:45", value=88),
                        MetricDatapoint(timestamp="13:00", value=94),
                        MetricDatapoint(timestamp="13:05", value=96),
                    ],
                ),
                "latency": MetricSeries(
                    metric_name="request_latency_p99", service="auth-service", unit="ms",
                    datapoints=[
                        MetricDatapoint(timestamp="11:00", value=45),
                        MetricDatapoint(timestamp="12:00", value=120),
                        MetricDatapoint(timestamp="12:30", value=800),
                        MetricDatapoint(timestamp="12:45", value=3000),
                        MetricDatapoint(timestamp="13:00", value=8000),
                        MetricDatapoint(timestamp="13:05", value=12000),
                    ],
                ),
                "gc_pauses": MetricSeries(
                    metric_name="gc_pause_duration", service="auth-service", unit="ms",
                    datapoints=[
                        MetricDatapoint(timestamp="11:00", value=15),
                        MetricDatapoint(timestamp="12:00", value=200),
                        MetricDatapoint(timestamp="12:30", value=1500),
                        MetricDatapoint(timestamp="13:00", value=4200),
                    ],
                ),
            },
            "api-gateway": {
                "error_rate": MetricSeries(
                    metric_name="error_rate", service="api-gateway", unit="percent",
                    datapoints=[
                        MetricDatapoint(timestamp="12:00", value=0.1),
                        MetricDatapoint(timestamp="12:45", value=2.0),
                        MetricDatapoint(timestamp="13:00", value=10.0),
                        MetricDatapoint(timestamp="13:05", value=25.0),
                    ],
                ),
                "connections": MetricSeries(
                    metric_name="active_connections", service="api-gateway", unit="count",
                    datapoints=[
                        MetricDatapoint(timestamp="12:00", value=2500),
                        MetricDatapoint(timestamp="12:45", value=3200),
                        MetricDatapoint(timestamp="13:00", value=4200),
                        MetricDatapoint(timestamp="13:05", value=4800),
                    ],
                ),
            },
            "user-service": {
                "cpu_usage": MetricSeries(
                    metric_name="cpu_usage", service="user-service", unit="percent",
                    datapoints=[
                        MetricDatapoint(timestamp="12:00", value=25),
                        MetricDatapoint(timestamp="12:45", value=30),
                        MetricDatapoint(timestamp="13:00", value=55),
                        MetricDatapoint(timestamp="13:05", value=80),
                        MetricDatapoint(timestamp="13:08", value=90),
                    ],
                ),
                "request_rate": MetricSeries(
                    metric_name="request_rate", service="user-service", unit="req/s",
                    datapoints=[
                        MetricDatapoint(timestamp="12:00", value=500),
                        MetricDatapoint(timestamp="13:00", value=800),
                        MetricDatapoint(timestamp="13:05", value=1500),
                        MetricDatapoint(timestamp="13:08", value=1800),
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
        if service == "auth-service" and diagnostic == "memory_profile":
            return ActionResult(
                success=True,
                message="Memory profile complete for auth-service.",
                data={
                    "total_memory_mb": 3840,
                    "used_memory_mb": 3686,
                    "usage_percent": 96.0,
                    "top_allocations": [
                        {"object": "JWTTokenCache", "size_mb": 2800, "count": 1200000,
                         "note": "Cache grows unbounded — no eviction policy configured in v2.3.2"},
                        {"object": "RequestBuffer", "size_mb": 400, "count": 50000},
                        {"object": "SessionStore", "size_mb": 200, "count": 80000},
                    ],
                    "gc_overhead_percent": 35.0,
                    "finding": "JWTTokenCache is consuming 73% of heap. v2.3.2 introduced caching "
                               "but forgot to set maxSize or TTL. Cache grows with every unique token. "
                               "Known fix: rollback to v2.2.x or upgrade to v2.3.5+.",
                },
            )
        if service == "auth-service" and diagnostic == "health_check":
            return ActionResult(
                success=True,
                message="Health check: DEGRADED.",
                data={
                    "status": "degraded",
                    "memory_critical": True,
                    "latency_critical": True,
                    "checks": {
                        "redis": "OK (but barely reachable due to GC pauses)",
                        "database": "OK",
                    },
                    "deployed_version": "v2.3.2",
                    "last_stable_version": "v2.2.8",
                    "uptime": "2h 05m (deployed 2h ago)",
                },
            )
        if service == "api-gateway" and diagnostic == "connection_analysis":
            return ActionResult(
                success=True,
                message="Gateway connection analysis complete.",
                data={
                    "active_connections": 4800,
                    "max_connections": 5000,
                    "retry_rate": "3x normal",
                    "root_cause": "auth-service timeouts triggering client retries, which "
                                  "amplify traffic 3x and cascade to all downstream services.",
                },
            )
        return ActionResult(
            success=True,
            message=f"Diagnostic '{diagnostic}' on {service}: no specific findings.",
            data={"status": "ok", "finding": "No anomalies detected."},
        )

    def apply_remediation(self, service: str, action: str, params: dict) -> ActionResult:
        if service == "auth-service" and action in ("rollback", "rollback_deployment"):
            self._service_states["auth-service"].update({
                "health": "healthy",
                "cpu_percent": 22.0,
                "memory_percent": 32.0,
                "error_rate_percent": 0.1,
                "request_latency_p99_ms": 50.0,
                "recent_deployments": ["v2.2.8 (rolled back from v2.3.2)"],
            })
            # Cascading recovery
            self._service_states["api-gateway"].update({
                "error_rate_percent": 5.0,
                "request_latency_p99_ms": 500.0,
                "active_connections": 3000,
            })
            return ActionResult(
                success=True,
                message="Rolled back auth-service from v2.3.2 to v2.2.8. Memory leak resolved. "
                        "Token validation latency returning to normal. Gateway retry storm subsiding.",
                data={"rolled_back_to": "v2.2.8", "memory_freed_mb": 2800},
            )

        if service == "auth-service" and action == "restart":
            self._service_states["auth-service"].update({
                "memory_percent": 32.0,
                "request_latency_p99_ms": 200.0,
            })
            return ActionResult(
                success=True,
                message="auth-service restarted. Memory cleared temporarily. WARNING: v2.3.2 still "
                        "deployed — memory will leak again. Rollback recommended for permanent fix.",
                data={"temporary_fix": True, "time_until_recurrence": "~2 hours"},
            )

        if service == "api-gateway" and action == "scale":
            replicas = params.get("replicas", 6)
            self._service_states["api-gateway"].update({
                "health": "healthy",
                "cpu_percent": 40.0,
                "error_rate_percent": 2.0,
                "request_latency_p99_ms": 200.0,
                "active_connections": 2000,
            })
            return ActionResult(
                success=True,
                message=f"Scaled api-gateway to {replicas} replicas. Load distributed. Error rate dropping.",
                data={"replicas": replicas},
            )

        if service == "notification-service" and action in ("drain_queue", "scale"):
            self._service_states["notification-service"].update({
                "health": "healthy",
                "error_rate_percent": 0.5,
                "request_latency_p99_ms": 600.0,
            })
            return ActionResult(
                success=True,
                message="Notification queue draining. Backlog processing. ETA: 15 minutes.",
                data={"queue_depth": 20000, "drain_rate": "2000/min"},
            )

        return ActionResult(
            success=True,
            message=f"Applied '{action}' to {service}.",
            data={"service": service, "action": action},
        )
