"""Replay arm + Inspire hand together from a converted dataset, in ONE process
and ONE loop, so both stay frame-locked -- unlike running replay_robot_eno1.py
(arm) and replay_hand_only.py (hand) in two separate terminals, which have
independent 's' prompts and are not synchronized to each other.

Combines, in a single script:
  - Arm control: same G1_29_ArmController/G1_29_ArmIK path as replay_robot.py
    (rt/lowcmd, kTopicLowCommand_Debug unless --motion). Legs/waist get locked
    to whatever pose the robot is in at startup; only the 14 arm joints move.
  - Hand control: talks directly to the FTP/Modbus bridge
    (inspire_hand_ftp_driver.py, started per Useme.md Buoc 4) on
    rt/inspire_hand/ctrl/l|r with inspire_dds.inspire_hand_ctrl -- NOT the
    replay_robot.py --ee inspire1 path, which publishes to the wrong topic
    (rt/inspire/cmd) for this hardware and would silently do nothing.
  - Network interface pinning (eno1) and onboard AI/Sport mode release, same
    as replay_robot_eno1.py.
  - The episodes= filter is a no-op for a locally-converted dataset (see
    replay_robot.py's own history for why); the frame range is computed here
    from dataset.meta.episodes instead of trusting dataset.num_frames.

Prerequisite: the FTP bridge must already be running for both hands (Useme.md
Buoc 4, Terminal 1a/1b) -- if nothing is subscribed on
rt/inspire_hand/ctrl/l|r the hand simply will not move, with no error either
side.

Usage:
    python replay_arm_and_hand_eno1.py --repo-id local/place_bottle_test1 --episode 10
"""
NETWORK_INTERFACE = "eno1"

import argparse
import threading
import time

import numpy as np
import logging_mp
from sshkeyboard import listen_keyboard

logging_mp.basicConfig(level=logging_mp.INFO)
logger_mp = logging_mp.getLogger(__name__)

LEFT_HAND_TOPIC = "rt/inspire_hand/ctrl/l"
RIGHT_HAND_TOPIC = "rt/inspire_hand/ctrl/r"

# action layout from conversion (Unitree_G1_Inspire_3Cam):
# [0:7]=left_arm [7:14]=right_arm [14:20]=left_ee [20:26]=right_ee
ARM = slice(0, 14)
LEFT_EE = slice(14, 20)
RIGHT_EE = slice(20, 26)


def scale_to_hardware(qpos_0_to_1):
    """Match Inspire_Controller_FTP._send_hand_command's scaling exactly."""
    return [int(np.clip(val * 1000, 0, 1000)) for val in qpos_0_to_1]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--root", default=None, help="dataset root; default is the HF cache used by convert")
    parser.add_argument("--episode", type=int, required=True, help="0-based episode index (see dataset.meta)")
    parser.add_argument("--frequency", type=float, default=30.0)
    parser.add_argument("--motion", action="store_true",
                        help="skip releasing the onboard AI/Sport mode (locomotion mode precondition instead)")
    args = parser.parse_args()

    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelPublisher
    ChannelFactoryInitialize(0, NETWORK_INTERFACE)

    if not args.motion:
        from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

        msc = MotionSwitcherClient()
        msc.SetTimeout(1.0)
        msc.Init()
        status, result = msc.CheckMode()
        while result.get("name"):
            logger_mp.info(f"Releasing onboard mode '{result['name']}'...")
            msc.ReleaseMode()
            time.sleep(1)
            status, result = msc.CheckMode()
        logger_mp.info("Onboard AI/Sport controller released.")

    from unitree_lerobot.eval_robot.robot_control.robot_arm import G1_29_ArmController
    from unitree_lerobot.eval_robot.robot_control.robot_arm_ik import G1_29_ArmIK
    from inspire_sdkpy import inspire_dds
    from inspire_sdkpy.inspire_hand_defaut import get_inspire_hand_ctrl
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    arm_ik = G1_29_ArmIK()
    arm_ctrl = G1_29_ArmController(motion_mode=args.motion, simulation_mode=False)

    left_hand_pub = ChannelPublisher(LEFT_HAND_TOPIC, inspire_dds.inspire_hand_ctrl)
    left_hand_pub.Init()
    right_hand_pub = ChannelPublisher(RIGHT_HAND_TOPIC, inspire_dds.inspire_hand_ctrl)
    right_hand_pub.Init()

    # NOTE: episodes= only affects what gets *downloaded* from the Hub; for a
    # local dataset it's a no-op, so the frame range is computed ourselves.
    dataset = LeRobotDataset(repo_id=args.repo_id, root=args.root, episodes=[args.episode])
    actions = dataset.hf_dataset.select_columns("action")
    from_idx = dataset.meta.episodes["dataset_from_index"][args.episode]
    to_idx = dataset.meta.episodes["dataset_to_index"][args.episode] - 1
    num_episode_frames = to_idx - from_idx + 1
    logger_mp.info(f"Loaded episode {args.episode}: {num_episode_frames} frames "
                   f"@ {args.frequency} Hz (~{num_episode_frames / args.frequency:.1f}s)")

    def send_hand(action_np, label=None):
        left_scaled = scale_to_hardware(action_np[LEFT_EE])
        right_scaled = scale_to_hardware(action_np[RIGHT_EE])

        left_msg = get_inspire_hand_ctrl()
        left_msg.angle_set = left_scaled
        left_msg.mode = 0b0001
        left_hand_pub.Write(left_msg)

        right_msg = get_inspire_hand_ctrl()
        right_msg.angle_set = right_scaled
        right_msg.mode = 0b0001
        right_hand_pub.Write(right_msg)

        if label:
            logger_mp.info(f"{label}  hand L={left_scaled} R={right_scaled}")

    def move_to_pose_and_wait(arm_target, label, hand_action_np=None, tolerance_rad=0.05, timeout_s=10.0):
        """clip_arm_q_target rate-limits the arm move (arm_velocity_limit=20.0
        rad/s), so this is already a controlled, gradual motion, not a fixed
        sleep -- polls the real arm joint state instead of guessing how long
        the move takes. hand_action_np is optional: pass None to leave the
        hand alone (e.g. when returning the arm to its pre-command pose,
        where the hand should stay wherever the FTP bridge already has it)."""
        tau = arm_ik.solve_tau(arm_target)
        arm_ctrl.ctrl_dual_arm(arm_target, tau)
        if hand_action_np is not None:
            send_hand(hand_action_np)
        wait_start = time.perf_counter()
        while True:
            max_err = float(np.max(np.abs(arm_ctrl.get_current_dual_arm_q() - arm_target)))
            if max_err < tolerance_rad:
                logger_mp.info(f"Reached {label} (max joint error {max_err:.4f} rad).")
                return
            if time.perf_counter() - wait_start > timeout_s:
                logger_mp.warning(f"Timed out waiting for {label} (max joint error {max_err:.4f} rad).")
                return
            time.sleep(0.1)

    init_action = actions[from_idx]["action"].numpy()
    final_action = actions[to_idx]["action"].numpy()

    user_input = input("Please enter the start signal (enter 's' to start the subsequent program): ")
    if user_input.lower() != "s":
        logger_mp.info("Huy.")
        return

    logger_mp.info("Initializing robot to starting pose...")
    move_to_pose_and_wait(init_action[ARM], "starting pose", hand_action_np=init_action)

    confirm = input("Robot is at the episode's starting pose. Enter 's' to start playback: ")
    if confirm.lower() != "s":
        logger_mp.info("Playback cancelled.")
        return

    # 'q' (any time from here on) requests stopping the program for good.
    # 's' (only listened to while idle between episodes, see the outer loop
    # below) requests another playback of the same episode. Ctrl+C is
    # equivalent to 'q' wherever it's caught below. Either way, the robot
    # finishes moving to the episode's actual final recorded pose instead of
    # freezing wherever it happened to be interrupted.
    stop_requested = threading.Event()
    replay_requested = threading.Event()

    def on_press(key):
        if key == "q" and not stop_requested.is_set():
            logger_mp.info("'q' received -- stopping and moving to the episode's final pose.")
            stop_requested.set()
        elif key == "s":
            replay_requested.set()

    listener_thread = threading.Thread(
        target=listen_keyboard,
        kwargs={"on_press": on_press, "until": None, "sequential": False},
        daemon=True,
    )
    listener_thread.start()

    # Logging every frame floods the terminal at 30 Hz; throttle to ~1 line
    # every 3 seconds of playback instead, scaled to whatever --frequency is.
    log_every_n_frames = max(1, round(3.0 * args.frequency))

    def play_episode_once():
        """Move to the episode's start pose (a no-op if already there, e.g.
        right after the confirmation step below), play through it or stop
        early on 'q'/Ctrl+C, then settle at its final pose."""
        move_to_pose_and_wait(init_action[ARM], "starting pose", hand_action_np=init_action)
        try:
            for i, global_idx in enumerate(range(from_idx, to_idx + 1)):
                if stop_requested.is_set():
                    logger_mp.info(f"Stopping early at frame {i}/{num_episode_frames}.")
                    break
                loop_start = time.perf_counter()
                action_np = actions[global_idx]["action"].numpy()

                arm_action = action_np[ARM]
                tau = arm_ik.solve_tau(arm_action)
                arm_ctrl.ctrl_dual_arm(arm_action, tau)

                log_this_frame = i % log_every_n_frames == 0
                label = f"frame {i}/{num_episode_frames}" if log_this_frame else None
                send_hand(action_np, label)
                if log_this_frame:
                    logger_mp.info(f"frame {i}/{num_episode_frames}  arm_action {arm_action}, tau {tau}")

                time.sleep(max(0, (1.0 / args.frequency) - (time.perf_counter() - loop_start)))
            else:
                logger_mp.info("Reached the end of the episode.")
        except KeyboardInterrupt:
            logger_mp.info("Ctrl+C received -- stopping and moving to the episode's final pose.")
            stop_requested.set()

        logger_mp.info("Moving to the episode's final recorded pose...")
        move_to_pose_and_wait(final_action[ARM], "episode's final pose", hand_action_np=final_action)

    while True:
        play_episode_once()
        if stop_requested.is_set():
            break

        logger_mp.info("Episode finished. Press 's' to play it again, or 'q'/Ctrl+C to stop.")
        replay_requested.clear()  # ignore any stray 's' presses that landed during playback
        try:
            while not stop_requested.is_set() and not replay_requested.is_set():
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger_mp.info("Ctrl+C received -- stopping.")
            break
        if stop_requested.is_set():
            break
        # replay_requested is set -> loop back and play the episode again


if __name__ == "__main__":
    main()
