"""'
Refer to:   lerobot/lerobot/scripts/eval.py
            lerobot/lerobot/scripts/econtrol_robot.py
            lerobot/robot_devices/control_utils.py
"""

import time
import torch
import logging
import threading

from sshkeyboard import listen_keyboard

import numpy as np
from pprint import pformat
from dataclasses import asdict
from torch import nn
from contextlib import nullcontext
from typing import Any
from lerobot.policies.factory import make_policy, make_pre_post_processors
from lerobot.utils.utils import (
    get_safe_torch_device,
    init_logging,
)
from lerobot.configs import parser
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.pretrained import PreTrainedPolicy
from multiprocessing.sharedctypes import SynchronizedArray
from lerobot.processor.rename_processor import rename_stats
from lerobot.processor import (
    PolicyAction,
    PolicyProcessorPipeline,
)
from unitree_lerobot.eval_robot.make_robot import (
    setup_image_client,
    setup_robot_interface,
    process_images_and_observations,
)
from unitree_lerobot.eval_robot.utils.utils import (
    cleanup_resources,
    predict_action,
    to_list,
    to_scalar,
    EvalRealConfig,
)
from unitree_lerobot.eval_robot.utils.rerun_visualizer import RerunLogger, visualization_data

import logging_mp

logger_mp = logging_mp.getLogger(__name__)
logger_mp.setLevel(logging_mp.INFO)


def eval_policy(
    cfg: EvalRealConfig,
    dataset: LeRobotDataset,
    policy: PreTrainedPolicy | None = None,
    preprocessor: PolicyProcessorPipeline[dict[str, Any], dict[str, Any]] | None = None,
    postprocessor: PolicyProcessorPipeline[PolicyAction, PolicyAction] | None = None,
):
    assert isinstance(policy, nn.Module), "Policy must be a PyTorch nn module."

    logger_mp.info(f"Arguments: {cfg}")

    if cfg.visualization:
        rerun_logger = RerunLogger()

    # Reset policy and processor if they are provided
    if policy is not None and preprocessor is not None and postprocessor is not None:
        policy.reset()
        preprocessor.reset()
        postprocessor.reset()

    image_client = image_config = None
    arm_ctrl = None
    try:
        # --- Setup Phase ---
        # setup_image_client() returns (image_client, image_config) -- a plain tuple, not a dict. This
        # used to be unpacked as a 7-key dict (tv_img_array, is_binocular, ...) that setup_image_client()
        # never actually produced, crashing with "TypeError: tuple indices must be integers or slices,
        # not str" the moment process_images_and_observations() was called. Fixed to match the same
        # (image_client, image_config) tuple + 3-arg process_images_and_observations() call already
        # proven correct in replay_robot.py -- see Checklist.md.
        image_client, image_config = setup_image_client(cfg)
        robot_interface = setup_robot_interface(cfg)

        # Unpack interfaces for convenience
        arm_ctrl, arm_ik, ee_shared_mem, arm_dof, ee_dof = (
            robot_interface[key] for key in ["arm_ctrl", "arm_ik", "ee_shared_mem", "arm_dof", "ee_dof"]
        )

        # Get initial pose from the first step of the dataset
        from_idx = dataset.meta.episodes["dataset_from_index"][0]
        step = dataset[from_idx]
        # Same [arm_dof | left_ee | right_ee] layout the policy predicts, so one vector
        # seeds both the arm target and the hand targets.
        init_state = step["observation.state"].cpu().numpy()
        init_arm_pose = init_state[:arm_dof]

        def send_ee_action(action_np):
            """Write one EE action into the hand controller's shared memory."""
            left = action_np[arm_dof : arm_dof + ee_dof]
            right = action_np[arm_dof + ee_dof : arm_dof + 2 * ee_dof]
            if isinstance(ee_shared_mem["left"], SynchronizedArray):
                ee_shared_mem["left"][:] = to_list(left)
                ee_shared_mem["right"][:] = to_list(right)
            elif hasattr(ee_shared_mem["left"], "value") and hasattr(ee_shared_mem["right"], "value"):
                ee_shared_mem["left"].value = to_scalar(left)
                ee_shared_mem["right"].value = to_scalar(right)

        def move_to_start_pose(tolerance_rad=0.05, timeout_s=10.0):
            """Drive the arms (and hands) to the episode's first recorded pose and wait
            until they actually arrive. ctrl_dual_arm() rate-limits the move through
            clip_arm_q_target, so the fixed time.sleep(1.0) this replaces could not
            guarantee arrival -- poll the real joint state instead, the same approach
            already proven in replay_robot.py. Also commands the hands, which the old
            flow left wherever they happened to be until the first policy action."""
            tau = arm_ik.solve_tau(init_arm_pose)
            arm_ctrl.ctrl_dual_arm(init_arm_pose, tau)
            if cfg.ee:
                send_ee_action(init_state)
            wait_start = time.perf_counter()
            while True:
                max_err = float(np.max(np.abs(arm_ctrl.get_current_dual_arm_q() - init_arm_pose)))
                if max_err < tolerance_rad:
                    logger_mp.info(f"Reached starting pose (max joint error {max_err:.4f} rad).")
                    return
                if time.perf_counter() - wait_start > timeout_s:
                    logger_mp.warning(
                        f"Timed out waiting for starting pose (max joint error {max_err:.4f} rad)."
                    )
                    return
                time.sleep(0.1)

        user_input = input("Enter 's' to move the robot to the episode's starting pose: ")
        idx = 0
        print(f"user_input: {user_input}")
        full_state = None
        if user_input.lower() == "s":
            if cfg.send_real_robot:
                # "The initial positions of the robot's arm and fingers take the initial positions during data recording."
                logger_mp.info("Initializing robot to starting pose...")
                move_to_start_pose()
            else:
                logger_mp.info(
                    "send_real_robot=False -- DRY RUN: robot will NOT move to starting pose, "
                    "arm/hand commands below are computed but not sent."
                )

            # Second gate, matching replay_arm_and_hand_eno1.py. The policy drives the
            # robot from its own predictions -- nothing bounds them to the recorded
            # trajectory -- and this script has no keyboard stop (only Ctrl+C), so the
            # old single-prompt flow went from 's' to a moving policy in 1 second with
            # no chance to check the robot first. Don't collapse these two prompts.
            confirm = input(
                "Robot is at the starting pose. Enter 's' to START POLICY INFERENCE ('q' stops it): "
            )
            if confirm.lower() != "s":
                logger_mp.info("Policy inference cancelled -- the robot stays at the starting pose.")
                return
            # 'q' stops inference at any point. Started only here, after both input()
            # gates are done -- listen_keyboard() and input() both read stdin, so they
            # must not be active at the same time (same ordering as replay_arm_and_hand_eno1.py).
            # Daemon thread, no explicit stop: the process exits right after the finally
            # block, which is the pattern already proven working in the replay scripts.
            stop_requested = threading.Event()

            def on_press(key):
                if key == "q" and not stop_requested.is_set():
                    logger_mp.info("'q' received -- stopping policy inference.")
                    stop_requested.set()

            listener_thread = threading.Thread(
                target=listen_keyboard,
                kwargs={"on_press": on_press, "until": None, "sequential": False},
                daemon=True,
            )
            listener_thread.start()

            # --- Run Main Loop ---
            logger_mp.info(f"Starting evaluation loop at {cfg.frequency} Hz. Press 'q' to stop.")
            while True:
                if stop_requested.is_set():
                    logger_mp.info(f"Policy inference stopped after {idx} steps.")
                    break
                loop_start_time = time.perf_counter()
                # 1. Get Observations
                observation, current_arm_q = process_images_and_observations(
                    image_client, image_config, arm_ctrl
                )
                left_ee_state = right_ee_state = np.array([])
                if cfg.ee:
                    with ee_shared_mem["lock"]:
                        full_state = np.array(ee_shared_mem["state"][:])
                        left_ee_state = full_state[:ee_dof]
                        right_ee_state = full_state[ee_dof:]
                state_tensor = torch.from_numpy(
                    np.concatenate((current_arm_q, left_ee_state, right_ee_state), axis=0)
                ).float()
                observation["observation.state"] = state_tensor
                # 2. Get Action from Policy
                action = predict_action(
                    observation,
                    policy,
                    get_safe_torch_device(policy.config.device),
                    preprocessor,
                    postprocessor,
                    policy.config.use_amp,
                    step["task"],
                    use_dataset=cfg.use_dataset,
                    robot_type=None,
                )
                action_np = action.cpu().numpy()
                # 3. Execute Action -- gated on cfg.send_real_robot: when False this is a dry run,
                # the policy still runs and predicted actions still reach the visualizer below, but
                # nothing is written to the arm controller or the hand shared memory (previously this
                # block ran unconditionally regardless of send_real_robot -- see Checklist.md).
                arm_action = action_np[:arm_dof]
                if cfg.send_real_robot:
                    tau = arm_ik.solve_tau(arm_action)
                    arm_ctrl.ctrl_dual_arm(arm_action, tau)

                if cfg.ee and cfg.send_real_robot:
                    send_ee_action(action_np)

                if cfg.visualization:
                    visualization_data(idx, observation, state_tensor.numpy(), action_np, rerun_logger)
                idx += 1
                # Maintain frequency
                time.sleep(max(0, (1.0 / cfg.frequency) - (time.perf_counter() - loop_start_time)))
    except Exception as e:
        logger_mp.info(f"An error occurred: {e}")
    finally:
        # Hand both arms back to the onboard controller before exiting. With
        # --motion the arm controller holds arm_sdk's takeover weight
        # (motor_cmd[kNotUsedJoint0].q) at 1.0 for the whole run; without this
        # step it stays at 1.0 after the process dies, arm_sdk keeps the arms
        # latched, and the robot never regains them -- see Checklist.md.
        if arm_ctrl is not None:
            try:
                if cfg.send_real_robot:
                    arm_ctrl.ctrl_dual_arm_go_home()
                else:
                    # DRY RUN. G1_29_ArmController's _ctrl_motor_state() thread publishes
                    # at 250 Hz unconditionally -- it never looks at send_real_robot -- so
                    # ctrl_dual_arm_go_home() would set q_target=zeros(14) and physically
                    # drive the arms home in a run the user was told is a dry run (the same
                    # trap as bug 6's hand controller). The arms have not been commanded
                    # anywhere here (q_target is still the pose read at init), but with
                    # --motion arm_sdk's weight IS latched at 1.0, so release just the
                    # weight: hands control back without moving anything.
                    arm_ctrl.release_arm_sdk_weight()
            except Exception as e:
                logger_mp.error(f"Failed to hand the arms back: {e}")
        if image_client is not None:
            # No real shared-memory resources with this ImageClient (see replay_robot.py's identical
            # no-op call) -- kept only so cleanup_resources() still logs and runs its close/unlink loop
            # over an empty list.
            cleanup_resources({"shm_resources": []})


@parser.wrap()
def eval_main(cfg: EvalRealConfig):
    logging.info(pformat(asdict(cfg)))

    # Check device is available
    device = get_safe_torch_device(cfg.policy.device, log=True)

    torch.backends.cudnn.benchmark = True
    torch.backends.cuda.matmul.allow_tf32 = True

    logging.info("Making policy.")

    dataset = LeRobotDataset(repo_id=cfg.repo_id, video_backend=cfg.video_backend)

    policy = make_policy(cfg=cfg.policy, ds_meta=dataset.meta)
    policy.eval()

    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=cfg.policy,
        pretrained_path=cfg.policy.pretrained_path,
        dataset_stats=rename_stats(dataset.meta.stats, cfg.rename_map),
        preprocessor_overrides={
            "device_processor": {"device": cfg.policy.device},
            "rename_observations_processor": {"rename_map": cfg.rename_map},
        },
    )

    with torch.no_grad(), torch.autocast(device_type=device.type) if cfg.policy.use_amp else nullcontext():
        eval_policy(cfg, dataset, policy, preprocessor, postprocessor)

    logging.info("End of eval")


if __name__ == "__main__":
    init_logging()
    eval_main()
