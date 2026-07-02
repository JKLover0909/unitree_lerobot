#!/usr/bin/env python3
"""Move Inspire FTP hands to the first hand pose of a raw WBT episode.

This script assumes the two Inspire FTP bridges are already running:

    rt/inspire_hand/state/l|r
    rt/inspire_hand/ctrl/l|r

It reads action.hand_cmd from the raw WBT dataset, scales it to Inspire
angle_set units, and publishes a gradual command. Body/arm joints are not
controlled here; use the C++ g1_wbt_body_replay --init-only flow for that.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from test_inspire_hand_command import InspireStateReader, initialize_dds, load_sdk, print_state
from wbt_full_body_replay import DEFAULT_RAW_ROOT, HAND_DOF, HAND_TOTAL_DOF, load_data, load_episodes


CONTROL_CONFIRMATION = "SEND_WBT_INITIAL_INSPIRE_HANDS"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_RAW_ROOT, help="Raw LeRobot dataset root.")
    parser.add_argument("--episode", type=int, default=0)
    parser.add_argument("--network-interface", default=None)
    parser.add_argument("--hand-action-scale", type=float, default=1000.0)
    parser.add_argument("--max-hand-delta", type=float, default=50.0)
    parser.add_argument("--max-error", type=float, default=10.0)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--state-timeout-s", type=float, default=10.0)
    parser.add_argument("--frequency", type=float, default=20.0)
    parser.add_argument("--force", type=int, default=500)
    parser.add_argument("--speed", type=int, default=300)
    parser.add_argument("--disable-left-hand", action="store_true")
    parser.add_argument("--disable-right-hand", action="store_true")
    parser.add_argument("--ignore-inspire-status", action="store_true")
    parser.add_argument("--send-command", action="store_true")
    parser.add_argument(
        "--control-confirmation",
        default="",
        help=f"Required with --send-command; must equal {CONTROL_CONFIRMATION!r}.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.frequency <= 0:
        raise ValueError("--frequency must be positive")
    if args.timeout_s <= 0 or args.state_timeout_s <= 0:
        raise ValueError("Timeouts must be positive")
    if args.max_hand_delta <= 0:
        raise ValueError("--max-hand-delta must be positive")
    if args.max_error < 0:
        raise ValueError("--max-error must be non-negative")
    if args.force < 0 or args.speed < 0:
        raise ValueError("--force and --speed must be non-negative")
    if args.disable_left_hand and args.disable_right_hand:
        raise ValueError("Both hands are disabled")
    if args.send_command and args.control_confirmation != CONTROL_CONFIRMATION:
        raise ValueError(f"Publishing requires --control-confirmation={CONTROL_CONFIRMATION}")


def hand_suffix(hand: str) -> str:
    return "l" if hand == "left" else "r"


def load_initial_hand_target(args: argparse.Namespace) -> np.ndarray:
    episodes = load_episodes(args.root)
    if args.episode not in episodes:
        raise ValueError(f"Episode {args.episode} is not available in {args.root}")
    ep = episodes[args.episode]
    rows = load_data(args.root, ep.start, ep.stop)
    hand_cmd = np.asarray(rows["hand_cmd"][0], dtype=np.float32).reshape(HAND_TOTAL_DOF)
    target = np.clip(hand_cmd * float(args.hand_action_scale), 0, 1000)
    print(
        f"Loaded episode={args.episode} initial hand_cmd at dataset_index={int(rows['index'][0])}, "
        f"frame_index={int(rows['frame_index'][0])}"
    )
    print(f"  raw hand_cmd: {np.array2string(hand_cmd, precision=4, suppress_small=True)}")
    print(f"  angle target: {target.astype(int).tolist()}")
    return target.astype(np.float32)


def make_ctrl_msg(sdk, angle: np.ndarray, args: argparse.Namespace):
    return sdk.inspire_hand_ctrl(
        pos_set=[0] * HAND_DOF,
        angle_set=np.clip(angle, 0, 1000).astype(np.int16).tolist(),
        force_set=[int(args.force)] * HAND_DOF,
        speed_set=[int(args.speed)] * HAND_DOF,
        mode=0b1101,
    )


def main() -> None:
    args = parse_args()
    validate_args(args)

    target = load_initial_hand_target(args)
    sdk = load_sdk()
    initialize_dds(sdk, args.network_interface)

    sides: list[tuple[str, int]] = []
    if not args.disable_left_hand:
        sides.append(("left", 0))
    if not args.disable_right_hand:
        sides.append(("right", HAND_DOF))

    readers = {}
    publishers = {}
    current_targets = {}
    for side, offset in sides:
        suffix = hand_suffix(side)
        state_topic = f"rt/inspire_hand/state/{suffix}"
        ctrl_topic = f"rt/inspire_hand/ctrl/{suffix}"
        reader = InspireStateReader(sdk.ChannelSubscriber, sdk.inspire_hand_state, state_topic)
        print(f"Reading {side} Inspire state from {state_topic} ...")
        state = reader.wait(args.state_timeout_s)
        print_state(f"{side} initial state:", state)
        if not args.ignore_inspire_status:
            bad_err = np.flatnonzero(state["err"] != 0)
            bad_status = np.flatnonzero(state["status"] == 7)
            if len(bad_err) or len(bad_status):
                raise RuntimeError(
                    f"{side} Inspire reports err={state['err'].tolist()} status={state['status'].tolist()}. "
                    "Use --ignore-inspire-status only if you intentionally want to continue."
                )
        readers[side] = reader
        current_targets[side] = np.asarray(state["angle_act"], dtype=np.float32)
        if args.send_command:
            publisher = sdk.ChannelPublisher(ctrl_topic, sdk.inspire_hand_ctrl)
            publisher.Init()
            publishers[side] = publisher

    if not args.send_command:
        print("Dry run only. No Inspire commands were published.")
        return

    print(
        f"Moving Inspire hands to dataset initial pose: "
        f"max_delta={args.max_hand_delta}, max_error={args.max_error}, force={args.force}, speed={args.speed}"
    )
    start = time.monotonic()
    last_print = 0.0
    period_s = 1.0 / args.frequency
    while True:
        max_error = 0.0
        for side, offset in sides:
            desired = target[offset : offset + HAND_DOF]
            feedback = readers[side].get()
            current = current_targets[side]
            if feedback is not None:
                current = np.asarray(feedback["angle_act"], dtype=np.float32)
            command = current + np.clip(desired - current, -args.max_hand_delta, args.max_hand_delta)
            current_targets[side] = command
            publishers[side].Write(make_ctrl_msg(sdk, command, args))
            max_error = max(max_error, float(np.max(np.abs(desired - current))))

        now = time.monotonic()
        elapsed = now - start
        if now - last_print >= 1.0:
            print(f"Initializing Inspire hands: elapsed={elapsed:.1f}s max_error={max_error:.1f}")
            last_print = now
        if max_error <= args.max_error:
            print(f"Inspire initial hand pose reached: max_error={max_error:.1f}")
            break
        if elapsed > args.timeout_s:
            raise TimeoutError(f"Timed out initializing Inspire hands: max_error={max_error:.1f}")
        time.sleep(period_s)

    for side, _offset in sides:
        final = readers[side].wait(args.state_timeout_s)
        print_state(f"{side} final state:", final)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise
