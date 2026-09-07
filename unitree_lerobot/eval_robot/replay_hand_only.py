"""Replay only the Inspire hands from a converted dataset -- no arm motion.

replay_robot.py cannot do this: its loop unconditionally calls
arm_ctrl.ctrl_dual_arm() every frame, and its --ee inspire1 path talks to the
wrong hand controller for this rig (Inspire_Controller publishes on
"rt/inspire/cmd", but the FTP/Modbus bridge that actually drives this hand --
inspire_hand_ftp_driver.py, started per Useme.md Buoc 4 -- subscribes on
"rt/inspire_hand/ctrl/l" and "rt/inspire_hand/ctrl/r"). This script talks to
that bridge directly, matching xr_teleoperate/teleop/robot_control/
robot_hand_inspire.py's Inspire_Controller_FTP byte-for-byte:
  - same topics: rt/inspire_hand/ctrl/l, rt/inspire_hand/ctrl/r
  - same message type: inspire_dds.inspire_hand_ctrl
  - same field: angle_set (mode=0b0001 -> bridge writes Modbus reg 1486)
  - same scale: recorded qpos is a 0.0-1.0 float; the bridge wants int16
    0-1000, so int(clip(val*1000, 0, 1000)) per element (Inspire_Controller_FTP
    line ~316-317).

Run this alongside replay_robot_eno1.py (arm) in a second terminal to replay
arm + hand together -- they are separate processes with independent 's'
prompts, so press 's' in both terminals close together; this does not
frame-lock them to each other.

IMPORTANT -- LeRobotDataset's episodes= filter is a no-op for a dataset that
was converted locally rather than pulled from the Hub (see replay_robot.py's
own fix for the full story): dataset.num_frames covers the WHOLE dataset, not
just the requested episode. This script computes the frame range itself from
dataset.meta.episodes instead of trusting num_frames/episodes=.

Prerequisite: the FTP bridge must already be running for both hands (Useme.md
Buoc 4, Terminal 1a/1b) -- this script only publishes; if nothing is
subscribed on rt/inspire_hand/ctrl/l|r the hand simply will not move, with no
error on either side.

Usage:
    python replay_hand_only.py --repo-id local/place_bottle_test1 --episode 10
"""
import argparse
import threading
import time

import numpy as np
import logging_mp
from sshkeyboard import listen_keyboard

logging_mp.basicConfig(level=logging_mp.INFO)
logger_mp = logging_mp.getLogger(__name__)

NETWORK_INTERFACE = "eno1"
LEFT_TOPIC = "rt/inspire_hand/ctrl/l"
RIGHT_TOPIC = "rt/inspire_hand/ctrl/r"

# action layout from conversion (Unitree_G1_Inspire_3Cam):
# [0:7]=left_arm [7:14]=right_arm [14:20]=left_ee [20:26]=right_ee
LEFT_EE = slice(14, 20)
RIGHT_EE = slice(20, 26)


def scale_to_hardware(qpos_0_to_1):
    """Match Inspire_Controller_FTP._send_hand_command's scaling exactly."""
    return [int(np.clip(val * 1000, 0, 1000)) for val in qpos_0_to_1]


def send_pose(left_pub, right_pub, action_np, label=None):
    left_scaled = scale_to_hardware(action_np[LEFT_EE])
    right_scaled = scale_to_hardware(action_np[RIGHT_EE])

    left_msg = get_inspire_hand_ctrl()
    left_msg.angle_set = left_scaled
    left_msg.mode = 0b0001
    left_pub.Write(left_msg)

    right_msg = get_inspire_hand_ctrl()
    right_msg.angle_set = right_scaled
    right_msg.mode = 0b0001
    right_pub.Write(right_msg)

    if label:
        logger_mp.info(f"{label}  L={left_scaled}  R={right_scaled}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--root", default=None, help="dataset root; default is the HF cache used by convert")
    parser.add_argument("--episode", type=int, required=True, help="0-based episode index (see dataset.meta)")
    parser.add_argument("--frequency", type=float, default=30.0)
    args = parser.parse_args()

    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelPublisher
    ChannelFactoryInitialize(0, NETWORK_INTERFACE)

    global get_inspire_hand_ctrl
    from inspire_sdkpy import inspire_dds
    from inspire_sdkpy.inspire_hand_defaut import get_inspire_hand_ctrl
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    left_pub = ChannelPublisher(LEFT_TOPIC, inspire_dds.inspire_hand_ctrl)
    left_pub.Init()
    right_pub = ChannelPublisher(RIGHT_TOPIC, inspire_dds.inspire_hand_ctrl)
    right_pub.Init()

    # NOTE: episodes= only affects what gets *downloaded* from the Hub; for a
    # local dataset it's a no-op, so we compute the frame range ourselves.
    dataset = LeRobotDataset(repo_id=args.repo_id, root=args.root, episodes=[args.episode])
    actions = dataset.hf_dataset.select_columns("action")

    from_idx = dataset.meta.episodes["dataset_from_index"][args.episode]
    to_idx = dataset.meta.episodes["dataset_to_index"][args.episode] - 1
    num_episode_frames = to_idx - from_idx + 1
    logger_mp.info(f"Loaded episode {args.episode}: {num_episode_frames} frames "
                   f"@ {args.frequency} Hz (~{num_episode_frames / args.frequency:.1f}s)")

    user_input = input("Nhap 's' de bat dau replay ban tay (KHONG dry-run, gui lenh thuc ngay): ")
    if user_input.lower() != "s":
        logger_mp.info("Huy.")
        return

    stop_requested = threading.Event()

    def on_press(key):
        if key == "s" and not stop_requested.is_set():
            logger_mp.info("Second 's' received -- stopping and moving to the episode's final pose.")
            stop_requested.set()

    listener_thread = threading.Thread(
        target=listen_keyboard,
        kwargs={"on_press": on_press, "until": None, "sequential": False},
        daemon=True,
    )
    listener_thread.start()

    log_every_n_frames = max(1, round(3.0 * args.frequency))

    try:
        for i, global_idx in enumerate(range(from_idx, to_idx + 1)):
            if stop_requested.is_set():
                logger_mp.info(f"Stopping early at frame {i}/{num_episode_frames}.")
                break
            loop_start = time.perf_counter()
            action_np = actions[global_idx]["action"].numpy()

            label = f"frame {i}/{num_episode_frames}" if i % log_every_n_frames == 0 else None
            send_pose(left_pub, right_pub, action_np, label)

            time.sleep(max(0, (1.0 / args.frequency) - (time.perf_counter() - loop_start)))
        else:
            logger_mp.info("Reached the end of the episode.")
    except KeyboardInterrupt:
        logger_mp.info("Ctrl+C received -- stopping and moving to the episode's final pose.")

    final_action_np = actions[to_idx]["action"].numpy()
    send_pose(left_pub, right_pub, final_action_np, "Moving to episode's final hand pose")


if __name__ == "__main__":
    main()
