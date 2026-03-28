"""
Task 3 (Hard): Data Inconsistency from Blue-Green Deployment Race Condition

Scenario: A blue-green deployment of payment-service had both old (v3.1.0) and
new (v3.2.0) versions running simultaneously for 8 minutes. The new version
changed the payment confirmation schema, but the old version was still processing
orders using stale cached schemas. This created data inconsistencies:

- 847 orders marked as "paid" in order-service but payment-service shows "pending"
- 23 duplicate payment records
- Customer complaints and refund requests spiking

The agent must:
1. Identify that the data inconsistency is the core issue (not just service health)
2. Trace it to the blue-green deployment overlap
3. Run data consistency checks
4. Apply data reconciliation
5. Fix the deployment to prevent recurrence

This is hard because:
- Services appear healthy (the deployment completed successfully)
- Symptoms are subtle: complaint rate increase, not outright failures
- Requires correlating data across services
- Multiple investigation paths needed
"""

from __future__ import annotations
from typing import List
from .base import BaseScenario
from models import (
    Alert, AlertSeverity, LogEntry, MetricSeries, MetricDatapoint, ActionResult,
)


class DataCorruption(BaseScenario):
    task_id = "task3_data_corruption"
    task_description = (
        "A data inconsistency incident caused by a deployment race condition. "
        "Customer complaints are rising. Some orders show as paid but payments "
        "were never processed. You must investigate across multiple services, "
        "identify the root cause, assess the blast radius, apply data reconciliation, "
        "and resolve the incident."
    )
    difficulty = "hard"
    incident_title = "Data inconsistency — orders marked paid but payments not processed"
    initial_severity = "SEV2"
    max_steps = 35

    root_cause_service = "payment-service"
    root_cause_description = (
        "Blue-green deployment race condition: payment-service v3.1.0 and v3.2.0 "
        "ran simultaneously for 8 minutes. Schema mismatch caused 847 orders to be "
        "incorrectly marked as paid."
    )
    root_cause_keywords = [
        "blue-green", "deployment", "race", "payment-service",
        "schema", "v3.2", "v3.1", "simultaneous",
    ]
    relevant_services = [
        "payment-service", "order-service", "database-primary",
        "redis-cache", "message-queue", "api-gateway",
    ]
    correct_remediations = [
        ("payment-service", "data_reconciliation"),
        ("payment-service", "fix_deployment_strategy"),
        ("redis-cache", "invalidate_cache"),
        ("order-service", "reprocess_affected_orders"),
    ]
    required_diagnostics = [
        ("payment-service", "data_consistency_check"),
        ("order-service", "order_payment_reconciliation"),
    ]

    def setup(self):
        # payment-service: looks healthy but has data issues
        self._service_states["payment-service"].update({
            "health": "healthy",
            "cpu_percent": 18.0,
            "memory_percent": 28.0,
            "error_rate_percent": 0.8,
            "request_latency_p99_ms": 380.0,
            "recent_deployments": [
                "v3.2.0 deployed 3 hours ago (blue-green)",
                "v3.1.0 terminated 2h52m ago",
            ],
        })

        # order-service: slight elevation in errors from inconsistent state
        self._service_states["order-service"].update({
            "error_rate_percent": 2.5,
            "request_latency_p99_ms": 280.0,
        })

        # redis-cache: has stale entries
        self._service_states["redis-cache"].update({
            "memory_percent": 72.0,
        })

        # Everything else looks normal — that's what makes this hard

        # Initial alerts — subtle, not screaming outage
        self._active_alerts = [
            Alert(
                alert_id="ALT-301",
                service="order-service",
                severity=AlertSeverity.WARNING,
                message="Customer complaint rate 5x normal in last 2 hours. Topic: 'payment not processed'.",
                fired_at="12:30 UTC",
            ),
            Alert(
                alert_id="ALT-302",
                service="payment-service",
                severity=AlertSeverity.WARNING,
                message="Refund request rate 3x normal. 23 duplicate payment records detected.",
                fired_at="12:35 UTC",
            ),
            Alert(
                alert_id="ALT-303",
                service="order-service",
                severity=AlertSeverity.INFO,
                message="847 orders in 'paid' status with no matching payment confirmation in last 3 hours.",
                fired_at="12:40 UTC",
            ),
        ]

        self._alert_timeline = [
            (6, Alert(
                alert_id="ALT-304",
                service="payment-service",
                severity=AlertSeverity.WARNING,
                message="Data integrity alert: payment_confirmation table has 23 records with duplicate transaction IDs.",
                fired_at="12:58 UTC",
            )),
            (10, Alert(
                alert_id="ALT-305",
                service="order-service",
                severity=AlertSeverity.CRITICAL,
                message="Support team escalation: 200+ tickets opened for 'charged but order not fulfilled'.",
                fired_at="13:10 UTC",
            )),
            (15, Alert(
                alert_id="ALT-306",
                service="api-gateway",
                severity=AlertSeverity.WARNING,
                message="Elevated retry rate on /api/orders/confirm endpoint. Clients retrying failed confirmations.",
                fired_at="13:25 UTC",
            )),
            # Red herrings
            (4, Alert(
                alert_id="ALT-307",
                service="notification-service",
                severity=AlertSeverity.INFO,
                message="Email delivery delay: 3rd party SMTP provider reporting 2 min latency. Unrelated maintenance.",
                fired_at="12:52 UTC",
                is_red_herring=True,
            )),
            (8, Alert(
                alert_id="ALT-308",
                service="database-replica",
                severity=AlertSeverity.INFO,
                message="Scheduled maintenance: replica failover test completed successfully.",
                fired_at="13:04 UTC",
                is_red_herring=True,
            )),
        ]

    def get_logs(self, service: str, query: str = "", time_range: str = "1h") -> List[LogEntry]:
        logs_db = {
            "payment-service": [
                LogEntry(timestamp="09:45:00", level="INFO", service="payment-service",
                         message="Blue-green deployment initiated: v3.1.0 (blue) → v3.2.0 (green)."),
                LogEntry(timestamp="09:45:30", level="INFO", service="payment-service",
                         message="v3.2.0 containers starting. Health checks pending."),
                LogEntry(timestamp="09:46:00", level="INFO", service="payment-service",
                         message="v3.2.0 health checks passing. Traffic shift: 0% → green."),
                LogEntry(timestamp="09:46:30", level="INFO", service="payment-service",
                         message="Traffic shifting: 50% blue (v3.1.0), 50% green (v3.2.0)."),
                LogEntry(timestamp="09:47:00", level="WARN", service="payment-service",
                         message="Both versions active simultaneously. v3.2.0 uses new payment_confirmation "
                                 "schema (added 'idempotency_key' field). v3.1.0 does not recognize this field."),
                LogEntry(timestamp="09:48:00", level="WARN", service="payment-service",
                         message="v3.1.0 processing payment confirmation without idempotency_key. "
                                 "Writing to DB with NULL idempotency_key."),
                LogEntry(timestamp="09:50:00", level="WARN", service="payment-service",
                         message="v3.2.0 confirming payment with idempotency_key. v3.1.0 already wrote a "
                                 "record for same transaction → duplicate entry created."),
                LogEntry(timestamp="09:52:00", level="INFO", service="payment-service",
                         message="Traffic shift: 100% green. v3.1.0 draining."),
                LogEntry(timestamp="09:53:00", level="INFO", service="payment-service",
                         message="v3.1.0 terminated. Blue-green deployment complete."),
                LogEntry(timestamp="09:55:00", level="WARN", service="payment-service",
                         message="Post-deploy check: 23 duplicate transaction records found in payment_confirmation table."),
                LogEntry(timestamp="10:30:00", level="ERROR", service="payment-service",
                         message="Data inconsistency: 847 orders reference payment confirmations that were "
                                 "written by v3.1.0 with old schema. These lack idempotency_key validation "
                                 "and some confirmations were never actually sent to payment gateway."),
                LogEntry(timestamp="12:00:00", level="ERROR", service="payment-service",
                         message="Refund requests increasing. Root cause: orders marked 'paid' based on v3.1.0 "
                                 "confirmation records, but v3.1.0 cached stale gateway responses from redis."),
            ],
            "order-service": [
                LogEntry(timestamp="09:47:00", level="INFO", service="order-service",
                         message="Received payment confirmation for order ORD-88421. Status → PAID."),
                LogEntry(timestamp="09:48:00", level="INFO", service="order-service",
                         message="Received payment confirmation for order ORD-88435. Status → PAID."),
                LogEntry(timestamp="09:50:00", level="WARN", service="order-service",
                         message="Duplicate payment confirmation received for ORD-88421. Ignoring duplicate."),
                LogEntry(timestamp="10:30:00", level="ERROR", service="order-service",
                         message="Customer dispute: order ORD-88421 shows PAID but customer says card not charged."),
                LogEntry(timestamp="12:00:00", level="ERROR", service="order-service",
                         message="Bulk analysis: 847 orders in PAID status have no matching successful payment "
                                 "gateway transaction. These were confirmed by payment-service v3.1.0 using stale cache."),
                LogEntry(timestamp="12:30:00", level="ERROR", service="order-service",
                         message="Customer complaint volume 5x normal. All related to 'payment not processed' issue."),
            ],
            "redis-cache": [
                LogEntry(timestamp="09:46:00", level="INFO", service="redis-cache",
                         message="Normal operation. Hit rate: 92%."),
                LogEntry(timestamp="09:47:00", level="WARN", service="redis-cache",
                         message="Cache entries written by payment-service v3.1.0 use old key format: "
                                 "pay:confirm:{txn_id}. v3.2.0 uses new format: pay:confirm:{txn_id}:{idempotency_key}."),
                LogEntry(timestamp="09:48:00", level="WARN", service="redis-cache",
                         message="v3.1.0 reading stale cache entries that v3.2.0 cannot see (different key format). "
                                 "Cache miss for v3.2.0 on entries written by v3.1.0."),
                LogEntry(timestamp="09:53:00", level="INFO", service="redis-cache",
                         message="v3.1.0 terminated. Stale cache entries from old key format remain (TTL: 24h)."),
            ],
            "database-primary": [
                LogEntry(timestamp="09:50:00", level="WARN", service="database-primary",
                         message="Duplicate key violation on payment_confirmation table: txn_id=TXN-44521. "
                                 "Both v3.1.0 and v3.2.0 wrote a confirmation for the same transaction."),
                LogEntry(timestamp="09:51:00", level="WARN", service="database-primary",
                         message="23 duplicate key warnings in payment_confirmation table during deployment window."),
                LogEntry(timestamp="10:00:00", level="INFO", service="database-primary",
                         message="Query: SELECT COUNT(*) FROM orders WHERE status='paid' AND payment_confirmed_at "
                                 "BETWEEN '09:45' AND '09:53' AND payment_gateway_status IS NULL → 847 rows."),
            ],
            "message-queue": [
                LogEntry(timestamp="09:47:00", level="INFO", service="message-queue",
                         message="Payment confirmation events from both v3.1.0 and v3.2.0 arriving simultaneously."),
                LogEntry(timestamp="09:48:00", level="WARN", service="message-queue",
                         message="Duplicate message IDs detected: 23 payment events have same transaction ID "
                                 "but different schema versions."),
            ],
        }
        entries = logs_db.get(service, [
            LogEntry(timestamp="12:00:00", level="INFO", service=service,
                     message="All systems nominal. No issues detected."),
        ])
        if query:
            entries = [e for e in entries if query.lower() in e.message.lower()]
        return entries

    def get_metrics(self, service: str, metric: str) -> List[MetricSeries]:
        metrics_db = {
            "payment-service": {
                "error_rate": MetricSeries(
                    metric_name="error_rate", service="payment-service", unit="percent",
                    datapoints=[
                        MetricDatapoint(timestamp="09:00", value=0.02),
                        MetricDatapoint(timestamp="09:45", value=0.1),
                        MetricDatapoint(timestamp="09:47", value=2.5),
                        MetricDatapoint(timestamp="09:53", value=0.8),
                        MetricDatapoint(timestamp="10:00", value=0.5),
                        MetricDatapoint(timestamp="12:00", value=0.8),
                    ],
                ),
                "duplicate_records": MetricSeries(
                    metric_name="duplicate_payment_records", service="payment-service", unit="count",
                    datapoints=[
                        MetricDatapoint(timestamp="09:00", value=0),
                        MetricDatapoint(timestamp="09:47", value=5),
                        MetricDatapoint(timestamp="09:50", value=15),
                        MetricDatapoint(timestamp="09:53", value=23),
                        MetricDatapoint(timestamp="10:00", value=23),
                    ],
                ),
            },
            "order-service": {
                "complaint_rate": MetricSeries(
                    metric_name="customer_complaint_rate", service="order-service", unit="per_hour",
                    datapoints=[
                        MetricDatapoint(timestamp="09:00", value=5),
                        MetricDatapoint(timestamp="10:00", value=12),
                        MetricDatapoint(timestamp="11:00", value=45),
                        MetricDatapoint(timestamp="12:00", value=120),
                        MetricDatapoint(timestamp="12:30", value=200),
                    ],
                ),
                "inconsistent_orders": MetricSeries(
                    metric_name="paid_without_payment", service="order-service", unit="count",
                    datapoints=[
                        MetricDatapoint(timestamp="09:45", value=0),
                        MetricDatapoint(timestamp="09:50", value=200),
                        MetricDatapoint(timestamp="09:53", value=847),
                        MetricDatapoint(timestamp="10:00", value=847),
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
        if service == "payment-service" and diagnostic == "data_consistency_check":
            return ActionResult(
                success=True,
                message="Data consistency check completed on payment-service.",
                data={
                    "total_payments_in_window": 3200,
                    "consistent_records": 2330,
                    "inconsistent_records": 847,
                    "duplicate_records": 23,
                    "affected_time_window": "09:45:00 - 09:53:00 UTC",
                    "affected_orders": 847,
                    "root_cause_analysis": (
                        "During blue-green deployment, v3.1.0 and v3.2.0 ran simultaneously "
                        "for ~8 minutes. v3.1.0 used old cache key format and stale gateway "
                        "responses to confirm payments. v3.2.0 used new schema with idempotency "
                        "checks. Orders confirmed by v3.1.0 during this window have no actual "
                        "payment gateway transaction. 23 transactions were confirmed by both "
                        "versions, creating duplicates."
                    ),
                    "blast_radius": {
                        "affected_customers": 847,
                        "total_value_at_risk": "$127,450.00",
                        "duplicate_charges": 23,
                        "duplicate_charge_value": "$3,420.00",
                    },
                },
            )
        if service == "order-service" and diagnostic == "order_payment_reconciliation":
            return ActionResult(
                success=True,
                message="Order-payment reconciliation diagnostic complete.",
                data={
                    "orders_marked_paid": 3200,
                    "orders_with_valid_payment": 2330,
                    "orders_marked_paid_no_payment": 847,
                    "orders_with_duplicate_payment": 23,
                    "recommendation": (
                        "1. Revert 847 orders from 'paid' to 'pending_payment'. "
                        "2. Reprocess payment for these orders. "
                        "3. Deduplicate 23 duplicate payment records. "
                        "4. Refund 23 customers who were double-charged."
                    ),
                },
            )
        if service == "payment-service" and diagnostic == "health_check":
            return ActionResult(
                success=True,
                message="Health check: HEALTHY (service is up, but data integrity issues exist).",
                data={
                    "status": "healthy",
                    "deployed_version": "v3.2.0",
                    "previous_version": "v3.1.0 (terminated 2h52m ago)",
                    "deployment_type": "blue-green",
                    "deployment_duration": "8 minutes dual-traffic",
                    "note": "Service is healthy but data written during deployment window is inconsistent.",
                },
            )
        if service == "redis-cache" and diagnostic == "stale_entries":
            return ActionResult(
                success=True,
                message="Stale cache entry analysis complete.",
                data={
                    "total_stale_entries": 1200,
                    "stale_key_pattern": "pay:confirm:{txn_id} (old format from v3.1.0)",
                    "new_key_pattern": "pay:confirm:{txn_id}:{idempotency_key} (v3.2.0 format)",
                    "ttl_remaining": "~21 hours",
                    "recommendation": "Invalidate all keys matching old pattern to prevent stale reads.",
                },
            )
        return ActionResult(
            success=True,
            message=f"Diagnostic '{diagnostic}' on {service}: no specific findings.",
            data={"status": "ok", "finding": "No anomalies detected."},
        )

    def apply_remediation(self, service: str, action: str, params: dict) -> ActionResult:
        if service == "payment-service" and action == "data_reconciliation":
            return ActionResult(
                success=True,
                message="Data reconciliation initiated on payment-service.",
                data={
                    "orders_reverted": 847,
                    "duplicates_removed": 23,
                    "refunds_initiated": 23,
                    "refund_total": "$3,420.00",
                    "orders_queued_for_reprocessing": 847,
                    "status": "Reconciliation in progress. ETA: 30 minutes for full reprocessing.",
                },
            )
        if service == "payment-service" and action == "fix_deployment_strategy":
            return ActionResult(
                success=True,
                message="Deployment strategy updated to prevent recurrence.",
                data={
                    "changes": [
                        "Blue-green deployment now requires schema compatibility check before traffic split",
                        "Added mandatory cache invalidation step between blue and green phases",
                        "Added idempotency validation gate: no traffic split until both versions agree on schema",
                        "Max dual-traffic window reduced from 10 min to 30 seconds",
                    ],
                    "status": "Deployment pipeline updated. Will apply to next release.",
                },
            )
        if service == "redis-cache" and action in ("invalidate_cache", "flush_stale"):
            return ActionResult(
                success=True,
                message="Stale cache entries invalidated.",
                data={
                    "keys_removed": 1200,
                    "pattern": "pay:confirm:* (old format)",
                    "status": "Cache clean. All payment lookups will now hit database for fresh data.",
                },
            )
        if service == "order-service" and action == "reprocess_affected_orders":
            return ActionResult(
                success=True,
                message="Affected orders queued for reprocessing.",
                data={
                    "orders_reprocessed": 847,
                    "successful_payments": 0,
                    "status": "Orders reverted to pending_payment and queued for payment reprocessing.",
                    "eta": "15 minutes for all orders to be reprocessed.",
                },
            )
        return ActionResult(
            success=True,
            message=f"Applied '{action}' to {service}.",
            data={"service": service, "action": action},
        )
