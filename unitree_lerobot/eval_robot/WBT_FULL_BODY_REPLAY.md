# WBT Full-Body Replay

Script:

```text
unitree_lerobot/eval_robot/wbt_full_body_replay.py
```

Mục tiêu:

- Đọc raw WBT dataset chưa flatten.
- Dùng `action.robot_q_desired[7:36]` làm target cho 29 motor G1.
- Bỏ qua root pose `action.robot_q_desired[0:7]` vì root/base pose không thể replay trực tiếp bằng joint command.
- Có thể publish `action.hand_cmd[0:12]` sang bridge Inspire hand nếu bridge đang chạy.

Raw dataset mặc định:

```text
/home/jkl0909/.cache/huggingface/lerobot/unitreerobotics/G1_WBT_Inspire_Pick_Up_Drinks_raw3tmp
```

## 0. Chuẩn Bị

Activate môi trường:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot
```

Interface đang dùng với G1:

```text
enp1s0
```

IP Inspire hand:

```text
left  = 192.168.123.210
right = 192.168.123.211
```

Khác với pipeline pickup drink 26D đã chạy thành công qua `rt/arm_sdk`, script full-body dùng:

```text
rt/lowcmd
rt/lowstate
```

Đây là low-level full-body control. Chỉ chạy real robot khi robot được treo/đỡ an toàn hoặc có người giữ emergency stop.

## 1. Bật Bridge Cho Inspire Hand

Terminal 1, tay trái:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python unitree_lerobot/eval_robot/inspire_hand_ftp_driver.py \
  --network-interface=enp1s0 \
  --hand=left \
  --ip=192.168.123.210 \
  --frequency=20 \
  --no-touch
```

Terminal 2, tay phải:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python unitree_lerobot/eval_robot/inspire_hand_ftp_driver.py \
  --network-interface=enp1s0 \
  --hand=right \
  --ip=192.168.123.211 \
  --frequency=20 \
  --no-touch
```

Bridge publish state:

```text
rt/inspire_hand/state/l
rt/inspire_hand/state/r
```

Bridge nhận control:

```text
rt/inspire_hand/ctrl/l
rt/inspire_hand/ctrl/r
```

## 2. Test Inspire Hand Trước

Read-only tay phải:

```bash
python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=right
```

Read-only tay trái:

```bash
python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=left
```

Đóng/mở tay phải:

```bash
python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=right \
  --preset=close \
  --force=500 \
  --speed=300 \
  --send-command \
  --control-confirmation=SEND_TEST_INSPIRE_HAND

python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=right \
  --preset=open \
  --force=500 \
  --speed=300 \
  --send-command \
  --control-confirmation=SEND_TEST_INSPIRE_HAND
```

Nếu tay trái vẫn báo `status=7` hoặc joint ngón út kẹt, khi replay full-body có thể tạm:

```text
--ignore-inspire-status
--disable-left-hand
```

## 3. Preview

Chỉ đọc dataset và in range các khớp. Không gửi lệnh robot.

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python unitree_lerobot/eval_robot/wbt_full_body_replay.py \
  --preview-only \
  --episode=0 \
  --episode-count=3 \
  --max-steps=10
```

## 4. Dry Run Playback

Chạy vòng replay và ghi CSV, nhưng không publish `rt/lowcmd`.

```bash
python unitree_lerobot/eval_robot/wbt_full_body_replay.py \
  --episode=0 \
  --episode-count=1 \
  --max-steps=100 \
  --frequency=30
```

Output:

```text
wbt_full_body_results/
```

## 5. Real Robot Full-Body Test

Rất nguy hiểm hơn arm-only replay. Chỉ chạy khi robot được treo/đỡ an toàn hoặc có người giữ emergency stop.

Lệnh test ngắn 30 step, có cả tay Inspire:

```bash
python unitree_lerobot/eval_robot/wbt_full_body_replay.py \
  --episode=0 \
  --episode-count=1 \
  --max-steps=30 \
  --frequency=30 \
  --network-interface=enp1s0 \
  --initialize-from-dataset \
  --initialization-speed-rad-s=0.05 \
  --initialization-max-error-rad=0.10 \
  --max-body-delta-rad=0.005 \
  --low-body-kp-scale=0.25 \
  --arm-kp-scale=0.8 \
  --hand-force=300 \
  --hand-speed=200 \
  --max-hand-delta=50 \
  --send-actions \
  --control-confirmation=SEND_FULL_BODY_G1_WBT
```

Flow đúng:

```text
Loaded raw dataset...
episode=0 dataset_index=0..655 actions=656 ...
G1 MotionSwitcher: ...
left Inspire state: ...
right Inspire state: ...
Initializing full body to first dataset joint pose...
Initial body pose reached: max_error=...
Initial pose stage done. Enter 's' to start full-body replay, anything else to stop:
```

Chỉ nhập:

```text
s
```

nếu robot đang ổn định.

Nếu robot không nhận `rt/lowcmd` vì đang có active motion mode, chỉ khi thật sự hiểu rủi ro mới thêm:

```text
--release-motion-mode
```

Không thêm flag này một cách máy móc. `rt/lowcmd` là low-level full-body command, khác với `rt/arm_sdk`.

## 6. Chạy Không Điều Khiển Tay

Nếu chỉ muốn test full-body joint command, không gửi Inspire hand:

```bash
python unitree_lerobot/eval_robot/wbt_full_body_replay.py \
  --episode=0 \
  --episode-count=1 \
  --max-steps=30 \
  --frequency=30 \
  --network-interface=enp1s0 \
  --initialize-from-dataset \
  --initialization-speed-rad-s=0.05 \
  --initialization-max-error-rad=0.10 \
  --max-body-delta-rad=0.005 \
  --low-body-kp-scale=0.25 \
  --arm-kp-scale=0.8 \
  --no-hands \
  --send-actions \
  --control-confirmation=SEND_FULL_BODY_G1_WBT
```

## 7. Chạy Nhiều Episode

Giống pipeline pickup drink đã deploy, dùng:

```text
--episode-count=N
```

Ví dụ chạy episode `0, 1, 2` ở dry-run:

```bash
python unitree_lerobot/eval_robot/wbt_full_body_replay.py \
  --episode=0 \
  --episode-count=3 \
  --frequency=30
```

Không nên chạy nhiều episode real robot liên tục khi chưa kiểm từng initial pose.

## 8. Param Quan Trọng

```text
--send-actions
```

Bật gửi command thật. Không có flag này thì dry run.

```text
--control-confirmation=SEND_FULL_BODY_G1_WBT
```

Xác nhận bắt buộc trước khi publish `rt/lowcmd`.

```text
--initialize-from-dataset
```

Đưa 29 khớp body về pose đầu episode trước khi replay.

```text
--max-body-delta-rad=0.005
```

Giới hạn mỗi step full-body. Ở 30 Hz tương đương khoảng `0.15 rad/s`.
Nên bắt đầu rất nhỏ vì có chân/thân.

```text
--low-body-kp-scale=0.25
```

Giảm stiffness cho 15 khớp chân/thân so với bảng Kp SDK gốc.

```text
--arm-kp-scale=0.8
```

Scale Kp cho 14 khớp tay.

```text
--max-hand-delta=50
```

Giới hạn mỗi step bàn tay Inspire đổi tối đa 50 đơn vị trên thang `0..1000`.

```text
--ignore-inspire-status
```

Bỏ chặn `status=7` của Inspire hand. Chỉ dùng khi đã biết lỗi phần cứng và vẫn muốn tiếp tục.

```text
--disable-left-hand
--disable-right-hand
```

Không publish command tới một bên tay.

```text
--release-motion-mode
```

Gọi MotionSwitcher `ReleaseMode()` trước khi low-level control. Chỉ dùng khi chủ động chuyển sang full-body low-level, vì robot có thể mất balance nếu command không đúng.

## 9. C++ Body Replay

Ngoài script Python `wbt_full_body_replay.py`, repo có thêm flow C++ để chuyển phần gửi lệnh 29 khớp G1 sang `unitree_sdk2` C++.

Nếu muốn đi giống repo Holosoma hơn, ưu tiên dùng:

```bash
python unitree_lerobot/eval_robot/wbt_holosoma_unitree_replay.py \
  --episode=0 \
  --episode-count=1 \
  --max-steps=30 \
  --frequency=30 \
  --preview-only
```

Backend này không tự publish `rt/lowcmd`; nó dùng binding C++/pybind11 `unitree_interface` giống Holosoma:

```text
create_robot -> read_low_state -> create_zero_command -> write_low_command
```

Nếu thiếu binding, cài wheel `unitree_sdk2` từ `amazon-far/unitree_sdk2` giống hướng dẫn trong `Useme-C.md`.

Ý tưởng:

```text
Python export raw dataset -> CSV q0..q28
C++ g1_wbt_body_replay    -> rt/lowcmd / rt/lowstate
```

Ở bản đầu, C++ replay chỉ điều khiển 29 khớp body G1. Inspire hand vẫn dùng pipeline Python/bridge riêng nếu cần.

Build binary:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot

cmake -S unitree_lerobot/eval_robot/cpp \
  -B build/wbt_cpp_replay \
  -DCMAKE_PREFIX_PATH=/usr/local

cmake --build build/wbt_cpp_replay -j"$(nproc)"
```

Export episode từ raw dataset sang CSV:

```bash
python unitree_lerobot/eval_robot/export_wbt_full_body_csv.py \
  --episode=0 \
  --episode-count=1 \
  --max-steps=30 \
  --output=wbt_cpp_replay_inputs/episode0_30.csv
```

Dry-run C++ không gửi lệnh robot:

```bash
./build/wbt_cpp_replay/g1_wbt_body_replay \
  --input-csv=wbt_cpp_replay_inputs/episode0_30.csv \
  --frequency=30 \
  --print-every=10 \
  --log-csv=/tmp/wbt_cpp_replay_log.csv
```

Real robot, test rất ngắn, chỉ init cổ chân:

```bash
./build/wbt_cpp_replay/g1_wbt_body_replay \
  --input-csv=wbt_cpp_replay_inputs/episode0_30.csv \
  --network-interface=enp1s0 \
  --frequency=30 \
  --initialize-from-first-row \
  --initialization-speed-rad-s=0.05 \
  --initialization-max-error-rad=0.10 \
  --initialization-timeout-s=60 \
  --init-joints=4,5,10,11 \
  --max-body-delta-rad=0.005 \
  --low-body-kp-scale=0.25 \
  --arm-kp-scale=0.8 \
  --send-actions \
  --control-confirmation=SEND_FULL_BODY_G1_WBT
```

Real robot, chỉ init 2 cánh tay qua `rt/arm_sdk`:

```bash
./build/wbt_cpp_replay/g1_wbt_body_replay \
  --input-csv=wbt_cpp_replay_inputs/episode0_30.csv \
  --network-interface=enp1s0 \
  --frequency=30 \
  --initialize-from-first-row \
  --init-only \
  --arm-sdk \
  --init-joints=15,16,17,18,19,20,21,22,23,24,25,26,27,28 \
  --initialization-speed-rad-s=0.05 \
  --initialization-max-error-rad=0.10 \
  --initialization-timeout-s=120 \
  --max-body-delta-rad=0.005 \
  --low-body-kp-scale=0.25 \
  --arm-kp-scale=0.8 \
  --send-actions \
  --control-confirmation=SEND_FULL_BODY_G1_WBT
```

Nếu log `G1 MotionSwitcher` vẫn báo `name=ai`, `rt/lowcmd` có thể bị motion service chặn. Với riêng eo/tay, ưu tiên `--arm-sdk` để giữ robot ở mode cân bằng.

Real robot, init tuần tự 5 nhóm:

```bash
./build/wbt_cpp_replay/g1_wbt_body_replay \
  --input-csv=wbt_cpp_replay_inputs/episode0_30.csv \
  --network-interface=enp1s0 \
  --frequency=30 \
  --initialize-from-first-row \
  --initialization-speed-rad-s=0.05 \
  --initialization-max-error-rad=0.10 \
  --initialization-timeout-s=180 \
  --init-sequential \
  --init-group-pause-s=2.0 \
  --max-body-delta-rad=0.005 \
  --low-body-kp-scale=0.25 \
  --arm-kp-scale=0.8 \
  --send-actions \
  --control-confirmation=SEND_FULL_BODY_G1_WBT
```

Sau init, C++ cũng dừng lại và hỏi:

```text
Initial pose stage done. Enter 's' to start C++ full-body replay, anything else to stop:
```

Chỉ nhập `s` khi robot đang được treo/đỡ an toàn và tư thế init ổn.

## 10. Mapping

`action.robot_q_desired` có 36 chiều:

```text
0  root position x
1  root position y
2  root position z
3  root quaternion w
4  root quaternion x
5  root quaternion y
6  root quaternion z
7  left_hip_pitch
8  left_hip_roll
9  left_hip_yaw
10 left_knee
11 left_ankle_pitch
12 left_ankle_roll
13 right_hip_pitch
14 right_hip_roll
15 right_hip_yaw
16 right_knee
17 right_ankle_pitch
18 right_ankle_roll
19 waist_yaw
20 waist_roll
21 waist_pitch
22 left_shoulder_pitch
23 left_shoulder_roll
24 left_shoulder_yaw
25 left_elbow
26 left_wrist_roll
27 left_wrist_pitch
28 left_wrist_yaw
29 right_shoulder_pitch
30 right_shoulder_roll
31 right_shoulder_yaw
32 right_elbow
33 right_wrist_roll
34 right_wrist_pitch
35 right_wrist_yaw
```
