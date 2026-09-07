"""Run replay_robot.py pinned to a specific DDS network interface, with the
robot's onboard AI/Sport controller released first.

Two gaps vs. xr_teleoperate/teleop_hand_and_arm.py that replay_robot.py does
not cover on its own:

1. Network interface. EvalRealConfig has no --network_interface flag, and the
   arm controller (robot_control/robot_arm.py) calls ChannelFactoryInitialize(0)
   with no interface, which falls back to CycloneDDS auto-detection. On a
   multi-NIC host (robot ethernet + wifi + docker bridges) that auto-pick is
   not reliable -- packets can silently go out the wrong interface with no
   error, so the robot simply never moves. ChannelFactory.Init() is a
   class-level singleton (see its `__initialized` guard): whoever calls it
   first wins for the whole process, so calling it here before importing
   replay_robot locks in the interface below and makes robot_arm.py's own bare
   call harmless.

2. Onboard AI/Sport mode. teleop_hand_and_arm.py calls
   MotionSwitcher().Enter_Debug_Mode() whenever --motion is not passed, which
   releases the robot's own onboard balance controller before sending raw
   joint commands. replay_robot.py never does this -- grep the whole
   eval_robot tree, there is no MotionSwitcher reference anywhere in it. If
   the robot is still in "ai" mode when a lowcmd trajectory is published, its
   own onboard controller keeps fighting to hold a standing posture on the
   same motors: symptom is buzzing/jitter and the robot not visibly following
   the recorded trajectory, even though our sent arm_action values are
   correct and changing normally (confirmed from a real run's log). Skip this
   release only if you intend to run with --motion (locomotion mode), which
   has its own precondition (Regular mode via R1+X) per Useme.md.

Usage: identical to replay_robot.py, e.g.
    python replay_robot_eno1.py --repo_id local/place_bottle_test1 --episodes 10 \
        --arm G1_29 --ee "" --frequency 30
"""
import sys
import time

NETWORK_INTERFACE = "eno1"

from unitree_sdk2py.core.channel import ChannelFactoryInitialize

ChannelFactoryInitialize(0, NETWORK_INTERFACE)

if "--motion" not in sys.argv:
    from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

    msc = MotionSwitcherClient()
    msc.SetTimeout(1.0)
    msc.Init()
    status, result = msc.CheckMode()
    while result.get("name"):
        print(f"[replay_robot_eno1] Releasing onboard mode '{result['name']}'...")
        msc.ReleaseMode()
        time.sleep(1)
        status, result = msc.CheckMode()
    print("[replay_robot_eno1] Onboard AI/Sport controller released.")

from unitree_lerobot.eval_robot.replay_robot import replay_main

if __name__ == "__main__":
    replay_main()
