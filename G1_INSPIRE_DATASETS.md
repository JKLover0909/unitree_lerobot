# Unitree G1 + Inspire Datasets

Các dataset dưới đây nằm trong Hugging Face org:

```text
https://huggingface.co/unitreerobotics
```

Nhóm cần quan tâm cho robot hiện tại là các dataset có tên:

```text
G1_WBT_Inspire_*
```

Vì chúng dùng Unitree G1, whole-body teleoperation/WBT và Inspire hand.

## Dataset Đang Dùng

```text
unitreerobotics/G1_WBT_Inspire_Pick_Up_Drinks
```

Bản local đã convert/flatten:

```text
/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Pick_Up_Drinks_flat26
```

Thông tin local:

```text
total_episodes = 300
total_frames   = 323252
fps            = 30
format         = flat26
```

Format deploy hiện tại:

```text
26D = 14 G1 arm joints + 6 left Inspire + 6 right Inspire
```

Mapping:

```text
action[0:14]   -> G1 two arms
action[14:20]  -> left Inspire hand
action[20:26]  -> right Inspire hand
```

Dataset hand action dùng scale `0..1`; script deploy scale sang Inspire command `0..1000`.

## Các Dataset G1 + WBT + Inspire Tìm Thấy

| Dataset | Ghi chú |
|---|---|
| `unitreerobotics/G1_WBT_Inspire_Clean_The_Living_Room` | G1 + Inspire, có vẻ nhỏ/preview hoặc dataset mới |
| `unitreerobotics/G1_WBT_Inspire_Collect_Clothes_MainCamOnly` | Main camera only |
| `unitreerobotics/G1_WBT_Inspire_Pickup_Pillow_MainCamOnly` | Main camera only |
| `unitreerobotics/G1_WBT_Inspire_Put_Clothes_into_Washing_Machine_MainCamOnly` | Main camera only |
| `unitreerobotics/G1_WBT_Inspire_Put_Clothes_into_Washing_Machine` | Bản đầy đủ hơn |
| `unitreerobotics/G1_WBT_Inspire_Put_Clothes_Into_Basket` | WBT Inspire |
| `unitreerobotics/G1_WBT_Inspire_Put_Drinks_Into_Fridge` | WBT Inspire |
| `unitreerobotics/G1_WBT_Inspire_Put_Vegetables_Into_Basket` | WBT Inspire |
| `unitreerobotics/G1_WBT_Inspire_Pick_Up_Drinks` | Dataset đang dùng |
| `unitreerobotics/G1_WBT_Inspire_Take_Plates_Into_Dishwasher` | WBT Inspire |

## Subset Đã Tải Để Replay

Ngày 2026-06-18 đã tải metadata/parquet, lấy 3 episode đầu và convert sang `flat26_first3` cho toàn bộ 10 dataset G1 + Inspire.

Các subset này **không có video**, chỉ dùng cho replay dataset action với:

```text
--use-dataset-action
```

Tất cả subset đã validate bằng `LeRobotDataset`, mỗi row có:

```text
observation.state shape = (26,)
action shape            = (26,)
```

| Dataset subset local | Episodes | Frames |
|---|---:|---:|
| `/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Clean_The_Living_Room_flat26_first3` | 3 | 2783 |
| `/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Collect_Clothes_MainCamOnly_flat26_first3` | 3 | 903 |
| `/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Pickup_Pillow_MainCamOnly_flat26_first3` | 3 | 749 |
| `/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Put_Clothes_into_Washing_Machine_MainCamOnly_flat26_first3` | 3 | 627 |
| `/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Put_Clothes_into_Washing_Machine_flat26_first3` | 3 | 5043 |
| `/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Put_Clothes_Into_Basket_flat26_first3` | 3 | 2410 |
| `/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Put_Drinks_Into_Fridge_flat26_first3` | 3 | 1820 |
| `/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Put_Vegetables_Into_Basket_flat26_first3` | 3 | 2839 |
| `/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Pick_Up_Drinks_flat26_first3` | 3 | 2145 |
| `/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Take_Plates_Into_Dishwasher_flat26_first3` | 3 | 5531 |

Script đã dùng:

```bash
/home/jkl0909/.holosoma_deps/miniconda3/envs/unitree_lerobot/bin/python \
  scripts/download_g1_inspire_first3.py
```

Script tải:

```text
meta/**
data/**/*.parquet
```

và bỏ qua:

```text
videos/**
images/**
*.mp4
*.png
*.jpg
```

Mapping convert đã verify bằng bộ `Pick_Up_Drinks`:

```text
observation.state = observation.state.robot_q_current[22:36] + observation.state.hand_state[0:12]
action            = action.robot_q_desired[22:36]      + action.hand_cmd[0:12]
```

Lý do dùng `robot_q_*[22:36]`: so sánh với bản local `Pick_Up_Drinks_flat26` hiện có cho sai số arm/hand bằng `0.0`.

## Lệnh Replay Một Subset Bất Kỳ

Ví dụ replay 3 episode đầu của `Put_Drinks_Into_Fridge`:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot

python unitree_lerobot/eval_robot/wbt_inspire_hybrid_infer.py \
  --policy-path=/home/jkl0909/code/Son/unitree_lerobot/unitree_lerobot/lerobot/outputs/g1_wbt_inspire_pick_up_drinks_act_bs16/checkpoints/last/pretrained_model \
  --repo-id=local/G1_WBT_Inspire_Put_Drinks_Into_Fridge_flat26_first3 \
  --root=/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Put_Drinks_Into_Fridge_flat26_first3 \
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

Để thử dataset khác, chỉ thay hai dòng:

```text
--repo-id=local/<TEN_DATASET>_flat26_first3
--root=/home/jkl0909/.cache/huggingface/lerobot/local/<TEN_DATASET>_flat26_first3
```

## Lưu Ý Về `MainCamOnly`

Các dataset có hậu tố:

```text
MainCamOnly
```

thường chỉ giữ camera chính. Chúng có thể nhẹ hơn nhưng cần kiểm tra lại schema trước khi dùng với policy/script hiện tại.

Với deploy/replay hiện tại, quan trọng nhất là dataset phải có đủ action/state để convert về:

```text
14 arm + 6 left hand + 6 right hand = 26D
```

## Không Phải Dataset Nào Cũng Chạy Thẳng Được

Có hai chế độ khác nhau:

### 1. Replay Dataset Action

Có thể chạy không cần train policy nếu dataset có action đúng format và đã convert mapping.

Điều kiện:

```text
- action có đủ cánh tay và tay Inspire
- mapping joint đúng với robot thật
- scale tay đúng: 0..1 hoặc 0..1000
- camera không bắt buộc nếu chỉ replay action
```

### 2. Policy Inference

Cần checkpoint policy đã train/fine-tune cho đúng dataset/task/format.

Không thể lấy một dataset mới rồi dùng checkpoint cũ một cách chắc chắn nếu:

```text
- task khác nhiều
- camera khác
- state/action shape khác
- robot/hand/action mapping khác
```

## Format Gốc Thường Gặp

Các dataset WBT Inspire trên Hugging Face thường có schema kiểu:

```text
observation.state.ee_state
observation.state.hand_state
observation.state.robot_q_current

action.ee_action
action.hand_cmd
action.robot_q_desired
```

Trong khi script deploy hiện tại đang dùng flat format:

```text
observation.state: 26D
action:            26D
```

Vì vậy dataset mới thường cần bước convert/flatten trước khi chạy bằng `wbt_inspire_hybrid_infer.py`.

## Cách Tải Dataset Mới

Ví dụ tải dataset khác về cache Hugging Face/LeRobot:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot

python - <<'PY'
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="unitreerobotics/G1_WBT_Inspire_Put_Drinks_Into_Fridge",
    repo_type="dataset",
    local_dir="/home/jkl0909/.cache/huggingface/lerobot/unitreerobotics/G1_WBT_Inspire_Put_Drinks_Into_Fridge",
)
PY
```

Sau khi tải, cần kiểm tra schema:

```bash
find /home/jkl0909/.cache/huggingface/lerobot/unitreerobotics/G1_WBT_Inspire_Put_Drinks_Into_Fridge -maxdepth 3 -type f | head
```

Và kiểm tra metadata:

```bash
find /home/jkl0909/.cache/huggingface/lerobot/unitreerobotics/G1_WBT_Inspire_Put_Drinks_Into_Fridge -name 'info.json' -o -name '*.parquet' | head
```

## Kiểm Tra Dataset Đang Có Trong Cache

```bash
du -h --max-depth=3 /home/jkl0909/.cache/huggingface/lerobot | sort -h | tail -40
```

Hiện tại sau khi xóa ToastedBread, dataset chính còn lại là:

```text
/home/jkl0909/.cache/huggingface/lerobot/local/G1_WBT_Inspire_Pick_Up_Drinks_flat26
```

## Ghi Chú Quan Trọng

- `G1_Dex3_*` là G1 với Dex3, không phải Inspire.
- `G1_Brainco_*` là G1 với BrainCo hand, không phải Inspire.
- `G1_Dex1_*` là G1 với Dex1/gripper setup, không phải Inspire.
- Với setup hiện tại, ưu tiên `G1_WBT_Inspire_*`.
