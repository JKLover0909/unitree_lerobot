"""'
Refer to:   lerobot/lerobot/scripts/eval.py
            lerobot/lerobot/scripts/econtrol_robot.py
            lerobot/robot_devices/control_utils.py
"""

import threading
import time
import numpy as np
from sshkeyboard import listen_keyboard

from multiprocessing.sharedctypes import SynchronizedArray
from lerobot.configs import parser
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from unitree_lerobot.eval_robot.make_robot import (
    setup_image_client,
    setup_robot_interface,
    process_images_and_observations,
)
from unitree_lerobot.eval_robot.utils.utils import cleanup_resources, EvalRealConfig

from unitree_lerobot.eval_robot.utils.rerun_visualizer import RerunLogger, visualization_data
from unitree_lerobot.eval_robot.utils.utils import to_list, to_scalar

import logging_mp

logger_mp = logging_mp.getLogger(__name__)
logger_mp.setLevel(logging_mp.INFO)


@parser.wrap()
def replay_main(cfg: EvalRealConfig):
    logger_mp.info(f"Arguments: {cfg}")

    if cfg.visualization:
        rerun_logger = RerunLogger()
        image_client, image_config = setup_image_client(cfg)
    else:
        image_client, image_config = None, None

    robot_interface = setup_robot_interface(cfg)

    """The main control and evaluation loop."""
    # Unpack interfaces for convenience
    arm_ctrl, arm_ik, ee_shared_mem, arm_dof, ee_dof = (
        robot_interface[key] for key in ["arm_ctrl", "arm_ik", "ee_shared_mem", "arm_dof", "ee_dof"]
    )

    logger_mp.info(f"Starting evaluation loop at {cfg.frequency} Hz.")

    # NOTE: LeRobotDataset's episodes= filter only takes effect when pulling
    # from the Hub (it picks which files to download); for a dataset that is
    # already local -- like this one, written directly by the converter --
    # load_hf_dataset() always loads every episode, so dataset.num_frames and
    # actions[i] below silently cover the WHOLE dataset, not just cfg.episodes.
    # Verified directly: with episodes=[10], num_frames still came back 5521
    # (all 11 episodes) instead of 397, and frame 0 matched episode 0's first
    # action, not episode 10's. dataset.meta.episodes is likewise always the
    # full, unfiltered table -- index it by cfg.episodes, never by [0].
    dataset = LeRobotDataset(repo_id=cfg.repo_id, root=cfg.root, episodes=[cfg.episodes])
    actions = dataset.hf_dataset.select_columns("action")

    # dataset_to_index is exclusive, so -1 for the last real frame.
    from_idx = dataset.meta.episodes["dataset_from_index"][cfg.episodes]
    to_idx = dataset.meta.episodes["dataset_to_index"][cfg.episodes] - 1
    num_episode_frames = to_idx - from_idx + 1
    init_left_arm_pose = dataset[from_idx]["observation.state"][:14].cpu().numpy()
    final_left_arm_pose = dataset[to_idx]["observation.state"][:14].cpu().numpy()

    def move_to_pose_and_wait(target_pose, label, tolerance_rad=0.05, timeout_s=10.0):
        """clip_arm_q_target rate-limits the move, so a fixed sleep can't
        guarantee arrival -- poll the real joint state instead."""
        tau = arm_ik.solve_tau(target_pose)
        arm_ctrl.ctrl_dual_arm(target_pose, tau)
        wait_start = time.perf_counter()
        while True:
            max_err = float(np.max(np.abs(arm_ctrl.get_current_dual_arm_q() - target_pose)))
            if max_err < tolerance_rad:
                logger_mp.info(f"Reached {label} (max joint error {max_err:.4f} rad).")
                return
            if time.perf_counter() - wait_start > timeout_s:
                logger_mp.warning(f"Timed out waiting for {label} (max joint error {max_err:.4f} rad).")
                return
            time.sleep(0.1)

    user_input = input("Please enter the start signal (enter 's' to start the subsequent program):")
    if user_input.lower() == "s":
        # "The initial positions of the robot's arm and fingers take the initial positions during data recording."
        logger_mp.info("Initializing robot to starting pose...")
        move_to_pose_and_wait(init_left_arm_pose, "starting pose")

        confirm = input("Robot is at the episode's starting pose. Enter 's' to start playback: ")
        if confirm.lower() != "s":
            logger_mp.info("Playback cancelled.")
            cleanup_resources({"shm_resources": []})
            return

        # A second 's' press during playback, or Ctrl+C, both request an early
        # stop -- caught below so the robot still finishes moving to the
        # episode's actual final recorded pose instead of freezing wherever it
        # happened to be interrupted.
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

        # Logging every frame floods the terminal at 30 Hz; throttle to ~1 line
        # every 3 seconds of playback instead, scaled to whatever --frequency is.
        log_every_n_frames = max(1, round(3.0 * cfg.frequency))

        try:
            for i, global_idx in enumerate(range(from_idx, to_idx + 1)):
                if stop_requested.is_set():
                    logger_mp.info(f"Stopping early at frame {i}/{num_episode_frames}.")
                    break
                loop_start_time = time.perf_counter()
                log_this_frame = i % log_every_n_frames == 0

                left_ee_state = right_ee_state = np.array([])
                action_np = actions[global_idx]["action"].numpy()

                # exec action
                arm_action = action_np[:arm_dof]
                tau = arm_ik.solve_tau(arm_action)
                arm_ctrl.ctrl_dual_arm(arm_action, tau)
                if log_this_frame:
                    logger_mp.info(f"frame {i}/{num_episode_frames}  arm_action {arm_action}, tau {tau}")

                if cfg.ee:
                    ee_action_start_idx = arm_dof
                    left_ee_action = action_np[ee_action_start_idx : ee_action_start_idx + ee_dof]
                    right_ee_action = action_np[ee_action_start_idx + ee_dof : ee_action_start_idx + 2 * ee_dof]
                    if log_this_frame:
                        logger_mp.info(f"EE Action: left {left_ee_action}, right {right_ee_action}")

                    with ee_shared_mem["lock"]:
                        full_state = np.array(ee_shared_mem["state"][:])
                        left_ee_state = full_state[:ee_dof]
                        right_ee_state = full_state[ee_dof:]

                    if isinstance(ee_shared_mem["left"], SynchronizedArray):
                        ee_shared_mem["left"][:] = to_list(left_ee_action)
                        ee_shared_mem["right"][:] = to_list(right_ee_action)
                    elif hasattr(ee_shared_mem["left"], "value") and hasattr(ee_shared_mem["right"], "value"):
                        ee_shared_mem["left"].value = to_scalar(left_ee_action)
                        ee_shared_mem["right"].value = to_scalar(right_ee_action)

                if cfg.visualization:
                    observation, current_arm_q = process_images_and_observations(
                        image_client, image_config, arm_ctrl
                    )
                    state = np.concatenate((current_arm_q, left_ee_state, right_ee_state))

                    visualization_data(i, observation, state, action_np, rerun_logger)

                # Maintain frequency
                time.sleep(max(0, (1.0 / cfg.frequency) - (time.perf_counter() - loop_start_time)))
            else:
                logger_mp.info("Reached the end of the episode.")
        except KeyboardInterrupt:
            logger_mp.info("Ctrl+C received -- stopping and moving to the episode's final pose.")

        logger_mp.info("Moving to the episode's final recorded pose before exiting...")
        move_to_pose_and_wait(final_left_arm_pose, "episode's final pose")

    cleanup_resources({"shm_resources": []})


if __name__ == "__main__":
    replay_main()
