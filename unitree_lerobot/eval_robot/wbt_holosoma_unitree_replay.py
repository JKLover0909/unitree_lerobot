#!/usr/bin/env python3
"""Replay raw WBT G1 body actions through Holosoma-style Unitree binding.

This script keeps dataset parsing and safety gates in Python, but sends robot
commands through the C++/pybind11 ``unitree_interface`` binding used by
Holosoma:

    unitree_interface.create_robot(...)
    read_low_state()
    create_zero_command()
    write_low_command(cmd)

It intentionally does not publish ``rt/lowcmd`` manually. If the binding is not
installed in the active environment, install the Unitree wheel used by Holosoma
or run inside the Holosoma inference environment.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from wbt_full_body_replay import (
    CONTROL_CONFIRMATION,
    DEFAULT_RAW_ROOT,
    G1_JOINT_NAMES,
    G1_MOTOR_DOF,
    KD,
    KP,
    ROOT_DOF,
    clip_step,
    initialize_body,
    load_data,
    load_episodes,
    load_info,
    summarize_episode,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_RAW_ROOT, help="Raw LeRobot dataset root.")
    parser.add_argument("--episode", type=int, default=0)
    parser.add_argument("--episode-count", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=None, help="Max actions per episode.")
    parser.add_argument("--frequency", type=float, default=30.0)
    parser.add_argument("--network-interface", default=None)
    parser.add_argument("--output-root", type=Path, default=Path("wbt_holosoma_results"))
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--send-actions", action="store_true")
    parser.add_argument("--control-confirmation", default="")
    parser.add_argument("--state-timeout-s", type=float, default=5.0)
    parser.add_argument("--initialize-from-dataset", action="store_true")
    parser.add_argument("--init-only", action="store_true", help="Exit after initialization.")
    parser.add_argument("--initialization-speed-rad-s", type=float, default=0.10)
    parser.add_argument("--initialization-timeout-s", type=float, default=180.0)
    parser.add_argument("--initialization-max-error-rad", type=float, default=0.10)
    parser.add_argument("--max-body-delta-rad", type=float, default=0.015)
    parser.add_argument(
        "--low-body-kp-scale",
        type=float,
        default=0.35,
        help="Scale kp for joints 0:15. Conservative default.",
    )
    parser.add_argument("--arm-kp-scale", type=float, default=1.0, help="Scale kp for arm joints 15:29.")
    parser.add_argument("--preview-only", action="store_true")
    parser.add_argument("--print-every", type=int, default=50)
    parser.add_argument(
        "--init-sequential",
        action="store_true",
        help="Initialize left leg, right leg, waist, left arm, right arm sequentially.",
    )
    parser.add_argument("--init-group-pause-s", type=float, default=1.0)
    parser.add_argument(
        "--init-joints",
        default=None,
        help=(
            "Comma-separated joint indices to initialize. Example for both arms: "
            "15,16,17,18,19,20,21,22,23,24,25,26,27,28"
        ),
    )
    parser.add_argument(
        "--hold-inactive-joints",
        action="store_true",
        help=(
            "When --init-joints/--init-sequential is used, command inactive joints "
            "to their current q with normal kp/kd instead of passive damping."
        ),
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.frequency <= 0:
        raise ValueError("--frequency must be positive")
    if args.episode_count <= 0:
        raise ValueError("--episode-count must be positive")
    if args.max_steps is not None and args.max_steps <= 0:
        raise ValueError("--max-steps must be positive")
    if args.max_body_delta_rad <= 0:
        raise ValueError("--max-body-delta-rad must be positive")
    if args.initialization_speed_rad_s <= 0:
        raise ValueError("--initialization-speed-rad-s must be positive")
    if args.initialization_timeout_s <= 0:
        raise ValueError("--initialization-timeout-s must be positive")
    if args.initialization_max_error_rad <= 0:
        raise ValueError("--initialization-max-error-rad must be positive")
    if args.print_every <= 0:
        raise ValueError("--print-every must be positive")
    if args.init_only and not args.initialize_from_dataset:
        raise ValueError("--init-only requires --initialize-from-dataset")
    if args.init_joints is not None and args.init_sequential:
        raise ValueError("--init-joints and --init-sequential cannot be used together")
    if args.send_actions and args.control_confirmation != CONTROL_CONFIRMATION:
        raise ValueError(f"Real full-body control requires --control-confirmation={CONTROL_CONFIRMATION}")


def make_run_dir(args: argparse.Namespace) -> Path:
    if args.run_name:
        name = args.run_name
    else:
        name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_episode-{args.episode:03d}"
    run_dir = args.output_root / name
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def import_unitree_interface():
    """Import Holosoma's C++ binding and preload bundled DDS libs when present."""
    spec = importlib.util.find_spec("unitree_interface")
    if spec is None:
        raise ModuleNotFoundError(
            "unitree_interface binding is not installed. Install the Holosoma/amazon-far "
            "Unitree wheel in this environment, then rerun this script."
        )

    if spec.submodule_search_locations:
        ui_dir = Path(spec.submodule_search_locations[0])
        for lib_name in ("libddsc.so.0", "libddscxx.so.0"):
            lib_path = ui_dir / lib_name
            if lib_path.exists():
                ctypes.CDLL(str(lib_path), mode=ctypes.RTLD_GLOBAL)

    import unitree_interface  # type: ignore

    return unitree_interface


def create_unitree_robot(unitree_interface: Any, interface: str | None):
    robot_type = unitree_interface.RobotType.G1
    message_type = unitree_interface.MessageType.HG
    interface_arg = interface or ""
    if hasattr(unitree_interface, "create_robot"):
        return unitree_interface.create_robot(interface_arg, robot_type, message_type)
    if hasattr(unitree_interface, "UnitreeInterface"):
        return unitree_interface.UnitreeInterface(interface_arg, robot_type, message_type)
    raise RuntimeError("unitree_interface has neither create_robot nor UnitreeInterface")


class HolosomaUnitreeIO:
    """Small LeRobot-side wrapper around Holosoma's Unitree C++ binding."""

    def __init__(self, args: argparse.Namespace):
        unitree_interface = import_unitree_interface()
        self.robot = create_unitree_robot(unitree_interface, args.network_interface)
        if hasattr(self.robot, "set_control_mode"):
            self.robot.set_control_mode(unitree_interface.ControlMode.PR)

        self.kp = KP.copy()
        self.kp[:15] *= float(args.low_body_kp_scale)
        self.kp[15:] *= float(args.arm_kp_scale)
        self.kd = KD.copy()
        self._last_q = self.current_body_q(args.state_timeout_s)
        print(
            "Holosoma-style Unitree binding connected: "
            f"interface={args.network_interface or '<default>'} control_mode=PR"
        )

    def _read_state(self) -> Any:
        return self.robot.read_low_state()

    def current_body_q(self, max_age_s: float) -> np.ndarray:
        del max_age_s  # read_low_state is synchronous in the Holosoma binding.
        state = self._read_state()
        q = np.asarray(state.motor.q, dtype=np.float32)
        if q.shape[0] < G1_MOTOR_DOF:
            raise RuntimeError(f"Expected at least {G1_MOTOR_DOF} motors from low state, got {q.shape[0]}")
        return q[:G1_MOTOR_DOF].copy()

    def publish_body(
        self,
        q_target: np.ndarray,
        kp_scale_low_body: float,
        kp_scale_arm: float,
        active_joints: list[int] | None = None,
    ) -> None:
        del kp_scale_low_body, kp_scale_arm  # gains are already built from args.
        target = np.asarray(q_target, dtype=np.float32).reshape(G1_MOTOR_DOF)
        q_cmd = target.copy()
        kp = self.kp.copy()
        kd = self.kd.copy()

        if active_joints is not None:
            active = np.zeros(G1_MOTOR_DOF, dtype=bool)
            active[np.asarray(active_joints, dtype=np.int64)] = True
            current = self.current_body_q(0.0)
            q_cmd[~active] = current[~active]
            if not getattr(self, "hold_inactive_joints", False):
                kp[~active] = 0.0
                kd[~active] = 0.5

        cmd = self.robot.create_zero_command()
        cmd.q_target = [float(v) for v in q_cmd]
        cmd.dq_target = [0.0] * G1_MOTOR_DOF
        cmd.tau_ff = [0.0] * G1_MOTOR_DOF
        cmd.kp = [float(v) for v in kp]
        cmd.kd = [float(v) for v in kd]
        self.robot.write_low_command(cmd)
        self._last_q = q_cmd


def replay_episode(
    ep,
    rows: dict[str, np.ndarray],
    args: argparse.Namespace,
    run_dir: Path,
    io: HolosomaUnitreeIO | None,
) -> None:
    q_full = rows["q_desired"]
    if q_full.ndim != 2 or q_full.shape[1] != ROOT_DOF + G1_MOTOR_DOF:
        raise ValueError(f"Expected q_desired shape (T, 36), got {q_full.shape}")
    actions = len(q_full) if args.max_steps is None else min(len(q_full), args.max_steps)
    body_targets = q_full[:actions, ROOT_DOF : ROOT_DOF + G1_MOTOR_DOF]

    csv_path = run_dir / f"episode-{ep.episode_index:03d}_steps.csv"
    with open(csv_path, "w") as f:
        f.write("action_step,episode,dataset_index,frame_index,dry_run,max_body_delta,body_target_norm,body_command_norm\n")

        if io is not None and args.initialize_from_dataset:
            io.hold_inactive_joints = bool(args.hold_inactive_joints)
            initialize_body(io, body_targets[0], args)
            if args.init_only:
                print("Init-only requested; stopping after initial pose stage.")
                return

        if io is not None:
            user_input = input(
                "Initial pose stage done. Enter 's' to start Holosoma-style full-body replay, anything else to stop: "
            )
            if user_input.strip().lower() != "s":
                print("Stopped before replay.")
                return

        print(
            f"Starting Holosoma-style full-body playback: episode={ep.episode_index} "
            f"dataset_index={ep.start}..{ep.start + actions - 1} actions={actions} dry_run={io is None}"
        )
        body_last = None if io is None else io.current_body_q(args.state_timeout_s)
        for step in range(actions):
            loop_start = time.perf_counter()
            target = body_targets[step]
            if io is None:
                command = target
                max_delta = 0.0 if body_last is None else float(np.max(np.abs(command - body_last)))
            else:
                assert body_last is not None
                command = clip_step(target, body_last, args.max_body_delta_rad)
                max_delta = float(np.max(np.abs(command - body_last)))
                io.publish_body(command, args.low_body_kp_scale, args.arm_kp_scale)
                body_last = command

            f.write(
                f"{step + 1},{ep.episode_index},{int(rows['index'][step])},{int(rows['frame_index'][step])},"
                f"{io is None},{max_delta:.9g},{float(np.linalg.norm(target)):.9g},"
                f"{float(np.linalg.norm(command)):.9g}\n"
            )
            if (step + 1) % args.print_every == 0 or step + 1 == actions:
                print(
                    f"action_step={step + 1}/{actions} dataset_index={int(rows['index'][step])} "
                    f"max_delta={max_delta:.4f} source=holosoma_binding dry_run={io is None}"
                )
            elapsed = time.perf_counter() - loop_start
            time.sleep(max(0.0, (1.0 / args.frequency) - elapsed))


def run(args: argparse.Namespace) -> Path:
    validate_args(args)
    info = load_info(args.root)
    episodes = load_episodes(args.root)
    print(
        f"Loaded raw dataset: root={args.root} fps={info.get('fps')} "
        f"episodes={info.get('total_episodes')} frames={info.get('total_frames')}"
    )

    selected = []
    for ep_idx in range(args.episode, args.episode + args.episode_count):
        if ep_idx not in episodes:
            raise ValueError(f"Episode {ep_idx} is not available in {args.root}")
        selected.append(episodes[ep_idx])

    loaded = []
    for ep in selected:
        rows = load_data(args.root, ep.start, ep.stop)
        summarize_episode(ep, rows["q_desired"])
        loaded.append((ep, rows))

    run_dir = make_run_dir(args)
    config = vars(args).copy()
    config["root"] = str(config["root"])
    config["output_root"] = str(config["output_root"])
    config["backend"] = "holosoma_unitree_interface"
    with open(run_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    if args.preview_only:
        print(f"Preview written: {run_dir}")
        return run_dir

    io = HolosomaUnitreeIO(args) if args.send_actions else None
    for ep, rows in loaded:
        replay_episode(ep, rows, args, run_dir, io)
    print(f"WBT Holosoma-style replay results: {run_dir}")
    return run_dir


def main() -> None:
    try:
        run(parse_args())
    except ModuleNotFoundError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
