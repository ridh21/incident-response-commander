"""
Grading system for the Incident Response Commander environment.

Computes a final score in [0.0, 1.0] based on multiple dimensions:
- Investigation efficiency (0.20)
- Root cause accuracy (0.30)
- Remediation correctness (0.25)
- Time efficiency (0.10)
- Communication quality (0.10)
- Safety bonus (0.05)
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from models import Reward, RewardBreakdown

if TYPE_CHECKING:
    from server.scenarios.base import BaseScenario


def compute_final_grade(scenario: "BaseScenario") -> Reward:
    """Compute the final grade for a completed episode.

    This is called when the episode ends (either resolved or max steps reached).
    It provides a comprehensive final score based on the entire trajectory.
    """
    bd = scenario.reward_breakdown

    # ── Investigation efficiency (0.0 - 0.20) ──────
    relevant_investigated = len(
        scenario.services_investigated & set(scenario.relevant_services)
    )
    total_relevant = len(scenario.relevant_services)
    if total_relevant > 0:
        coverage = relevant_investigated / total_relevant
        bd.investigation_efficiency = round(min(0.20, coverage * 0.20), 4)

    # Bonus for running required diagnostics
    required_diags_done = sum(
        1 for s, d in scenario.required_diagnostics
        if (s, d) in scenario.diagnostics_run
    )
    if scenario.required_diagnostics:
        diag_ratio = required_diags_done / len(scenario.required_diagnostics)
        bd.investigation_efficiency = round(
            min(0.20, bd.investigation_efficiency + diag_ratio * 0.05), 4
        )

    # ── Root cause accuracy (0.0 - 0.30) ───────────
    if scenario.root_cause_correct:
        bd.root_cause_accuracy = 0.30
    elif scenario.root_cause_declared is not None:
        # Partial credit: check how many keywords matched
        rc_lower = scenario.root_cause_declared.lower()
        matched = sum(1 for kw in scenario.root_cause_keywords if kw.lower() in rc_lower)
        ratio = matched / max(1, len(scenario.root_cause_keywords))
        bd.root_cause_accuracy = round(min(0.20, ratio * 0.20), 4)
    else:
        bd.root_cause_accuracy = 0.0

    # ── Remediation correctness (0.0 - 0.25) ───────
    correct_count = 0
    for svc, act in scenario.remediations_applied:
        if any(svc == cs and act == ca for cs, ca in scenario.correct_remediations):
            correct_count += 1
    if scenario.correct_remediations:
        rem_ratio = min(1.0, correct_count / max(1, min(3, len(scenario.correct_remediations))))
        bd.remediation_correctness = round(rem_ratio * 0.25, 4)

    # ── Time efficiency (0.0 - 0.10) ───────────────
    if scenario.incident_resolved:
        ratio = scenario.step_count / scenario.max_steps
        if ratio < 0.35:
            bd.time_efficiency = 0.10
        elif ratio < 0.50:
            bd.time_efficiency = 0.08
        elif ratio < 0.65:
            bd.time_efficiency = 0.06
        elif ratio < 0.80:
            bd.time_efficiency = 0.04
        else:
            bd.time_efficiency = 0.02
    else:
        bd.time_efficiency = 0.0  # Not resolved = no time bonus

    # ── Communication quality (0.0 - 0.10) ─────────
    updates = len(scenario.status_updates)
    if updates >= 3:
        bd.communication_quality = 0.10
    elif updates >= 2:
        bd.communication_quality = 0.07
    elif updates >= 1:
        bd.communication_quality = 0.04
    else:
        bd.communication_quality = 0.0

    # ── Safety bonus (−0.10 to 0.05) ───────────────
    if scenario.destructive_on_healthy == 0:
        bd.safety_bonus = 0.05
    else:
        penalty = min(0.15, scenario.destructive_on_healthy * 0.03)
        bd.safety_bonus = round(max(-0.10, 0.05 - penalty), 4)

    # ── Total ──────────────────────────────────────
    total = (
        bd.investigation_efficiency
        + bd.root_cause_accuracy
        + bd.remediation_correctness
        + bd.time_efficiency
        + bd.communication_quality
        + bd.safety_bonus
    )
    total = round(max(0.0, min(1.0, total)), 4)

    return Reward(
        value=total,
        breakdown=bd,
        step_reward=0.0,
        cumulative=total,
        feedback=_generate_feedback(scenario, bd, total),
    )


def _generate_feedback(scenario: "BaseScenario", bd: RewardBreakdown, total: float) -> str:
    parts = []
    parts.append(f"Final score: {total:.2f}/1.00")
    parts.append(f"  Investigation: {bd.investigation_efficiency:.2f}/0.20")
    parts.append(f"  Root cause:    {bd.root_cause_accuracy:.2f}/0.30")
    parts.append(f"  Remediation:   {bd.remediation_correctness:.2f}/0.25")
    parts.append(f"  Time:          {bd.time_efficiency:.2f}/0.10")
    parts.append(f"  Communication: {bd.communication_quality:.2f}/0.10")
    parts.append(f"  Safety:        {bd.safety_bonus:.2f}/0.05")

    if not scenario.incident_resolved:
        parts.append("\nIncident was NOT resolved within the step limit.")
    if not scenario.root_cause_declared:
        parts.append("Root cause was never declared.")
    elif not scenario.root_cause_correct:
        parts.append(f"Root cause declared but incorrect: '{scenario.root_cause_declared}'")

    return "\n".join(parts)
