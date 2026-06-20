#!/usr/bin/env python3
"""Hybrid online inference for G1 WBT Inspire Pick Up Drinks flat26 policies.

This runner is for the flattened WBT Inspire dataset:

    observation.state = 14 G1 arm joints + 12 Inspire hand joints
    action            = 14 G1 arm joints + 12 Inspire hand commands

For an early real-robot deployment, camera observations are still read from the
dataset while the 26D proprioceptive state is read from the real robot:

    dataset images + real G1 arm state + real Inspire left/right angle_act
        -> ACT policy
        -> action[:14]      to G1 arm controller
        -> action[14:20]    to rt/inspire_hand/ctrl/l
        -> action[20:26]    to rt/inspire_hand/ctrl/r

The Inspire FTP Modbus->DDS bridges must already be running, e.g.:

    python unitree_lerobot/eval_robot/inspire_hand_ftp_driver.py --hand=left  --ip=192.168.123.210 ...
    python unitree_lerobot/eval_robot/inspire_hand_ftp_driver.py --hand=right --ip=192.168.123.211 ...

Default mode is dry-run. Real control requires --send-actions and an explicit
confirmation string.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch

from lerobot.configs.policies import PreTrainedConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.factory import make_policy, make_pre_post_processors
from lerobot.processor.rename_processor import rename_stats
from lerobot.utils.utils import get_safe_torch_device, init_logging

from unitree_lerobot.eval_robot.hybrid_arm_utils import ARM_DOF, chunk_timestep_range, limit_arm_target
from unitree_lerobot.eval_robot.utils.utils import extract_observation


HAND_DOF = 6
DUAL_HAND_DOF = 12
STATE_DOF = ARM_DOF + DUAL_HAND_DOF
CONTROL_CONFIRMATION = "SEND_TO_REAL_G1_INSPIRE"
HAND_MODE_ANGLE_FORCE_SPEED = 0b1101


def add_inspire_idl_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inspire_idl_root = repo_root / "inspire_hand_ws" / "inspire_hand_sdk" / "inspire_sdkpy"
    if inspire_idl_root.exists():
        sys.path.insert(0, str(inspire_idl_root))


class InspireStateReader:
    def __init__(self, subscriber_cls, state_type, suffix: str, timeout_s: float):
        self.topic = f"rt/inspire_hand/state/{suffix}"
        self._state: dict[str, np.ndarray] | None = None
        self._last_update_s: float | None = None
        self._lock = threading.Lock()
        self._subscriber = subscriber_cls(self.topic, state_type)
        self._subscriber.Init(self._callback, 10)
        self.wait(timeout_s)

    def _callback(self, msg) -> None:
        state = {
            "angle_act": np.asarray(msg.angle_act, dtype=np.float32),
            "pos_act": np.asarray(msg.pos_act, dtype=np.float32),
            "force_act": np.asarray(msg.force_act, dtype=np.float32),
            "current": np.asarray(msg.current, dtype=np.float32),
            "err": np.asarray(msg.err, dtype=np.int16),
            "status": np.asarray(msg.status, dtype=np.int16),
            "temperature": np.asarray(msg.temperature, dtype=np.int16),
        }
        with self._lock:
            self._state = state
            self._last_update_s = time.monotonic()

    def get(self, max_age_s: float) -> dict[str, np.ndarray]:
        with self._lock:
            state = None if self._state is None else {key: value.copy() for key, value in self._state.items()}
            last_update_s = self._last_update_s
        if state is None or last_update_s is None:
            raise RuntimeError(f"No Inspire state received on {self.topic}")
        age_s = time.monotonic() - last_update_s
        if age_s > max_age_s:
            raise TimeoutError(f"Inspire state on {self.topic} is stale ({age_s:.3f}s > {max_age_s:.3f}s)")
        return state

    def wait(self, timeout_s: float) -> dict[str, np.ndarray]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                return self.get(max_age_s=timeout_s)
            except Exception:
                time.sleep(0.01)
        raise TimeoutError(f"No Inspire state received on {self.topic} within {timeout_s:.1f}s")


class InspireCommandPublisher:
    def __init__(self, publisher_cls, ctrl_type, suffix: str):
        self.topic = f"rt/inspire_hand/ctrl/{suffix}"
        self._ctrl_type = ctrl_type
        self._publisher = publisher_cls(self.topic, ctrl_type)
        self._publisher.Init()

    def send(self, angle_set: np.ndarray, force: int, speed: int) -> None:
        target = np.asarray(angle_set, dtype=np.float32).reshape(-1)
        if target.shape != (HAND_DOF,) or not np.all(np.isfinite(target)):
            raise ValueError(f"Invalid Inspire target for {self.topic}: shape={target.shape}")
        target_i16 = np.clip(np.rint(target), 0, 1000).astype(np.int16).tolist()
        cmd = self._ctrl_type(
            pos_set=[0] * HAND_DOF,
            angle_set=target_i16,
            force_set=[int(force)] * HAND_DOF,
            speed_set=[int(speed)] * HAND_DOF,
            mode=HAND_MODE_ANGLE_FORCE_SPEED,
        )
        self._publisher.Write(cmd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-path", required=True)
    parser.add_argument("--repo-id", default="local/G1_WBT_Inspire_Pick_Up_Drinks_flat26")
    parser.add_argument("--root", default=None)
    parser.add_argument("--episode", type=int, default=0)
    parser.add_argument("--episode-count", type=int, default=1, help="Run this many consecutive episodes.")
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--max-policy-steps", type=int, default=120)
    parser.add_argument(
        "--actions-per-inference",
        type=int,
        default=100,
        help="Maximum actions consumed from each ACT chunk.",
    )
    parser.add_argument(
        "--prefetch-threshold",
        type=float,
        default=0.9,
        help="Start background inference when the queue falls to this fraction of actions-per-inference.",
    )
    parser.add_argument(
        "--synchronous-inference",
        action="store_true",
        help="Disable background prefetch and wait for each ACT chunk synchronously.",
    )
    parser.add_argument("--frequency", type=float, default=30.0)
    parser.add_argument("--network-interface", default=None)
    parser.add_argument("--motion", action="store_true", help="Use rt/arm_sdk for G1 arms.")
    parser.add_argument("--send-actions", action="store_true", help="Publish arm and hand actions. Default is dry-run.")
    parser.add_argument("--control-confirmation", default="")
    parser.add_argument("--state-timeout-s", type=float, default=0.25)
    parser.add_argument("--dds-wait-timeout-s", type=float, default=10.0)
    parser.add_argument("--max-arm-delta-rad", type=float, default=0.02)
    parser.add_argument("--max-hand-delta", type=float, default=80.0, help="Max Inspire angle units per step.")
    parser.add_argument(
        "--hand-state-scale",
        type=float,
        default=1000.0,
        help="Divide real Inspire angle_act by this before feeding observation.state to the policy.",
    )
    parser.add_argument(
        "--hand-action-scale",
        type=float,
        default=1000.0,
        help="Multiply policy/dataset hand actions by this before sending Inspire commands.",
    )
    parser.add_argument("--hand-force", type=int, default=500)
    parser.add_argument("--hand-speed", type=int, default=300)
    parser.add_argument("--disable-arms", action="store_true", help="Read G1 arm state but do not publish arm commands.")
    parser.add_argument("--disable-left-hand", action="store_true")
    parser.add_argument("--disable-right-hand", action="store_true")
    parser.add_argument("--ignore-inspire-status", action="store_true")
    parser.add_argument(
        "--use-dataset-action",
        action="store_true",
        help="Replay dataset action directly instead of using the policy output.",
    )
    parser.add_argument("--initialize-from-dataset", action="store_true")
    parser.add_argument(
        "--initialize-arms-only",
        action="store_true",
        help="During dataset-pose initialization, move/check only G1 arms and ignore Inspire hands.",
    )
    parser.add_argument("--initialization-speed-rad-s", type=float, default=0.05)
    parser.add_argument("--initialization-max-tracking-error-rad", type=float, default=0.05)
    parser.add_argument("--initialization-timeout-s", type=float, default=120.0)
    parser.add_argument("--output-root", default="wbt_inspire_results")
    parser.add_argument("--run-name", default=None)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.frequency <= 0:
        raise ValueError("--frequency must be positive")
    if args.episode < 0 or args.start_frame < 0:
        raise ValueError("--episode and --start-frame must be non-negative")
    if args.episode_count <= 0:
        raise ValueError("--episode-count must be positive")
    if args.max_policy_steps is not None and args.max_policy_steps <= 0:
        raise ValueError("--max-policy-steps must be positive")
    if args.actions_per_inference <= 0:
        raise ValueError("--actions-per-inference must be positive")
    if not 0 < args.prefetch_threshold < 1:
        raise ValueError("--prefetch-threshold must be between zero and one")
    if args.max_arm_delta_rad <= 0 or args.max_hand_delta <= 0:
        raise ValueError("Delta limits must be positive")
    if args.hand_state_scale <= 0 or args.hand_action_scale <= 0:
        raise ValueError("Hand scale values must be positive")
    if args.state_timeout_s <= 0 or args.dds_wait_timeout_s <= 0:
        raise ValueError("Timeout values must be positive")
    if args.initialization_max_tracking_error_rad <= 0:
        raise ValueError("--initialization-max-tracking-error-rad must be positive")
    if args.send_actions and args.control_confirmation != CONTROL_CONFIRMATION:
        raise ValueError(
            f"Real robot control requires --control-confirmation={CONTROL_CONFIRMATION}. "
            "Run without --send-actions for dry-run."
        )
    if args.initialize_from_dataset and not args.send_actions:
        raise ValueError("--initialize-from-dataset requires --send-actions")


def episode_bounds(dataset: LeRobotDataset, episode: int, start_frame: int) -> tuple[int, int]:
    if episode >= dataset.meta.total_episodes:
        raise ValueError(f"Episode {episode} is out of range [0, {dataset.meta.total_episodes - 1}]")
    episode_from = int(dataset.meta.episodes["dataset_from_index"][episode])
    episode_to = int(dataset.meta.episodes["dataset_to_index"][episode])
    start = episode_from + start_frame
    if start >= episode_to:
        raise ValueError(f"start-frame {start_frame} is outside episode {episode}")
    return start, episode_to


def make_run_dir(output_root: Path, run_name: str | None, episode: int, episode_count: int = 1) -> Path:
    if run_name is None or episode_count > 1:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_name = f"{timestamp}_episode-{episode:03d}"
    run_dir = output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def load_policy_and_processors(policy_path: Path, dataset: LeRobotDataset):
    policy_cfg = PreTrainedConfig.from_pretrained(policy_path)
    if policy_cfg.type != "act":
        raise ValueError(f"Async WBT inference requires an ACT checkpoint, got {policy_cfg.type!r}")
    state_feature = policy_cfg.input_features.get("observation.state")
    action_feature = policy_cfg.output_features.get("action")
    if state_feature is None or tuple(state_feature.shape) != (STATE_DOF,):
        raise ValueError(f"Checkpoint observation.state must have shape ({STATE_DOF},)")
    if action_feature is None or tuple(action_feature.shape) != (STATE_DOF,):
        raise ValueError(f"Checkpoint action must have shape ({STATE_DOF},)")
    policy_cfg.pretrained_path = policy_path
    device = get_safe_torch_device(policy_cfg.device, log=True)
    policy = make_policy(cfg=policy_cfg, ds_meta=dataset.meta)
    policy.eval()
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=policy_cfg,
        pretrained_path=policy_path,
        dataset_stats=rename_stats(dataset.meta.stats, {}),
        preprocessor_overrides={
            "device_processor": {"device": policy_cfg.device},
            "rename_observations_processor": {"rename_map": {}},
        },
    )
    return policy_cfg, policy, preprocessor, postprocessor, device


def predict_action_chunk(
    observation: dict[str, Any],
    task: str,
    policy,
    preprocessor,
    postprocessor,
    device: torch.device,
) -> np.ndarray:
    batch = {}
    for name, value in observation.items():
        if not hasattr(value, "unsqueeze"):
            continue
        batch[name] = value.unsqueeze(0).to(device)
    batch["task"] = task or ""
    batch["robot_type"] = ""
    with (
        torch.inference_mode(),
        torch.autocast(device_type=device.type)
        if device.type == "cuda" and policy.config.use_amp
        else nullcontext(),
    ):
        processed = preprocessor(batch)
        chunk = policy.predict_action_chunk(processed)
        chunk = postprocessor(chunk)
    chunk_np = chunk.squeeze(0).detach().cpu().numpy()
    if chunk_np.ndim != 2 or chunk_np.shape[1] != STATE_DOF or not np.all(np.isfinite(chunk_np)):
        raise ValueError(f"Expected finite action chunk shape (T, {STATE_DOF}), got {chunk_np.shape}")
    return chunk_np


@dataclass
class QueuedAction:
    predicted: np.ndarray
    chunk_offset: int
    inference_anchor: int
    inference_s: float
    report_inference: bool = False


@dataclass
class InferenceResult:
    anchor: int
    action_chunk: np.ndarray
    inference_s: float


def infer_action_chunk(
    dataset,
    anchor: int,
    real_state: np.ndarray,
    policy,
    preprocessor,
    postprocessor,
    device: torch.device,
) -> InferenceResult:
    observation, task, _, _ = compose_observation(dataset, anchor, real_state)
    preprocessor.reset()
    postprocessor.reset()
    inference_start = time.perf_counter()
    chunk = predict_action_chunk(observation, task, policy, preprocessor, postprocessor, device)
    return InferenceResult(
        anchor=anchor,
        action_chunk=chunk,
        inference_s=time.perf_counter() - inference_start,
    )


def merge_inference_result(
    action_queue: dict[int, QueuedAction],
    result: InferenceResult,
    current_timestep: int,
    actions_per_inference: int,
    stop_timestep: int,
) -> int:
    timesteps = chunk_timestep_range(
        result.anchor,
        len(result.action_chunk),
        actions_per_inference,
        current_timestep,
    )
    inserted_timesteps = []
    for timestep in timesteps:
        if timestep >= stop_timestep:
            break
        offset = timestep - result.anchor
        action_queue[timestep] = QueuedAction(
            predicted=result.action_chunk[offset],
            chunk_offset=offset,
            inference_anchor=result.anchor,
            inference_s=result.inference_s,
        )
        inserted_timesteps.append(timestep)
    if inserted_timesteps:
        action_queue[min(inserted_timesteps)].report_inference = True
    return len(inserted_timesteps)


def tensor_to_numpy(value: Any) -> np.ndarray:
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().numpy()
    return np.asarray(value)


def tensor_item_int(value: Any) -> int:
    if isinstance(value, torch.Tensor):
        return int(value.item())
    return int(value)


def get_dataset_row_no_video(dataset, dataset_index: int) -> dict[str, Any]:
    dataset._ensure_hf_dataset_loaded()
    return dataset.hf_dataset[dataset_index]


def compose_observation(
    dataset, dataset_index: int, real_state_26d: np.ndarray
) -> tuple[dict[str, Any], str, np.ndarray, dict[str, Any]]:
    step = dataset[dataset_index]
    dataset_state = tensor_to_numpy(step["observation.state"])
    if dataset_state.shape != (STATE_DOF,):
        raise ValueError(f"Dataset observation.state must be ({STATE_DOF},), got {dataset_state.shape}")
    observation = extract_observation(step)
    observation = {
        name: value.clone() if isinstance(value, torch.Tensor) else value for name, value in observation.items()
    }
    observation["observation.state"] = torch.as_tensor(real_state_26d, dtype=step["observation.state"].dtype)
    return observation, step["task"], dataset_state, step


def read_arm_state(state_source, max_age_s: float) -> np.ndarray:
    try:
        return state_source.get_current_dual_arm_q(max_age_s=max_age_s)
    except TypeError:
        state = np.asarray(state_source.get_current_dual_arm_q(), dtype=np.float32)
        if state.shape != (ARM_DOF,) or not np.all(np.isfinite(state)):
            raise RuntimeError(f"Invalid G1 arm state: shape={state.shape}")
        return state


def read_hand_state(reader: InspireStateReader, max_age_s: float, label: str, ignore_status: bool) -> np.ndarray:
    state = reader.get(max_age_s=max_age_s)
    angle = state["angle_act"].astype(np.float32)
    if angle.shape != (HAND_DOF,) or not np.all(np.isfinite(angle)):
        raise RuntimeError(f"Invalid {label} Inspire angle state: {angle}")
    err = state["err"]
    status = state["status"]
    if not ignore_status:
        bad_err = np.flatnonzero(err != 0)
        bad_status = np.flatnonzero(status == 7)
        if len(bad_err) or len(bad_status):
            raise RuntimeError(
                f"{label} Inspire reports err={err.tolist()} status={status.tolist()}. "
                "Use --ignore-inspire-status only if you intentionally want to continue."
            )
    return angle


def limit_hand_target(predicted: np.ndarray, current: np.ndarray, max_delta: float) -> np.ndarray:
    predicted = np.asarray(predicted, dtype=np.float32).reshape(-1)
    current = np.asarray(current, dtype=np.float32).reshape(-1)
    if predicted.shape != (HAND_DOF,) or current.shape != (HAND_DOF,):
        raise ValueError(f"Expected hand vectors ({HAND_DOF},), got {predicted.shape} and {current.shape}")
    delta = np.clip(predicted - current, -max_delta, max_delta)
    return np.clip(current + delta, 0, 1000)


def setup_dds_and_io(args: argparse.Namespace):
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelPublisher, ChannelSubscriber

    add_inspire_idl_path()
    from inspire_dds import inspire_hand_ctrl, inspire_hand_state

    if args.send_actions:
        try:
            if args.network_interface:
                ChannelFactoryInitialize(0, args.network_interface)
            else:
                ChannelFactoryInitialize(0)
        except TypeError:
            ChannelFactoryInitialize(0)

        from unitree_lerobot.eval_robot.hybrid_arm_infer import report_motion_mode
        from unitree_lerobot.eval_robot.robot_control.robot_arm import G1_29_ArmController
        from unitree_lerobot.eval_robot.robot_control.robot_arm_ik import G1_29_ArmIK

        report_motion_mode()
        if args.motion:
            print(
                "G1 arm SDK preflight: the robot must be in Regular motion-control mode "
                "(latest R3 sequence: L2+B, L2+UP, then R1+X), not Running or Debug mode. "
                "MotionSwitcher name 'ai' alone does not identify this sub-mode.",
                flush=True,
            )
        arm_source = G1_29_ArmController(
            motion_mode=args.motion,
            simulation_mode=False,
            initialize_dds=False,
        )
        arm_ik = G1_29_ArmIK()
        current = arm_source.get_current_dual_arm_q()
        arm_source.ctrl_dual_arm(current, arm_ik.solve_tau(current))
    else:
        from unitree_lerobot.eval_robot.robot_control.arm_state_reader import G1ArmStateReader

        arm_source = G1ArmStateReader(
            network_interface=args.network_interface,
            timeout_s=args.dds_wait_timeout_s,
        )
        arm_ik = None

    left_reader = InspireStateReader(ChannelSubscriber, inspire_hand_state, "l", args.dds_wait_timeout_s)
    right_reader = InspireStateReader(ChannelSubscriber, inspire_hand_state, "r", args.dds_wait_timeout_s)
    left_pub = right_pub = None
    if args.send_actions:
        left_pub = InspireCommandPublisher(ChannelPublisher, inspire_hand_ctrl, "l")
        right_pub = InspireCommandPublisher(ChannelPublisher, inspire_hand_ctrl, "r")
    return arm_source, arm_ik, left_reader, right_reader, left_pub, right_pub


def initialize_from_dataset_pose(
    args: argparse.Namespace,
    arm_source,
    arm_ik,
    left_reader,
    right_reader,
    left_pub,
    right_pub,
    target_state: np.ndarray,
) -> None:
    target_arm = target_state[:ARM_DOF]
    target_left = target_state[ARM_DOF : ARM_DOF + HAND_DOF] * args.hand_action_scale
    target_right = target_state[ARM_DOF + HAND_DOF :] * args.hand_action_scale
    deadline = time.monotonic() + args.initialization_timeout_s
    arm_step = args.initialization_speed_rad_s / args.frequency
    start_s = time.monotonic()
    last_report_s = 0.0
    initial_arm = read_arm_state(arm_source, args.state_timeout_s)
    trajectory_arm = initial_arm.copy()

    print(
        "Initializing to dataset pose "
        f"({'arms only' if args.initialize_arms_only else 'arms + hands'}): "
        f"arm_step={arm_step:.5f} rad/tick",
        flush=True,
    )

    while time.monotonic() < deadline:
        current_arm = read_arm_state(arm_source, args.state_timeout_s)
        current_left = None
        current_right = None
        if not args.initialize_arms_only:
            current_left = read_hand_state(left_reader, args.state_timeout_s, "left", args.ignore_inspire_status)
            current_right = read_hand_state(right_reader, args.state_timeout_s, "right", args.ignore_inspire_status)
        trajectory_arm = limit_arm_target(target_arm, trajectory_arm, arm_step)
        next_arm = limit_arm_target(trajectory_arm, current_arm, args.initialization_max_tracking_error_rad)

        if not args.disable_arms:
            arm_source.ctrl_dual_arm(next_arm, arm_ik.solve_tau(next_arm))
        if not args.initialize_arms_only and not args.disable_left_hand:
            next_left = limit_hand_target(target_left, current_left, args.max_hand_delta)
            left_pub.send(next_left, args.hand_force, args.hand_speed)
        if not args.initialize_arms_only and not args.disable_right_hand:
            next_right = limit_hand_target(target_right, current_right, args.max_hand_delta)
            right_pub.send(next_right, args.hand_force, args.hand_speed)

        arm_error = 0.0 if args.disable_arms else float(np.max(np.abs(target_arm - current_arm)))
        hand_errors = []
        if not args.initialize_arms_only and not args.disable_left_hand:
            hand_errors.append(float(np.max(np.abs(target_left - current_left))))
        if not args.initialize_arms_only and not args.disable_right_hand:
            hand_errors.append(float(np.max(np.abs(target_right - current_right))))
        hand_error = max(hand_errors) if hand_errors else 0.0
        now_s = time.monotonic()
        if now_s - last_report_s >= 1.0:
            elapsed_s = now_s - start_s
            arm_motion = 0.0 if args.disable_arms else float(np.max(np.abs(current_arm - initial_arm)))
            print(
                f"Initializing dataset pose: elapsed={elapsed_s:.1f}s "
                f"arm_error={arm_error:.3f} rad moved={arm_motion:.3f} rad hand_error={hand_error:.1f}",
                flush=True,
            )
            last_report_s = now_s
            if (
                not args.disable_arms
                and now_s - start_s >= 3.0
                and arm_motion < 0.005
            ):
                if args.motion:
                    raise RuntimeError(
                        "Commands were published to rt/arm_sdk but no arm motion was detected. "
                        "Confirm the G1 is in Regular motion-control mode (R1+X), not Running mode (R2+A) "
                        "or Debug mode (L2+R2). MotionSwitcher name 'ai' alone does not identify this sub-mode. "
                        "No robot mode was changed automatically."
                    )
                raise RuntimeError(
                    "Commands were published to rt/lowcmd but no arm motion was detected. "
                    "If a G1 motion service is active, rerun with --motion to use rt/arm_sdk."
                )
        if arm_error < 0.03 and hand_error < 15:
            print("Dataset initial arm pose reached." if args.initialize_arms_only else "Dataset initial arm/hand pose reached.")
            return
        time.sleep(1.0 / args.frequency)
    raise TimeoutError("Timed out while initializing to dataset pose")


def write_config(run_dir: Path, args: argparse.Namespace, policy_cfg, start: int, stop: int, episode: int) -> None:
    config = vars(args).copy()
    config.update(
        {
            "effective_episode": episode,
            "policy_path": str(Path(args.policy_path).resolve()),
            "dataset_start_index": start,
            "dataset_stop_index": stop,
            "policy_type": policy_cfg.type,
            "dry_run": not args.send_actions,
            "action_source": "dataset" if args.use_dataset_action else "policy",
            "state_dof": STATE_DOF,
        }
    )
    (run_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")


def confirm_start() -> bool:
    while True:
        try:
            response = input("Initial pose reached. Enter 's' to start, or 'q' to stop: ")
        except EOFError:
            print("No interactive input received. Holding pose and stopping.")
            return False
        response = response.strip().lower()
        if response == "s":
            return True
        if response in {"q", "n", "no", "stop"}:
            return False
        if response == "":
            print("Empty input ignored. Type 's' to start or 'q' to stop.")
            continue
        print("Unknown input. Type 's' to start or 'q' to stop.")


def run_episode(
    args: argparse.Namespace,
    dataset: LeRobotDataset,
    policy_cfg,
    policy,
    preprocessor,
    postprocessor,
    device: torch.device,
    arm_source,
    arm_ik,
    left_reader,
    right_reader,
    left_pub,
    right_pub,
    episode: int,
    episode_offset: int,
) -> tuple[Path, bool]:
    start_frame = args.start_frame if episode_offset == 0 else 0
    start, episode_stop = episode_bounds(dataset, episode, start_frame)
    stop = episode_stop
    if args.max_policy_steps is not None:
        stop = min(stop, start + args.max_policy_steps)
    total_steps = stop - start
    episode_remaining_steps = episode_stop - start

    run_dir = make_run_dir(Path(args.output_root), args.run_name, episode, args.episode_count)
    write_config(run_dir, args, policy_cfg, start, stop, episode)
    csv_path = run_dir / "steps.csv"
    fieldnames = [
        "policy_step",
        "dataset_index",
        "dataset_frame",
        "chunk_offset",
        "inference_anchor",
        "inference_s",
        "action_queue_size",
        "queue_wait_s",
        "action_source",
        "loop_s",
        "sent_to_robot",
        "arm_state",
        "left_hand_state",
        "right_hand_state",
        "predicted_action",
        "limited_arm",
        "limited_left_hand",
        "limited_right_hand",
        "dataset_state",
        "dataset_action",
    ]

    def read_current_state() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        arm_state = read_arm_state(arm_source, args.state_timeout_s)
        left_state = read_hand_state(left_reader, args.state_timeout_s, "left", args.ignore_inspire_status)
        right_state = read_hand_state(right_reader, args.state_timeout_s, "right", args.ignore_inspire_status)
        real_state = np.concatenate(
            [
                arm_state,
                left_state / args.hand_state_scale,
                right_state / args.hand_state_scale,
            ]
        ).astype(np.float32)
        return arm_state, left_state, right_state, real_state

    try:
        print(f"Loading initial dataset state at index {start} without video decode...", flush=True)
        first_step = get_dataset_row_no_video(dataset, start)
        first_state = tensor_to_numpy(first_step["observation.state"])
        if first_state.shape != (STATE_DOF,):
            raise ValueError(f"Dataset observation.state must be ({STATE_DOF},), got {first_state.shape}")
        if args.initialize_from_dataset:
            initialize_from_dataset_pose(
                args,
                arm_source,
                arm_ik,
                left_reader,
                right_reader,
                left_pub,
                right_pub,
                first_state,
            )
            if not confirm_start():
                return run_dir, False

        action_source = "dataset" if args.use_dataset_action else "policy"
        max_steps_text = "episode end" if args.max_policy_steps is None else str(args.max_policy_steps)
        print(
            f"Starting {action_source} action playback: episode={episode} "
            f"dataset_index={start}..{stop - 1} actions={total_steps} "
            f"(episode_remaining={episode_remaining_steps}, max_policy_steps={max_steps_text})",
            flush=True,
        )

        with csv_path.open("w", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            def execute_action(
                dataset_index: int,
                step: dict[str, Any],
                dataset_state: np.ndarray,
                dataset_action: np.ndarray,
                action: np.ndarray,
                inference_s: float,
                chunk_offset: int,
                inference_anchor: int,
                action_queue_size: int,
                queue_wait_s: float,
                loop_start: float,
            ) -> None:
                arm_state, left_state, right_state, _ = read_current_state()
                pred_arm = action[:ARM_DOF]
                pred_left = action[ARM_DOF : ARM_DOF + HAND_DOF] * args.hand_action_scale
                pred_right = action[ARM_DOF + HAND_DOF :] * args.hand_action_scale
                limited_arm = limit_arm_target(pred_arm, arm_state, args.max_arm_delta_rad)
                limited_left = limit_hand_target(pred_left, left_state, args.max_hand_delta)
                limited_right = limit_hand_target(pred_right, right_state, args.max_hand_delta)

                if args.send_actions:
                    if not args.disable_arms:
                        arm_source.ctrl_dual_arm(limited_arm, arm_ik.solve_tau(limited_arm))
                    if not args.disable_left_hand:
                        left_pub.send(limited_left, args.hand_force, args.hand_speed)
                    if not args.disable_right_hand:
                        right_pub.send(limited_right, args.hand_force, args.hand_speed)

                writer.writerow(
                    {
                        "policy_step": dataset_index - start,
                        "dataset_index": dataset_index,
                        "dataset_frame": tensor_item_int(step["frame_index"]),
                        "chunk_offset": chunk_offset,
                        "inference_anchor": inference_anchor,
                        "inference_s": inference_s,
                        "action_queue_size": action_queue_size,
                        "queue_wait_s": queue_wait_s,
                        "action_source": "dataset" if args.use_dataset_action else "policy",
                        "loop_s": time.perf_counter() - loop_start,
                        "sent_to_robot": args.send_actions,
                        "arm_state": json.dumps(arm_state.tolist()),
                        "left_hand_state": json.dumps(left_state.tolist()),
                        "right_hand_state": json.dumps(right_state.tolist()),
                        "predicted_action": json.dumps(action.tolist()),
                        "limited_arm": json.dumps(limited_arm.tolist()),
                        "limited_left_hand": json.dumps(limited_left.tolist()),
                        "limited_right_hand": json.dumps(limited_right.tolist()),
                        "dataset_state": json.dumps(dataset_state.tolist()),
                        "dataset_action": json.dumps(dataset_action.tolist()),
                    }
                )
                csv_file.flush()

            if args.use_dataset_action:
                for dataset_index in range(start, stop):
                    loop_start = time.perf_counter()
                    step = get_dataset_row_no_video(dataset, dataset_index)
                    dataset_state = tensor_to_numpy(step["observation.state"])
                    dataset_action = tensor_to_numpy(step["action"])
                    action = dataset_action.astype(np.float32)
                    if action.shape != (STATE_DOF,) or not np.all(np.isfinite(action)):
                        raise ValueError(f"Expected dataset action shape ({STATE_DOF},), got {action.shape}")
                    execute_action(
                        dataset_index,
                        step,
                        dataset_state,
                        dataset_action,
                        action,
                        inference_s=0.0,
                        chunk_offset=-1,
                        inference_anchor=-1,
                        action_queue_size=0,
                        queue_wait_s=0.0,
                        loop_start=loop_start,
                    )
                    policy_step = dataset_index - start + 1
                    if policy_step % 50 == 0 or dataset_index + 1 == stop:
                        print(
                            f"action_step={policy_step}/{total_steps} dataset_index={dataset_index} "
                            f"source=dataset dry_run={not args.send_actions}",
                            flush=True,
                        )
                    elapsed = time.perf_counter() - loop_start
                    time.sleep(max(0.0, 1.0 / args.frequency - elapsed))
            else:
                prefetch_count = max(1, int(np.ceil(args.actions_per_inference * args.prefetch_threshold)))
                action_queue: dict[int, QueuedAction] = {}
                inference_future: Future[InferenceResult] | None = None

                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="wbt-act-inference") as executor:

                    def submit_inference(anchor: int) -> Future[InferenceResult]:
                        _, _, _, real_state = read_current_state()
                        return executor.submit(
                            infer_action_chunk,
                            dataset,
                            anchor,
                            real_state,
                            policy,
                            preprocessor,
                            postprocessor,
                            device,
                        )

                    inference_future = submit_inference(start)
                    print("Preparing initial ACT action chunk...", flush=True)

                    for dataset_index in range(start, stop):
                        loop_start = time.perf_counter()
                        queue_wait_s = 0.0

                        if inference_future is not None and inference_future.done():
                            result = inference_future.result()
                            inserted = merge_inference_result(
                                action_queue,
                                result,
                                dataset_index,
                                args.actions_per_inference,
                                stop,
                            )
                            print(
                                f"inference anchor={result.anchor - start} "
                                f"time={result.inference_s * 1000:.1f}ms "
                                f"usable_actions={inserted} queue={len(action_queue)}",
                                flush=True,
                            )
                            inference_future = None

                        for stale_timestep in [t for t in action_queue if t < dataset_index]:
                            del action_queue[stale_timestep]

                        if dataset_index not in action_queue:
                            if inference_future is None:
                                inference_future = submit_inference(dataset_index)
                            wait_start = time.perf_counter()
                            result = inference_future.result()
                            queue_wait_s = time.perf_counter() - wait_start
                            inserted = merge_inference_result(
                                action_queue,
                                result,
                                dataset_index,
                                args.actions_per_inference,
                                stop,
                            )
                            print(
                                f"inference anchor={result.anchor - start} "
                                f"time={result.inference_s * 1000:.1f}ms "
                                f"usable_actions={inserted} queue={len(action_queue)} "
                                f"wait={queue_wait_s * 1000:.1f}ms",
                                flush=True,
                            )
                            inference_future = None
                            if dataset_index not in action_queue:
                                raise RuntimeError("Inference completed without an action for the current timestep")

                        queued_action = action_queue.pop(dataset_index)
                        step = get_dataset_row_no_video(dataset, dataset_index)
                        dataset_state = tensor_to_numpy(step["observation.state"])
                        dataset_action = tensor_to_numpy(step["action"])
                        inference_s = queued_action.inference_s if queued_action.report_inference else 0.0
                        execute_action(
                            dataset_index,
                            step,
                            dataset_state,
                            dataset_action,
                            queued_action.predicted,
                            inference_s=inference_s,
                            chunk_offset=queued_action.chunk_offset,
                            inference_anchor=queued_action.inference_anchor - start,
                            action_queue_size=len(action_queue),
                            queue_wait_s=queue_wait_s,
                            loop_start=loop_start,
                        )

                        next_timestep = dataset_index + 1
                        remaining_actions = sum(t >= next_timestep for t in action_queue)
                        remaining_episode = stop - next_timestep
                        should_prefetch = (
                            not args.synchronous_inference and remaining_actions <= prefetch_count
                        ) or (args.synchronous_inference and remaining_actions == 0)
                        if (
                            should_prefetch
                            and remaining_actions < remaining_episode
                            and inference_future is None
                            and next_timestep < stop
                        ):
                            inference_future = submit_inference(next_timestep)

                        policy_step = dataset_index - start + 1
                        if policy_step % 50 == 0 or next_timestep == stop:
                            print(
                                f"action_step={policy_step}/{total_steps} dataset_index={dataset_index} "
                                f"queue={remaining_actions} prefetch={inference_future is not None} "
                                f"wait={queue_wait_s * 1000:.1f}ms dry_run={not args.send_actions}",
                                flush=True,
                            )

                        elapsed = time.perf_counter() - loop_start
                        time.sleep(max(0.0, 1.0 / args.frequency - elapsed))
    finally:
        if args.send_actions and arm_source is not None and arm_ik is not None:
            try:
                hold_arm = read_arm_state(arm_source, args.state_timeout_s)
                arm_source.ctrl_dual_arm(hold_arm, arm_ik.solve_tau(hold_arm))
            except Exception as exc:
                print(f"WARNING: failed to hold final arm state: {exc}")

    return run_dir, True


def run(args: argparse.Namespace) -> Path:
    validate_args(args)
    dataset = LeRobotDataset(repo_id=args.repo_id, root=args.root)
    last_episode = args.episode + args.episode_count - 1
    if last_episode >= dataset.meta.total_episodes:
        raise ValueError(f"Episode range {args.episode}..{last_episode} is out of range [0, {dataset.meta.total_episodes - 1}]")
    policy_cfg, policy, preprocessor, postprocessor, device = load_policy_and_processors(Path(args.policy_path), dataset)
    if not args.use_dataset_action and policy_cfg.chunk_size < args.actions_per_inference:
        raise ValueError(
            f"--actions-per-inference={args.actions_per_inference} exceeds ACT chunk_size={policy_cfg.chunk_size}"
        )

    arm_source = arm_ik = left_reader = right_reader = left_pub = right_pub = None
    try:
        arm_source, arm_ik, left_reader, right_reader, left_pub, right_pub = setup_dds_and_io(args)
        last_run_dir = None
        for offset, episode in enumerate(range(args.episode, args.episode + args.episode_count)):
            if args.episode_count > 1:
                print(f"===== Episode {episode} ({offset + 1}/{args.episode_count}) =====", flush=True)
            last_run_dir, completed = run_episode(
                args=args,
                dataset=dataset,
                policy_cfg=policy_cfg,
                policy=policy,
                preprocessor=preprocessor,
                postprocessor=postprocessor,
                device=device,
                arm_source=arm_source,
                arm_ik=arm_ik,
                left_reader=left_reader,
                right_reader=right_reader,
                left_pub=left_pub,
                right_pub=right_pub,
                episode=episode,
                episode_offset=offset,
            )
            if not completed:
                print(f"Stopped before episode {episode} playback.", flush=True)
                break
    finally:
        if args.send_actions and arm_source is not None and arm_ik is not None:
            try:
                hold_arm = read_arm_state(arm_source, args.state_timeout_s)
                arm_source.ctrl_dual_arm(hold_arm, arm_ik.solve_tau(hold_arm))
            except Exception as exc:
                print(f"WARNING: failed to hold final arm state: {exc}")
    assert last_run_dir is not None
    return last_run_dir


def main() -> None:
    init_logging()
    args = parse_args()
    run_dir = run(args)
    print(f"WBT Inspire hybrid inference results: {run_dir.resolve()}")


if __name__ == "__main__":
    main()
