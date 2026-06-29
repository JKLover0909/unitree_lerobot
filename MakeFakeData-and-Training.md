# Fake Flat26 Dataset + Training Handoff

File này ghi lại toàn bộ flow đã làm để biến một episode tự record bằng **1 camera head D435i + 14 khớp cánh tay G1** thành dataset giả dạng **LeRobot flat26** để có thể dùng lại pipeline/policy ACT cũ của task `G1_WBT_Inspire_Pick_Up_Drinks`.

Mục tiêu của nhánh training:

```text
son-train-headcam-fake-flat26
```

## 1. Bối Cảnh

Checkpoint pickup drink cũ được train theo format:

```text
input:
  observation.state[26]
  observation.images.head_stereo_left
  observation.images.head_stereo_right
  observation.images.wrist_left
  observation.images.wrist_right

output:
  action[26]
```

Trong đó:

```text
state/action[0:14]   = 14 khớp hai cánh tay G1
state/action[14:20]  = 6 khớp Inspire hand trái
state/action[20:26]  = 6 khớp Inspire hand phải
```

Nhưng episode mới record hiện chỉ có:

```text
1 camera head D435i
14 khớp cánh tay G1
timestamp
```

Không có:

```text
4 camera thật
12 khớp tay Inspire theo thời gian
action command thật
```

Vì vậy ta tạo dataset giả để khớp interface cũ.

## 2. Raw Episode Đầu Vào

Raw episode local:

```text
/home/jkl0909/code/Son/unitree_lerobot/episode_20260629_172043
```

Cấu trúc:

```text
episode_20260629_172043/
  metadata.json
  timestamps.csv
  states/
    arm14.csv
  videos/
    head.mp4
```

Thông tin đã kiểm tra:

```text
video: 848x480, 30 FPS, 877 frames
arm14 rows: 877
timestamp rows: 877
```

`arm14.csv` chứa:

```text
arm0..arm13 = q15..q28 của G1
```

Tức là 14 khớp:

```text
left shoulder pitch/roll/yaw
left elbow
left wrist roll/pitch/yaw
right shoulder pitch/roll/yaw
right elbow
right wrist roll/pitch/yaw
```

## 3. Quy Ước Fake Dataset

### 3.1. Fake 4 Camera Từ 1 Camera

Policy cũ yêu cầu 4 camera:

```text
observation.images.head_stereo_left
observation.images.head_stereo_right
observation.images.wrist_left
observation.images.wrist_right
```

Dataset mới chỉ có:

```text
videos/head.mp4
```

Nên ta resize video head từ `848x480` về `640x480`, sau đó copy cùng một video vào cả 4 key.

Kết quả:

```text
4 video streams giống hệt nhau
shape mỗi frame: [3, 480, 640]
```

### 3.2. Fake 12 Khớp Inspire Hand

Đã đọc state hiện tại của hai tay Inspire bằng bridge + read-only script.

Left:

```text
angle_act = [299, 0, 300, 207, 122, 116]
```

Right:

```text
angle_act = [299, 302, 384, 463, 102, 0]
```

Ghép đúng format policy:

```python
hand12_raw = [
    299, 0, 300, 207, 122, 116,
    299, 302, 384, 463, 102, 0,
]
```

Dataset flat26 dùng hand state/action scale `0..1`, nên lưu:

```python
hand12_scaled = [
    0.299, 0.000, 0.300, 0.207, 0.122, 0.116,
    0.299, 0.302, 0.384, 0.463, 0.102, 0.000,
]
```

12 giá trị này được giữ cố định trong toàn bộ episode.

### 3.3. Fake Action

Raw episode mới chỉ có state, không có command/action thật.

Vì vậy tạo:

```text
action[t] = state[t + k]
```

Hiện dùng:

```text
k = 1
```

Do đó frame cuối bị drop.

Raw có `877` frame, dataset fake có:

```text
876 frames
```

Format cuối:

```text
observation.state[0:14]   = arm14[t]
observation.state[14:26]  = hand12_scaled cố định

action[0:14]              = arm14[t + 1]
action[14:26]             = hand12_scaled cố định
```

## 4. Script Converter

Script đã thêm vào repo:

```text
scripts/make_fake_flat26_from_headcam_arm14.py
```

Script tạo dataset LeRobot-style gồm:

```text
data/chunk-000/file-000.parquet
meta/info.json
meta/stats.json
meta/tasks.parquet
meta/episodes/chunk-000/file-000.parquet
videos/observation.images.head_stereo_left/chunk-000/file-000.mp4
videos/observation.images.head_stereo_right/chunk-000/file-000.mp4
videos/observation.images.wrist_left/chunk-000/file-000.mp4
videos/observation.images.wrist_right/chunk-000/file-000.mp4
conversion_summary.json
```

## 5. Lệnh Tạo Dataset Fake

Chạy trên máy local có raw episode:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python scripts/make_fake_flat26_from_headcam_arm14.py \
  --episode-dir=/home/jkl0909/code/Son/unitree_lerobot/episode_20260629_172043 \
  --output-root=/home/jkl0909/.cache/huggingface/lerobot/local/G1_headcam_arm14_fake_flat26_20260629_172043 \
  --repo-id=local/G1_headcam_arm14_fake_flat26_20260629_172043 \
  --task=G1_headcam_arm14_fake_flat26 \
  --k=1 \
  --hand12-raw 299 0 300 207 122 116 299 302 384 463 102 0 \
  --overwrite
```

Dataset output:

```text
/home/jkl0909/.cache/huggingface/lerobot/local/G1_headcam_arm14_fake_flat26_20260629_172043
```

Repo id:

```text
local/G1_headcam_arm14_fake_flat26_20260629_172043
```

Summary đã sinh:

```json
{
  "repo_id": "local/G1_headcam_arm14_fake_flat26_20260629_172043",
  "frames": 876,
  "k": 1,
  "camera_note": "Same head.mp4 resized to 640x480 and duplicated into all four policy camera keys.",
  "action_note": "action[t] = state[t + k]. Last k source frames are dropped."
}
```

## 6. Verify Dataset

Kiểm tra bằng `LeRobotDataset`:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

PYTHONPATH=/home/jkl0909/code/Son/unitree_lerobot/unitree_lerobot/lerobot/src:$PYTHONPATH \
python - <<'PY'
from lerobot.datasets.lerobot_dataset import LeRobotDataset

root = "/home/jkl0909/.cache/huggingface/lerobot/local/G1_headcam_arm14_fake_flat26_20260629_172043"
ds = LeRobotDataset(
    repo_id="local/G1_headcam_arm14_fake_flat26_20260629_172043",
    root=root,
)

print("len", len(ds), "fps", ds.fps)
item = ds[0]
print("state", item["observation.state"].shape)
print("action", item["action"].shape)
for key in [
    "observation.images.head_stereo_left",
    "observation.images.head_stereo_right",
    "observation.images.wrist_left",
    "observation.images.wrist_right",
]:
    print(key, item[key].shape)
PY
```

Kết quả đã verify:

```text
len 876 fps 30
state torch.Size([26])
action torch.Size([26])
observation.images.head_stereo_left torch.Size([3, 480, 640])
observation.images.head_stereo_right torch.Size([3, 480, 640])
observation.images.wrist_left torch.Size([3, 480, 640])
observation.images.wrist_right torch.Size([3, 480, 640])
```

## 7. Copy Dataset Sang Server Training

Nhánh code đã push:

```text
son-train-headcam-fake-flat26
```

Server training có IP:

```text
100.98.27.115
```

Nếu user server là `jkl`, tạo thư mục đích:

```bash
ssh jkl@100.98.27.115 "mkdir -p /home/jkl/.cache/huggingface/lerobot/local"
```

Copy dataset:

```bash
rsync -avh --progress \
  /home/jkl0909/.cache/huggingface/lerobot/local/G1_headcam_arm14_fake_flat26_20260629_172043 \
  jkl@100.98.27.115:/home/jkl/.cache/huggingface/lerobot/local/
```

Lưu ý cú pháp đúng là:

```text
user@host:/path
```

Không phải:

```text
host@user:/path
```

## 8. Checkout Nhánh Trên Server

Trên server training:

```bash
cd /path/to/unitree_lerobot
git fetch origin
git switch son-train-headcam-fake-flat26
git pull
```

Nếu server chưa clone repo:

```bash
git clone https://github.com/JKLover0909/unitree_lerobot.git
cd unitree_lerobot
git switch son-train-headcam-fake-flat26
```

## 9. Lệnh Train Test Pipeline

Chạy thử ngắn để kiểm tra dataset/pipeline:

```bash
cd /path/to/unitree_lerobot/unitree_lerobot/lerobot
conda activate unitree_lerobot

python src/lerobot/scripts/lerobot_train.py \
  --dataset.repo_id=local/G1_headcam_arm14_fake_flat26_20260629_172043 \
  --dataset.root=/home/jkl/.cache/huggingface/lerobot/local/G1_headcam_arm14_fake_flat26_20260629_172043 \
  --policy.type=act \
  --policy.push_to_hub=false \
  --policy.input_features='{"observation.state":{"type":"STATE","shape":[26]},"observation.images.head_stereo_left":{"type":"VISUAL","shape":[3,480,640]},"observation.images.head_stereo_right":{"type":"VISUAL","shape":[3,480,640]},"observation.images.wrist_left":{"type":"VISUAL","shape":[3,480,640]},"observation.images.wrist_right":{"type":"VISUAL","shape":[3,480,640]}}' \
  --policy.output_features='{"action":{"type":"ACTION","shape":[26]}}' \
  --policy.chunk_size=100 \
  --policy.n_action_steps=100 \
  --policy.device=cuda \
  --batch_size=4 \
  --num_workers=4 \
  --steps=1000 \
  --save_freq=500 \
  --log_freq=50 \
  --eval_freq=0 \
  --output_dir=outputs/g1_headcam_arm14_fake_flat26_act_test
```

Nếu server không có GPU/CUDA, đổi:

```bash
--policy.device=cpu
```

## 10. Lệnh Fine-Tune Từ Checkpoint Pickup Drink Cũ

Checkpoint cũ local trên máy deploy:

```text
/home/jkl0909/code/Son/unitree_lerobot/unitree_lerobot/lerobot/outputs/g1_wbt_inspire_pick_up_drinks_act_bs16/checkpoints/last/pretrained_model
```

Trên server cần có checkpoint tương ứng. Nếu copy sang server, ví dụ đặt ở:

```text
/home/jkl/unitree_checkpoints/g1_wbt_inspire_pick_up_drinks_act_bs16/checkpoints/last/pretrained_model
```

Fine-tune:

```bash
cd /path/to/unitree_lerobot/unitree_lerobot/lerobot
conda activate unitree_lerobot

python src/lerobot/scripts/lerobot_train.py \
  --dataset.repo_id=local/G1_headcam_arm14_fake_flat26_20260629_172043 \
  --dataset.root=/home/jkl/.cache/huggingface/lerobot/local/G1_headcam_arm14_fake_flat26_20260629_172043 \
  --policy.type=act \
  --policy.pretrained_path=/home/jkl/unitree_checkpoints/g1_wbt_inspire_pick_up_drinks_act_bs16/checkpoints/last/pretrained_model \
  --policy.push_to_hub=false \
  --batch_size=4 \
  --num_workers=4 \
  --steps=5000 \
  --save_freq=1000 \
  --log_freq=50 \
  --eval_freq=0 \
  --output_dir=outputs/g1_headcam_arm14_fake_flat26_act_finetune
```

Nếu output dir đã tồn tại, đổi tên output hoặc xóa/chọn `--resume=true` đúng checkpoint.

## 11. Giới Hạn Và Cảnh Báo

Dataset này là fake-compatibility dataset, không phải dataset chuẩn như WBT gốc.

Các phần fake:

```text
4 camera = cùng 1 head camera nhân 4
12 hand dims = fixed pose, không có chuyển động thật
action[t] = state[t+1], không phải command thật
```

Ý nghĩa:

- Dùng được để test pipeline training ACT theo interface cũ.
- Có thể fine-tune thử policy cũ để robot học lại arm trajectory theo camera head.
- Không nên kỳ vọng generalization tốt vì chỉ có 1 episode.
- Nếu muốn train thật, cần record nhiều episode và tốt nhất record thêm command/action thật.

## 12. Sau Khi Train Xong

Checkpoint mới sẽ nằm dưới:

```text
unitree_lerobot/lerobot/outputs/g1_headcam_arm14_fake_flat26_act_test/checkpoints/last/pretrained_model
```

hoặc:

```text
unitree_lerobot/lerobot/outputs/g1_headcam_arm14_fake_flat26_act_finetune/checkpoints/last/pretrained_model
```

Khi muốn deploy lại lên robot bằng script cũ, cần dùng dataset root fake này và policy path mới:

```text
--policy-path=/path/to/new/checkpoints/last/pretrained_model
--repo-id=local/G1_headcam_arm14_fake_flat26_20260629_172043
--root=/home/jkl/.cache/huggingface/lerobot/local/G1_headcam_arm14_fake_flat26_20260629_172043
```

Lưu ý: script deploy hiện tại vẫn sẽ đọc 4 video key từ dataset. Vì trong dataset fake, cả 4 video đều là cùng một head camera nên policy input vẫn khớp shape cũ.
