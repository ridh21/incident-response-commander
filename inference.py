"""
Baseline inference script for the Incident Response Commander environment.

Uses OpenAI API client to power an LLM agent that acts as an on-call SRE,
diagnosing and resolving production incidents through the OpenEnv API.

Required environment variables:
    API_BASE_URL  — The API endpoint for the LLM (e.g., http://localhost:8000/v1)
    MODEL_NAME    — The model identifier (e.g., meta-llama/Llama-3.1-8B-Instruct)
    HF_TOKEN      — Hugging Face / API key

Usage:
    export API_BASE_URL="http://localhost:8000/v1"
    export MODEL_NAME="meta-llama/Llama-3.1-8B-Instruct"
    export HF_TOKEN="hf_..."
    python inference.py
"""

import os
import sys
import json
import time
import requests
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

# Load .env file if present
load_dotenv()

# ── Configuration ───────────────────────────────

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/v1")
MODEL_NAME = os.environ.get("MODEL_NAME", "meta-llama/Llama-3.1-8B-Instruct")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
ENV_URL = os.environ.get("ENV_URL", "http://localhost:7860")

TASKS = ["task1_db_outage", "task2_cascade_failure", "task3_data_corruption"]


def emit_start(task_id: str) -> None:
    print(f"[START] task={task_id}", flush=True)


def emit_step(step: int, step_reward: float) -> None:
    print(f"[STEP] step={step} reward={step_reward}", flush=True)


def emit_end(task_id: str, score: float, steps: int) -> None:
    print(f"[END] task={task_id} score={score} steps={steps}", flush=True)


# ── LLM Client ──────────────────────────────────

llm_client = OpenAI(
    base_url=API_BASE_URL,
    api_key=HF_TOKEN,
)

SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE) responding to a production incident.
You have access to a microservice infrastructure with these services:
api-gateway, auth-service, user-service, order-service, payment-service,
notification-service, database-primary, database-replica, redis-cache, message-queue.

Your goal is to:
1. Investigate the incident by checking alerts, logs, metrics, and running diagnostics
2. Identify the root cause
3. Apply the correct remediation
4. Post status updates to keep stakeholders informed
5. Resolve the incident

Available actions (return EXACTLY ONE action as JSON):

{"action_type": "check_alerts"} — View all active monitoring alerts
{"action_type": "investigate_service", "target_service": "<name>"} — Check a service's health and status
{"action_type": "query_logs", "target_service": "<name>", "parameters": {"query": "<search>", "time_range": "1h"}} — Search service logs
{"action_type": "check_metrics", "target_service": "<name>", "parameters": {"metric": "all"}} — View service metrics
{"action_type": "view_dependency_graph", "target_service": "<name>"} — View service dependencies (target_service optional)
{"action_type": "run_diagnostic", "target_service": "<name>", "parameters": {"diagnostic": "<type>"}} — Run a specific diagnostic
{"action_type": "consult_runbook", "target_service": "<name>"} — Read the runbook for a service
{"action_type": "apply_remediation", "target_service": "<name>", "parameters": {"action": "<fix>", "params": {}}} — Apply a fix
{"action_type": "rollback_deployment", "target_service": "<name>"} — Rollback a recent deployment
{"action_type": "scale_service", "target_service": "<name>", "parameters": {"replicas": 5}} — Scale a service
{"action_type": "restart_service", "target_service": "<name>"} — Restart a service
{"action_type": "update_status", "parameters": {"severity": "SEV1", "message": "<status update>"}} — Post a status update
{"action_type": "declare_root_cause", "parameters": {"root_cause": "<description>"}} — Declare the root cause
{"action_type": "resolve_incident", "parameters": {"summary": "<summary>", "resolution": "<what was done>"}} — Resolve the incident

STRATEGY:
- Start by checking alerts to understand the situation
- Investigate affected services, check their logs and metrics
- Run targeted diagnostics based on what you find
- Consult runbooks for known issues
- Declare the root cause once identified
- Apply remediation(s) to fix the issue
- Post status updates throughout (at least 2)
- Resolve the incident with a summary

IMPORTANT: Respond with ONLY a JSON object for the action. No other text."""


def format_observation(obs: dict) -> str:
    """Format an observation into a readable string for the LLM."""
    parts = []
    parts.append(f"=== INCIDENT: {obs.get('title', 'Unknown')} ===")
    parts.append(f"Severity: {obs.get('severity', 'Unknown')} | Step: {obs.get('step_number', 0)}/{obs.get('max_steps', 0)} | Elapsed: {obs.get('elapsed_minutes', 0)} min")
    parts.append(f"Task: {obs.get('task_description', 'Unknown')}")

    affected = obs.get("affected_services", [])
    if affected:
        parts.append(f"Affected services: {', '.join(affected)}")

    investigated = obs.get("services_investigated", [])
    if investigated:
        parts.append(f"Already investigated: {', '.join(investigated)}")

    alerts = obs.get("active_alerts", [])
    if alerts:
        parts.append(f"\n--- Active Alerts ({len(alerts)}) ---")
        for a in alerts:
            parts.append(f"  [{a.get('severity', '?').upper()}] {a.get('service', '?')}: {a.get('message', '')}")

    result = obs.get("action_result")
    if result:
        parts.append(f"\n--- Last Action Result ---")
        parts.append(f"  Success: {result.get('success', False)}")
        parts.append(f"  Message: {result.get('message', '')}")
        data = result.get("data", {})
        if data:
            parts.append(f"  Data: {json.dumps(data, indent=2)}")
        logs = result.get("logs", [])
        if logs:
            parts.append(f"  Logs ({len(logs)} entries):")
            for log in logs[:10]:
                parts.append(f"    [{log.get('timestamp', '')}] {log.get('level', '')}: {log.get('message', '')}")
        metrics = result.get("metrics", [])
        if metrics:
            parts.append(f"  Metrics ({len(metrics)} series):")
            for m in metrics:
                parts.append(f"    {m.get('metric_name', '')}: {[dp.get('value') for dp in m.get('datapoints', [])[-5:]]}")
        services = result.get("services", [])
        if services:
            for s in services:
                parts.append(f"  Service {s.get('name', '')}: health={s.get('health', '?')}, "
                            f"cpu={s.get('cpu_percent', 0)}%, mem={s.get('memory_percent', 0)}%, "
                            f"errors={s.get('error_rate_percent', 0)}%, "
                            f"p99={s.get('request_latency_p99_ms', 0)}ms, "
                            f"conns={s.get('active_connections', 0)}")
                deploys = s.get("recent_deployments", [])
                if deploys:
                    parts.append(f"    Recent deployments: {deploys}")

    return "\n".join(parts)


def parse_action(text: str) -> Optional[dict]:
    """Parse an LLM response into an action dict."""
    text = text.strip()

    # Try to extract JSON from the response
    # Handle cases where the LLM wraps JSON in markdown code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]

    try:
        action = json.loads(text)
        # Ensure action_type is present
        if "action_type" not in action:
            return None
        # Build proper action structure
        result = {"action_type": action["action_type"]}
        if "target_service" in action:
            result["target_service"] = action["target_service"]
        if "parameters" in action:
            result["parameters"] = action["parameters"]
        return result
    except (json.JSONDecodeError, KeyError):
        return None


def get_fallback_action(step: int, obs: dict) -> dict:
    """Provide a deterministic fallback action if LLM parsing fails."""
    if step <= 1:
        return {"action_type": "check_alerts"}

    affected = obs.get("affected_services", [])
    investigated = obs.get("services_investigated", [])
    uninvestigated = [s for s in affected if s not in investigated]

    if uninvestigated:
        return {"action_type": "investigate_service", "target_service": uninvestigated[0]}

    # Default: investigate known important services in order
    services = [
        "order-service", "database-primary", "auth-service",
        "payment-service", "api-gateway", "user-service",
    ]
    for svc in services:
        if svc not in investigated:
            return {"action_type": "query_logs", "target_service": svc, "parameters": {"query": "error"}}

    return {"action_type": "check_alerts"}


def run_task(task_id: str) -> float:
    """Run a single task and return the final score."""
    final_score = 0.0
    step_count = 0
    emit_start(task_id)

    print(f"\n{'='*60}", flush=True)
    print(f"  Starting task: {task_id}", flush=True)
    print(f"{'='*60}", flush=True)

    try:
        # Reset environment for this task
        resp = requests.post(f"{ENV_URL}/reset", json={"task_id": task_id})
        resp.raise_for_status()
        obs = resp.json()

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        done = False

        while not done:
            step_count += 1
            obs_text = format_observation(obs)
            messages.append({"role": "user", "content": obs_text})

            # Keep context window manageable: keep system + last 12 messages
            if len(messages) > 14:
                messages = [messages[0]] + messages[-12:]

            # Call LLM
            action_dict = None
            try:
                completion = llm_client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=512,
                )
                llm_response = completion.choices[0].message.content or ""
                messages.append({"role": "assistant", "content": llm_response})
                action_dict = parse_action(llm_response)
            except Exception as e:
                print(f"  [Step {step_count}] LLM error: {e}", flush=True)

            # Fallback if LLM fails
            if action_dict is None:
                action_dict = get_fallback_action(step_count, obs)
                print(f"  [Step {step_count}] Using fallback action: {action_dict['action_type']}", flush=True)
            else:
                print(
                    f"  [Step {step_count}] Action: {action_dict['action_type']}"
                    f"{' → ' + action_dict.get('target_service', '') if action_dict.get('target_service') else ''}",
                    flush=True,
                )

            # Execute action
            try:
                resp = requests.post(
                    f"{ENV_URL}/step",
                    json={"action": action_dict},
                )
                resp.raise_for_status()
                result = resp.json()
            except Exception as e:
                print(f"  [Step {step_count}] Step error: {e}", flush=True)
                break

            obs = result["observation"]
            reward = result["reward"]
            done = result["done"]
            _info = result["info"]

            step_reward = float(reward.get("step_reward", 0.0))
            emit_step(step_count, step_reward)

            print(
                f"    Reward: step={step_reward:.3f}, "
                f"cumulative={reward.get('cumulative', 0):.3f}",
                flush=True,
            )

            if done:
                final_score = float(reward.get("value", 0.0))
                print(f"\n  Task completed in {step_count} steps.", flush=True)
                print(f"  Final score: {final_score:.4f}", flush=True)
                feedback = reward.get("feedback", "")
                if feedback:
                    print(f"\n  Feedback:\n  {feedback.replace(chr(10), chr(10) + '  ')}", flush=True)
                break
    finally:
        emit_end(task_id, final_score, step_count)

    return final_score


def main():
    print("=" * 60, flush=True)
    print("  Incident Response Commander — Baseline Inference", flush=True)
    print("=" * 60, flush=True)
    print(f"  LLM endpoint: {API_BASE_URL}", flush=True)
    print(f"  Model: {MODEL_NAME}", flush=True)
    print(f"  Environment: {ENV_URL}", flush=True)
    print(f"  Tasks: {TASKS}", flush=True)
    print(flush=True)

    # Verify environment is running
    try:
        resp = requests.get(f"{ENV_URL}/health")
        resp.raise_for_status()
        print("  Environment health check: OK", flush=True)
    except Exception as e:
        print(f"  ERROR: Cannot reach environment at {ENV_URL}: {e}", flush=True)
        print("  Start the environment first: python -m server.app", flush=True)
        sys.exit(1)

    scores = {}
    start_time = time.time()

    for task_id in TASKS:
        task_start = time.time()
        score = run_task(task_id)
        task_duration = time.time() - task_start
        scores[task_id] = score
        print(f"  Task {task_id}: score={score:.4f}, time={task_duration:.1f}s", flush=True)

    total_time = time.time() - start_time

    # Summary
    print("\n" + "=" * 60, flush=True)
    print("  RESULTS SUMMARY", flush=True)
    print("=" * 60, flush=True)
    for task_id, score in scores.items():
        bar = "#" * int(score * 40) + "." * (40 - int(score * 40))
        print(f"  {task_id:30s} [{bar}] {score:.4f}", flush=True)

    avg_score = sum(scores.values()) / len(scores) if scores else 0
    print(f"\n  Average score: {avg_score:.4f}", flush=True)
    print(f"  Total runtime: {total_time:.1f}s", flush=True)
    print("=" * 60, flush=True)

    return scores


if __name__ == "__main__":
    main()
