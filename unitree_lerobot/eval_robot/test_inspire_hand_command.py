#!/usr/bin/env python3
"""Read and gently test Inspire FTP hand DDS commands.

This script follows the notebooks in ./Notebooks:

    control: rt/inspire_hand/ctrl/l or rt/inspire_hand/ctrl/r
    state:   rt/inspire_hand/state/l or rt/inspire_hand/state/r
    IDL:     inspire_sdkpy.inspire_dds.inspire_hand_ctrl/state

Default mode is read-only. Publishing requires both --send-command and an
explicit confirmation string.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np


CONTROL_CONFIRMATION = "SEND_TEST_INSPIRE_HAND"
JOINT_NAMES = ["pinky", "ring", "middle", "index", "thumb_bend", "thumb_rotation"]
DOF = 6
PRESETS = {
    "open": [800, 800, 800, 800, 500, 0],
    "close": [0, 0, 0, 0, 0, 1000],
}


@dataclass
class InspireSdk:
    ChannelFactoryInitialize: object
    ChannelPublisher: object
    ChannelSubscriber: object
    inspire_hand_ctrl: object
    inspire_hand_state: object


class InspireStateReader:
    def __init__(self, subscriber_cls, state_type, topic: str):
        self.topic = topic
        self._state: dict[str, np.ndarray] | None = None
        self._lock = threading.Lock()
        self._subscriber = subscriber_cls(topic, state_type)
        self._subscriber.Init(self._callback, 10)

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

    def get(self) -> dict[str, np.ndarray] | None:
        with self._lock:
            if self._state is None:
                return None
            return {key: value.copy() for key, value in self._state.items()}

    def wait(self, timeout_s: float) -> dict[str, np.ndarray]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            state = self.get()
            if state is not None:
                return state
            time.sleep(0.01)
        raise TimeoutError(f"No Inspire state received on {self.topic} within {timeout_s:.1f}s")


def load_sdk() -> InspireSdk:
    repo_root = Path(__file__).resolve().parents[2]
    inspire_idl_root = repo_root / "inspire_hand_ws" / "inspire_hand_sdk" / "inspire_sdkpy"
    if inspire_idl_root.exists():
        sys.path.insert(0, str(inspire_idl_root))

    try:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelPublisher, ChannelSubscriber
        from inspire_dds import inspire_hand_ctrl, inspire_hand_state
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing SDK package. This test needs unitree_sdk2py, cyclonedds, and the Inspire "
            "IDL package. The script auto-adds inspire_hand_ws/inspire_hand_sdk/inspire_sdkpy "
            "when that folder exists."
        ) from exc

    return InspireSdk(
        ChannelFactoryInitialize=ChannelFactoryInitialize,
        ChannelPublisher=ChannelPublisher,
        ChannelSubscriber=ChannelSubscriber,
        inspire_hand_ctrl=inspire_hand_ctrl,
        inspire_hand_state=inspire_hand_state,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network-interface", default=None, help="DDS NIC, e.g. enp1s0. Optional if DDS config handles it.")
    parser.add_argument("--hand", choices=["left", "right"], default="right")
    parser.add_argument("--joint", type=int, default=3, help="Joint id: 0..5")
    parser.add_argument("--delta", type=int, default=50, help="Small angle_set delta in Inspire 0..1000 units.")
    parser.add_argument("--target", type=int, default=None, help="Absolute angle_set target for one joint.")
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default=None,
        help="Send a full-hand preset angle vector from the notebook.",
    )
    parser.add_argument("--force", type=int, default=200)
    parser.add_argument("--speed", type=int, default=200)
    parser.add_argument("--min-angle", type=int, default=0)
    parser.add_argument("--max-angle", type=int, default=1000)
    parser.add_argument("--read-timeout-s", type=float, default=10.0)
    parser.add_argument("--read-only-duration-s", type=float, default=3.0)
    parser.add_argument("--publish-duration-s", type=float, default=2.0)
    parser.add_argument("--frequency", type=float, default=20.0)
    parser.add_argument("--movement-threshold", type=float, default=5.0)
    parser.add_argument("--send-command", action="store_true")
    parser.add_argument(
        "--control-confirmation",
        default="",
        help=f"Required with --send-command; must equal {CONTROL_CONFIRMATION!r}.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not 0 <= args.joint < DOF:
        raise ValueError("--joint must be in [0, 5]")
    if args.preset is not None and args.target is not None:
        raise ValueError("--preset and --target cannot be used together")
    if args.min_angle < 0 or args.max_angle > 1000 or args.min_angle >= args.max_angle:
        raise ValueError("Angle limits must satisfy 0 <= min < max <= 1000")
    if abs(args.delta) > 200:
        raise ValueError("--delta is intentionally capped to +/-200 for this smoke test")
    if args.force < 0 or args.speed < 0:
        raise ValueError("--force and --speed must be non-negative")
    if args.frequency <= 0 or args.read_timeout_s <= 0 or args.publish_duration_s <= 0:
        raise ValueError("frequency/timeouts must be positive")
    if args.send_command and args.control_confirmation != CONTROL_CONFIRMATION:
        raise ValueError(f"Publishing requires --control-confirmation={CONTROL_CONFIRMATION}")


def initialize_dds(sdk: InspireSdk, network_interface: str | None) -> None:
    try:
        if network_interface:
            sdk.ChannelFactoryInitialize(0, network_interface)
        else:
            sdk.ChannelFactoryInitialize(0)
    except TypeError:
        # Some Unitree SDK versions only accept domain id here.
        sdk.ChannelFactoryInitialize(0)


def hand_suffix(hand: str) -> str:
    return "l" if hand == "left" else "r"


def print_state(label: str, state: dict[str, np.ndarray]) -> None:
    print(label)
    for key in ["angle_act", "pos_act", "force_act", "current", "err", "status", "temperature"]:
        value = state.get(key)
        if value is not None:
            print(f"  {key}: {np.array2string(value, precision=1, suppress_small=True)}")


def build_command(sdk: InspireSdk, current_angle: np.ndarray, args: argparse.Namespace):
    target = current_angle.astype(np.float32).copy()
    if target.shape != (DOF,):
        raise ValueError(f"Expected current angle shape ({DOF},), got {target.shape}")

    if args.preset is not None:
        target = np.asarray(PRESETS[args.preset], dtype=np.float32)
    elif args.target is None:
        target[args.joint] += float(args.delta)
    else:
        target[args.joint] = float(args.target)
    target = np.clip(target, args.min_angle, args.max_angle).astype(np.int16)

    cmd = sdk.inspire_hand_ctrl(
        pos_set=[0] * DOF,
        angle_set=target.tolist(),
        force_set=[int(args.force)] * DOF,
        speed_set=[int(args.speed)] * DOF,
        mode=0b1101,  # angle + force + speed, matching the notebook style.
    )
    return cmd, target


def main() -> None:
    args = parse_args()
    validate_args(args)

    sdk = load_sdk()
    initialize_dds(sdk, args.network_interface)

    suffix = hand_suffix(args.hand)
    state_topic = f"rt/inspire_hand/state/{suffix}"
    ctrl_topic = f"rt/inspire_hand/ctrl/{suffix}"

    reader = InspireStateReader(sdk.ChannelSubscriber, sdk.inspire_hand_state, state_topic)
    print(f"Reading {args.hand} Inspire state from {state_topic} ...")
    initial = reader.wait(args.read_timeout_s)
    print_state("Initial state:", initial)

    if not args.send_command:
        deadline = time.monotonic() + args.read_only_duration_s
        latest = initial
        samples = 0
        while time.monotonic() < deadline:
            state = reader.get()
            if state is not None:
                latest = state
                samples += 1
            time.sleep(0.02)
        print_state(f"Latest state after read-only sampling ({samples} samples):", latest)
        print("Read-only check passed. No commands were published.")
        return

    publisher = sdk.ChannelPublisher(ctrl_topic, sdk.inspire_hand_ctrl)
    publisher.Init()

    cmd, target = build_command(sdk, initial["angle_act"], args)
    if args.preset is None:
        print(f"Publishing to {ctrl_topic}: joint={args.joint} ({JOINT_NAMES[args.joint]})")
    else:
        print(f"Publishing to {ctrl_topic}: preset={args.preset}")
    print(f"  target angle_set: {target.tolist()}")
    print(f"  force={args.force}, speed={args.speed}, mode=0b1101")

    period_s = 1.0 / args.frequency
    deadline = time.monotonic() + args.publish_duration_s
    while time.monotonic() < deadline:
        publisher.Write(cmd)
        time.sleep(period_s)

    final = reader.wait(args.read_timeout_s)
    print_state("Final state:", final)
    if args.preset is None:
        movement = float(abs(final["angle_act"][args.joint] - initial["angle_act"][args.joint]))
        movement_label = f"Selected joint angle_act movement: {movement:.3f}"
    else:
        movement = float(np.max(np.abs(final["angle_act"] - initial["angle_act"])))
        movement_label = f"Full-hand max angle_act movement: {movement:.3f}"
    print(movement_label)
    if movement < args.movement_threshold:
        raise RuntimeError(
            "Command was published but observed movement is below threshold. "
            "Check Inspire driver, topic suffix, hand power, and whether angle_act is the right feedback field."
        )
    print("Command check passed: selected Inspire state changed.")


if __name__ == "__main__":
    main()
