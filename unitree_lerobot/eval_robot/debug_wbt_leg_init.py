#!/usr/bin/env python3
"""Debug why WBT leg initialization does not reach the dataset start pose.

Default behavior is read-only:

1. Load the first action of a raw WBT episode.
2. Read current G1 lowstate.
3. Print current/target/error for selected leg joints.

Optional probe mode sends a tiny low-level command to one selected joint and
reports whether lowstate feedback changed. This helps separate:

- target pose is far from current pose,
- only one joint dominates max_error,
- low-level leg commands are being ignored or overridden by the active motion
  service / balance controller.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from wbt_full_body_replay import (
    CONTROL_CONFIRMATION,
    DEFAULT_RAW_ROOT,
    G1_JOINT_NAMES,
    G1_MOTOR_DOF,
    ROOT_DOF,
    RobotIO,
    load_data,
    load_episodes,
    load_info,
)


DEBUG_CONFIRMATION = "SEND_WBT_LEG_DEBUG_PROBE"
DEFAULT_LEG_JOINTS = "0,1,2,3,4,5,6,7,8,9,10,11"


def parse_joint_list(raw: str) -> list[int]:
    try:
        joints = [int(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError(f"Expected comma-separated joint indices, got {raw!r}") from exc
    invalid = [idx for idx in joints if idx < 0 or idx >= G1_MOTOR_DOF]
    if invalid:
        raise ValueError(f"Joint indices out of range 0..{G1_MOTOR_DOF - 1}: {invalid}")
    return sorted(set(joints))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_RAW_ROOT, help="Raw LeRobot WBT dataset root.")
    parser.add_argument("--episode", type=int, default=0)
    parser.add_argument("--network-interface", default=None)
    parser.add_argument("--state-timeout-s", type=float, default=5.0)
    parser.add_argument("--init-joints", default=DEFAULT_LEG_JOINTS)
    parser.add_argument(
        "--initialization-max-error-rad",
        type=float,
        default=0.10,
        help="Threshold used by init scripts; only used for reporting here.",
    )
    parser.add_argument("--low-body-kp-scale", type=float, default=0.20)
    parser.add_argument("--arm-kp-scale", type=float, default=0.0)
    parser.add_argument(
        "--release-motion-mode",
        action="store_true",
        help="Dangerous: call MotionSwitcher.ReleaseMode through RobotIO before reading/probing.",
    )
    parser.add_argument("--send-probe", action="store_true", help="Send a tiny probe command to one joint.")
    parser.add_argument("--probe-joint", type=int, default=None, help="Joint index to probe. Required with --send-probe.")
    parser.add_argument("--probe-delta-rad", type=float, default=0.02)
    parser.add_argument("--probe-duration-s", type=float, default=2.0)
    parser.add_argument("--probe-frequency", type=float, default=30.0)
    parser.add_argument("--probe-min-movement-rad", type=float, default=0.005)
    parser.add_argument(
        "--probe-support-selected-joints",
        action="store_true",
        help=(
            "During probe, keep all --init-joints stiff at their current position "
            "instead of activating only --probe-joint. Useful for leg joints under load."
        ),
    )
    parser.add_argument("--control-confirmation", default="")
    args = parser.parse_args()

    if args.state_timeout_s <= 0:
        raise ValueError("--state-timeout-s must be positive")
    if args.initialization_max_error_rad <= 0:
        raise ValueError("--initialization-max-error-rad must be positive")
    if args.low_body_kp_scale < 0 or args.arm_kp_scale < 0:
        raise ValueError("kp scales must be non-negative")
    if args.send_probe:
        if args.probe_joint is None:
            raise ValueError("--send-probe requires --probe-joint")
        if args.probe_joint < 0 or args.probe_joint >= G1_MOTOR_DOF:
            raise ValueError(f"--probe-joint must be in range 0..{G1_MOTOR_DOF - 1}")
        if args.probe_delta_rad <= 0 or args.probe_duration_s <= 0 or args.probe_frequency <= 0:
            raise ValueError("probe delta, duration, and frequency must be positive")
        if args.control_confirmation != DEBUG_CONFIRMATION:
            raise ValueError(f"--send-probe requires --control-confirmation={DEBUG_CONFIRMATION}")
    return args


def make_robot_io_args(args: argparse.Namespace) -> argparse.Namespace:
    """Build the minimal attribute set expected by wbt_full_body_replay.RobotIO."""
    return argparse.Namespace(
        network_interface=args.network_interface,
        release_motion_mode=args.release_motion_mode,
        state_timeout_s=args.state_timeout_s,
        no_hands=True,
        disable_left_hand=True,
        disable_right_hand=True,
        ignore_inspire_status=True,
        hand_force=0,
        hand_speed=0,
        hand_action_scale=1.0,
        max_hand_delta=1.0,
    )


def load_episode_start_target(root: Path, episode: int) -> tuple[np.ndarray, int, int]:
    info = load_info(root)
    episodes = load_episodes(root)
    if episode not in episodes:
        raise ValueError(f"Episode {episode} is not available in {root}")
    ep = episodes[episode]
    rows = load_data(root, ep.start, ep.stop)
    q_full = rows["q_desired"]
    if q_full.ndim != 2 or q_full.shape[1] != ROOT_DOF + G1_MOTOR_DOF:
        raise ValueError(f"Expected q_desired shape (T, 36), got {q_full.shape}")
    print(
        f"Loaded raw dataset: root={root} fps={info.get('fps')} "
        f"episodes={info.get('total_episodes')} frames={info.get('total_frames')}"
    )
    print(
        f"Episode {episode}: dataset_index={ep.start}..{ep.stop - 1} "
        f"length={ep.length}; using first dataset_index={int(rows['index'][0])}"
    )
    return q_full[0, ROOT_DOF : ROOT_DOF + G1_MOTOR_DOF].astype(np.float32), ep.start, ep.stop


def print_error_table(target: np.ndarray, current: np.ndarray, joints: list[int], threshold: float) -> int:
    errors = np.abs(target[joints] - current[joints])
    worst_local = int(np.argmax(errors))
    worst_joint = joints[worst_local]
    print("\nSelected-joint error table:")
    print("idx  joint_name              current(rad)  target(rad)   error(rad)")
    print("---  ----------------------  ------------  -----------   ----------")
    for idx in joints:
        print(
            f"{idx:>3}  {G1_JOINT_NAMES[idx]:<22}  "
            f"{current[idx]:>12.4f}  {target[idx]:>11.4f}   {abs(target[idx] - current[idx]):>10.4f}"
        )
    print(
        f"\nmax_error={float(errors[worst_local]):.4f} rad at joint "
        f"{worst_joint} ({G1_JOINT_NAMES[worst_joint]})"
    )
    if float(errors[worst_local]) <= threshold:
        print(f"Result: already within threshold {threshold:.3f} rad for selected joints.")
    else:
        print(f"Result: not within threshold {threshold:.3f} rad yet.")
    return worst_joint


def run_probe(io: RobotIO, target: np.ndarray, args: argparse.Namespace, support_joints: list[int]) -> None:
    assert args.probe_joint is not None
    joint = int(args.probe_joint)
    before = io.current_body_q(args.state_timeout_s)
    error_to_dataset = float(target[joint] - before[joint])
    sign = 1.0 if error_to_dataset >= 0 else -1.0
    if abs(error_to_dataset) > 1e-6:
        delta = sign * min(float(args.probe_delta_rad), abs(error_to_dataset))
    else:
        delta = float(args.probe_delta_rad)
    probe_target = before.copy()
    probe_target[joint] = before[joint] + delta

    print(
        f"\nSending probe to joint {joint} ({G1_JOINT_NAMES[joint]}): "
        f"current={before[joint]:.4f}, dataset_target={target[joint]:.4f}, "
        f"command={probe_target[joint]:.4f}, duration={args.probe_duration_s:.2f}s"
    )
    if args.probe_support_selected_joints:
        active_joints = support_joints
        print(f"Probe support: holding selected joints stiff: {active_joints}")
    else:
        active_joints = [joint]

    period = 1.0 / float(args.probe_frequency)
    deadline = time.monotonic() + float(args.probe_duration_s)
    writes = 0
    while time.monotonic() < deadline:
        io.publish_body(
            probe_target,
            kp_scale_low_body=args.low_body_kp_scale,
            kp_scale_arm=args.arm_kp_scale,
            active_joints=active_joints,
        )
        writes += 1
        time.sleep(period)

    after = io.current_body_q(args.state_timeout_s)
    moved = float(after[joint] - before[joint])
    print(
        f"Probe result: writes={writes}, before={before[joint]:.4f}, "
        f"after={after[joint]:.4f}, moved={moved:.4f} rad"
    )
    if abs(moved) < float(args.probe_min_movement_rad):
        print(
            "Diagnosis: feedback movement is below threshold. Low-level leg command is likely "
            "being ignored, overridden by motion/balance mode, or the selected joint cannot move in this state."
        )
    else:
        print(
            "Diagnosis: feedback changed. Command path can affect this joint; if full init still waits forever, "
            "look for a different joint dominating max_error or for too strict/slow init parameters."
        )


def main() -> None:
    args = parse_args()
    joints = parse_joint_list(args.init_joints)
    target, _, _ = load_episode_start_target(args.root, args.episode)

    io = RobotIO(make_robot_io_args(args))
    try:
        low_state = io.reader.get(args.state_timeout_s)
        print(f"Lowstate mode_machine={low_state.get('mode_machine')}")
    except Exception as exc:
        print(f"WARNING: could not read lowstate mode_machine: {exc}")
    current = io.current_body_q(args.state_timeout_s)
    worst_joint = print_error_table(target, current, joints, args.initialization_max_error_rad)

    print("\nSuggested next checks:")
    print(f"- Probe worst joint: --send-probe --probe-joint={worst_joint}")
    print("- If max_error does not change during init/probe, the issue is command acceptance/mode, not dataset parsing.")
    print("- If probe moves but init does not finish, inspect the table for the remaining high-error joint.")

    if args.send_probe:
        run_probe(io, target, args, joints)
    else:
        print(f"\nRead-only mode. To send a tiny probe, add --control-confirmation={DEBUG_CONFIRMATION}.")


if __name__ == "__main__":
    main()
