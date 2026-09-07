"""Print the arm's current 14-joint pose -- read-only, no motion commanded.

Use this to capture a known-good "rest" pose (e.g. arms hanging by the sides)
for replay_arm_and_hand_eno1.py to land on, instead of guessing joint angles.

G1_29_ArmController's own __init__ locks every joint (including the arms) to
wherever it measures them at construction time -- so as soon as this script
connects, the arm is held right where it already was; it does not move.
Manually posing the robot BEFORE running this (with the robot in whatever
mode lets you move it by hand -- e.g. a damped/compliant mode) is what
actually sets the pose being printed.

Usage:
    python print_current_arm_pose.py
Prints the 14-value dual-arm q, then exits without sending anything further.
"""
NETWORK_INTERFACE = "eno1"

from unitree_sdk2py.core.channel import ChannelFactoryInitialize

ChannelFactoryInitialize(0, NETWORK_INTERFACE)

from unitree_lerobot.eval_robot.robot_control.robot_arm import G1_29_ArmController

arm_ctrl = G1_29_ArmController(motion_mode=False, simulation_mode=False)
pose = arm_ctrl.get_current_dual_arm_q()

print()
print("Current dual-arm q (14 values: [L: pitch,roll,yaw,elbow,wristRoll,wristPitch,wristYaw, R: same]):")
print(pose.tolist())
