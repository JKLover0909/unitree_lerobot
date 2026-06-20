#!/usr/bin/env python3
"""Replay raw WBT G1 full-body joint actions.

This script targets the raw Unitree WBT datasets whose action.robot_q_desired is
36D:

    action.robot_q_desired[0:7]   root/base pose from mocap or estimator
    action.robot_q_desired[7:36]  G1 29 motor joint targets
    action.hand_cmd[0:12]         left/right Inspire commands

By default this is a dry run and only writes logs. Sending low-level full-body
commands to a real G1 is substantially more dangerous than arm SDK control. Real
command publishing requires both --send-actions and an exact confirmation string.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq


CONTROL_CONFIRMATION = "SEND_FULL_BODY_G1_WBT"
ROOT_DOF = 7
G1_MOTOR_DOF = 29
HAND_DOF = 6
HAND_TOTAL_DOF = 12

DEFAULT_RAW_ROOT = Path(
    "/home/jkl0909/.cache/huggingface/lerobot/unitreerobotics/"
    "G1_WBT_Inspire_Pick_Up_Drinks_raw3tmp"
)


G1_JOINT_NAMES = [
    "left_hip_pitch",
    "left_hip_roll",
    "left_hip_yaw",
    "left_knee",
    "left_ankle_pitch",
    "left_ankle_roll",
    "right_hip_pitch",
    "right_hip_roll",
    "right_hip_yaw",
    "right_knee",
    "right_ankle_pitch",
    "right_ankle_roll",
    "waist_yaw",
    "waist_roll",
    "waist_pitch",
    "left_shoulder_pitch",
    "left_shoulder_roll",
    "left_shoulder_yaw",
    "left_elbow",
    "left_wrist_roll",
    "left_wrist_pitch",
    "left_wrist_yaw",
    "right_shoulder_pitch",
    "right_shoulder_roll",
    "right_shoulder_yaw",
    "right_elbow",
    "right_wrist_roll",
    "right_wrist_pitch",
    "right_wrist_yaw",
]


KP = np.asarray(
    [
        60,
        60,
        60,
        100,
        40,
        40,
        60,
        60,
        60,
        100,
        40,
        40,
        60,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
        40,
    ],
    dtype=np.float32,
)
KD = np.asarray(
    [
        1,
        1,
        1,
        2,
        1,
        1,
        1,
        1,
        1,
        2,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
    ],
    dtype=np.float32,
)


@dataclass
class EpisodeInfo:
    episode_index: int
    length: int
    start: int
    stop: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_RAW_ROOT, help="Raw LeRobot dataset root.")
    parser.add_argument("--episode", type=int, default=0)
    parser.add_argument("--episode-count", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=None, help="Max actions per episode.")
    parser.add_argument("--frequency", type=float, default=30.0)
    parser.add_argument("--network-interface", default=None)
    parser.add_argument("--output-root", type=Path, default=Path("wbt_full_body_results"))
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--send-actions", action="store_true")
    parser.add_argument("--control-confirmation", default="")
    parser.add_argument(
        "--release-motion-mode",
        action="store_true",
        help="Call MotionSwitcher.ReleaseMode before low-level control. Dangerous; only use intentionally.",
    )
    parser.add_argument(
        "--no-hands",
        action="store_true",
        help="Do not publish Inspire hand commands even if hand_cmd exists.",
    )
    parser.add_argument("--hand-force", type=int, default=500)
    parser.add_argument("--hand-speed", type=int, default=300)
    parser.add_argument("--hand-action-scale", type=float, default=1000.0)
    parser.add_argument("--max-body-delta-rad", type=float, default=0.015)
    parser.add_argument("--max-hand-delta", type=float, default=50.0)
    parser.add_argument("--ignore-inspire-status", action="store_true")
    parser.add_argument("--disable-left-hand", action="store_true")
    parser.add_argument("--disable-right-hand", action="store_true")
    parser.add_argument("--state-timeout-s", type=float, default=5.0)
    parser.add_argument("--initialize-from-dataset", action="store_true")
    parser.add_argument("--initialization-speed-rad-s", type=float, default=0.10)
    parser.add_argument("--initialization-timeout-s", type=float, default=180.0)
    parser.add_argument("--initialization-max-error-rad", type=float, default=0.10)
    parser.add_argument(
        "--low-body-kp-scale",
        type=float,
        default=0.35,
        help="Scale kp for joints 0:15 during real playback. Conservative by default.",
    )
    parser.add_argument(
        "--arm-kp-scale",
        type=float,
        default=1.0,
        help="Scale kp for arm joints 15:29 during real playback.",
    )
    parser.add_argument("--preview-only", action="store_true", help="Only print dataset summary and exit.")
    parser.add_argument("--print-every", type=int, default=50)
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
    if args.send_actions and args.control_confirmation != CONTROL_CONFIRMATION:
        raise ValueError(f"Real full-body control requires --control-confirmation={CONTROL_CONFIRMATION}")


def load_info(root: Path) -> dict[str, Any]:
    with open(root / "meta" / "info.json") as f:
        info = json.load(f)
    feature = info["features"].get("action.robot_q_desired")
    if feature is None or feature.get("shape") != [36]:
        raise ValueError("Expected raw dataset with action.robot_q_desired shape [36]")
    return info


def load_episodes(root: Path) -> dict[int, EpisodeInfo]:
    path = root / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    table = pq.read_table(
        path,
        columns=["episode_index", "length", "dataset_from_index", "dataset_to_index"],
    )
    result = {}
    for row in table.to_pylist():
        ep = EpisodeInfo(
            episode_index=int(row["episode_index"]),
            length=int(row["length"]),
            start=int(row["dataset_from_index"]),
            stop=int(row["dataset_to_index"]),
        )
        result[ep.episode_index] = ep
    return result


def load_data(root: Path, start: int, stop: int) -> dict[str, np.ndarray]:
    data_dir = root / "data" / "chunk-000"
    arrays = {
        "action.robot_q_desired": [],
        "action.hand_cmd": [],
        "episode_index": [],
        "frame_index": [],
        "index": [],
    }
    for file_path in sorted(data_dir.glob("file-*.parquet")):
        table = pq.read_table(file_path, columns=list(arrays))
        df = table.to_pandas()
        mask = (df["index"] >= start) & (df["index"] < stop)
        if not mask.any():
            continue
        part = df.loc[mask]
        arrays["action.robot_q_desired"].extend(part["action.robot_q_desired"].to_list())
        arrays["action.hand_cmd"].extend(part["action.hand_cmd"].to_list())
        arrays["episode_index"].extend(part["episode_index"].to_list())
        arrays["frame_index"].extend(part["frame_index"].to_list())
        arrays["index"].extend(part["index"].to_list())
    if not arrays["index"]:
        raise ValueError(f"No rows found for dataset index range [{start}, {stop})")
    return {
        "q_desired": np.asarray(arrays["action.robot_q_desired"], dtype=np.float32),
        "hand_cmd": np.asarray(arrays["action.hand_cmd"], dtype=np.float32),
        "episode_index": np.asarray(arrays["episode_index"], dtype=np.int64),
        "frame_index": np.asarray(arrays["frame_index"], dtype=np.int64),
        "index": np.asarray(arrays["index"], dtype=np.int64),
    }


def make_run_dir(args: argparse.Namespace) -> Path:
    if args.run_name:
        name = args.run_name
    else:
        name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_episode-{args.episode:03d}"
    run_dir = args.output_root / name
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


class LowStateReader:
    def __init__(self, subscriber_cls, state_type):
        self._lock = threading.Lock()
        self._state = None
        self._subscriber = subscriber_cls("rt/lowstate", state_type)
        self._subscriber.Init(self._callback, 10)

    def _callback(self, msg) -> None:
        q = np.asarray([msg.motor_state[i].q for i in range(G1_MOTOR_DOF)], dtype=np.float32)
        dq = np.asarray([msg.motor_state[i].dq for i in range(G1_MOTOR_DOF)], dtype=np.float32)
        with self._lock:
            self._state = {
                "q": q,
                "dq": dq,
                "mode_machine": int(msg.mode_machine),
                "time": time.monotonic(),
            }

    def get(self, max_age_s: float) -> dict[str, Any]:
        with self._lock:
            state = None if self._state is None else {k: v.copy() if isinstance(v, np.ndarray) else v for k, v in self._state.items()}
        if state is None:
            raise TimeoutError("No rt/lowstate received yet")
        if time.monotonic() - state["time"] > max_age_s:
            raise TimeoutError("rt/lowstate is stale")
        return state

    def wait(self, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        last_error = None
        while time.monotonic() < deadline:
            try:
                return self.get(timeout_s)
            except TimeoutError as exc:
                last_error = exc
                time.sleep(0.01)
        raise TimeoutError(f"No rt/lowstate within {timeout_s:.1f}s") from last_error


class InspireStateReader:
    def __init__(self, subscriber_cls, state_type, topic: str):
        self.topic = topic
        self._lock = threading.Lock()
        self._state: dict[str, np.ndarray | float] | None = None
        self._subscriber = subscriber_cls(topic, state_type)
        self._subscriber.Init(self._callback, 10)

    def _callback(self, msg) -> None:
        state = {
            "angle_act": np.asarray(msg.angle_act, dtype=np.float32),
            "err": np.asarray(msg.err, dtype=np.int16),
            "status": np.asarray(msg.status, dtype=np.int16),
            "time": time.monotonic(),
        }
        with self._lock:
            self._state = state

    def get(self, max_age_s: float) -> dict[str, np.ndarray | float]:
        with self._lock:
            state = None if self._state is None else {
                k: v.copy() if isinstance(v, np.ndarray) else v for k, v in self._state.items()
            }
        if state is None:
            raise TimeoutError(f"No Inspire state received on {self.topic}")
        if time.monotonic() - float(state["time"]) > max_age_s:
            raise TimeoutError(f"Inspire state on {self.topic} is stale")
        return state

    def wait(self, timeout_s: float) -> dict[str, np.ndarray | float]:
        deadline = time.monotonic() + timeout_s
        last_error = None
        while time.monotonic() < deadline:
            try:
                return self.get(timeout_s)
            except TimeoutError as exc:
                last_error = exc
                time.sleep(0.01)
        raise TimeoutError(f"No Inspire state received on {self.topic} within {timeout_s:.1f}s") from last_error


def add_inspire_idl_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inspire_idl_root = repo_root / "inspire_hand_ws" / "inspire_hand_sdk" / "inspire_sdkpy"
    if inspire_idl_root.exists():
        sys.path.insert(0, str(inspire_idl_root))


class RobotIO:
    def __init__(self, args: argparse.Namespace):
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelPublisher, ChannelSubscriber
        from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, LowState_
        from unitree_sdk2py.utils.crc import CRC

        try:
            if args.network_interface:
                ChannelFactoryInitialize(0, args.network_interface)
            else:
                ChannelFactoryInitialize(0)
        except TypeError:
            ChannelFactoryInitialize(0)

        if args.release_motion_mode:
            from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

            msc = MotionSwitcherClient()
            msc.SetTimeout(5.0)
            msc.Init()
            status, mode = msc.CheckMode()
            print(f"G1 MotionSwitcher before lowcmd: status={status}, mode={mode}")
            if mode.get("name"):
                print("Releasing active motion mode for low-level full-body control...")
                msc.ReleaseMode()
                time.sleep(1.0)
                print(f"G1 MotionSwitcher after release: {msc.CheckMode()}")
        else:
            try:
                from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

                msc = MotionSwitcherClient()
                msc.SetTimeout(2.0)
                msc.Init()
                print(f"G1 MotionSwitcher: {msc.CheckMode()}")
            except Exception as exc:
                print(f"WARNING: could not inspect G1 MotionSwitcher mode: {exc}")

        self.crc = CRC()
        self.low_cmd = unitree_hg_msg_dds__LowCmd_()
        self.publisher = ChannelPublisher("rt/lowcmd", LowCmd_)
        self.publisher.Init()
        self.reader = LowStateReader(ChannelSubscriber, LowState_)
        first = self.reader.wait(args.state_timeout_s)
        self.mode_machine = int(first["mode_machine"])
        self.low_cmd.mode_pr = 0
        self.low_cmd.mode_machine = self.mode_machine

        self.hand_publishers = {}
        self.hand_readers = {}
        self.inspire_ctrl_type = None
        self.hand_last: np.ndarray | None = None
        if not args.no_hands:
            add_inspire_idl_path()
            try:
                from inspire_dds import inspire_hand_ctrl, inspire_hand_state
            except ModuleNotFoundError:
                print("WARNING: inspire_dds not found; disabling hand command publish.")
            else:
                self.inspire_ctrl_type = inspire_hand_ctrl
                if not args.disable_left_hand:
                    self.hand_publishers["left"] = ChannelPublisher("rt/inspire_hand/ctrl/l", inspire_hand_ctrl)
                    self.hand_publishers["left"].Init()
                    self.hand_readers["left"] = InspireStateReader(
                        ChannelSubscriber, inspire_hand_state, "rt/inspire_hand/state/l"
                    )
                if not args.disable_right_hand:
                    self.hand_publishers["right"] = ChannelPublisher("rt/inspire_hand/ctrl/r", inspire_hand_ctrl)
                    self.hand_publishers["right"].Init()
                    self.hand_readers["right"] = InspireStateReader(
                        ChannelSubscriber, inspire_hand_state, "rt/inspire_hand/state/r"
                    )
                self.hand_last = self.read_hand_angles(args)

    def current_body_q(self, max_age_s: float) -> np.ndarray:
        return self.reader.get(max_age_s)["q"]

    def publish_body(self, q_target: np.ndarray, kp_scale_low_body: float, kp_scale_arm: float) -> None:
        q_target = np.asarray(q_target, dtype=np.float32)
        if q_target.shape != (G1_MOTOR_DOF,):
            raise ValueError(f"Expected G1 body target shape ({G1_MOTOR_DOF},), got {q_target.shape}")
        kp = KP.copy()
        kp[:15] *= float(kp_scale_low_body)
        kp[15:] *= float(kp_scale_arm)
        for i in range(G1_MOTOR_DOF):
            self.low_cmd.motor_cmd[i].mode = 1
            self.low_cmd.motor_cmd[i].tau = 0.0
            self.low_cmd.motor_cmd[i].q = float(q_target[i])
            self.low_cmd.motor_cmd[i].dq = 0.0
            self.low_cmd.motor_cmd[i].kp = float(kp[i])
            self.low_cmd.motor_cmd[i].kd = float(KD[i])
        self.low_cmd.mode_pr = 0
        self.low_cmd.mode_machine = self.mode_machine
        self.low_cmd.crc = self.crc.Crc(self.low_cmd)
        self.publisher.Write(self.low_cmd)

    def read_hand_angles(self, args: argparse.Namespace) -> np.ndarray | None:
        if not self.hand_readers:
            return None
        result = np.zeros(HAND_TOTAL_DOF, dtype=np.float32)
        for side, offset in [("left", 0), ("right", HAND_DOF)]:
            reader = self.hand_readers.get(side)
            if reader is None:
                continue
            state = reader.wait(args.state_timeout_s)
            angle = np.asarray(state["angle_act"], dtype=np.float32)
            err = np.asarray(state["err"], dtype=np.int16)
            status = np.asarray(state["status"], dtype=np.int16)
            print(
                f"{side} Inspire state: angle_act={angle.astype(int).tolist()} "
                f"err={err.tolist()} status={status.tolist()}"
            )
            if not args.ignore_inspire_status:
                bad_err = np.flatnonzero(err != 0)
                bad_status = np.flatnonzero(status == 7)
                if len(bad_err) or len(bad_status):
                    raise RuntimeError(
                        f"{side} Inspire reports err={err.tolist()} status={status.tolist()}. "
                        "Use --ignore-inspire-status only if you intentionally want to continue."
                    )
            result[offset : offset + HAND_DOF] = angle
        return result

    def publish_hands(self, hand_cmd: np.ndarray, args: argparse.Namespace) -> np.ndarray:
        if self.inspire_ctrl_type is None or not self.hand_publishers:
            return np.zeros(HAND_TOTAL_DOF, dtype=np.float32)
        hand = np.asarray(hand_cmd, dtype=np.float32).reshape(HAND_TOTAL_DOF) * float(args.hand_action_scale)
        hand = np.clip(hand, 0, 1000)
        if self.hand_last is not None:
            hand = self.hand_last + np.clip(hand - self.hand_last, -args.max_hand_delta, args.max_hand_delta)
            hand = np.clip(hand, 0, 1000)
        targets = {
            "left": hand[:HAND_DOF].astype(np.int16).tolist(),
            "right": hand[HAND_DOF:].astype(np.int16).tolist(),
        }
        for side, target in targets.items():
            publisher = self.hand_publishers.get(side)
            if publisher is None:
                continue
            msg = self.inspire_ctrl_type(
                pos_set=[0] * HAND_DOF,
                angle_set=target,
                force_set=[int(args.hand_force)] * HAND_DOF,
                speed_set=[int(args.hand_speed)] * HAND_DOF,
                mode=0b1101,
            )
            publisher.Write(msg)
        self.hand_last = hand.astype(np.float32)
        return hand.astype(np.float32)


def clip_step(target: np.ndarray, current: np.ndarray, max_delta: float) -> np.ndarray:
    return current + np.clip(target - current, -max_delta, max_delta)


def summarize_episode(ep: EpisodeInfo, q_desired: np.ndarray) -> None:
    root = q_desired[:, :ROOT_DOF]
    body = q_desired[:, ROOT_DOF : ROOT_DOF + G1_MOTOR_DOF]
    print(
        f"episode={ep.episode_index} dataset_index={ep.start}..{ep.stop - 1} "
        f"actions={len(q_desired)} root_range_xyz="
        f"{np.round(root[:, :3].min(axis=0), 3).tolist()}..{np.round(root[:, :3].max(axis=0), 3).tolist()}"
    )
    for idx, name in enumerate(G1_JOINT_NAMES):
        print(
            f"  body[{idx:02d}] {name:20s} "
            f"min={body[:, idx].min(): .3f} max={body[:, idx].max(): .3f} "
            f"std={body[:, idx].std(): .3f}"
        )


def initialize_body(io: RobotIO, first_target: np.ndarray, args: argparse.Namespace) -> None:
    print("Initializing full body to first dataset joint pose...")
    max_step = args.initialization_speed_rad_s / args.frequency
    start = time.monotonic()
    last_print = 0.0
    while True:
        current = io.current_body_q(args.state_timeout_s)
        error = np.max(np.abs(first_target - current))
        if error <= args.initialization_max_error_rad:
            print(f"Initial body pose reached: max_error={error:.3f} rad")
            return
        if time.monotonic() - start > args.initialization_timeout_s:
            raise TimeoutError(f"Timed out initializing body pose: max_error={error:.3f} rad")
        command = clip_step(first_target, current, max_step)
        io.publish_body(command, args.low_body_kp_scale, args.arm_kp_scale)
        now = time.monotonic()
        if now - last_print >= 1.0:
            print(f"Initializing body: elapsed={now - start:.1f}s max_error={error:.3f} rad")
            last_print = now
        time.sleep(1.0 / args.frequency)


def replay_episode(
    ep: EpisodeInfo,
    rows: dict[str, np.ndarray],
    args: argparse.Namespace,
    run_dir: Path,
    io: RobotIO | None,
) -> None:
    q_full = rows["q_desired"]
    hand_cmd = rows["hand_cmd"]
    if q_full.ndim != 2 or q_full.shape[1] != ROOT_DOF + G1_MOTOR_DOF:
        raise ValueError(f"Expected q_desired shape (T, 36), got {q_full.shape}")
    actions = len(q_full) if args.max_steps is None else min(len(q_full), args.max_steps)
    body_targets = q_full[:actions, ROOT_DOF : ROOT_DOF + G1_MOTOR_DOF]

    csv_path = run_dir / f"episode-{ep.episode_index:03d}_steps.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "action_step",
                "episode",
                "dataset_index",
                "frame_index",
                "dry_run",
                "max_body_delta",
                "body_target_norm",
                "body_command_norm",
            ],
        )
        writer.writeheader()

        if io is not None and args.initialize_from_dataset:
            initialize_body(io, body_targets[0], args)

        if io is not None:
            user_input = input(
                "Initial pose stage done. Enter 's' to start full-body replay, anything else to stop: "
            )
            if user_input.strip().lower() != "s":
                print("Stopped before replay.")
                return

        print(
            f"Starting full-body dataset playback: episode={ep.episode_index} "
            f"dataset_index={ep.start}..{ep.start + actions - 1} actions={actions} "
            f"dry_run={io is None}"
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
                if not args.no_hands:
                    io.publish_hands(hand_cmd[step], args)
                body_last = command

            writer.writerow(
                {
                    "action_step": step + 1,
                    "episode": ep.episode_index,
                    "dataset_index": int(rows["index"][step]),
                    "frame_index": int(rows["frame_index"][step]),
                    "dry_run": io is None,
                    "max_body_delta": max_delta,
                    "body_target_norm": float(np.linalg.norm(target)),
                    "body_command_norm": float(np.linalg.norm(command)),
                }
            )
            if (step + 1) % args.print_every == 0 or step + 1 == actions:
                print(
                    f"action_step={step + 1}/{actions} dataset_index={int(rows['index'][step])} "
                    f"max_delta={max_delta:.4f} dry_run={io is None}"
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
    with open(run_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    if args.preview_only:
        print(f"Preview written: {run_dir}")
        return run_dir

    io = RobotIO(args) if args.send_actions else None
    for ep, rows in loaded:
        replay_episode(ep, rows, args, run_dir, io)
    print(f"WBT full-body replay results: {run_dir}")
    return run_dir


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
