"""Offline adapter to unmodified native airline evaluator components.

This module is evaluator-private: the actor must never import it or receive a
Task/evaluation_criteria object. Recorded chronological messages are mandatory
when there were tool calls. No transcript, tool result, or answer is invented.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _content(value: str) -> Any:
    """Compare native JSON contents structurally and plain text literally."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _response_key(response: Any) -> dict:
    """Exclude transport timestamps but preserve native result/error identity."""
    return {
        "id": response.id,
        "requestor": response.requestor,
        "error": response.error,
        "content": _content(response.content),
    }


def evaluate(
    task_id: str,
    actions: list[dict],
    messages: list[dict] | None = None,
    *,
    termination_reason: str = "agent_stop",
    actor_final_db_hash: str | None = None,
) -> dict:
    """Replay recorded calls, then score native ENV and COMMUNICATE components.

    Each action is {id, name, arguments, requestor?, response}, where response
    is the recorded native ToolMessage JSON. Messages must be the full native
    chronological transcript including matching calls/results. This adapter is
    deliberately restricted to tasks without initial message history and with
    reward basis DB and/or COMMUNICATE; unsupported criteria fail closed.

    The aggregate is adapter-composed using native multiplicative semantics,
    with the native termination gate. It is not an invocation of the complete
    benchmark orchestrator or evaluate_simulation registry entry point.
    """
    from bootstrap import install

    isolation = install()

    from tau2.data_model.message import (
        AssistantMessage,
        SystemMessage,
        ToolCall,
        ToolMessage,
        UserMessage,
    )
    from tau2.data_model.tasks import RewardType
    from tau2.domains.airline.environment import get_environment, get_tasks
    from tau2.evaluator.evaluator_communicate import CommunicateEvaluator
    from tau2.evaluator.evaluator_env import EnvironmentEvaluator

    tasks = [task for task in get_tasks(None) if task.id == str(task_id)]
    if len(tasks) != 1:
        raise ValueError(f"Task ID must identify one native task: {task_id}")
    task = tasks[0]
    if task.evaluation_criteria is None:
        raise ValueError("Task without criteria cannot establish native success")
    basis = set(task.evaluation_criteria.reward_basis)
    if not basis or not basis <= {RewardType.DB, RewardType.COMMUNICATE}:
        raise ValueError("This offline adapter only supports DB/COMMUNICATE basis")
    initial = task.initial_state
    if initial is not None and initial.message_history:
        raise ValueError("Initial message histories require a separately audited adapter")
    if messages is None:
        if actions:
            raise ValueError("Recorded chronological messages required for tool calls")
        messages = []

    classes = {
        "assistant": AssistantMessage,
        "user": UserMessage,
        "system": SystemMessage,
        "tool": ToolMessage,
    }
    trajectory = []
    for message in messages:
        role = message.get("role")
        if role not in classes:
            raise ValueError(f"Unsupported transcript role: {role}")
        trajectory.append(classes[role].model_validate(message))

    pairs = []
    cursor = 0
    seen_ids = set()
    while cursor < len(trajectory):
        message = trajectory[cursor]
        cursor += 1
        if isinstance(message, ToolMessage):
            raise ValueError("Orphan tool response in recorded transcript")
        if isinstance(message, (AssistantMessage, UserMessage)) and message.is_tool_call():
            for call in message.tool_calls:
                if not call.id or call.id in seen_ids:
                    raise ValueError("Tool call IDs must be nonempty and unique")
                seen_ids.add(call.id)
                if call.requestor != message.role:
                    raise ValueError("Tool requestor differs from transcript sender")
                if cursor >= len(trajectory):
                    raise ValueError("Missing recorded tool response")
                response = trajectory[cursor]
                cursor += 1
                if not isinstance(response, ToolMessage):
                    raise ValueError("Recorded tool response must follow its call")
                if response.id != call.id or response.requestor != call.requestor:
                    raise ValueError("Tool response identity differs from its call")
                pairs.append((call, response))
    if len(actions) != len(pairs):
        raise ValueError("Action log and transcript call counts differ")
    for index, (action, (call, response)) in enumerate(zip(actions, pairs, strict=True)):
        logged_call = ToolCall.model_validate(
            {key: action[key] for key in ("id", "name", "arguments", "requestor") if key in action}
        )
        if logged_call != call:
            raise ValueError(f"Action log differs from transcript at call {index}")
        if "response" not in action:
            raise ValueError(f"Action {index} has no recorded native response")
        logged_response = ToolMessage.model_validate(action["response"])
        if _response_key(logged_response) != _response_key(response):
            raise ValueError(f"Action log response differs at call {index}")

    initialization_data = initial.initialization_data if initial else None
    initialization_actions = initial.initialization_actions if initial else None
    replay = get_environment()
    replay.set_state(
        initialization_data=initialization_data,
        initialization_actions=initialization_actions,
        message_history=[],
        strict=True,
    )
    # Native EnvironmentEvaluator skips replaying reads. This additional audit
    # actually executes every logged call and checks its result against the log.
    for index, (call, expected) in enumerate(pairs):
        actual = replay.get_response(call)
        if _response_key(actual) != _response_key(expected):
            raise ValueError(f"Independent native response replay differs at call {index}")
    replay_hash = replay.get_db_hash()
    if actor_final_db_hash is not None and actor_final_db_hash != replay_hash:
        raise ValueError("Live actor final DB hash differs from full recorded replay")

    env_reward = EnvironmentEvaluator.calculate_reward(
        environment_constructor=get_environment,
        task=task,
        full_trajectory=trajectory,
        solo_mode=False,
        env_kwargs={},
        strict_replay=True,
    )
    comm_reward = CommunicateEvaluator.calculate_reward(
        task=task,
        full_trajectory=trajectory,
    )
    component_product = 1.0
    breakdown = {}
    if RewardType.DB in basis:
        component_product *= env_reward.reward
        breakdown["DB"] = env_reward.reward
    if RewardType.COMMUNICATE in basis:
        component_product *= comm_reward.reward
        breakdown["COMMUNICATE"] = comm_reward.reward
    normal_stop = termination_reason in {"agent_stop", "user_stop"}
    return {
        "schema_version": "airline_native_component_evaluation_v1",
        "task_id": str(task_id),
        "scoring_method": "adapter_composition_of_unmodified_native_ENV_and_COMMUNICATE",
        "native_orchestrator_run": False,
        "reward_basis": [item.value for item in task.evaluation_criteria.reward_basis],
        "termination_reason": termination_reason,
        "native_termination_gate_passed": normal_stop,
        "adapter_composed_native_reward": component_product if normal_stop else 0.0,
        "component_product_before_termination_gate": component_product,
        "reward_breakdown": breakdown,
        "native_environment": env_reward.model_dump(mode="json"),
        "native_communicate": comm_reward.model_dump(mode="json"),
        "communication_requirement_count": len(task.evaluation_criteria.communicate_info or []),
        "communication_score_vacuous": not bool(task.evaluation_criteria.communicate_info),
        "nl_assertions_present_but_not_scored": bool(task.evaluation_criteria.nl_assertions),
        "all_recorded_tool_responses_reproduced": True,
        "recorded_tool_call_count": len(pairs),
        "replay_final_db_hash": replay_hash,
        "actor_final_db_hash": actor_final_db_hash,
        "actor_final_db_match_verified": actor_final_db_hash is not None,
        "initial_state_is_null": initial is None,
        "model_calls": 0,
        "isolation": isolation,
    }


def main() -> None:
    """Evaluate one completed, immutable run JSON in a separate process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = evaluate(**payload)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
