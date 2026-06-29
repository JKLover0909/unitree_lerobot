#!/usr/bin/env python3
"""Convert one recorded head-camera + arm14 episode into fake LeRobot flat26.

The generated dataset keeps the old WBT Inspire pickup policy interface:

* observation.state/action: 26D = arm14 + fixed hand12
* four visual keys, all backed by the same resized head-camera video
* action[t] = state[t + k], with k=1 by default

This is intentionally a compatibility dataset. The 12 Inspire hand values and
three extra camera streams are synthetic placeholders.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd


ARM_NAMES = [
    "kLeftShoulderPitch",
    "kLeftShoulderRoll",
    "kLeftShoulderYaw",
    "kLeftElbow",
    "kLeftWristRoll",
    "kLeftWristPitch",
    "kLeftWristYaw",
    "kRightShoulderPitch",
    "kRightShoulderRoll",
    "kRightShoulderYaw",
    "kRightElbow",
    "kRightWristRoll",
    "kRightWristPitch",
    "kRightWristYaw",
]
HAND_NAMES = [f"inspire_hand_{i}" for i in range(12)]
STATE_NAMES = ARM_NAMES + HAND_NAMES
VIDEO_KEYS = [
    "observation.images.head_stereo_left",
    "observation.images.head_stereo_right",
    "observation.images.wrist_left",
    "observation.images.wrist_right",
]
DEFAULT_HAND12_RAW = [
    299,
    0,
    300,
    207,
    122,
    116,
    299,
    302,
    384,
    463,
    102,
    0,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--episode-dir",
        type=Path,
        required=True,
        help="Recorded episode folder containing states/arm14.csv, timestamps.csv, videos/head.mp4.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Output dataset root. Default: HF local cache with name derived from episode dir.",
    )
    parser.add_argument("--repo-id", default=None, help="Logical repo id stored in metadata only.")
    parser.add_argument("--task", default="G1_headcam_arm14_fake_flat26")
    parser.add_argument("--k", type=int, default=1, help="Use action[t] = state[t + k].")
    parser.add_argument(
        "--hand12-raw",
        type=float,
        nargs=12,
        default=DEFAULT_HAND12_RAW,
        help="Fixed Inspire hand angles in 0..1000 units: left6 then right6.",
    )
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--video-width", type=int, default=640)
    parser.add_argument("--video-height", type=int, default=480)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def stats_for_array(values: np.ndarray) -> dict[str, list]:
    values = np.asarray(values)
    return {
        "min": np.min(values, axis=0).tolist(),
        "max": np.max(values, axis=0).tolist(),
        "mean": np.mean(values, axis=0).tolist(),
        "std": np.std(values, axis=0).tolist(),
        "count": [int(values.shape[0])],
        "q01": np.quantile(values, 0.01, axis=0).tolist(),
        "q10": np.quantile(values, 0.10, axis=0).tolist(),
        "q50": np.quantile(values, 0.50, axis=0).tolist(),
        "q90": np.quantile(values, 0.90, axis=0).tolist(),
        "q99": np.quantile(values, 0.99, axis=0).tolist(),
    }


def image_stats(frame_count: int) -> dict[str, list]:
    channel_shape = [[[0.0]], [[0.0]], [[0.0]]]
    one_shape = [[[1.0]], [[1.0]], [[1.0]]]
    mean_shape = [[[0.5]], [[0.5]], [[0.5]]]
    std_shape = [[[0.25]], [[0.25]], [[0.25]]]
    return {
        "min": channel_shape,
        "max": one_shape,
        "mean": mean_shape,
        "std": std_shape,
        "count": [int(frame_count)],
        "q01": channel_shape,
        "q10": mean_shape,
        "q50": mean_shape,
        "q90": one_shape,
        "q99": one_shape,
    }


def resize_video(src: Path, dst: Path, frames: int, width: int, height: int, fps: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-vf",
        f"scale={width}:{height}",
        "-frames:v",
        str(frames),
        "-r",
        str(fps),
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(dst),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    args = parse_args()
    episode_dir = args.episode_dir.resolve()
    if args.k < 1:
        raise ValueError("--k must be >= 1")

    arm_csv = episode_dir / "states" / "arm14.csv"
    timestamps_csv = episode_dir / "timestamps.csv"
    video_src = episode_dir / "videos" / "head.mp4"
    for path in [arm_csv, timestamps_csv, video_src]:
        if not path.exists():
            raise FileNotFoundError(path)

    dataset_name = f"{episode_dir.name}_fake_flat26_k{args.k}"
    output_root = args.output_root
    if output_root is None:
        output_root = Path.home() / ".cache" / "huggingface" / "lerobot" / "local" / dataset_name
    output_root = output_root.resolve()
    repo_id = args.repo_id or f"local/{output_root.name}"

    if output_root.exists():
        if not args.overwrite:
            raise FileExistsError(f"{output_root} exists. Pass --overwrite to replace it.")
        shutil.rmtree(output_root)

    arm_df = pd.read_csv(arm_csv)
    ts_df = pd.read_csv(timestamps_csv)
    arm_cols = [f"arm{i}" for i in range(14)]
    missing = [col for col in arm_cols if col not in arm_df.columns]
    if missing:
        raise ValueError(f"Missing arm columns: {missing}")
    if len(arm_df) != len(ts_df):
        raise ValueError(f"arm rows ({len(arm_df)}) != timestamp rows ({len(ts_df)})")
    if len(arm_df) <= args.k:
        raise ValueError(f"Need more than k={args.k} rows, got {len(arm_df)}")

    arm = arm_df[arm_cols].to_numpy(dtype=np.float32)
    hand = (np.asarray(args.hand12_raw, dtype=np.float32) / 1000.0).reshape(1, 12)
    state_all = np.concatenate([arm, np.repeat(hand, len(arm), axis=0)], axis=1).astype(np.float32)

    states = state_all[:-args.k]
    actions = state_all[args.k:]
    frame_count = len(states)
    timestamps = (np.arange(frame_count, dtype=np.float32) / float(args.fps)).astype(np.float32)

    output_root.mkdir(parents=True)
    (output_root / "data" / "chunk-000").mkdir(parents=True)
    (output_root / "meta" / "episodes" / "chunk-000").mkdir(parents=True)

    data = pd.DataFrame(
        {
            "observation.state": [row.astype(np.float32) for row in states],
            "action": [row.astype(np.float32) for row in actions],
            "timestamp": timestamps,
            "frame_index": np.arange(frame_count, dtype=np.int64),
            "episode_index": np.zeros(frame_count, dtype=np.int64),
            "index": np.arange(frame_count, dtype=np.int64),
            "task_index": np.zeros(frame_count, dtype=np.int64),
        }
    )
    data.to_parquet(output_root / "data" / "chunk-000" / "file-000.parquet", index=False)

    episode_row = {
        "episode_index": np.array([0], dtype=np.int64),
        "tasks": [[args.task]],
        "length": np.array([frame_count], dtype=np.int64),
        "data/chunk_index": np.array([0], dtype=np.int64),
        "data/file_index": np.array([0], dtype=np.int64),
        "dataset_from_index": np.array([0], dtype=np.int64),
        "dataset_to_index": np.array([frame_count], dtype=np.int64),
        "meta/episodes/chunk_index": np.array([0], dtype=np.int64),
        "meta/episodes/file_index": np.array([0], dtype=np.int64),
    }
    duration_s = float(frame_count) / float(args.fps)
    for key in VIDEO_KEYS:
        episode_row[f"videos/{key}/chunk_index"] = np.array([0], dtype=np.int64)
        episode_row[f"videos/{key}/file_index"] = np.array([0], dtype=np.int64)
        episode_row[f"videos/{key}/from_timestamp"] = np.array([0.0], dtype=np.float32)
        episode_row[f"videos/{key}/to_timestamp"] = np.array([duration_s], dtype=np.float32)
    episodes = pd.DataFrame(episode_row)
    episodes.to_parquet(output_root / "meta" / "episodes" / "chunk-000" / "file-000.parquet", index=False)

    tasks = pd.DataFrame({"task_index": np.array([0], dtype=np.int64), "task": [args.task]})
    tasks.to_parquet(output_root / "meta" / "tasks.parquet", index=False)

    video_feature = {
        "dtype": "video",
        "shape": [args.video_height, args.video_width, 3],
        "names": ["height", "width", "channel"],
        "info": {
            "video.height": args.video_height,
            "video.width": args.video_width,
            "video.codec": "h264",
            "video.pix_fmt": "yuv420p",
            "video.is_depth_map": False,
            "video.fps": args.fps,
            "video.channels": 3,
            "has_audio": False,
        },
    }
    features = {
        "observation.state": {"dtype": "float32", "shape": [26], "names": [STATE_NAMES]},
        "action": {"dtype": "float32", "shape": [26], "names": [STATE_NAMES]},
        **{key: video_feature for key in VIDEO_KEYS},
        "timestamp": {"dtype": "float32", "shape": [1], "names": None},
        "frame_index": {"dtype": "int64", "shape": [1], "names": None},
        "episode_index": {"dtype": "int64", "shape": [1], "names": None},
        "index": {"dtype": "int64", "shape": [1], "names": None},
        "task_index": {"dtype": "int64", "shape": [1], "names": None},
    }
    info = {
        "codebase_version": "v3.0",
        "robot_type": "Unitree_G1_fake_headcam_flat26",
        "total_episodes": 1,
        "total_frames": frame_count,
        "total_tasks": 1,
        "chunks_size": 1000,
        "data_files_size_in_mb": 100,
        "video_files_size_in_mb": 500,
        "fps": args.fps,
        "splits": {"train": "0:1"},
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "features": features,
    }
    (output_root / "meta" / "info.json").write_text(json.dumps(info, indent=4) + "\n")

    stats = {
        "observation.state": stats_for_array(states),
        "action": stats_for_array(actions),
        "timestamp": stats_for_array(timestamps.reshape(-1, 1)),
        "frame_index": stats_for_array(np.arange(frame_count, dtype=np.int64).reshape(-1, 1)),
        "episode_index": stats_for_array(np.zeros((frame_count, 1), dtype=np.int64)),
        "index": stats_for_array(np.arange(frame_count, dtype=np.int64).reshape(-1, 1)),
        "task_index": stats_for_array(np.zeros((frame_count, 1), dtype=np.int64)),
    }
    for key in VIDEO_KEYS:
        stats[key] = image_stats(frame_count)
    (output_root / "meta" / "stats.json").write_text(json.dumps(stats, indent=4) + "\n")

    first_video = output_root / "videos" / VIDEO_KEYS[0] / "chunk-000" / "file-000.mp4"
    resize_video(video_src, first_video, frame_count, args.video_width, args.video_height, args.fps)
    for key in VIDEO_KEYS[1:]:
        dst = output_root / "videos" / key / "chunk-000" / "file-000.mp4"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(first_video, dst)

    summary = {
        "repo_id": repo_id,
        "output_root": str(output_root),
        "source_episode_dir": str(episode_dir),
        "frames": frame_count,
        "k": args.k,
        "hand12_raw": [float(x) for x in args.hand12_raw],
        "hand12_scaled": hand.reshape(-1).tolist(),
        "camera_note": "Same head.mp4 resized to 640x480 and duplicated into all four policy camera keys.",
        "action_note": "action[t] = state[t + k]. Last k source frames are dropped.",
    }
    (output_root / "conversion_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
