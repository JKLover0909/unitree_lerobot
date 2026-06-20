# Unitree LeRobot Deploy Notes

File này ghi lại các lệnh đã dùng để deploy robot thật trong repo này.

Danh sách dataset G1 + Inspire có sẵn trên Hugging Face được ghi riêng ở:

```text
G1_INSPIRE_DATASETS.md
```

Nhánh hiện tại:

```bash
son-deploy-pickupdrink-inspire
```

## 0. Chuẩn Bị Chung

Activate môi trường đúng:

```bash
conda activate unitree_lerobot
cd /home/jkl0909/code/Son/unitree_lerobot
```

Robot G1 cần ở Regular motion-control mode để nhận lệnh tay qua `rt/arm_sdk`.
Trên remote R3 đã dùng chuỗi:

```text
L2 + B
L2 + UP
R1 + X
```

Không dùng:

```text
R2 + A   Running mode
L2 + R2  Debug/development mode
```

Interface robot đang dùng:

```text
enp1s0
```

IP Inspire hand:

```text
left  = 192.168.123.210
right = 192.168.123.211
```

Giữ sẵn nút dừng khẩn cấp khi dùng `--send-actions`.

## 1. Task Pick Up Drinks Với G1 + Inspire Hand

Dataset local:

```text
/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Pick_Up_Drinks_flat26
```

Checkpoint:

```text
/home/jkl0909/code/Son/unitree_lerobot/unitree_lerobot/lerobot/outputs/g1_wbt_inspire_pick_up_drinks_act_bs16/checkpoints/last/pretrained_model
```

Action/state format đang deploy:

```text
26D = 14 G1 arm joints + 6 left Inspire + 6 right Inspire
```

Mapping:

```text
action[0:14]   -> G1 two arms
action[14:20]  -> left Inspire hand
action[20:26]  -> right Inspire hand
```

Dataset hand action dùng scale `0..1`; Inspire SDK command dùng `0..1000`.
Script `wbt_inspire_hybrid_infer.py` đã scale bằng:

```text
--hand-state-scale=1000
--hand-action-scale=1000
```

## 2. Bật Bridge Cho Inspire Hand

Inspire hand không tự publish DDS state. Cần chạy bridge Modbus TCP sang DDS.

Terminal 1, tay trái:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot

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

python unitree_lerobot/eval_robot/inspire_hand_ftp_driver.py \
  --network-interface=enp1s0 \
  --hand=right \
  --ip=192.168.123.211 \
  --frequency=20 \
  --no-touch
```

Bridge sẽ publish:

```text
rt/inspire_hand/state/l
rt/inspire_hand/state/r
```

và subscribe:

```text
rt/inspire_hand/ctrl/l
rt/inspire_hand/ctrl/r
```

## 3. Test Inspire Hand

Read-only tay phải:

```bash
python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=right
```

Test một joint tay phải:

```bash
python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=right \
  --joint=3 \
  --delta=50 \
  --force=200 \
  --speed=200 \
  --send-command \
  --control-confirmation=SEND_TEST_INSPIRE_HAND
```

Quy ước preset đã kiểm trên robot:

```text
open  = [800, 800, 800, 800, 500, 0]
close = [0, 0, 0, 0, 0, 1000]
```

Đóng tay phải:

```bash
python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=right \
  --preset=close \
  --force=500 \
  --speed=300 \
  --send-command \
  --control-confirmation=SEND_TEST_INSPIRE_HAND
```

Mở tay phải:

```bash
python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=right \
  --preset=open \
  --force=500 \
  --speed=300 \
  --send-command \
  --control-confirmation=SEND_TEST_INSPIRE_HAND
```

Đóng tay trái:

```bash
python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=left \
  --preset=close \
  --force=500 \
  --speed=300 \
  --send-command \
  --control-confirmation=SEND_TEST_INSPIRE_HAND
```

Mở tay trái:

```bash
python unitree_lerobot/eval_robot/test_inspire_hand_command.py \
  --network-interface=enp1s0 \
  --hand=left \
  --preset=open \
  --force=500 \
  --speed=300 \
  --send-command \
  --control-confirmation=SEND_TEST_INSPIRE_HAND
```

Ghi chú phần cứng hiện tại:

- Tay phải đã test OK.
- Tay trái có vấn đề ở joint ngón út/joint 0, `angle_act[0]` kẹt khoảng `337`.
- Có lúc tay trái báo `status=7`; hiểu là actuator/electric-cylinder fault stop.
- Lệnh chuẩn hiện bật cả hai tay. Theo dõi tay trái sát; `--ignore-inspire-status` chỉ bỏ chặn phần mềm, không sửa lỗi phần cứng.

## 4. Dry Run Pick Up Drinks

Dry run không gửi lệnh thật vì không có `--send-actions`.

```bash
cd /home/jkl0909/code/Son/unitree_lerobot

python unitree_lerobot/eval_robot/wbt_inspire_hybrid_infer.py \
  --policy-path=/home/jkl0909/code/Son/unitree_lerobot/unitree_lerobot/lerobot/outputs/g1_wbt_inspire_pick_up_drinks_act_bs16/checkpoints/last/pretrained_model \
  --repo-id=local/G1_WBT_Inspire_Pick_Up_Drinks_flat26 \
  --root=/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Pick_Up_Drinks_flat26 \
  --episode=0 \
  --max-policy-steps=30 \
  --actions-per-inference=100 \
  --prefetch-threshold=0.9 \
  --frequency=30 \
  --network-interface=enp1s0 \
  --motion \
  --ignore-inspire-status
```

Kỳ vọng:

```text
dry_run=True
```

## 5. Replay Dataset Action Trên Robot Thật

Đây là chế độ đã dùng để kiểm tra robot làm theo dữ liệu gốc.
Có `--use-dataset-action`, nghĩa là không dùng policy sinh action mà phát lại action trong dataset.

Lệnh khuyến nghị hiện tại:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot

python unitree_lerobot/eval_robot/wbt_inspire_hybrid_infer.py \
  --policy-path=/home/jkl0909/code/Son/unitree_lerobot/unitree_lerobot/lerobot/outputs/g1_wbt_inspire_pick_up_drinks_act_bs16/checkpoints/last/pretrained_model \
  --repo-id=local/G1_WBT_Inspire_Pick_Up_Drinks_flat26 \
  --root=/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Pick_Up_Drinks_flat26 \
  --episode=0 \
  --max-policy-steps=600 \
  --frequency=30 \
  --network-interface=enp1s0 \
  --motion \
  --ignore-inspire-status \
  --use-dataset-action \
  --initialize-from-dataset \
  --initialize-arms-only \
  --initialization-speed-rad-s=0.20 \
  --initialization-max-tracking-error-rad=0.08 \
  --initialization-timeout-s=180 \
  --max-arm-delta-rad=0.04 \
  --max-hand-delta=50 \
  --hand-force=500 \
  --hand-speed=300 \
  --send-actions \
  --control-confirmation=SEND_TO_REAL_G1_INSPIRE
```

Flow đúng:

```text
Loading initial dataset state at index 0 without video decode...
Initializing to dataset pose (arms only): ...
Initializing dataset pose: elapsed=... arm_error=... moved=...
Dataset initial arm pose reached.
Initial pose reached. Enter 's' to start, or 'q' to stop:
```

Nhập:

```text
s
```

Lưu ý: nếu có `--use-dataset-action` thì chương trình đang replay dataset action, không phải policy infer.

Trong lúc chạy, script in tiến độ mỗi 50 action:

```text
Starting dataset action playback: episode=2 dataset_index=1372..2144 actions=773 (...)
action_step=50/773 dataset_index=1421 inference=0.0ms source=dataset dry_run=False
action_step=100/773 dataset_index=1471 inference=0.0ms source=dataset dry_run=False
...
action_step=773/773 dataset_index=2144 inference=0.0ms source=dataset dry_run=False
```

`action_step` là số thứ tự tương đối trong episode. `dataset_index` là index tuyệt đối trong toàn dataset.

Ví dụ episode 2:

```text
action_step=1   -> dataset_index=1372
action_step=50  -> dataset_index=1421
action_step=773 -> dataset_index=2144
```

## 6. Chạy Policy Thật

Nếu bỏ `--use-dataset-action`, script sẽ dùng checkpoint để sinh action từ:

```text
dataset images + real G1 arm state + real Inspire hand state
```

Policy mode dùng async prefetch mặc định. Chunk đầu tiên vẫn phải chờ khoảng 1 giây; các chunk sau được infer trong thread nền khi robot đang thực hiện queue hiện tại.

Lệnh policy thật:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot

python unitree_lerobot/eval_robot/wbt_inspire_hybrid_infer.py \
  --policy-path=/home/jkl0909/code/Son/unitree_lerobot/unitree_lerobot/lerobot/outputs/g1_wbt_inspire_pick_up_drinks_act_bs16/checkpoints/last/pretrained_model \
  --repo-id=local/G1_WBT_Inspire_Pick_Up_Drinks_flat26 \
  --root=/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Pick_Up_Drinks_flat26 \
  --episode=0 \
  --max-policy-steps=120 \
  --actions-per-inference=100 \
  --prefetch-threshold=0.9 \
  --frequency=30 \
  --network-interface=enp1s0 \
  --motion \
  --ignore-inspire-status \
  --initialize-from-dataset \
  --initialize-arms-only \
  --initialization-speed-rad-s=0.20 \
  --initialization-max-tracking-error-rad=0.08 \
  --initialization-timeout-s=180 \
  --max-arm-delta-rad=0.01 \
  --max-hand-delta=20 \
  --hand-force=300 \
  --hand-speed=200 \
  --send-actions \
  --control-confirmation=SEND_TO_REAL_G1_INSPIRE
```

## 7. Chạy Episode Khác

Dataset `G1_WBT_Inspire_Pick_Up_Drinks_flat26` có 300 episode, index hợp lệ:

```text
0..299
```

Đổi:

```bash
--episode=5
```

Nếu muốn chạy hết episode, bỏ `--max-policy-steps` hoặc đặt lớn hơn số frame của episode.
Không nên loop nhiều episode liên tục trên robot thật khi chưa kiểm từng initial pose.

Một số episode đầu:

```text
episode 0: dataset_index 0    -> 655,  656 action, ~21.87s
episode 1: dataset_index 656  -> 1371, 716 action, ~23.87s
episode 2: dataset_index 1372 -> 2144, 773 action, ~25.77s
episode 3: dataset_index 2145 -> 2918, 774 action, ~25.80s
episode 4: dataset_index 2919 -> 3742, 824 action, ~27.47s
```

Episode không chồng lấn. `dataset_to_index` là exclusive, nên frame cuối thật là `dataset_to_index - 1`.

## 8. Chạy Nhiều Episode Liên Tiếp

Script hỗ trợ:

```text
--episode-count=N
```

Ví dụ chạy nối tiếp episode `0, 1, 2`:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot

python unitree_lerobot/eval_robot/wbt_inspire_hybrid_infer.py \
  --policy-path=/home/jkl0909/code/Son/unitree_lerobot/unitree_lerobot/lerobot/outputs/g1_wbt_inspire_pick_up_drinks_act_bs16/checkpoints/last/pretrained_model \
  --repo-id=local/G1_WBT_Inspire_Pick_Up_Drinks_flat26 \
  --root=/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Pick_Up_Drinks_flat26 \
  --episode=0 \
  --episode-count=3 \
  --max-policy-steps=1200 \
  --frequency=30 \
  --network-interface=enp1s0 \
  --motion \
  --ignore-inspire-status \
  --use-dataset-action \
  --initialize-from-dataset \
  --initialize-arms-only \
  --initialization-speed-rad-s=0.20 \
  --initialization-max-tracking-error-rad=0.08 \
  --initialization-timeout-s=180 \
  --max-arm-delta-rad=0.04 \
  --max-hand-delta=50 \
  --hand-force=500 \
  --hand-speed=300 \
  --send-actions \
  --control-confirmation=SEND_TO_REAL_G1_INSPIRE
```

Flow:

```text
===== Episode 0 (1/3) =====
... init pose ...
Initial pose reached. Enter 's' to start, or 'q' to stop:
... replay episode 0 ...
===== Episode 1 (2/3) =====
... init pose ...
Initial pose reached. Enter 's' to start, or 'q' to stop:
... replay episode 1 ...
```

DDS, arm controller và Inspire readers/publishers chỉ được init một lần ở đầu process. Các episode sau reuse connection này, tránh lỗi:

```text
[ChannelFactory] create domain error
Exception: channel factory init error.
```

## 9. Các Param Quan Trọng

```text
--motion
```

Gửi lệnh cánh tay qua `rt/arm_sdk`.

```text
--send-actions
```

Bật gửi command thật. Không có flag này thì dry run.

```text
--control-confirmation=SEND_TO_REAL_G1_INSPIRE
```

Xác nhận an toàn bắt buộc khi gửi lệnh thật.

```text
--use-dataset-action
```

Replay action từ dataset, không dùng policy infer.

```text
--initialize-from-dataset
```

Đưa robot về pose đầu episode trước khi chạy.

```text
--initialize-arms-only
```

Chỉ initialize 14 khớp cánh tay, bỏ qua bàn tay/ngón tay.

```text
--episode-count=3
```

Chạy nhiều episode liên tiếp từ `--episode`. Ví dụ `--episode=2 --episode-count=3` sẽ chạy episode `2, 3, 4`.

```text
--actions-per-inference=100
```

Số action tối đa lấy từ mỗi ACT chunk. Checkpoint hiện tại có `chunk_size=100` nên không được đặt lớn hơn 100.

```text
--prefetch-threshold=0.9
```

Bắt đầu infer nền khi queue còn tối đa 90% của `actions-per-inference`. Giá trị này ưu tiên khởi động prefetch sớm trên CPU laptop.

```text
--synchronous-inference
```

Tắt async để debug/so sánh. Không dùng flag này khi muốn tránh đứng ở ranh giới chunk.

```text
--initialization-speed-rad-s=0.20
```

Tốc độ target khi đưa cánh tay về pose đầu, đơn vị rad/s.
Nếu arm_error giảm đều nhưng chậm, có thể thử `0.25`.
Nếu `moved=0.000`, tăng speed không giải quyết được.

```text
--initialization-max-tracking-error-rad=0.08
```

Giới hạn target init không bỏ xa trạng thái thật quá nhiều.

```text
--max-arm-delta-rad=0.04
```

Giới hạn mỗi step biểu diễn của cánh tay. Ở 30 Hz tương đương khoảng `1.2 rad/s`.

Trước đây `0.02` làm robot bám dataset chậm, tay có thể không giơ cao/kịp như video. Nếu `0.04` vẫn thấp nhưng chuyển động ổn, thử `0.05`.

```text
--max-hand-delta=50
```

Giới hạn mỗi step bàn tay Inspire đổi tối đa 50 đơn vị trên thang `0..1000`.

```text
--max-policy-steps=1200
```

Trong replay dataset, tham số này nghĩa là số action tối đa phát trong episode hiện tại. Số action thực tế là:

```text
min(max-policy-steps, số action còn lại của episode)
```

Nếu episode chỉ có 716 action, đặt `--max-policy-steps=1200` vẫn chỉ chạy 716 action.

## 10. Lỗi Thường Gặp

Nếu init in:

```text
arm_error=1.174 rad moved=0.000 rad
```

thì cánh tay không tracking lệnh. Đây không phải lỗi tốc độ. Kiểm tra robot đã vào Regular motion-control mode chưa.

Nếu có:

```text
Commands were published to rt/arm_sdk but no arm motion was detected
```

thì `rt/arm_sdk` đang publish nhưng robot không nhận/không thực thi. Đưa robot lại đúng mode:

```text
L2 + B
L2 + UP
R1 + X
```

Nếu Inspire state timeout:

```text
No Inspire state received on rt/inspire_hand/state/...
```

thì bridge tay chưa chạy hoặc sai IP/interface.

Nếu tay trái báo `status=7`, dùng:

```text
--ignore-inspire-status
--disable-left-hand
```

để tiếp tục test cánh tay và tay phải.

Nếu chạy nhiều episode và gặp:

```text
[ChannelFactory] create domain error
Exception: channel factory init error.
```

nghĩa là code đang cố `ChannelFactoryInitialize` nhiều lần trong cùng process. Bản hiện tại đã sửa bằng cách init DDS một lần rồi reuse cho các episode sau.

## 11. Legacy: ToastedBread Với G1 + Dex3

Phần này là pipeline cũ của task ToastedBread/Dex3.

Ý tưởng:

- Dùng video và Dex3 state từ dataset Kaggle/LeRobot.
- Dùng 14 khớp tay thật của G1 làm `observation.state[:14]`.
- Policy ACT xuất action Dex3 đầy đủ, nhưng robot chỉ nhận phần `14` khớp hai cánh tay.
- Có async prefetch để tránh delay CPU ở ranh giới chunk.

Dry run:

```bash
python unitree_lerobot/eval_robot/hybrid_arm_infer.py \
  --policy-path=/home/jkl0909/code/Son/unitree_lerobot/unitree_lerobot/lerobot/outputs/g1_dex3_toastedbread_act/checkpoints/last/pretrained_model \
  --episode=0 \
  --max-policy-steps=120 \
  --actions-per-inference=75 \
  --prefetch-threshold=0.5 \
  --frequency=30 \
  --max-action-delta-rad=0.02 \
  --network-interface=enp1s0
```

Real robot test 120 step:

```bash
python unitree_lerobot/eval_robot/hybrid_arm_infer.py \
  --policy-path=/home/jkl0909/code/Son/unitree_lerobot/unitree_lerobot/lerobot/outputs/g1_dex3_toastedbread_act/checkpoints/last/pretrained_model \
  --episode=0 \
  --max-policy-steps=120 \
  --actions-per-inference=75 \
  --prefetch-threshold=0.5 \
  --frequency=30 \
  --initialization-speed-rad-s=0.05 \
  --initialization-max-tracking-error-rad=0.05 \
  --initialization-timeout-s=120 \
  --max-action-delta-rad=0.02 \
  --network-interface=enp1s0 \
  --motion \
  --initialize-from-dataset \
  --send-actions \
  --control-confirmation=SEND_TO_REAL_G1
```

Khi hiện:

```text
Dataset initial arm pose reached. Policy has not started yet.
Enter 's' to start policy control, or anything else to stop while holding pose:
```

chỉ nhập `s` nếu tư thế tay ổn định và an toàn.

## 12. Test Camera G1

Repo hiện có code nền để đọc camera, nhưng pipeline `wbt_inspire_hybrid_infer.py` hiện vẫn dùng video từ dataset. Trước khi nối camera thật vào policy, test camera riêng trước.

### 12.1. Test trực tiếp camera/front video bằng Unitree SDK

Lệnh này kiểm tra robot có trả ảnh camera qua SDK không. Ảnh sẽ được lưu vào `camera_test_results/...`.

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python unitree_lerobot/eval_robot/test_g1_head_camera.py \
  --source=unitree-video \
  --network-interface=enp1s0 \
  --frames=5
```

Nếu máy có màn hình và muốn xem live frame:

```bash
python unitree_lerobot/eval_robot/test_g1_head_camera.py \
  --source=unitree-video \
  --network-interface=enp1s0 \
  --frames=100 \
  --display
```

### 12.2. Test camera qua ImageServer/ImageClient

Chỉ dùng lệnh này sau khi đã chạy image server ở máy/cụm camera host. Mặc định client hỏi config ở `192.168.123.164:60000`.

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python unitree_lerobot/eval_robot/test_g1_head_camera.py \
  --source=image-client \
  --host=192.168.123.164 \
  --request-port=60000 \
  --frames=5
```

Kết luận hiện tại:

- Đã có code đọc camera trực tiếp kiểu Unitree SDK trong `inspire_hand_ws/unitree_sdk2_python/example/front_camera/`.
- Đã có lớp `ImageServer/ImageClient` để stream head/wrist camera qua ZMQ/WebRTC.
- `wbt_inspire_hybrid_infer.py` chưa dùng camera live; nó vẫn lấy ảnh/video từ dataset rồi thay state thật của tay/cánh tay vào.
- Muốn deploy policy bằng camera thật cần thêm bước nối `ImageClient` vào observation và phải đúng key camera mà checkpoint đã train.
