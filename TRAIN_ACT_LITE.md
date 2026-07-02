# ACT-Lite: Training Guide

## Tổng Quan

ACT-Lite là phiên bản tối ưu của ACT cho setup **1 camera đầu + 14 khớp tay G1**.
So với ACT gốc:

| | ACT gốc (fake data) | ACT-Lite (native data) |
|---|---|---|
| Camera | 4 (trùng nhau) | 1 |
| State/Action dim | 26 (12 giả) | 14 |
| ResNet backbone | 4 bản | 1 bản |
| VRAM | ~4x | ~1x |

## Step 1: Tạo Dataset Native

```bash
python scripts/make_native_headcam_arm14.py \
  --episode-dir episode_20260629_172043 \
  --overwrite
```

Output sẽ nằm ở:
```
~/.cache/huggingface/lerobot/local/episode_20260629_172043_native_arm14_k1/
```

Kiểm tra `meta/info.json`:
- `observation.state.shape = [14]`
- `action.shape = [14]`
- Chỉ có 1 video key: `observation.images.head`

## Step 2: Training

```bash
python -m lerobot.scripts.lerobot_train \
  --policy.type=act_lite \
  --dataset.repo_id=local/episode_20260629_172043_native_arm14_k1 \
  --dataset.root=$HOME/.cache/huggingface/lerobot/local/episode_20260629_172043_native_arm14_k1 \
  --batch_size=8 \
  --steps=100000 \
  --eval_freq=-1 \
  --log_freq=200 \
  --save_freq=20000 \
  --policy.device=cuda \
  --policy.push_to_hub=false
```

### Dry-run (test nhanh 10 steps)

```bash
python -m lerobot.scripts.lerobot_train \
  --policy.type=act_lite \
  --dataset.repo_id=local/episode_20260629_172043_native_arm14_k1 \
  --dataset.root=$HOME/.cache/huggingface/lerobot/local/episode_20260629_172043_native_arm14_k1 \
  --batch_size=2 \
  --steps=10 \
  --eval_freq=-1 \
  --save_checkpoint=false \
  --policy.device=cuda \
  --policy.push_to_hub=false
```

## Step 3: Inference trên Robot

```bash
python unitree_lerobot/eval_robot/hybrid_arm_infer.py \
  --policy-path outputs/train/.../checkpoints/last/pretrained_model \
  --repo-id local/episode_20260629_172043_native_arm14_k1 \
  --root $HOME/.cache/huggingface/lerobot/local/episode_20260629_172043_native_arm14_k1
```

Script `hybrid_arm_infer.py` tự động phát hiện policy type:
- **ACT-Lite**: Output 14D → dùng trực tiếp
- **ACT gốc**: Output 26D → slice `[:, 0:14]`

## Kiến Trúc ACT-Lite

```
Input:
  observation.state[14]          → Linear(14, 512) → State Token
  observation.images.head[3,480,640] → ResNet18 → Conv1x1 → Visual Tokens

VAE Encoder (training only):
  [cls] + [state] + [action_seq(100x14)] → Transformer(4 layers) → z(32)

Transformer Encoder:
  [latent z] + [State Token] + [Visual Tokens] → Self-Attention(4 layers)

Transformer Decoder:
  100 Action Queries → Cross-Attention → Linear(512, 14) → actions[100, 14]
```

## Ghi Chú

- File policy mới nằm ở: `lerobot/src/lerobot/policies/act_lite/`
- Code ACT gốc **không bị thay đổi** — vẫn dùng được cho dataset 26D/4-cam cũ
- Checkpoint ACT-Lite không tương thích với checkpoint ACT gốc (khác số chiều)
