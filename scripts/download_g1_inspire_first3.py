#!/usr/bin/env python3
"""Download and flatten the first 3 episodes of Unitree G1 WBT Inspire datasets.

This intentionally downloads only metadata and parquet data, not videos/images.
The output format matches the current real-robot replay runner:

    observation.state = robot_q_current[22:36] + hand_state
    action            = robot_q_desired[22:36] + hand_cmd
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
from huggingface_hub import snapshot_download


DATASETS = [
    "unitreerobotics/G1_WBT_Inspire_Clean_The_Living_Room",
    "unitreerobotics/G1_WBT_Inspire_Collect_Clothes_MainCamOnly",
    "unitreerobotics/G1_WBT_Inspire_Pickup_Pillow_MainCamOnly",
    "unitreerobotics/G1_WBT_Inspire_Put_Clothes_into_Washing_Machine_MainCamOnly",
    "unitreerobotics/G1_WBT_Inspire_Put_Clothes_into_Washing_Machine",
    "unitreerobotics/G1_WBT_Inspire_Put_Clothes_Into_Basket",
    "unitreerobotics/G1_WBT_Inspire_Put_Drinks_Into_Fridge",
    "unitreerobotics/G1_WBT_Inspire_Put_Vegetables_Into_Basket",
    "unitreerobotics/G1_WBT_Inspire_Pick_Up_Drinks",
    "unitreerobotics/G1_WBT_Inspire_Take_Plates_Into_Dishwasher",
]

RAW_ROOT = Path("/home/jkl0909/.cache/huggingface/lerobot/unitreerobotics")
OUT_ROOT = Path("/home/jkl0909/.cache/huggingface/lerobot/local")
EPISODE_COUNT = 3
ARM_SLICE = slice(22, 36)
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


def repo_name(repo_id: str) -> str:
    return repo_id.split("/", 1)[1]


def download_raw(repo_id: str) -> Path:
    name = repo_name(repo_id)
    raw_dir = RAW_ROOT / f"{name}_raw_meta_parquet"
    print(f"\n=== Downloading metadata/parquet: {repo_id} ===", flush=True)
    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        local_dir=raw_dir,
        allow_patterns=["meta/**", "data/**/*.parquet", "**/meta/**", "**/data/**/*.parquet", "*.json", "*.md"],
        ignore_patterns=["videos/**", "images/**", "*.mp4", "*.png", "*.jpg", "*.jpeg"],
    )
    return raw_dir


def dataset_root(raw_dir: Path) -> Path:
    if (raw_dir / "meta/info.json").exists():
        return raw_dir
    candidates = sorted(raw_dir.glob("*/meta/info.json"))
    if len(candidates) == 1:
        return candidates[0].parents[1]
    if candidates:
        raise RuntimeError(f"Multiple nested dataset roots found: {[str(p) for p in candidates]}")
    return raw_dir


def load_raw_data(raw_dir: Path) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    root = dataset_root(raw_dir)
    info_path = root / "meta/info.json"
    if not info_path.exists():
        raise FileNotFoundError(f"Missing {info_path}")
    info = json.loads(info_path.read_text())

    parquet_files = sorted((root / "data").glob("chunk-*/*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found under {root / 'data'}")
    data = pd.concat([pd.read_parquet(path) for path in parquet_files], ignore_index=True)
    data = data.sort_values("index").reset_index(drop=True)

    episodes_files = sorted((root / "meta/episodes").glob("chunk-*/*.parquet"))
    if episodes_files:
        episodes = pd.concat([pd.read_parquet(path) for path in episodes_files], ignore_index=True)
        episodes = episodes.sort_values("episode_index").reset_index(drop=True)
    else:
        rows = []
        for episode_index, group in data.groupby("episode_index", sort=True):
            rows.append(
                {
                    "episode_index": int(episode_index),
                    "tasks": [0],
                    "length": int(len(group)),
                    "dataset_from_index": int(group["index"].min()),
                    "dataset_to_index": int(group["index"].max()) + 1,
                }
            )
        episodes = pd.DataFrame(rows)
    return info, data, episodes


def validate_schema(data: pd.DataFrame) -> None:
    required = [
        "observation.state.hand_state",
        "observation.state.robot_q_current",
        "action.hand_cmd",
        "action.robot_q_desired",
        "timestamp",
        "frame_index",
        "episode_index",
        "index",
        "task_index",
    ]
    missing = [key for key in required if key not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def stack_column(series: pd.Series, expected_width: int, column: str) -> np.ndarray:
    arr = np.stack(series.to_numpy()).astype(np.float32)
    if arr.ndim != 2 or arr.shape[1] < expected_width:
        raise ValueError(f"{column} has shape {arr.shape}, expected at least width {expected_width}")
    return arr


def make_flat_subset(data: pd.DataFrame, episodes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected_eps = sorted(episodes["episode_index"].astype(int).unique().tolist())[:EPISODE_COUNT]
    subset = data[data["episode_index"].isin(selected_eps)].copy()
    if subset.empty:
        raise ValueError("No rows selected for the first episodes")
    subset = subset.sort_values(["episode_index", "frame_index", "index"]).reset_index(drop=True)

    robot_state = stack_column(subset["observation.state.robot_q_current"], 36, "observation.state.robot_q_current")
    robot_action = stack_column(subset["action.robot_q_desired"], 36, "action.robot_q_desired")
    hand_state = stack_column(subset["observation.state.hand_state"], 12, "observation.state.hand_state")
    hand_action = stack_column(subset["action.hand_cmd"], 12, "action.hand_cmd")

    flat_state = np.concatenate([robot_state[:, ARM_SLICE], hand_state[:, :12]], axis=1).astype(np.float32)
    flat_action = np.concatenate([robot_action[:, ARM_SLICE], hand_action[:, :12]], axis=1).astype(np.float32)

    out = pd.DataFrame(
        {
            "observation.state": list(flat_state),
            "action": list(flat_action),
            "timestamp": subset["timestamp"].to_numpy(dtype=np.float32),
            "frame_index": subset["frame_index"].to_numpy(dtype=np.int64),
            "episode_index": subset["episode_index"].to_numpy(dtype=np.int64),
            "index": np.arange(len(subset), dtype=np.int64),
            "task_index": subset["task_index"].to_numpy(dtype=np.int64),
        }
    )

    episode_rows = []
    cursor = 0
    for new_ep, old_ep in enumerate(selected_eps):
        length = int((out["episode_index"] == old_ep).sum())
        out.loc[out["episode_index"] == old_ep, "episode_index"] = new_ep
        episode_rows.append(
            {
                "episode_index": new_ep,
                "tasks": [0],
                "length": length,
                "dataset_from_index": cursor,
                "dataset_to_index": cursor + length,
            }
        )
        cursor += length
    return out, pd.DataFrame(episode_rows)


def make_info(source_info: dict, total_episodes: int, total_frames: int) -> dict:
    names = [ARM_NAMES + HAND_NAMES]
    return {
        "codebase_version": source_info.get("codebase_version", "v3.0"),
        "robot_type": "Unitree_G1_Inspire_flat26_first3",
        "total_episodes": total_episodes,
        "total_frames": total_frames,
        "total_tasks": 1,
        "chunks_size": 1000,
        "data_files_size_in_mb": 100,
        "video_files_size_in_mb": 500,
        "fps": int(source_info.get("fps", 30)),
        "splits": {"train": f"0:{total_episodes}"},
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "features": {
            "observation.state": {"dtype": "float32", "shape": [26], "names": names},
            "action": {"dtype": "float32", "shape": [26], "names": names},
            "timestamp": {"dtype": "float32", "shape": [1], "names": None},
            "frame_index": {"dtype": "int64", "shape": [1], "names": None},
            "episode_index": {"dtype": "int64", "shape": [1], "names": None},
            "index": {"dtype": "int64", "shape": [1], "names": None},
            "task_index": {"dtype": "int64", "shape": [1], "names": None},
        },
    }


def stats_for_array(arr: np.ndarray) -> dict:
    return {
        "mean": arr.mean(axis=0).astype(float).tolist(),
        "std": arr.std(axis=0).astype(float).tolist(),
        "min": arr.min(axis=0).astype(float).tolist(),
        "max": arr.max(axis=0).astype(float).tolist(),
        "q01": np.quantile(arr, 0.01, axis=0).astype(float).tolist(),
        "q99": np.quantile(arr, 0.99, axis=0).astype(float).tolist(),
    }


def write_flat_dataset(repo_id: str, source_info: dict, flat: pd.DataFrame, episodes: pd.DataFrame) -> Path:
    name = repo_name(repo_id)
    out_dir = OUT_ROOT / f"{name}_flat26_first3"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "data/chunk-000").mkdir(parents=True)
    (out_dir / "meta/episodes/chunk-000").mkdir(parents=True)

    flat.to_parquet(out_dir / "data/chunk-000/file-000.parquet", index=False)
    episodes.to_parquet(out_dir / "meta/episodes/chunk-000/file-000.parquet", index=False)

    tasks = pd.DataFrame({"task_index": [0], "task": [name]})
    tasks.to_parquet(out_dir / "meta/tasks.parquet", index=False)

    info = make_info(source_info, len(episodes), len(flat))
    (out_dir / "meta/info.json").write_text(json.dumps(info, indent=4) + "\n")

    state = np.stack(flat["observation.state"].to_numpy()).astype(np.float32)
    action = np.stack(flat["action"].to_numpy()).astype(np.float32)
    stats = {
        "observation.state": stats_for_array(state),
        "action": stats_for_array(action),
    }
    (out_dir / "meta/stats.json").write_text(json.dumps(stats, indent=4) + "\n")
    return out_dir


def main() -> None:
    successes = []
    failures = []
    for repo_id in DATASETS:
        try:
            raw_dir = download_raw(repo_id)
            source_info, data, episodes = load_raw_data(raw_dir)
            validate_schema(data)
            flat, flat_episodes = make_flat_subset(data, episodes)
            out_dir = write_flat_dataset(repo_id, source_info, flat, flat_episodes)
            successes.append((repo_id, out_dir, len(flat), len(flat_episodes)))
            print(f"OK: {repo_id} -> {out_dir} ({len(flat)} frames, {len(flat_episodes)} episodes)", flush=True)
        except Exception as exc:
            failures.append((repo_id, str(exc)))
            print(f"FAILED: {repo_id}: {exc}", flush=True)

    print("\n=== Summary ===")
    for repo_id, out_dir, frames, episodes in successes:
        print(f"OK {repo_id}: {episodes} episodes, {frames} frames, root={out_dir}")
    if failures:
        print("\nFailures:")
        for repo_id, error in failures:
            print(f"FAIL {repo_id}: {error}")


if __name__ == "__main__":
    main()
