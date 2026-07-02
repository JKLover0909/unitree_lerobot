#!/usr/bin/env python3
"""Export raw WBT full-body actions to a simple CSV for C++ replay.

The C++ replay binary intentionally avoids depending on Arrow/Parquet. This
script keeps dataset decoding in Python and writes only the fields needed by the
Unitree C++ controller:

    q0..q28     = action.robot_q_desired[7:36], the 29 G1 motor targets
    hand0..11   = action.hand_cmd, kept for future hand replay support
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from wbt_full_body_replay import (
    DEFAULT_RAW_ROOT,
    G1_MOTOR_DOF,
    HAND_TOTAL_DOF,
    ROOT_DOF,
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
    parser.add_argument("--output", type=Path, default=None, help="Output CSV path.")
    parser.add_argument("--output-root", type=Path, default=Path("wbt_cpp_replay_inputs"))
    parser.add_argument("--preview-only", action="store_true", help="Print episode summaries without writing CSV.")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.episode_count <= 0:
        raise ValueError("--episode-count must be positive")
    if args.max_steps is not None and args.max_steps <= 0:
        raise ValueError("--max-steps must be positive")


def make_output_path(args: argparse.Namespace) -> Path:
    if args.output is not None:
        return args.output
    name = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        f"_episode-{args.episode:03d}_count-{args.episode_count}.csv"
    )
    return args.output_root / name


def main() -> None:
    args = parse_args()
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
    total_actions = 0
    for ep in selected:
        rows = load_data(args.root, ep.start, ep.stop)
        q_full = rows["q_desired"]
        if q_full.ndim != 2 or q_full.shape[1] != ROOT_DOF + G1_MOTOR_DOF:
            raise ValueError(f"Expected q_desired shape (T, 36), got {q_full.shape}")
        summarize_episode(ep, q_full)
        actions = len(q_full) if args.max_steps is None else min(len(q_full), args.max_steps)
        total_actions += actions
        loaded.append((ep, rows, actions))

    if args.preview_only:
        print(f"Preview only: selected_episodes={len(loaded)} total_actions={total_actions}")
        return

    output = make_output_path(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    q_columns = [f"q{i}" for i in range(G1_MOTOR_DOF)]
    hand_columns = [f"hand{i}" for i in range(HAND_TOTAL_DOF)]
    fieldnames = ["episode", "action_step", "dataset_index", "frame_index", *q_columns, *hand_columns]

    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ep, rows, actions in loaded:
            q_body = rows["q_desired"][:actions, ROOT_DOF : ROOT_DOF + G1_MOTOR_DOF]
            hand_cmd = rows["hand_cmd"][:actions]
            if hand_cmd.ndim == 1:
                hand_cmd = np.zeros((actions, HAND_TOTAL_DOF), dtype=np.float32)
            for i in range(actions):
                row = {
                    "episode": int(ep.episode_index),
                    "action_step": i + 1,
                    "dataset_index": int(rows["index"][i]),
                    "frame_index": int(rows["frame_index"][i]),
                }
                row.update({f"q{j}": f"{float(q_body[i, j]):.9g}" for j in range(G1_MOTOR_DOF)})
                row.update({f"hand{j}": f"{float(hand_cmd[i, j]):.9g}" for j in range(HAND_TOTAL_DOF)})
                writer.writerow(row)

    sidecar = output.with_suffix(output.suffix + ".json")
    with open(sidecar, "w") as f:
        json.dump(
            {
                "root": str(args.root),
                "episode": args.episode,
                "episode_count": args.episode_count,
                "max_steps_per_episode": args.max_steps,
                "total_actions": total_actions,
                "csv": str(output),
                "q_columns": q_columns,
                "hand_columns": hand_columns,
            },
            f,
            indent=2,
        )

    print(f"Exported WBT C++ replay CSV: {output}")
    print(f"Sidecar metadata: {sidecar}")
    print(f"total_actions={total_actions}")


if __name__ == "__main__":
    main()
