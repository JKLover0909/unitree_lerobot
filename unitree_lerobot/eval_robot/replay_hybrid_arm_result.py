#!/usr/bin/env python3
"""Replay arm targets saved by hybrid_arm_infer.py.

Use this for folders like:

    hybrid_arm_results/20260702_143319_episode-000/steps.csv

The chosen action column must contain a JSON list of 14 arm joint targets.
Common columns:

    predicted_arm_action  = raw policy output
    limited_arm_target    = policy output after max-delta clamp during that run
    dataset_arm_action    = fake/native dataset action, usually state[t+1]

Only G1 arm joints are controlled:

    0..6   left arm
    7..13  right arm

No hand joints are controlled here.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
LEROBOT_SRC = REPO_ROOT / "unitree_lerobot" / "lerobot" / "src"
if LEROBOT_SRC.exists() and str(LEROBOT_SRC) not in sys.path:
    sys.path.insert(0, str(LEROBOT_SRC))

from unitree_lerobot.eval_robot.hybrid_arm_utils import ARM_DOF, limit_arm_target
from unitree_lerobot.eval_robot.replay_recorded_arm14 import (
    initialize_arm,
    read_arm_state,
    setup_arm_io,
)


CONTROL_CONFIRMATION = "SEND_HYBRID_ARM_RESULT_G1"
DEFAULT_COLUMN = "predicted_arm_action"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--result-dir",
        type=Path,
        required=True,
        help="Folder containing steps.csv from hybrid_arm_infer.py.",
    )
    parser.add_argument(
        "--action-column",
        default=DEFAULT_COLUMN,
        choices=["predicted_arm_action", "limited_arm_target", "dataset_arm_action"],
        help="Which 14D target column to replay.",
    )
    parser.add_argument("--start-step", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--frequency", type=float, default=30.0)
    parser.add_argument(
        "--max-action-delta-rad",
        type=float,
        default=0.05,
        help="Live safety clamp from measured current arm state to command.",
    )
    parser.add_argument("--state-timeout-s", type=float, default=0.25)
    parser.add_argument("--dds-wait-timeout-s", type=float, default=10.0)
    parser.add_argument("--network-interface", default=None, help="DDS interface, e.g. enp1s0.")
    parser.add_argument("--motion", action="store_true", help="Use rt/arm_sdk instead of rt/lowcmd.")
    parser.add_argument("--send-actions", action="store_true", help="Actually publish arm commands.")
    parser.add_argument(
        "--control-confirmation",
        default="",
        help=f"Required with --send-actions; must equal {CONTROL_CONFIRMATION!r}.",
    )
    parser.add_argument(
        "--initialize-from-first-target",
        action="store_true",
        help="Move arms slowly to the first selected target before playback.",
    )
    parser.add_argument("--initialization-speed-rad-s", type=float, default=0.10)
    parser.add_argument("--initialization-max-tracking-error-rad", type=float, default=0.05)
    parser.add_argument("--initialization-timeout-s", type=float, default=120.0)
    parser.add_argument("--hold-final-s", type=float, default=0.5)
    parser.add_argument("--output-root", type=Path, default=Path("hybrid_arm_result_replay_results"))
    parser.add_argument("--run-name", default=None)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.start_step < 0:
        raise ValueError("--start-step must be non-negative")
    if args.max_steps is not None and args.max_steps <= 0:
        raise ValueError("--max-steps must be positive")
    if args.frequency <= 0:
        raise ValueError("--frequency must be positive")
    if args.max_action_delta_rad <= 0:
        raise ValueError("--max-action-delta-rad must be positive")
    if args.initialization_speed_rad_s <= 0 or args.initialization_max_tracking_error_rad <= 0:
        raise ValueError("Initialization speed/tracking error must be positive")
    if args.send_actions and args.control_confirmation != CONTROL_CONFIRMATION:
        raise ValueError(
            f"Real control requires --control-confirmation={CONTROL_CONFIRMATION}. "
            "Run without --send-actions for dry-run."
        )
    if args.initialize_from_first_target and not args.send_actions:
        raise ValueError("--initialize-from-first-target is only valid with --send-actions")


def parse_action(value: str, row_index: int, column: str) -> np.ndarray:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in row {row_index}, column {column}: {exc}") from exc
    arr = np.asarray(data, dtype=np.float32)
    if arr.shape != (ARM_DOF,) or not np.all(np.isfinite(arr)):
        raise ValueError(f"Invalid action at row {row_index}, column {column}: shape={arr.shape}")
    return arr


def load_targets(result_dir: Path, action_column: str) -> tuple[np.ndarray, list[int]]:
    steps_csv = result_dir / "steps.csv"
    if not steps_csv.exists():
        raise FileNotFoundError(steps_csv)

    targets: list[np.ndarray] = []
    policy_steps: list[int] = []
    with steps_csv.open(newline="") as f:
        reader = csv.DictReader(f)
        if action_column not in (reader.fieldnames or []):
            raise ValueError(f"{steps_csv} does not contain column {action_column!r}")
        for row_index, row in enumerate(reader):
            targets.append(parse_action(row[action_column], row_index, action_column))
            policy_steps.append(int(row.get("policy_step", row_index)))

    if not targets:
        raise ValueError(f"{steps_csv} contains no replay targets")
    return np.stack(targets), policy_steps


def make_run_dir(args: argparse.Namespace) -> Path:
    run_name = args.run_name or datetime.now().strftime("%Y%m%d_%H%M%S_hybrid-arm-result")
    run_dir = args.output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def write_config(
    run_dir: Path,
    args: argparse.Namespace,
    start: int,
    stop: int,
    total_rows: int,
) -> None:
    config = vars(args).copy()
    config["result_dir"] = str(args.result_dir.resolve())
    config["start_index"] = start
    config["stop_index"] = stop
    config["total_rows"] = total_rows
    config["dry_run"] = not args.send_actions
    (run_dir / "config.json").write_text(json.dumps(config, indent=2, default=str) + "\n")


def run(args: argparse.Namespace) -> Path:
    validate_args(args)
    result_dir = args.result_dir.resolve()
    targets, policy_steps = load_targets(result_dir, args.action_column)

    start = args.start_step
    if start >= len(targets):
        raise ValueError(f"--start-step {start} is outside rows [0, {len(targets) - 1}]")
    stop = len(targets)
    if args.max_steps is not None:
        stop = min(stop, start + args.max_steps)

    run_dir = make_run_dir(args)
    write_config(run_dir, args, start, stop, len(targets))
    log_path = run_dir / "steps.csv"

    state_source = controller = arm_ik = None
    try:
        state_source, controller, arm_ik = setup_arm_io(args)
        print(
            f"Loaded hybrid result targets: rows={len(targets)} column={args.action_column} "
            f"replay={start}..{stop - 1} steps={stop - start} dry_run={not args.send_actions}"
        )

        if args.initialize_from_first_target:
            initialize_arm(controller, arm_ik, targets[start], args)
            confirmation = input("Enter 's' to start hybrid result replay, anything else to stop: ")
            if confirmation.strip().lower() != "s":
                print("Replay cancelled.")
                return run_dir

        with log_path.open("w", newline="") as f:
            fieldnames = [
                "step",
                "source_row",
                "source_policy_step",
                "loop_s",
                "sent_to_robot",
                "current_arm_state",
                "source_arm_target",
                "live_limited_arm_target",
                "max_abs_source_delta",
                "max_abs_command_delta",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for step, source_row in enumerate(range(start, stop), start=1):
                loop_start = time.perf_counter()
                source_target = targets[source_row]
                current = read_arm_state(state_source, args.state_timeout_s)
                live_limited = limit_arm_target(source_target, current, args.max_action_delta_rad)

                if args.send_actions:
                    controller.ctrl_dual_arm(live_limited, arm_ik.solve_tau(live_limited))

                writer.writerow(
                    {
                        "step": step,
                        "source_row": source_row,
                        "source_policy_step": policy_steps[source_row],
                        "loop_s": time.perf_counter() - loop_start,
                        "sent_to_robot": args.send_actions,
                        "current_arm_state": json.dumps(current.tolist()),
                        "source_arm_target": json.dumps(source_target.tolist()),
                        "live_limited_arm_target": json.dumps(live_limited.tolist()),
                        "max_abs_source_delta": float(np.max(np.abs(source_target - current))),
                        "max_abs_command_delta": float(np.max(np.abs(live_limited - current))),
                    }
                )
                f.flush()

                if step % 30 == 0 or source_row == stop - 1:
                    print(
                        f"step={step}/{stop - start} source_row={source_row} "
                        f"dry_run={not args.send_actions}"
                    )

                elapsed = time.perf_counter() - loop_start
                time.sleep(max(0.0, 1.0 / args.frequency - elapsed))

        if args.send_actions and controller is not None and arm_ik is not None and args.hold_final_s > 0:
            hold_until = time.monotonic() + args.hold_final_s
            while time.monotonic() < hold_until:
                hold = read_arm_state(controller, args.state_timeout_s)
                controller.ctrl_dual_arm(hold, arm_ik.solve_tau(hold))
                time.sleep(1.0 / args.frequency)
    finally:
        if not args.send_actions and state_source is not None:
            state_source.close()

    return run_dir


def main() -> None:
    args = parse_args()
    run_dir = run(args)
    print(f"Hybrid arm result replay results: {run_dir.resolve()}")


if __name__ == "__main__":
    main()
