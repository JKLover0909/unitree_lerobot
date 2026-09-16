"""Run eval_g1.py pinned to a specific DDS network interface, with the robot's
onboard AI/Sport controller released first.

Same two gaps replay_robot_eno1.py covers, for the policy eval path:

1. Network interface. EvalRealConfig has no network_interface field, and the
   arm controller (robot_control/robot_arm.py) calls ChannelFactoryInitialize(0)
   with no interface, which falls back to CycloneDDS auto-detection. On this
   multi-NIC host (eno1 to the robot, plus wifi/tailscale/docker bridges) that
   auto-pick is not reliable -- packets can silently go out the wrong interface
   with no error, so the robot simply never moves. ChannelFactory.Init() is a
   class-level singleton, so calling it here before importing eval_g1 locks in
   the interface below and makes the bare call inside robot_arm.py harmless.

2. Onboard AI/Sport mode. eval_g1.py never calls MotionSwitcher. If the robot
   is still in "ai" mode when lowcmd arm targets are published, its onboard
   balance controller fights for the same motors: buzzing/jitter and the robot
   not following the policy, even though the actions being sent are correct.

Hand control: pass --ee=inspire_ftp for the FTP hands on this robot (the
inspire1 path publishes to rt/inspire/cmd, which this hardware ignores). The
FTP bridge must already be running for BOTH hands, see Useme.md:

    python unitree_lerobot/eval_robot/inspire_hand_ftp_driver.py \
        --network-interface=eno1 --hand=left  --ip=192.168.123.210 \
        --frequency=20 --no-touch
    python unitree_lerobot/eval_robot/inspire_hand_ftp_driver.py \
        --network-interface=eno1 --hand=right --ip=192.168.123.211 \
        --frequency=20 --no-touch

Usage: identical to eval_g1.py, e.g.
    python unitree_lerobot/eval_robot/eval_g1_eno1.py \
        --policy.path=/path/to/pretrained_model \
        --repo_id=local/pick_place_bottle --root="" --frequency=30 \
        --arm=G1_29 --ee=inspire_ftp --visualization=true --send_real_robot=false
"""
import sys
import time

NETWORK_INTERFACE = "eno1"


def _motion_flag_set() -> bool:
    """True if --motion was passed as truthy. draccus takes --motion=true as a
    single argv token, so a plain `"--motion" in sys.argv` membership test would
    miss it and wrongly release the onboard controller."""
    for i, arg in enumerate(sys.argv):
        if arg == "--motion":
            nxt = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
            return nxt.lower() not in ("false", "0", "no")
        if arg.startswith("--motion="):
            return arg.split("=", 1)[1].lower() not in ("false", "0", "no")
    return False


from unitree_sdk2py.core.channel import ChannelFactoryInitialize

ChannelFactoryInitialize(0, NETWORK_INTERFACE)
print(f"[eval_g1_eno1] DDS pinned to interface '{NETWORK_INTERFACE}'.")

if not _motion_flag_set():
    from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient

    msc = MotionSwitcherClient()
    msc.SetTimeout(1.0)
    msc.Init()
    status, result = msc.CheckMode()
    while result.get("name"):
        print(f"[eval_g1_eno1] Releasing onboard mode '{result['name']}'...")
        msc.ReleaseMode()
        time.sleep(1)
        status, result = msc.CheckMode()
    print("[eval_g1_eno1] Onboard AI/Sport controller released.")

from unitree_lerobot.eval_robot.eval_g1 import eval_main

if __name__ == "__main__":
    eval_main()
