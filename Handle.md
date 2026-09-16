# Handle.md — Bàn giao: finetune ACT "nhặt chai vào vòng" cho Unitree G1

Tài liệu này gói toàn bộ context của phiên làm việc (2026-09-15/16) để tiếp tục làm việc **trong repo
`unitree_lerobot`**. Repo điều phối riêng nằm ở `/home/jkl/Code/Fine-tune_pick_bottle_UnitreeG1`
(GitHub: `JKLover0909/Fine-tune_pick_bottle_UnitreeG1`, branch `main`) — chứa scaffold gọi sang repo này.

## 1. Đường dẫn quan trọng (checkpoint + dataset)

- **Checkpoint ACT đã train (50k step, dùng cái này):**
  `/home/jkl/Code/Fine-tune_pick_bottle_UnitreeG1/outputs/act_pick_bottle/checkpoints/050000/pretrained_model`
  (592M; còn có 010000..040000. Chứa `model.safetensors`, `config.json`, `train_config.json`,
  `policy_preprocessor.json`, `policy_postprocessor.json`.)
- **Dataset LeRobot đã convert:**
  `/home/jkl/.cache/huggingface/lerobot/local/pick_place_bottle` (969M) → repo_id `local/pick_place_bottle`
  (tự resolve trong HF cache, không cần `--root` cho eval_g1.py).
- **Chưa có link HuggingFace** — máy này **chưa `hf auth login`** (env `tv` có `huggingface_hub 0.35.3`
  nhưng không có token). Muốn có link Hub phải đăng nhập rồi push (xem mục 7).

## 2. Mục tiêu & phần cứng

- Task: G1 hai tay cầm **chai (quấn băng keo đen, nắp xanh)** đưa vào **vòng dây đen** trên **bàn tròn
  trắng**. 3 camera: head (color_0) + cổ tay trái (color_1) + cổ tay phải (color_2). Tay Inspire 6-dof/tay.
- **Chủ ý thiết kế:** tay TRÁI được giữ yên để wrist-cam trái nhìn cố định xuống bàn; tay PHẢI thao tác
  chai. → Khớp tay trái (`left_ee`, state idx 14-19) phương sai ~0 là BÌNH THƯỜNG, không phải lỗi.
- Máy: RTX 4070 Ti Super 16GB, i7-14700K, 31GB RAM, ~88GB đĩa trống. Env conda **`tv`**
  (lerobot 0.4.1, torch 2.3.0, av/pyav 16.1.0). GR00T/cloud không dùng — task hẹp, ACT là đủ và train
  local được.

## 3. Dữ liệu

- Nguồn thô: `xr_teleoperate/teleop/utils/data/` (12 bộ / 87 ep). Đã chọn 5 bộ cùng task "pick place
  bottle" + cùng setup: `pick_bottle_0914_2, place_bottle_0911_2, place_bottle_test1, pick_bottle_0914_1,
  place_bottle_0911` = 64 ep. **Loại 1 ep hỏng** `place_bottle_0911_2/episode_0015` (26 frame, tay phải
  không động) → còn **63 ep**.
- Loại KHỎI tập: `pick_bottle` (goal thật "pick up the cube"), `open_bottle_*` (task mở nắp), các bản
  `pick_bottle-test*` lẻ.
- Convert bằng `unitree_lerobot/utils/convert_unitree_json_to_lerobot.py --robot_type Unitree_G1_Inspire_3Cam`
  (config này ĐÚNG: 3 cam, `color_0→cam_left_high` (head), `color_1→cam_left_wrist`,
  `color_2→cam_right_wrist`). Converter glob `raw-dir/*/*` nên gộp mọi task-dir con → phải stage đúng 5 bộ
  đã chọn vào một thư mục trước khi convert.
- Kết quả: 63 ep, 35.355 frame, 30fps, state/action **[26]** = left_arm(7)+right_arm(7)+left_ee(6)+right_ee(6).

## 4. Kết quả train ACT

- Lệnh (env `tv`, card 16GB): `lerobot_train.py --policy.type=act --dataset.repo_id=local/pick_place_bottle
  --dataset.video_backend=pyav --batch_size=16 --steps=50000 --save_freq=10000`.
- ~5 giờ, ~0.40 s/step (batch 16, VRAM ~12.4GB). Loss hội tụ: 27.9 → **0.060** (50k). 5 checkpoint 10k→50k.

## 5. Kiểm tra inference OFFLINE (không cần robot) — ĐÃ CHẠY, kết quả tốt

- Script: `unitree_lerobot/eval_robot/offline_infer_dataset.py` (đã thêm cờ `--video-backend`, mặc định
  pyav). So action dự đoán vs action đã ghi, xuất metrics + plot. Không đụng phần cứng.
- Kết quả episode 0: **Overall MAE 0.0092**; left_arm 0.0045, right_arm 0.0120, left_dex3 0.0039,
  right_dex3 0.0193. Predicted bám sát ground-truth ở cả 4 nhóm (kể cả chuyển tiếp nắm/thả).
- Chạy lại: bên repo điều phối có `scripts/04_infer_offline.sh`. Trực tiếp:
  ```
  PYTHONNOUSERSITE=1 conda run -n tv python unitree_lerobot/eval_robot/offline_infer_dataset.py \
    --repo-id local/pick_place_bottle \
    --root /home/jkl/.cache/huggingface/lerobot/local/pick_place_bottle \
    --policy-path /home/jkl/Code/Fine-tune_pick_bottle_UnitreeG1/outputs/act_pick_bottle/checkpoints/050000/pretrained_model \
    --episode 0 --mode queued --video-backend pyav
  ```
- Lưu ý: đây là độ khớp demo (open-loop), **KHÔNG phải success rate thật**.

## 6. Inference lên ROBOT THẬT (closed-loop) — ĐÃ CHUẨN BỊ, chưa chạy (cần phần cứng)

- Script: `unitree_lerobot/eval_robot/eval_g1.py`. Nạp policy generic qua `--policy.path`; dùng
  `--repo_id` để lấy normalization stats + tư thế khởi tạo; `--arm=G1_29 --ee=inspire1` (inspire1 = 6-dof,
  khớp data). **`--send_real_robot` mặc định false** (chỉ chạy policy, không gửi lệnh ra robot) — nhưng
  file vẫn gọi `setup_image_client` + `setup_robot_interface` ngay khi khởi động, nên **bắt buộc có
  image_server + kết nối robot DDS/eno1 + driver tay** mới chạy được, kể cả khi false.
- Lệnh mẫu (env `tv`):
  ```
  PYTHONNOUSERSITE=1 conda run -n tv python unitree_lerobot/eval_robot/eval_g1.py \
    --policy.path=/home/jkl/Code/Fine-tune_pick_bottle_UnitreeG1/outputs/act_pick_bottle/checkpoints/050000/pretrained_model \
    --repo_id=local/pick_place_bottle --root="" --frequency=30 \
    --arm=G1_29 --ee=inspire1 --visualization=true --send_real_robot=false
  ```
  Khi an toàn (có trực e-stop) mới đặt `--send_real_robot=true`.
- **Điểm dễ vướng nhất:** tay được teleop qua driver **Inspire FTP (Modbus TCP)**
  (`eval_robot/inspire_hand_ftp_driver.py`), còn `eval_g1.py --ee=inspire1` dùng `Inspire_Controller`
  (DDS). Số chiều khớp (6-dof) nên policy chạy đúng, nhưng cần kiểm tra `Inspire_Controller` có điều khiển
  đúng con tay FTP này không, hoặc cần chạy driver FTP song song như lúc teleop.

## 7. Việc CÒN LẠI

1. **HuggingFace**: máy chưa auth. Đăng nhập rồi mới push được checkpoint/dataset để có link:
   `PYTHONNOUSERSITE=1 conda run -n tv hf auth login --token hf_xxx` (token quyền Write). Sau đó push
   checkpoint (592M) và/hoặc dataset (969M) lên repo private.
2. **Eval trên robot thật** (mục 6): bật image_server + robot, chạy visualize trước, rồi mới `send_real`.
3. **Push fork `unitree_lerobot`**: 2 commit fix đang ở **local, CHƯA push** — `631c822` (offline_infer
   thêm --video-backend), `87bd38a` (eval_g1/eval_g1_dataset/eval_g1_sim thêm cfg.video_backend, mặc định
   pyav). Branch `hungvd`.

## 8. Bẫy môi trường đã gặp (đã xử — nhớ để khỏi vấp lại)

1. **`PYTHONNOUSERSITE=1` bắt buộc** — nếu không, torchvision ở `~/.local` lệch version torch 2.3.0
   (lỗi `torch.library has no attribute register_fake`).
2. **torchcodec (backend video mặc định của LeRobot) hỏng với torch 2.3.0** — luôn dùng `pyav`. Convert
   lưu dataset dạng mp4 nên mọi bước đọc video phải ép pyav. `get_safe_default_codec()` vẫn chọn torchcodec
   nếu package chỉ *được cài* → phải truyền `video_backend=pyav` (đã vá trong các file eval + offline_infer).
3. **Process convert treo sau khi ghi xong** (multiprocessing không join) — dataset vẫn hợp lệ; kill bằng
   `pkill -9 -f convert_unitree_json_to_lerobot` sau khi `meta/info.json` đủ `total_episodes`.
4. **lerobot_train từ chối nếu `output_dir` đã tồn tại** (resume=False) — đừng mkdir trước.
5. **`conda run` buffer stdout** tới khi tiến trình thoát — không xem được log train live; theo dõi qua
   checkpoint mỗi save_freq và `nvidia-smi`.

## 9. Commit đã tạo trong phiên này

- `Fine-tune_pick_bottle_UnitreeG1` (đã push `main`): ae84b7e, f8e7b6b, 3ff0bcc, ef9fead, 478bd47.
- `unitree_lerobot` (branch `hungvd`, **chưa push**): 631c822, 87bd38a.
