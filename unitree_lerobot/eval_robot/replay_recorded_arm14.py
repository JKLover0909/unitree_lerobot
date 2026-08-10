#!/usr/bin/env python3
"""Replay a recorded G1 arm14 episode.

This script replays the raw recording format:

    episode_xxx/
      states/arm14.csv   # arm0..arm13 = G1 q15..q28
      timestamps.csv     # optional, used only for metadata alignment
      videos/head.mp4    # not used for control

Only the 14 arm joints are commanded:

    arm0..arm6   = left arm
    arm7..arm13  = right arm

No Inspire/Dex3 hand joints are controlled here.
The default mode is dry-run/read-only. Real robot control requires both
--send-actions and --control-confirmation=SEND_RECORDED_ARM14_G1.
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


CONTROL_CONFIRMATION = "SEND_RECORDED_ARM14_G1"
ARM_COLUMNS = [f"arm{i}" for i in range(ARM_DOF)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--episode-dir",
        type=Path,
        default=Path("episode_20260629_172043"),
        help="Folder containing states/arm14.csv.",
    )
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--frequency", type=float, default=30.0)
    parser.add_argument(
        "--max-action-delta-rad",
        type=float,
        default=0.05,
        help="Max command delta from current measured arm state per control tick.",
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
        "--initialize-from-first-row",
        action="store_true",
        help="Move arms slowly to the first replay row before starting playback.",
    )
    parser.add_argument("--initialization-speed-rad-s", type=float, default=0.10)
    parser.add_argument("--initialization-max-tracking-error-rad", type=float, default=0.05)
    parser.add_argument("--initialization-timeout-s", type=float, default=120.0)
    parser.add_argument("--hold-final-s", type=float, default=0.5)
    parser.add_argument("--output-root", type=Path, default=Path("recorded_arm14_replay_results"))
    parser.add_argument("--run-name", default=None)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.start_frame < 0:
        raise ValueError("--start-frame must be non-negative")
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
    if args.initialize_from_first_row and not args.send_actions:
        raise ValueError("--initialize-from-first-row is only valid with --send-actions")


def load_arm14_csv(episode_dir: Path) -> np.ndarray:
    csv_path = episode_dir / "states" / "arm14.csv"
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    rows: list[list[float]] = []
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        missing = [name for name in ARM_COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{csv_path} is missing columns: {missing}")
        for row in reader:
            rows.append([float(row[name]) for name in ARM_COLUMNS])

    if not rows:
        raise ValueError(f"{csv_path} contains no arm rows")
    data = np.asarray(rows, dtype=np.float32)
    if data.ndim != 2 or data.shape[1] != ARM_DOF or not np.all(np.isfinite(data)):
        raise ValueError(f"Invalid arm14 data shape={data.shape}")
    return data


def make_run_dir(args: argparse.Namespace) -> Path:
    if args.run_name is None:
        run_name = datetime.now().strftime("%Y%m%d_%H%M%S_recorded-arm14")
    else:
        run_name = args.run_name
    run_dir = args.output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def report_motion_mode() -> None:
    try:
        from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

        client = MotionSwitcherClient()
        client.SetTimeout(3.0)
        client.Init()
        code, mode = client.CheckMode()
        print(f"G1 MotionSwitcher: code={code}, mode={mode}")
    except Exception as exc:
        print(f"WARNING: Could not query G1 MotionSwitcher mode: {exc}")


def setup_arm_io(args: argparse.Namespace):
    if not args.send_actions:
        from unitree_lerobot.eval_robot.robot_control.arm_state_reader import G1ArmStateReader

        reader = G1ArmStateReader(
            network_interface=args.network_interface,
            timeout_s=args.dds_wait_timeout_s,
        )
        return reader, None, None

    from unitree_sdk2py.core.channel import ChannelFactoryInitialize

    ChannelFactoryInitialize(0, args.network_interface)
    report_motion_mode()
    if args.motion:
        print(
            "Using rt/arm_sdk. Put G1 in Regular motion-control mode before sending commands "
            "(R3 sequence used earlier: L2+B, L2+UP, then R1+X)."
        )

    from unitree_lerobot.eval_robot.robot_control.robot_arm import G1_29_ArmController
    from unitree_lerobot.eval_robot.robot_control.robot_arm_ik import G1_29_ArmIK

    controller = G1_29_ArmController(
        motion_mode=args.motion,
        simulation_mode=False,
        initialize_dds=False,
    )
    arm_ik = G1_29_ArmIK()
    current = controller.get_current_dual_arm_q()
    controller.ctrl_dual_arm(current, arm_ik.solve_tau(current))
    return controller, controller, arm_ik


def read_arm_state(state_source, max_age_s: float) -> np.ndarray:
    try:
        return np.asarray(state_source.get_current_dual_arm_q(max_age_s=max_age_s), dtype=np.float32)
    except TypeError:
        state = np.asarray(state_source.get_current_dual_arm_q(), dtype=np.float32)
    if state.shape != (ARM_DOF,) or not np.all(np.isfinite(state)):
        raise RuntimeError(f"Invalid G1 arm state: shape={state.shape}")
    return state


def initialize_arm(
    controller,
    arm_ik,
    target: np.ndarray,
    args: argparse.Namespace,
) -> None:
    start_s = time.monotonic()
    deadline = start_s + args.initialization_timeout_s
    max_delta_rad = args.initialization_speed_rad_s / args.frequency
    trajectory_target = read_arm_state(controller, args.state_timeout_s).copy()
    last_print_s = 0.0

    print(f"Initializing arms to first recorded row: arm_step={max_delta_rad:.5f} rad/tick")
    while True:
        now = time.monotonic()
        if now >= deadline:
            raise TimeoutError("Timed out while initializing to first recorded arm pose")

        current = read_arm_state(controller, args.state_timeout_s)
        trajectory_target = limit_arm_target(target, trajectory_target, max_delta_rad)
        command = limit_arm_target(
            trajectory_target,
            current,
            args.initialization_max_tracking_error_rad,
        )
        controller.ctrl_dual_arm(command, arm_ik.solve_tau(command))

        max_error = float(np.max(np.abs(target - current)))
        if max_error < 0.02:
            print("Initial recorded arm pose reached.")
            return

        if now - last_print_s >= 1.0:
            print(f"Initializing recorded pose: elapsed={now - start_s:.1f}s arm_error={max_error:.3f} rad")
            last_print_s = now
        time.sleep(1.0 / args.frequency)


def write_config(run_dir: Path, args: argparse.Namespace, start: int, stop: int, total_rows: int) -> None:
    config = vars(args).copy()
    config["episode_dir"] = str(args.episode_dir.resolve())
    config["dataset_start_index"] = start
    config["dataset_stop_index"] = stop
    config["total_rows"] = total_rows
    config["dry_run"] = not args.send_actions
    config["control_confirmation"] = args.control_confirmation
    (run_dir / "config.json").write_text(json.dumps(config, indent=2, default=str) + "\n")


def run(args: argparse.Namespace) -> Path:
    validate_args(args)
    episode_dir = args.episode_dir.resolve()
    arm_rows = load_arm14_csv(episode_dir)
    start = args.start_frame
    if start >= len(arm_rows):
        raise ValueError(f"--start-frame {start} is outside recorded rows [0, {len(arm_rows) - 1}]")
    stop = len(arm_rows)
    if args.max_steps is not None:
        stop = min(stop, start + args.max_steps)

    run_dir = make_run_dir(args)
    write_config(run_dir, args, start, stop, len(arm_rows))
    steps_path = run_dir / "steps.csv"

    state_source = controller = arm_ik = None
    try:
        state_source, controller, arm_ik = setup_arm_io(args)
        print(
            f"Loaded recorded arm14: rows={len(arm_rows)} replay={start}..{stop - 1} "
            f"steps={stop - start} dry_run={not args.send_actions}"
        )

        if args.initialize_from_first_row:
            initialize_arm(controller, arm_ik, arm_rows[start], args)
            confirmation = input("Enter 's' to start recorded arm replay, anything else to stop: ")
            if confirmation.strip().lower() != "s":
                print("Replay cancelled.")
                return run_dir

        with steps_path.open("w", newline="") as f:
            fieldnames = [
                "step",
                "recorded_index",
                "loop_s",
                "sent_to_robot",
                "current_arm_state",
                "recorded_arm_target",
                "limited_arm_target",
                "max_abs_recorded_delta",
                "max_abs_command_delta",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for step, recorded_index in enumerate(range(start, stop), start=1):
                loop_start = time.perf_counter()
                target = arm_rows[recorded_index]
                current = read_arm_state(state_source, args.state_timeout_s)
                limited = limit_arm_target(target, current, args.max_action_delta_rad)

                if args.send_actions:
                    controller.ctrl_dual_arm(limited, arm_ik.solve_tau(limited))

                writer.writerow(
                    {
                        "step": step,
                        "recorded_index": recorded_index,
                        "loop_s": time.perf_counter() - loop_start,
                        "sent_to_robot": args.send_actions,
                        "current_arm_state": json.dumps(current.tolist()),
                        "recorded_arm_target": json.dumps(target.tolist()),
                        "limited_arm_target": json.dumps(limited.tolist()),
                        "max_abs_recorded_delta": float(np.max(np.abs(target - current))),
                        "max_abs_command_delta": float(np.max(np.abs(limited - current))),
                    }
                )
                f.flush()

                if step % 30 == 0 or recorded_index == stop - 1:
                    print(
                        f"step={step}/{stop - start} recorded_index={recorded_index} "
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
    print(f"Recorded arm14 replay results: {run_dir.resolve()}")


if __name__ == "__main__":
    main()
