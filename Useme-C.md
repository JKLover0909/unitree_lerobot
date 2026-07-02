# Useme-C: WBT Full-Body Replay Bằng C++ / Holosoma Binding

File này dành riêng cho flow replay raw WBT dataset lên G1 bằng hai hướng:

1. **Holosoma-style binding**: Python replay, nhưng gửi lệnh qua C++/pybind11 `unitree_interface`, giống repo Holosoma.
2. **Direct C++ SDK2**: binary C++ tự publish `rt/lowcmd` / `rt/arm_sdk`.

Hiện tại nếu muốn đi giống Holosoma thì ưu tiên dùng:

```text
unitree_lerobot/eval_robot/wbt_holosoma_unitree_replay.py
```

Script này gọi:

```text
unitree_interface.create_robot(...)
read_low_state()
create_zero_command()
write_low_command(cmd)
```

Đây là khác với bản C++ direct publisher, vốn tự tạo `LowCmd_`, tự tính CRC và tự publish DDS topic.

Mục tiêu hiện tại:

```text
Raw LeRobot dataset
  -> Python replay
  -> Holosoma-style unitree_interface binding
  -> write_low_command(q_target, dq_target, tau_ff, kp, kd)
  -> 29 khớp body G1
```

Inspire hand vẫn dùng bridge Python riêng, vì Holosoma binding ở đây chỉ xử lý phần body Unitree.

## 0. Nguyên Tắc An Toàn

Full-body replay nguy hiểm hơn arm-only rất nhiều.

Chỉ chạy thật khi:

- Robot được treo/đỡ an toàn, hoặc có người giữ emergency stop.
- Đã dry-run CSV trước.
- Đã test từng phần nhỏ trước, ví dụ chỉ cổ chân hoặc chỉ tay.
- Không thêm `--release-motion-mode` một cách máy móc nếu chưa hiểu mode robot đang ở đâu.

Không có `--send-actions` thì C++ chỉ dry-run, không publish `rt/lowcmd`.

Muốn gửi lệnh thật bắt buộc phải có cả:

```text
--send-actions
--control-confirmation=SEND_FULL_BODY_G1_WBT
```

## 1. File Chính

Replay theo kiểu Holosoma:

```text
unitree_lerobot/eval_robot/wbt_holosoma_unitree_replay.py
```

Replay Python direct DDS cũ:

```text
unitree_lerobot/eval_robot/wbt_full_body_replay.py
```

Exporter Python:

```text
unitree_lerobot/eval_robot/export_wbt_full_body_csv.py
```

C++ replay:

```text
unitree_lerobot/eval_robot/cpp/g1_wbt_body_replay.cpp
```

Init Inspire hands theo pose đầu dataset:

```text
unitree_lerobot/eval_robot/initialize_wbt_inspire_hands.py
```

CMake:

```text
unitree_lerobot/eval_robot/cpp/CMakeLists.txt
```

Binary sau khi build:

```text
build/wbt_cpp_replay/g1_wbt_body_replay
```

Dataset raw mặc định:

```text
/home/jkl0909/.cache/huggingface/lerobot/unitreerobotics/G1_WBT_Inspire_Pick_Up_Drinks_raw3tmp
```

## 1A. Cài Binding Giống Holosoma

Nếu chạy script Holosoma-style mà gặp:

```text
unitree_interface binding is not installed
```

thì environment hiện tại chưa có wheel binding C++ của Holosoma/Amazon FAR.

Cài trong env đang điều khiển robot:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python -m pip install \
  "unitree_sdk2 @ https://github.com/amazon-far/unitree_sdk2/releases/download/0.1.3/unitree_sdk2-0.1.3-cp310-cp310-linux_x86_64.whl"
```

Kiểm tra:

```bash
python - <<'PY'
import unitree_interface
print("unitree_interface OK:", unitree_interface)
print("has create_robot:", hasattr(unitree_interface, "create_robot"))
PY
```

Nếu Python không phải 3.10 thì đổi wheel theo đúng tag `cp38`, `cp311`, hoặc `cp312`.

## 1B. Dry-Run Holosoma-Style

Không gửi lệnh robot:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python unitree_lerobot/eval_robot/wbt_holosoma_unitree_replay.py \
  --episode=0 \
  --episode-count=1 \
  --max-steps=30 \
  --frequency=30 \
  --preview-only
```

## 1C. Init Chỉ 2 Cánh Tay Bằng Holosoma-Style Binding

Lệnh này chỉ đưa 14 khớp hai cánh tay về pose đầu dataset rồi dừng, chưa replay:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python unitree_lerobot/eval_robot/wbt_holosoma_unitree_replay.py \
  --episode=0 \
  --episode-count=1 \
  --max-steps=30 \
  --frequency=30 \
  --network-interface=enp1s0 \
  --initialize-from-dataset \
  --init-only \
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

Nếu lỗi vẫn đứng nguyên `max_error` không đổi, nghĩa là robot/mode hiện tại vẫn không nhận low-level command qua binding, chứ không còn là lỗi tự publish DDS topic.

## 1D. Replay Full-Body Bằng Holosoma-Style Binding

Chỉ chạy khi robot được treo/đỡ an toàn:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python unitree_lerobot/eval_robot/wbt_holosoma_unitree_replay.py \
  --episode=0 \
  --episode-count=1 \
  --max-steps=120 \
  --frequency=30 \
  --network-interface=enp1s0 \
  --initialize-from-dataset \
  --initialization-speed-rad-s=0.05 \
  --initialization-max-error-rad=0.10 \
  --initialization-timeout-s=180 \
  --max-body-delta-rad=0.005 \
  --low-body-kp-scale=0.25 \
  --arm-kp-scale=0.8 \
  --send-actions \
  --control-confirmation=SEND_FULL_BODY_G1_WBT
```

Sau init, script sẽ hỏi:

```text
Initial pose stage done. Enter 's' to start Holosoma-style full-body replay, anything else to stop:
```

Chỉ nhập `s` khi pose init ổn.

## 2. Build C++

Chạy:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot

cmake -S unitree_lerobot/eval_robot/cpp \
  -B build/wbt_cpp_replay \
  -DCMAKE_PREFIX_PATH=/usr/local

cmake --build build/wbt_cpp_replay -j"$(nproc)"
```

Kiểm tra binary:

```bash
./build/wbt_cpp_replay/g1_wbt_body_replay --help
```

Nếu build OK sẽ có:

```text
build/wbt_cpp_replay/g1_wbt_body_replay
```

## 3. Export Dataset Sang CSV

Export 30 step đầu của episode 0:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python unitree_lerobot/eval_robot/export_wbt_full_body_csv.py \
  --episode=0 \
  --episode-count=1 \
  --max-steps=30 \
  --output=wbt_cpp_replay_inputs/episode0_30.csv
```

Export 3 episode đầu, mỗi episode tối đa 300 step:

```bash
python unitree_lerobot/eval_robot/export_wbt_full_body_csv.py \
  --episode=0 \
  --episode-count=3 \
  --max-steps=300 \
  --output=wbt_cpp_replay_inputs/episode0_2_300each.csv
```

Chỉ preview dataset, không ghi CSV:

```bash
python unitree_lerobot/eval_robot/export_wbt_full_body_csv.py \
  --preview-only \
  --episode=0 \
  --episode-count=1 \
  --max-steps=30
```

CSV output có các cột chính:

```text
episode, action_step, dataset_index, frame_index, q0..q28, hand0..hand11
```

C++ hiện chỉ dùng `q0..q28`.

## 4. Dry-Run C++

Dry-run không gửi lệnh robot:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot

./build/wbt_cpp_replay/g1_wbt_body_replay \
  --input-csv=wbt_cpp_replay_inputs/episode0_30.csv \
  --frequency=30 \
  --print-every=10 \
  --log-csv=/tmp/wbt_cpp_replay_log.csv
```

Output mong đợi:

```text
Loaded CSV: ... rows=30 ...
Starting C++ full-body CSV playback: rows=30 dry_run=true
action_step=10/30 ...
action_step=20/30 ...
action_step=30/30 ...
```

## 5. Test Robot Thật Theo Mức An Toàn

Interface robot đang dùng:

```text
enp1s0
```

## 5A. Quy Trình Đầy Đủ Trước Khi Replay

Mục tiêu của phần này:

```text
1. Bật bridge 2 tay Inspire.
2. Test đọc state và đóng/mở 2 tay.
3. Export dataset episode cần replay sang CSV.
4. Đưa 2 cánh tay về pose đầu dataset bằng C++.
5. Đưa 2 bàn tay Inspire về pose đầu dataset bằng Python.
6. Sau đó mới chạy replay dataset.
```

### Terminal 1: Bridge Tay Trái

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

### Terminal 2: Bridge Tay Phải

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

Bridge phải hiện log dạng:

```text
left bridge: 20.xx Hz, angle_act=[...]
right bridge: 20.xx Hz, angle_act=[...]
```

### Terminal 3: Read-Only Test 2 Tay

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=left

python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=right
```

### Terminal 3: Đóng 2 Tay

```bash
python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=left \
  --preset=close \
  --force=500 \
  --speed=300 \
  --send-command \
  --control-confirmation=SEND_TEST_INSPIRE_HAND

python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=right \
  --preset=close \
  --force=500 \
  --speed=300 \
  --send-command \
  --control-confirmation=SEND_TEST_INSPIRE_HAND
```

### Terminal 3: Mở 2 Tay

```bash
python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=left \
  --preset=open \
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

Nếu một tay đã sẵn ở đúng preset nên movement quá nhỏ và script báo lỗi threshold, có thể thêm:

```text
--movement-threshold=0
```

### Terminal 3: Export CSV Cho C++ Replay

Ví dụ export 30 step đầu episode 0:

```bash
python unitree_lerobot/eval_robot/export_wbt_full_body_csv.py \
  --episode=0 \
  --episode-count=1 \
  --max-steps=30 \
  --output=wbt_cpp_replay_inputs/episode0_30.csv
```

### Terminal 3: Đưa 2 Cánh Tay Về Pose Đầu Dataset Bằng C++

Lệnh này chỉ init joints `15..28`, tức 14 khớp hai cánh tay, rồi thoát luôn. Không replay.

Quan trọng: dùng `--arm-sdk` để publish vào `rt/arm_sdk`, giống pipeline toasted bread đã chạy được. Nếu dùng `rt/lowcmd` trong khi `G1 MotionSwitcher` vẫn báo `name=ai`, robot có thể không cử động và `max_error` đứng yên.

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

Nếu muốn tay lên nhanh hơn một chút sau khi đã test ổn, có thể tăng:

```text
--initialization-speed-rad-s=0.08
```

Không nên tăng vội quá cao.

### Terminal 3: Đưa 2 Bàn Tay Inspire Về Pose Đầu Dataset Bằng Python

Lệnh này đọc `action.hand_cmd[0:12]` của episode 0, scale sang thang `0..1000`, rồi publish dần tới:

```text
rt/inspire_hand/ctrl/l
rt/inspire_hand/ctrl/r
```

```bash
python unitree_lerobot/eval_robot/initialize_wbt_inspire_hands.py \
  --episode=0 \
  --network-interface=enp1s0 \
  --max-hand-delta=50 \
  --max-error=10 \
  --timeout-s=30 \
  --force=500 \
  --speed=300 \
  --send-command \
  --control-confirmation=SEND_WBT_INITIAL_INSPIRE_HANDS
```

Nếu tay trái vẫn có joint báo `status=7` nhưng vẫn muốn tiếp tục có chủ đích:

```bash
python unitree_lerobot/eval_robot/initialize_wbt_inspire_hands.py \
  --episode=0 \
  --network-interface=enp1s0 \
  --max-hand-delta=50 \
  --max-error=10 \
  --timeout-s=30 \
  --force=500 \
  --speed=300 \
  --ignore-inspire-status \
  --send-command \
  --control-confirmation=SEND_WBT_INITIAL_INSPIRE_HANDS
```

Nếu chỉ muốn init tay phải:

```bash
python unitree_lerobot/eval_robot/initialize_wbt_inspire_hands.py \
  --episode=0 \
  --network-interface=enp1s0 \
  --disable-left-hand \
  --max-hand-delta=50 \
  --force=500 \
  --speed=300 \
  --send-command \
  --control-confirmation=SEND_WBT_INITIAL_INSPIRE_HANDS
```

### Terminal 3: Replay Body Dataset Bằng C++

Sau khi cánh tay và bàn tay đã ở pose đầu, chạy replay body C++.

Lưu ý: binary C++ hiện tại replay **29 khớp body**, chưa replay continuous hand command.

```bash
./build/wbt_cpp_replay/g1_wbt_body_replay \
  --input-csv=wbt_cpp_replay_inputs/episode0_30.csv \
  --network-interface=enp1s0 \
  --frequency=30 \
  --max-body-delta-rad=0.005 \
  --low-body-kp-scale=0.25 \
  --arm-kp-scale=0.8 \
  --send-actions \
  --control-confirmation=SEND_FULL_BODY_G1_WBT
```

Khi hiện:

```text
Initial pose stage done. Enter 's' to start C++ full-body replay, anything else to stop:
```

Chỉ bấm:

```text
s
```

nếu robot đang ổn định.

### 5.1. Test Chỉ Cổ Chân

Đây là lệnh nên chạy thật đầu tiên vì chỉ init các khớp:

```text
4  = left_ankle_pitch
5  = left_ankle_roll
10 = right_ankle_pitch
11 = right_ankle_roll
```

Lệnh:

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

Sau init sẽ hiện:

```text
Initial pose stage done. Enter 's' to start C++ full-body replay, anything else to stop:
```

Nếu chỉ muốn test init, không bấm `s`. Nhập bất kỳ ký tự khác để dừng.

### 5.2. Test Chỉ Hai Tay

Dùng khi muốn kiểm tra phần C++ gửi lệnh tay trước, ít nguy hiểm hơn chân:

```bash
./build/wbt_cpp_replay/g1_wbt_body_replay \
  --input-csv=wbt_cpp_replay_inputs/episode0_30.csv \
  --network-interface=enp1s0 \
  --frequency=30 \
  --initialize-from-first-row \
  --initialization-speed-rad-s=0.05 \
  --initialization-max-error-rad=0.10 \
  --initialization-timeout-s=120 \
  --init-joints=15,16,17,18,19,20,21,22,23,24,25,26,27,28 \
  --max-body-delta-rad=0.005 \
  --low-body-kp-scale=0.25 \
  --arm-kp-scale=0.8 \
  --send-actions \
  --control-confirmation=SEND_FULL_BODY_G1_WBT
```

### 5.3. Init Tuần Tự 5 Nhóm

Thứ tự:

```text
left_leg -> right_leg -> waist -> left_arm -> right_arm
```

Lệnh:

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

### 5.4. Replay Ngắn 30 Step

Nếu init ổn, bấm:

```text
s
```

Robot sẽ replay tối đa số rows trong CSV, ví dụ `episode0_30.csv` là 30 action.

## 6. Chạy Episode Dài Hơn

Export 120 step:

```bash
python unitree_lerobot/eval_robot/export_wbt_full_body_csv.py \
  --episode=0 \
  --episode-count=1 \
  --max-steps=120 \
  --output=wbt_cpp_replay_inputs/episode0_120.csv
```

Replay:

```bash
./build/wbt_cpp_replay/g1_wbt_body_replay \
  --input-csv=wbt_cpp_replay_inputs/episode0_120.csv \
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

## 7. Các Tham Số Quan Trọng

```text
--input-csv
```

CSV đã export từ raw dataset.

```text
--frequency=30
```

Tốc độ replay. Dataset WBT là 30 FPS, nên giữ 30 trước.

```text
--initialize-from-first-row
```

Đưa robot về pose đầu tiên trong CSV trước khi replay.

```text
--init-joints=...
```

Chỉ init một số khớp, các khớp khác giữ passive damping.

```text
--init-sequential
```

Init từng nhóm khớp theo thứ tự, tránh đẩy cả 29 khớp cùng lúc.

```text
--initialization-speed-rad-s=0.05
```

Tốc độ đưa khớp về pose ban đầu. Bắt đầu từ `0.05`, chỉ tăng khi thật sự cần.

```text
--initialization-max-error-rad=0.10
```

Sai số cho phép để coi như đã tới pose ban đầu.

```text
--max-body-delta-rad=0.005
```

Giới hạn mỗi action step. Ở 30 Hz, `0.005 rad/step` tương đương khoảng `0.15 rad/s`.

```text
--low-body-kp-scale=0.25
```

Scale Kp cho chân + eo, tức joints `0..14`.

```text
--arm-kp-scale=0.8
```

Scale Kp cho hai tay, tức joints `15..28`.

```text
--release-motion-mode
```

Gọi `MotionSwitcher.ReleaseMode()` trước khi low-level control.

Chỉ dùng khi đã chủ động muốn chuyển sang low-level full-body. Nếu chưa chắc robot đang ở mode nào thì không thêm flag này.

```text
--arm-sdk
```

Publish sang `rt/arm_sdk` thay vì `rt/lowcmd`. Chỉ dùng cho eo/tay, tức joints `12..28`.

Đây là lựa chọn phù hợp khi chỉ muốn đưa cánh tay về pose đầu dataset trong lúc robot vẫn ở motion mode `ai` để giữ cân bằng.

## 8. Mapping q0..q28

CSV `q0..q28` tương ứng 29 motor G1:

```text
q0  left_hip_pitch
q1  left_hip_roll
q2  left_hip_yaw
q3  left_knee
q4  left_ankle_pitch
q5  left_ankle_roll
q6  right_hip_pitch
q7  right_hip_roll
q8  right_hip_yaw
q9  right_knee
q10 right_ankle_pitch
q11 right_ankle_roll
q12 waist_yaw
q13 waist_roll
q14 waist_pitch
q15 left_shoulder_pitch
q16 left_shoulder_roll
q17 left_shoulder_yaw
q18 left_elbow
q19 left_wrist_roll
q20 left_wrist_pitch
q21 left_wrist_yaw
q22 right_shoulder_pitch
q23 right_shoulder_roll
q24 right_shoulder_yaw
q25 right_elbow
q26 right_wrist_roll
q27 right_wrist_pitch
q28 right_wrist_yaw
```

Trong raw dataset:

```text
action.robot_q_desired[0:7]   root/base pose, C++ không replay trực tiếp
action.robot_q_desired[7:36]  29 motor joints, export thành q0..q28
action.hand_cmd[0:12]         Inspire hand, hiện chỉ export để dành
```

## 9. Debug

Nếu C++ không build được:

```bash
ls /usr/local/lib/libunitree_sdk2.a
ls /usr/local/lib/cmake/unitree_sdk2
```

Nếu không đọc được robot:

```bash
ping 192.168.123.164
```

Kiểm tra interface:

```bash
ip addr show enp1s0
```

Nếu replay không gửi lệnh:

- Kiểm tra có `--send-actions`.
- Kiểm tra đúng confirmation.
- Kiểm tra binary không đang chạy dry-run.

Nếu robot không chuyển động:

- Kiểm tra `G1 MotionSwitcher` log.
- Kiểm tra robot có đang chấp nhận `rt/lowcmd`.
- Thử `--release-motion-mode` chỉ khi đã hiểu rủi ro.
- Bắt đầu lại bằng `--init-joints=15,16,17,18,19,20,21,22,23,24,25,26,27,28` hoặc `--init-joints=4,5,10,11`.

## 10. Ghi Chú Git

Không commit các output tạm:

```text
build/
wbt_cpp_replay_inputs/
```

Các file source cần commit nếu muốn lưu flow C++:

```text
Useme-C.md
unitree_lerobot/eval_robot/export_wbt_full_body_csv.py
unitree_lerobot/eval_robot/initialize_wbt_inspire_hands.py
unitree_lerobot/eval_robot/cpp/CMakeLists.txt
unitree_lerobot/eval_robot/cpp/g1_wbt_body_replay.cpp
unitree_lerobot/eval_robot/WBT_FULL_BODY_REPLAY.md
```
