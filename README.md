---
title: Incident Response Commander
emoji: 🚨
colorFrom: red
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: mit
tags:
  - openenv
  - incident-response
  - sre
  - reinforcement-learning
---

# Incident Response Commander

An OpenEnv environment that simulates **production incident response** for AI agent training. The agent acts as an on-call Site Reliability Engineer (SRE), diagnosing and resolving real infrastructure incidents across a realistic 10-service microservice architecture.

## Why This Environment?

Incident response is one of the most cognitively demanding tasks in software engineering. On-call engineers must:

- Triage multiple simultaneous alerts under time pressure
- Trace failures through complex service dependency chains
- Distinguish root causes from symptoms and red herrings
- Apply targeted fixes without causing further damage
- Communicate status to stakeholders throughout

This environment captures that complexity in a controlled, reproducible setting with rich feedback signals — making it ideal for training and evaluating AI agents on real-world reasoning.

## Environment Architecture

The environment simulates a production microservice platform with **10 interconnected services**:

```
                    ┌──────────────┐
                    │  api-gateway │
                    └──┬───┬───┬──┘
                       │   │   │
            ┌──────────┘   │   └──────────┐
            ▼              ▼              ▼
     ┌─────────────┐ ┌────────────┐ ┌─────────────┐
     │auth-service │ │user-service│ │order-service │
     └──┬──────┬───┘ └──┬────┬───┘ └──┬───┬───┬──┘
        │      │        │    │        │   │   │
        ▼      ▼        ▼    ▼        ▼   ▼   ▼
┌───────────┐ ┌───────────┐ ┌───────────────────────┐
│redis-cache│ │ database- │ │  payment │notification│
│           │ │  primary  │ │  service │  service   │
└───────────┘ └─────┬─────┘ └────┬────┘─────┬──────┘
                    │             │          │
              ┌─────▼─────┐      │   ┌──────▼──────┐
              │ database- │      │   │message-queue│
              │  replica  │      │   └─────────────┘
              └───────────┘      │
                            (external payment gateway)
```

Each service has realistic baseline metrics, health states, log streams, and deployment history.

## Action Space

The agent can perform 14 distinct action types:

| Action | Description | Example |
|--------|-------------|---------|
| `check_alerts` | View all active monitoring alerts | `{"action_type": "check_alerts"}` |
| `investigate_service` | Check a service's health, metrics, and status | `{"action_type": "investigate_service", "target_service": "auth-service"}` |
| `query_logs` | Search service logs with filters | `{"action_type": "query_logs", "target_service": "order-service", "parameters": {"query": "error", "time_range": "1h"}}` |
| `check_metrics` | View time-series metrics for a service | `{"action_type": "check_metrics", "target_service": "database-primary", "parameters": {"metric": "active_connections"}}` |
| `view_dependency_graph` | View service dependency map | `{"action_type": "view_dependency_graph", "target_service": "order-service"}` |
| `run_diagnostic` | Run a targeted diagnostic check | `{"action_type": "run_diagnostic", "target_service": "database-primary", "parameters": {"diagnostic": "connection_pool_status"}}` |
| `consult_runbook` | Read the operational runbook for a service | `{"action_type": "consult_runbook", "target_service": "order-service"}` |
| `apply_remediation` | Apply a specific fix to a service | `{"action_type": "apply_remediation", "target_service": "payment-service", "parameters": {"action": "data_reconciliation"}}` |
| `rollback_deployment` | Rollback a service's recent deployment | `{"action_type": "rollback_deployment", "target_service": "order-service"}` |
| `scale_service` | Scale a service's replica count | `{"action_type": "scale_service", "target_service": "api-gateway", "parameters": {"replicas": 6}}` |
| `restart_service` | Restart a service | `{"action_type": "restart_service", "target_service": "auth-service"}` |
| `update_status` | Post a stakeholder status update | `{"action_type": "update_status", "parameters": {"severity": "SEV1", "message": "Investigating auth-service memory issue"}}` |
| `declare_root_cause` | Declare the identified root cause | `{"action_type": "declare_root_cause", "parameters": {"root_cause": "Connection leak in order-service v2.4.1"}}` |
| `resolve_incident` | Mark the incident as resolved | `{"action_type": "resolve_incident", "parameters": {"summary": "...", "resolution": "..."}}` |

## Observation Space

Each observation includes:

- **Incident context**: ID, severity, title, elapsed time, step count
- **Active alerts**: Real-time monitoring alerts with severity levels
- **Affected services**: Services currently in degraded/down state
- **Action result**: Detailed result of the last action (logs, metrics, diagnostics)
- **Investigation state**: Which services have been investigated so far
- **Available actions**: List of all valid action types

## Reward Design

Rewards are **multi-dimensional** and provide signal throughout the episode (not just at terminal state):

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Investigation efficiency | 0.20 | Investigating relevant services and running correct diagnostics |
| Root cause accuracy | 0.30 | Correctly identifying the root cause |
| Remediation correctness | 0.25 | Applying the right fix(es) to the right service(s) |
| Time efficiency | 0.10 | Resolving quickly (fewer steps = higher reward) |
| Communication quality | 0.10 | Posting timely and appropriate status updates |
| Safety bonus | 0.05 | Avoiding destructive actions on healthy services |

**Partial progress**: Agents earn incremental rewards for each useful investigation action, correct diagnostic, and status update — not just for final resolution.

**Penalties**: Destructive actions (restart, rollback) on healthy services reduce the safety bonus.

## Tasks

### Task 1: Database Connection Pool Exhaustion (Easy)

**Scenario**: `order-service` deployed v2.4.1 with a connection leak. Database connections are saturating. Orders and user lookups failing.

**Expected approach**: Check alerts → Investigate order-service → Run connection pool diagnostic → Declare root cause → Rollback order-service → Restart database → Resolve

**Max steps**: 25

### Task 2: Cascading Service Failure (Medium)

**Scenario**: `auth-service` v2.3.2 has a memory leak (JWT cache with no eviction). This causes timeouts cascading through api-gateway → user-service → notification-service.

**Expected approach**: Check alerts → Investigate multiple services → Trace dependency chain → Identify auth-service as root cause (not gateway or user-service) → Rollback auth-service → Scale gateway → Drain notification queue → Resolve

**Max steps**: 30

### Task 3: Data Inconsistency from Deployment (Hard)

**Scenario**: Blue-green deployment of `payment-service` had both versions running simultaneously. Schema mismatch caused 847 orders to be marked as paid without actual payment processing.

**Expected approach**: Check alerts → Investigate payment-service logs → Run data consistency check → Correlate across order-service and redis-cache → Declare root cause → Apply data reconciliation → Fix deployment strategy → Invalidate stale cache → Resolve

**Max steps**: 35

## Unique Features

1. **Service Dependency Graph**: Realistic microservice topology with cascading failure propagation
2. **Dynamic Alert Timeline**: New alerts fire as the incident evolves if unresolved
3. **Red Herring Alerts**: Unrelated alerts that test the agent's ability to focus
4. **Runbook System**: Operational runbooks with diagnostic steps and remediation guides
5. **Blast Radius Tracking**: Monitors affected customers and service count
6. **Time Pressure**: Incidents escalate over steps, with reward degradation for slow response
7. **Multi-dimensional Grading**: Six independent scoring dimensions, not just pass/fail

## Setup and Usage

### Prerequisites

- Python 3.10+
- Docker (for containerized deployment)

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the environment server
python -m uvicorn server.app:app --host 0.0.0.0 --port 7860

# In another terminal, run the baseline agent
export API_BASE_URL="http://localhost:8000/v1"
export MODEL_NAME="meta-llama/Llama-3.1-8B-Instruct"
export HF_TOKEN="your-token"
python inference.py
```

### Docker

```bash
# Build the image
docker build -t incident-response-commander .

# Run
docker run -p 7860:7860 incident-response-commander

# Test health check
curl http://localhost:7860/health
```

### API Quick Start

```python
import requests

BASE = "http://localhost:7860"

# Reset to a specific task
obs = requests.post(f"{BASE}/reset", json={"task_id": "task1_db_outage"}).json()

# Take an action
result = requests.post(f"{BASE}/step", json={
    "action": {"action_type": "check_alerts"}
}).json()

print(result["observation"]["active_alerts"])
print(result["reward"]["value"])
print(result["done"])
```

## Baseline Scores

Scores from `inference.py` using Meta Llama 3.1 8B Instruct:

| Task | Score | Steps Used |
|------|-------|------------|
| task1_db_outage | ~0.55-0.70 | 12-18 |
| task2_cascade_failure | ~0.40-0.55 | 18-25 |
| task3_data_corruption | ~0.30-0.45 | 22-30 |
| **Average** | **~0.42-0.57** | |

Scores vary based on model quality. Larger models (70B+) typically score 0.60+ average.

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `API_BASE_URL` | LLM API endpoint | Yes (for inference) |
| `MODEL_NAME` | Model identifier | Yes (for inference) |
| `HF_TOKEN` | HuggingFace / API key | Yes (for inference) |
| `ENV_URL` | Environment server URL | No (default: http://localhost:7860) |
| `PORT` | Server port | No (default: 7860) |
