# Agent Summary: Unitree G1 EDU Control

This folder mirrors `AGENT-read-This4G1-Edu/G1-Edu` but contains markdown notes extracted from the saved Unitree Document Center HTML pages. Web assets (`*_files`, CSS, JS, logos, QR images) are intentionally not mirrored.

## Highest-Level Mental Model

G1 EDU control has several separate layers. Do not mix them casually.

1. **Built-in high-level motion control**
   - Accessed through RPC clients such as `LocoClient` and `ArmAction`.
   - Handles modes such as damping, lock standing, walk/run, balance stand, sit/squat.
   - Depends on Unitree internal motion-control service.
   - Becomes invalid when debug mode fully exits the built-in controller.

2. **High-level upper-limb DDS control**
   - Publishes `LowCmd_` to `rt/arm_sdk`.
   - Depends on the built-in motion service.
   - Does **not** require debug mode.
   - Works in locked stance / movement-control modes.
   - Uses motor command index `29` as a weight/enable channel.

3. **Low-level full-body DDS control**
   - Publishes `LowCmd_` to `rt/lowcmd`.
   - Subscribes `LowState_` from `rt/lowstate`.
   - Controls body motors only; dexterous hands are separate.
   - Official examples use a 500 Hz loop.
   - Requires debug/user-control mode to avoid command conflict with the built-in motion controller.
   - This is the risky path for full-body replay.

4. **Dexterous hand control**
   - Dex3 uses `rt/dex3/left|right/cmd` and `rt/dex3/left|right/state`.
   - Inspire FTP uses `rt/inspire_hand/ctrl/*`, `rt/inspire_hand/state/*`, and optional touch topic.
   - Inspire default IPs: left `192.168.123.210`, right `192.168.123.211`.

5. **Sensors**
   - D435i depth camera is accessed via Intel RealSense/librealsense or realsense-ros.
   - It is not the same as the Go2 video-client API.
   - LiDAR is Livox MID360.

## Mode Lessons For This Repo

- For **arm-only / hand replay** that relies on `rt/arm_sdk`, do not use debug mode. Use locked/operation standing mode that keeps lower-body balance alive.
- For **full-body replay** via `rt/lowcmd`, debug/user-control mode is needed to avoid fighting the built-in controller, but then your controller owns balance risk.
- If robot does not move while commands are published, inspect current motion mode and whether the receiving service is valid in that mode.

## Joint/Topic Rules

- `rt/lowcmd` and `rt/lowstate` cover G1 body motors excluding dexterous hands.
- `LowCmd_.motor_cmd[35]` exists, but 29DOF body joints are indices `0..28`.
- In `rt/arm_sdk`, valid elements include index `29` as weight and indices `12..28` for waist/upper-limb parameters.
- For full-body code, read `mode_machine` from `LowState` and reuse it. The docs contain inconsistent mode_machine numbering across pages.
- Use `mode_pr = 0` PR mode for ankle/waist unless intentionally doing AB parallel-mechanism kinematics.

## Important Safety Notes

- Full-body low-level replay can topple the robot if lower-body/waist commands conflict with real balance.
- Start with dry-run, single-joint or joint-group tests, low gains, low deltas, and physical support.
- The official low-level examples explicitly say to suspend the robot before running routines that move multiple joints.
- `L2+B` is documented as damping/emergency-stop-like behavior, but damping can make the robot lose balance and fall.

## Duplicate Check

A content-hash check of the 34 saved HTML article bodies found no duplicate article groups. Duplicate files in the original HTML save are mostly shared website assets such as CSS, JS, logo, KaTeX, Mermaid, and QR images.
