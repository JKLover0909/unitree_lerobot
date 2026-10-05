# Checklist.md — Trạng thái dữ liệu & mô hình (G1 pick/place bottle)

Cập nhật lần cuối: **2026-09-20**. File này chỉ theo dõi *trạng thái* (đã quay / đã convert / đã train /
đã push chưa). Chi tiết lệnh chạy, bẫy môi trường, kiến trúc → xem [Handle.md](Handle.md).
Môi trường dùng cho mọi việc dưới đây: conda env **`tv`** (`export PYTHONNOUSERSITE=1` bắt buộc).

---

## 1. Bảng tổng quan — từng task thô đi tới đâu rồi

| Task thô (`xr_teleoperate/.../data/`) | Ep quay | Goal string | Trong dataset **63-ep** (đã train, đã push) | Trong **32-ep** (chưa convert riêng) | Ghi chú |
|---|---|---|---|---|---|
| `pick_bottle_0914_1` | 10 | `pick place the bottle` | ✅ 10 | — | |
| `pick_bottle_0914_2` | 21 | `pick place the bottle` | ✅ 21 | — | |
| `place_bottle_0911` | 6 | `pick place the bottle` | ✅ 6 | — | |
| `place_bottle_0911_2` | 16 | `pick place the bottle` | ✅ 15 | — | loại `episode_0015` (26 frame, tay phải không động) |
| `place_bottle_test1` | 11 | `place the bottle` | ✅ 11 | — | |
| `pick_bottle_0916_1` | 5 | `pick up the bottle` | ❌ | ✅ 5 | đã kiểm tra chất lượng, sạch |
| `pick_bottle_0916_2` | 16 | `pick up the bottle` | ❌ | ✅ 16 | đã kiểm tra chất lượng, sạch |
| `pick_bottle_0916_3` | 11 | `pick up the bottle` | ❌ | ✅ 11 | ⚠️ **`states.left_ee` đóng băng cả 11 ep** (bridge FTP tay trái treo lúc quay 15:43-15:47 16/09) — vô hại cho ACT tay-phải-only, **phải xử lý/ghi chú trước khi dùng cho GR00T** |
| **Tổng trên đĩa** | **96** | | **63** | **32** | |

`steps` giống hệt nhau ở mọi episode (`step1: reach; step2: grasp; step3: place`) — 32-ep và 63-ep là
**cùng một task vật lý**, chỉ khác chuỗi `goal` do gõ khác nhau lúc set `--task-goal`. Không phải hai task
khác nhau thật.

---

## 2. Dataset đã convert (LeRobot, cục bộ `~/.cache/huggingface/lerobot/local/`)

| Dataset local | Ep | Frame | Nguồn | Trạng thái |
|---|---|---|---|---|
| `pick_place_bottle` | 63 | 35.355 | 5 task cột "63-ep" ở bảng trên | ✅ Tập train của checkpoint ACT hiện có. ✅ Đã push HF (mục 4). Dấu vân tay stats đã đối chiếu khớp checkpoint (lệch ~1e-8). |
| `g1_inspire_pickplace_all` | 96 | 50.074 | Gộp **thô, không lọc** toàn bộ 8 task | Convert thử nghiệm, **chưa lọc** episode hỏng, **chưa push**, **không dùng để train**. Coi như staging, không phải nguồn chính thức. |
| *(chưa tạo)* 32-ep riêng | 32 | 14.693 | `pick_bottle_0916_1/2/3` | ❌ **Chưa convert.** Kế hoạch: convert thành dataset riêng, không gộp vào `pick_place_bottle` — xem mục 5. |

---

## 3. Checkpoint ACT (`Fine-tune_pick_bottle_UnitreeG1/outputs/act_pick_bottle/checkpoints/`)

### 3b. Fine-tune v2 (2026-09-21, ĐANG CHẠY) — 106-ep, khởi tạo từ checkpoint 050000

Theo yêu cầu "train tiếp với các video đã quay từ đó đến nay". Lưu ý quan trọng: checkpoint 050000
**không có `training_state`** (optimizer AdamW đã xoá 20/09) → đây **không phải `--resume` thật**, mà là
**fine-tune**: nạp trọng số `050000` làm điểm khởi đầu (`--policy.path`), optimizer + step counter khởi
tạo lại từ 0.

- **Dataset mới**: `local/pick_place_bottle_v2` — gộp **63-ep gốc + 43 episode mới** (`pick_bottle_0916_1`
  5 + `0916_2` 16 + `0916_3` 11 + `pick_bottle_2109_1` 11), loại `place_bottle_0911_2/episode_0015` như cũ.
  Convert xong 2026-09-21 16:05, xác nhận **106 episode / 55.533 frame** (khớp: 63-ep gốc 35.355 +
  43-ep mới ~20.178). **Không đụng** `local/pick_place_bottle` (63-ep) hay `g1-pick-place-bottle-63ep` trên
  HF — đúng nguyên tắc "không ghi đè" đã thống nhất ở mục 5.
- **Lệnh train**: `--policy.path=.../checkpoints/050000/pretrained_model` (kế thừa toàn bộ kiến trúc/hyperparam
  từ checkpoint: chunk_size=100, use_vae=true, dim_model mặc định...), `--dataset.repo_id=local/pick_place_bottle_v2`,
  batch=16, steps=50000, save_freq=10000, `--output_dir=.../outputs/act_pick_bottle_v2` (thư mục mới, không
  ghi đè `act_pick_bottle`). `push_to_hub=false` kế thừa sẵn từ checkpoint.
- **Xác nhận khởi động đúng**: log in ra `dataset.num_episodes=106`, `dataset.num_frames=55533`,
  `pretrained_path=.../050000/pretrained_model` — khớp đúng kỳ vọng. `step:200 loss:0.158` (thấp hơn nhiều
  so với train từ đầu — loss ban đầu 27.9 — vì khởi tạo từ trọng số đã học, nhưng cao hơn điểm hội tụ cũ
  0.060 vì optimizer nguội + dữ liệu mới). GPU 100%, ~13.25GB/16GB, ~0,375s/step → ước tính **~5 giờ** cho
  đủ 50k step.
- **Checkpoint sẽ lưu tại** `010000, 020000, 030000, 040000, 050000` dưới `outputs/act_pick_bottle_v2/checkpoints/`.
  Sau khi xong: đo MAE offline từng checkpoint như đã làm với v1, chọn checkpoint tốt nhất, **chưa quyết
  định push HF** (chờ đánh giá MAE + eval thật trước).
- **⏸️ TẠM DỪNG 2026-09-21 ~20:02** (người dùng phải về, chưa kịp xong 50k step). Dừng bằng
  `kill -TERM`, log kết thúc sạch bằng dòng `Terminated`, GPU đã nhả (374MB), không còn process con nào
  sót lại. Log dừng ở khoảng **step ~42.000/50.000** (loss 0.052 — đã thấp hơn cả checkpoint v1 hội tụ
  0.060), nhưng vì `save_freq=10000` nên **checkpoint đã lưu trên đĩa vẫn chỉ là `040000`** — ~2000 step
  tiến độ sau đó (từ lúc log cuối cùng) không được lưu, mất khi resume.
  **Checkpoint 040000 CÒN NGUYÊN `training_state`** (395MB, optimizer AdamW + LR scheduler) — khác hẳn
  checkpoint `050000` của v1 (đã xoá `training_state` ngày 20/09) — nên đây **resume được thật sự**, giữ
  nguyên optimizer/step, không phải fine-tune lại từ đầu như lúc khởi tạo v2 từ v1.
  **Lệnh resume (phiên sau)**: `scripts/02b_resume_train_v2.sh` (đã tạo, gọi
  `lerobot_train.py --config_path=.../checkpoints/last/pretrained_model/train_config.json --resume=true`;
  `last` hiện trỏ `040000`). Sẽ tiếp tục đúng từ step 40000, chạy nốt 10.000 step còn lại tới 50000 (~35-40
  phút theo tốc độ đo được ~0,32s/step). **Đừng xoá `training_state` của bất cứ checkpoint `act_pick_bottle_v2`
  nào cho tới khi train xong hẳn** — bài học từ việc xoá sớm ở v1 khiến mất khả năng resume.

- **✅ HOÀN TẤT 2026-09-22 08:59:47.** Resume qua `scripts/02b_resume_train_v2.sh` xác nhận bắt đầu đúng
  từ **step 40.000** (log dòng đầu: `step:40K smpl:643K` — khớp bit-exact với điểm dừng hôm trước), chạy
  mượt tới hết **step 50.000**, loss giảm tiếp 0,052 → **~0,050-0,051**, kết thúc bằng
  `Checkpoint policy after step 50000` + `End of training`, không lỗi. GPU đã nhả sạch (463MB), không còn
  process con nào sót.
  5 checkpoint đầy đủ tại `outputs/act_pick_bottle_v2/checkpoints/`: `010000, 020000, 030000, 040000, 050000`
  (mỗi cái có `training_state` riêng, **chưa xoá cái nào** — giữ khả năng resume/rollback nếu cần).
  **Việc tiếp theo (chưa làm)**: đo MAE offline từng checkpoint như đã làm với v1 (5 điểm) để chọn checkpoint
  tốt nhất của v2, so sánh với checkpoint `050000` của v1 (MAE 0,0092) xem 43 episode mới có cải thiện thật
  không — rồi mới quyết định có push HF (model + dataset `pick_place_bottle_v2`) hay không.

### 3c. MAE offline v2 (2026-09-22) — đã đo đủ 5 checkpoint, `050000` tốt nhất

Đo bằng `scripts/04_infer_offline.sh` (đã cập nhật default sang v2, xem dưới), dataset
`local/pick_place_bottle_v2`, episode 0, mode `queued` — cùng phương pháp đã dùng cho v1.

| Step | Overall MAE | left_arm | right_arm | left_dex3 | right_dex3 |
|---|---|---|---|---|---|
| 010000 | 0,009291 | 0,005733 | 0,012336 | 0,003923 | 0,017523 |
| 020000 | 0,008476 | 0,004175 | 0,012332 | 0,003412 | 0,016190 |
| 030000 | 0,008140 | 0,004167 | 0,011577 | 0,003181 | 0,015833 |
| 040000 | 0,007545 | 0,005296 | 0,010681 | 0,002888 | 0,012824 |
| **050000** | **0,006862** | **0,004065** | **0,008731** | **0,003122** | **0,013397** |

MAE giảm đơn điệu ở cả overall lẫn 4 nhóm, không có dấu hiệu overfit (khác v1 — v1 từng nhích nhẹ ở
040000). **`050000` là checkpoint tốt nhất của v2**, MAE thấp hơn checkpoint `050000` của v1 (0,006862 so
với 0,0092) — **nhưng đo trên episode 0 của HAI dataset khác nhau** (v2 gộp 106 ep, thứ tự episode có thể
khác v1's 63-ep), nên đây **chưa phải so sánh táo-với-táo hoàn toàn**, chỉ là tín hiệu tích cực ban đầu.
Muốn so chuẩn xác cần đo cả hai checkpoint trên cùng một episode giữ nguyên từ 63-ep gốc.
**Chưa eval trên robot thật** — MAE offline không chứng minh tỉ lệ thành công thật.

- **Đã cập nhật `scripts/04_infer_offline.sh`**: default checkpoint → `act_pick_bottle_v2/checkpoints/050000`,
  default dataset → `local/pick_place_bottle_v2` (thêm tham số vị trí thứ 3 `dataset_repo_id`, không đụng
  `REPO_ID` dùng chung trong `config.env` để giữ nguyên khả năng tái lập pipeline v1). Lý do bắt buộc đổi
  cả dataset chứ không chỉ checkpoint: `offline_infer_dataset.py` và `eval_g1.py` đều lấy
  `dataset.meta.stats` từ `--repo-id`/`--root` để **ghi đè** normalizer đã bake sẵn trong checkpoint — nếu
  chỉ đổi checkpoint mà giữ dataset cũ (63-ep), state/action sẽ bị chuẩn hoá sai, không báo lỗi gì.
  Output đổi sang `outputs/offline_infer_v2/` (tách biệt kết quả v1/v2).

### 3d. Fine-tune v3 trên `pick_bottle_0922_1` — thất bại, đã cô lập nguyên nhân (2026-09-22/23)

**v3** (2026-09-22): fine-tune từ v2/050000, dataset `local/pick_bottle_0922_1` (31 ep: 16 thật + **15 bản
sao `episode_0016`**), 5000 step, save_freq 1000. MAE offline tốt nhất (`005000`) = **0,013008** — tệ hơn
cả v2 (0,006862) lẫn v1 (0,0092).

**v3_clean** (2026-09-23, thí nghiệm đối chứng): fine-tune **cùng checkpoint gốc, cùng hyperparameter hệt
v3** (steps=5000, save_freq=1000, batch=16), chỉ đổi dataset thành `local/pick_bottle_0922_1_16ep` — **loại
bỏ hoàn toàn 15 bản sao**, chỉ còn 16 episode thật (2.361 frame). Mục đích: cô lập xem MAE tệ của v3 là do
bản sao hay do nguyên nhân khác.

| Step | Overall MAE |
|---|---|
| 001000 | 0,019836 |
| 002000 | 0,012342 |
| 003000 | 0,012738 (nhích lên nhẹ) |
| **004000** | **0,010299 — tốt nhất** |
| 005000 | 0,012681 (tệ đi so với 004000) |

**Kết luận đối chứng:**

| Checkpoint | MAE |
|---|---|
| v2 `050000` (chưa fine-tune thêm) | **0,006862** |
| v3 `005000` (31 ep, có 15 bản sao) | 0,013008 |
| v3_clean `004000` (16 ep, KHÔNG bản sao) | 0,010299 |

15 bản sao **đúng là một phần nguyên nhân** — loại bỏ giúp MAE giảm ~21% (0,013→0,0103). Nhưng **không phải
nguyên nhân chính**: ngay cả với dữ liệu hoàn toàn sạch, fine-tune trên batch quá nhỏ (16 ep / 2.361 frame,
so với 106 ep / 55.533 frame của v2) từ checkpoint v2 vẫn cho MAE **tệ hơn chính v2 không fine-tune thêm**.
Đây là dấu hiệu **catastrophic forgetting** do batch mới quá nhỏ/hẹp so với phân phối đã học, không phải
do trùng lặp. Kết quả đơn điệu giảm rồi tăng lại ở step cuối (khác pattern đơn điệu của v1/v2) cũng gợi ý
overfit sớm vào tập nhỏ.

**Khuyến nghị:** không fine-tune trực tiếp trên các batch nhỏ (< ~30 ep) tách rời. Muốn tận dụng dữ liệu
mới (`pick_bottle_0922_1` hoặc các batch tương lai) một cách an toàn, nên theo đúng mẫu đã làm với v2:
**gộp vào dataset huấn luyện đầy đủ** (`pick_place_bottle_v2`, 106 ep) rồi fine-tune từ v2/050000 trên toàn
bộ tập gộp, không fine-tune riêng lẻ trên batch nhỏ. **Cả v3 và v3_clean đều không nên dùng để infer robot
thật** — checkpoint tốt nhất hiện có vẫn là v2 `050000`.

### 3e. Train v4 TỪ ĐẦU trên 122-ep — vẫn chưa vượt được v2 (2026-09-23)

Theo yêu cầu "train lại ACT từ đầu với 122 ep": convert dataset mới `local/pick_place_bottle_122ep`
(**106-ep của v2 + 16 episode thật của `pick_bottle_0922_1`**, loại 15 bản sao, xác nhận 122 ep /
57.894 frame khớp đúng 55.533+2.361). Train **from-scratch** (`pretrained_path=None`, không nạp checkpoint
nào), batch=16, steps=50000, save_freq=10000 — cùng hyperparameter v1. Chạy 16:18→21:07 (~4h49m), loss
6,901→0,068-0,070, 5 checkpoint đầy đủ tại `outputs/act_pick_bottle_v4/checkpoints/`.

| Step | Overall MAE |
|---|---|
| 010000 | 0,020514 |
| 020000 | 0,017155 |
| 030000 | 0,013759 |
| 040000 | 0,012149 |
| **050000** | **0,010787 — tốt nhất, vẫn đang giảm, chưa bão hoà** |

**So sánh toàn bộ:**

| Checkpoint | MAE | Cách tạo |
|---|---|---|
| v2 `050000` | **0,006862 — vẫn tốt nhất** | fine-tune liên tiếp v1→v2, ~100k step tích luỹ |
| v4 `050000` | 0,010787 | train từ đầu, 122-ep, 50k step |
| v3_clean `004000` | 0,010299 | fine-tune từ v2, 16-ep sạch |
| v3 `005000` | 0,013008 | fine-tune từ v2, 31-ep có bản sao |

**Bất ngờ: train từ đầu trên nhiều dữ liệu hơn (122 so với 106-ep) vẫn không vượt được v2.** Nghi ngờ
chính: v2 tích luỹ hiệu quả **~100k bước gradient** qua chuỗi v1 (50k/63-ep) rồi v2 (50k/106-ep), trong
khi v4 chỉ có 50k bước từ khởi tạo ngẫu nhiên — ít hơn về tổng lượng train dù dataset lớn hơn. MAE v4 vẫn
**giảm đơn điệu, chưa có dấu hiệu bão hoà** ở step 50000 — khác các lần trước, gợi ý train thêm có thể còn
cải thiện. **Chưa dùng v4 để infer robot thật** — v2 `050000` vẫn là lựa chọn tốt nhất.

**Hai hướng chưa làm, chờ quyết định:** (1) resume v4 train thêm (còn nguyên `training_state`, xem MAE có
giảm tiếp không); (2) fine-tune từ v2/050000 trên đúng 122-ep (kết hợp cả lợi thế trọng số đã học lẫn dữ
liệu đầy đủ — hướng đã gợi ý ban đầu trước khi chọn train from-scratch).

Train trên `pick_place_bottle` (63 ep), batch 16, 50k step, ~5 giờ trên RTX 4070 Ti Super.
`training_state` (optimizer AdamW, 1.98GB) **đã xoá** ngày 20/09 — không resume train tiếp được từ
010000-040000 nữa, chỉ còn dùng cho inference.

| Step | `pretrained_model` | MAE offline (episode 0, queued) | Đã push HF |
|---|---|---|---|
| 010000 | ✅ 198M | Overall 0.0201 | ❌ |
| 020000 | ✅ 198M | Overall 0.0147 | ❌ |
| 030000 | ✅ 198M | Overall 0.0114 | ❌ |
| 040000 | ✅ 198M | Overall 0.0115 (nhích lên nhẹ so với 030000, không đáng ngại) | ❌ |
| **050000** | ✅ 198M | **Overall 0.0092 — tốt nhất** | ✅ **Đã push** |

MAE giảm gần như đơn điệu 010000→050000, không có dấu hiệu overfit VAE. `050000` là lựa chọn đúng,
không cần đổi. Đây vẫn là **MAE open-loop** (xem giải thích trong hội thoại) — chưa chứng minh được tỉ lệ
thành công thật trên robot.

---

## 4. Đã push lên HuggingFace (namespace `JKL0909`, tất cả **private**)

| Repo | Loại | Nội dung | Link |
|---|---|---|---|
| `g1-act-pick-place-bottle` | model | Checkpoint ACT v1 step 50000 (7 file, config+weights+normalizer) | https://huggingface.co/JKL0909/g1-act-pick-place-bottle |
| `g1-pick-place-bottle-63ep` | dataset | 63 ep / 35.355 frame, khớp đúng tập train của checkpoint trên | https://huggingface.co/datasets/JKL0909/g1-pick-place-bottle-63ep |
| `g1-pick-bottle-43ep` | dataset | **2026-09-22.** 43 ep / 20.178 frame = `pick_bottle_0916_1`(5)+`0916_2`(16)+`0916_3`(11)+`2109_1`(11). Phần quay **sau** 63-ep, tách riêng không gộp. Card ghi rõ 11 ep của `0916_3` có `left_ee` đóng băng (bridge FTP treo lúc quay). | https://huggingface.co/datasets/JKL0909/g1-pick-bottle-43ep |
| `g1-pick-bottle-0922-1` | dataset | **2026-09-22.** 31 ep / 4.416 frame = 16 ep thật (`0000-0003,0005-0016`, đã loại `episode_0004` hỏng) + **15 bản sao `episode_0016`**. Card ghi rõ 15 bản sao, cảnh báo không train trực tiếp trên bộ này mà không lọc — đã kiểm chứng thực tế: fine-tune trực tiếp (v3) làm MAE offline tệ hơn cả checkpoint gốc chưa fine-tune (0,013 so với 0,0069 của v2). | https://huggingface.co/datasets/JKL0909/g1-pick-bottle-0922-1 |

Đã xác nhận `private=True` cả 4 repo bằng `HfApi.repo_info()`/`dataset_info()`.

**Chưa push:** checkpoint v2 (`act_pick_bottle_v2`, 5 checkpoint 010000-050000, `050000` MAE 0,006862 —
tốt nhất hiện có), checkpoint v3 (không khuyến nghị dùng), dataset `local/pick_place_bottle_v2` (106-ep
gộp, dùng để train v2 — theo quyết định 2026-09-22 **không push nguyên khối** để tránh re-upload trùng
63-ep đã có sẵn; ai cần tái tạo thì tự gộp `g1-pick-place-bottle-63ep` + `g1-pick-bottle-43ep`), dataset
`g1_inspire_pickplace_all` (staging thử nghiệm, chưa lọc, không dùng).

---

## 5. Việc còn treo — kế hoạch cho 32-ep

Mục đích đã thống nhất với người dùng (2026-09-20):
- **Ngắn hạn**: dự phòng — chỉ dùng nếu train trên 63-ep tỏ ra chưa đủ hiệu quả.
- **Dài hạn**: gộp với 63-ep để finetune GR00T N1.5 (VLA, có dùng ngôn ngữ — khác ACT không dùng text).

Quyết định: **không gộp vào `pick_place_bottle`/`g1-pick-place-bottle-63ep` hiện có** — sẽ phá tính khớp
checkpoint↔dataset đang dùng (offline MAE đã đối chiếu đúng 63-ep). Việc cần làm khi thực hiện:

1. Convert 32 ep thành **dataset LeRobot riêng** (chưa cần đổi tên `goal`, giữ nguyên nhãn gốc).
2. Push lên HF thành **repo riêng, private** (gợi ý tên: `g1-pick-bottle-32ep`), tách biệt hoàn toàn với
   `g1-pick-place-bottle-63ep`.
3. **Dataset card phải ghi rõ**: 11/32 episode (`pick_bottle_0916_3`) có `states.left_ee` đóng băng do lỗi
   bridge FTP, không phải tín hiệu thật — cảnh báo trước khi dùng state 26 chiều đầy đủ (đặc biệt cho
   GR00T).
4. Khi thật sự cần gộp (train ACT v2 hoặc bắt đầu GR00T): convert lại **từ raw JSON gốc** thành dataset
   gộp mới (95 ep), lúc đó mới chuẩn hoá chuỗi `goal` cho nhất quán và xử lý/loại cột `left_ee` hỏng của
   11 ep trên. Đặt tên repo mới, **không ghi đè** `g1-pick-place-bottle-63ep` hay
   `g1-act-pick-place-bottle` để giữ khả năng tái lập kết quả cũ.

---

## 6. Cạm bẫy đã gặp, đáng nhớ khi quay lại (chi tiết đầy đủ ở Handle.md §8)

- `PYTHONNOUSERSITE=1` bắt buộc cho mọi lệnh Python trong env `tv` (torchvision ở `~/.local` lệch version).
- Convert dataset không báo lỗi nếu `raw-dir` rỗng/sai — luôn xem dòng `==> Cached N episodes` để chắc N
  đúng như kỳ vọng trước khi tin kết quả.
- Bridge `inspire_hand_ftp_driver.py` có thể liệt (ctrl hoặc state) mà vẫn chạy 20Hz bình thường, không báo
  lỗi gì — kiểm tra bằng cách đếm **số giá trị `angle_act` khác nhau** qua vài giây, không phải đếm tần số.
- Driver NVIDIA lệch version kernel-module/userspace sau khi `apt upgrade` chạy giữa lúc máy đang chạy —
  chỉ sửa bằng reboot, không sửa bằng cài lại gói.
- Trước khi xoá bất cứ thứ gì trong `~/.cache/huggingface/lerobot/local/`, kiểm tra xem có checkpoint nào
  đang phụ thuộc vào nó không (xem mục 3) — từng xoá nhầm `pick_place_bottle` một lần, phải convert lại từ
  raw JSON để khôi phục.
- **`eval_g1.py` — `--send_real_robot=false` KHÔNG có tác dụng gì trước ngày 2026-09-20** (đã vá). Cờ này
  parse được (khai báo hợp lệ ở `utils.py:134`) nhưng không hề được đọc trong vòng lặp: `arm_ctrl.ctrl_dual_arm(...)`
  và ghi `ee_shared_mem` chạy **vô điều kiện**, robot di chuyển thật ngay khi nhấn `s` dù đặt cờ `false`.
  Chỉ `eval_g1_dataset.py` gate đúng cờ này, `eval_g1.py` (dùng bởi `eval_g1_eno1.py`, script chính cho
  eval robot thật ở mục 5) thì không. Đã thêm `if cfg.send_real_robot:` quanh 3 chỗ gọi (về tư thế đầu,
  gửi arm action, ghi ee action) — giờ `false` mới thực sự là dry-run. **Nếu pull code mới đè lên bản vá
  này, phải kiểm tra lại trước khi tin `--send_real_robot=false` là an toàn.** `eval_g1.py` cũng không có
  cơ chế dừng an toàn (`listen_keyboard`/`q`) như `replay_arm_and_hand_eno1.py` — chỉ dừng được bằng
  Ctrl+C, robot không tự về tư thế cuối khi dừng.
- **`eval_g1.py` chưa từng chạy được lần nào trước 2026-09-20** — Handle.md ghi "code đã sẵn sàng, chỉ
  chờ phần cứng" nhưng thực ra có 4 lỗi độc lập chưa từng lộ ra vì chưa ai chạy thật:
  1. (mục trên) `send_real_robot` bị bỏ quên, không gate gì cả.
  2. `EvalRealConfig` (`utils.py`) thiếu hẳn field `image_host` → `make_robot.py:89` luôn fallback
     `127.0.0.1`, đè lên default đúng `192.168.123.164` của `ImageClient`. Đã thêm field
     `image_host: str = "192.168.123.164"`, giờ `--image_host=...` mới thực sự dùng được.
  3. `eval_g1.py` unpack `image_info` như **dict 7 khoá** (`tv_img_array`, `is_binocular`...) chưa từng
     tồn tại, và gọi `process_images_and_observations()` với **7 tham số** trong khi hàm thật (`make_robot.py`)
     chỉ nhận 3 (`img_client, camera_config, arm_ctrl`) và trả về **tuple** `(image_client, image_config)`.
     Lỗi: `TypeError: tuple indices must be integers or slices, not str`. Đã viết lại theo đúng mẫu đã chạy
     được của `replay_robot.py`.
  4. `process_images_and_observations()` (`make_robot.py`) cắt đôi ảnh head camera theo chiều ngang
     **vô điều kiện**, giả định camera đôi mắt (binocular). Camera thật của rig này là **mono, 480×640,
     `binocular: false`** (xác nhận bằng `ImageClient.get_cam_config()` thật từ PC2) — nếu không sửa,
     policy nhận `cam_left_high` bị cắt còn 480×320, sai hoàn toàn so với 480×640 lúc train, **không báo
     lỗi gì**. Đã thêm kiểm tra cờ `binocular` trước khi cắt.
  5. `rerun_visualizer.py` dùng `rr.Scalar(...)` — API cũ, bản `rerun-sdk` cài trong env `tv` là **0.26.2**
     đã đổi tên thành `rr.Scalars(...)` (số nhiều). Lỗi: `module 'rerun' has no attribute 'Scalar'`, crash
     ngay frame đầu tiên của vòng lặp eval. Đã đổi cả 2 chỗ dùng.

  Sau khi vá cả 5, dry-run `--send_real_robot=false --visualization=true` chạy sạch 25s liên tục ở 30Hz,
  không lỗi/không traceback trên terminal.

- **⚠️ NGHIÊM TRỌNG — bug thứ 6, `--send_real_robot=false` KHÔNG chặn được bàn tay di chuyển thật, dù đã
  vá bug ở trên** (phát hiện + vá 2026-09-20). `setup_robot_interface(cfg)` khởi tạo `Inspire_FTP_Controller`
  **vô điều kiện** (không xem `send_real_robot`), và class này tự spawn một **tiến trình con chạy ~100Hz
  liên tục** luôn gọi `ctrl_dual_hand()` gửi lệnh Modbus thật, đọc mục tiêu từ `ee_shared_mem["left"/"right"]`.
  Mảng này mặc định khởi tạo bằng **0** (`Array("d", 6, lock=True)`); khi `send_real_robot=False`,
  `eval_g1.py` đúng như thiết kế không ghi action policy vào đó — nhưng tiến trình con vẫn cứ đọc và gửi
  **0** liên tục, kéo tay thật về gần 0 mọi khớp. **Bằng chứng đo thật, theo dõi tay TRONG LÚC script chạy**
  (không chỉ trước/sau): tay trái từ `angle≈[999,997,1000,999,1000,990]` (duỗi hết cỡ) tụt xuống
  `[1,0,3,3,340,0]` chỉ 2 giây sau khi nhấn `s`, kèm dòng điện thật tăng vọt (872, 716, 769 — motor có lực
  thật). **Không tự hồi phục** sau khi script thoát — tay giữ nguyên vị trí bị kéo tới, người dùng phải tự
  kiểm tra phần cứng (lần này an toàn, không kẹt/hỏng gì).
  Đã vá tại nguồn: sau bước chờ subscribe DDS trong `Inspire_FTP_Controller.__init__`, **seed
  `left_hand_array`/`right_hand_array` bằng chính vị trí tay hiện tại** (đọc từ
  `left_hand_state_array`/`right_hand_state_array`) thay vì để mặc định 0 — nếu không ai ghi đè, tiến
  trình con giờ chỉ giữ nguyên vị trí, không kéo đi đâu. **Đã re-verify bằng live-monitor 2026-09-20**:
  chạy lại dry-run 15s trong khi theo dõi tay mỗi 2s — `angle_act` giữ phẳng suốt (dao động ±1-2, đúng
  nhiễu encoder bình thường), `current` gần như luôn 0 (một nhịp rất nhỏ 115 lúc seed, tắt ngay sau đó).
  Không còn cú nhảy hay dòng điện tăng vọt như trước khi vá. **`--send_real_robot=false` giờ mới thực sự
  an toàn cho cả tay lẫn cánh tay.**
  **Bài học phương pháp**: đọc log sau khi chạy xong là KHÔNG đủ để tin một "dry run" là an toàn — bug này
  không để lại traceback, không log gì bất thường, script vẫn báo "DRY RUN" đàng hoàng. Chỉ lộ ra khi theo
  dõi trạng thái tay thật **trong lúc** script đang chạy (subscribe `rt/inspire_hand/state/l|r`, in
  `angle_act`+`current` mỗi ~2s). **Mọi thay đổi liên quan tới eval robot thật từ nay phải verify theo cách
  này trước khi tuyên bố an toàn**, không dựa vào việc script thoát code 0.
- `Inspire_FTP_Controller` cũng có một cảnh báo khác lúc khởi động:
  `Timeout waiting for hand state on rt/inspire_hand/state/l|r ... Proceeding anyway` dù bridge đang chạy —
  đã đo trực tiếp cơ chế subscribe (`Init()` không callback + `.Read()` polling, giống hệt code thật) và
  thấy nhận tin trong **0.047s**, nên DDS/bridge không chậm; nghi là tranh chấp GIL lúc script đang nạp
  policy GPU + kết nối camera cùng lúc làm chậm luồng polling nhất thời. Không chặn chức năng (background
  thread vẫn chạy tiếp sau đó), nhưng chưa xác định chắc chắn nguyên nhân.
- **Các controller tay khác (`Dex3_1_Controller`, `Dex1_1_Gripper_Controller`, `Brainco_Controller`)
  nhiều khả năng có cùng lỗ hổng** (cùng pattern `spec["controller"](...)` + tiến trình con actuation liên
  tục) nhưng **chưa kiểm tra** — không dùng cho phần cứng hiện tại (`inspire_ftp`) nên chưa vá, nhưng nếu
  sau này đổi sang tay khác thì phải kiểm tra lại trước.

- **⚠️ Bug thứ 7 — robot bị đẩy về development mode, và arm_sdk không bao giờ được trả lại**
  (phát hiện + vá 2026-09-20). Hai vấn đề tách biệt, cùng một gốc là cờ `--motion`:

  **(a) Thiếu cờ `--motion` khi replay/eval.** Toàn bộ 8 task đã quay đều dùng `--motion`
  (xác nhận bằng `~/.bash_history`: cả 10 lệnh `teleop_hand_and_arm.py` đều có cờ này) → robot ở
  **Regular mode**, onboard controller giữ thăng bằng chân/thân, lệnh tay đi qua `rt/arm_sdk`.
  Nhưng mọi lệnh replay đã chạy đều **thiếu** `--motion`, nên wrapper `_eno1` gọi `MotionSwitcherClient.ReleaseMode()`
  trong vòng lặp cho tới khi không còn mode nào → robot rơi vào **development mode, buông xuôi, không tự
  cân bằng**, và arm controller ghi thẳng `rt/lowcmd` thay vì `rt/arm_sdk`. Đây **không phải bug code** mà
  là cờ bị bỏ sót: logic của wrapper `_eno1` là bản chép đúng `MotionSwitcher.Enter_Debug_Mode()` của teleop.
  **Cách dùng đúng: luôn truyền `--motion` (argparse) hoặc `--motion=true` (draccus) cho replay/eval**, và
  robot phải **đã ở Regular mode** (R1+X trên remote) trước khi chạy. Dấu hiệu xác nhận đúng: **không**
  thấy dòng `Releasing onboard mode '...'` lúc khởi động.

  **(b) Không script nào trả tay lại cho onboard controller khi thoát (lỗi thật, đã vá).** Ở `motion_mode=True`,
  `_ctrl_motor_state()` đặt `msg.motor_cmd[kNotUsedJoint0].q = 1.0` (joint 29 = trọng số giành quyền của
  arm_sdk) **một lần** rồi giữ nguyên suốt phiên. `teleop_hand_and_arm.py:634` có gọi `ctrl_dual_arm_go_home()`
  lúc cleanup để ramp trọng số 1→0, nhưng `eval_g1.py`, `replay_robot.py`, `replay_arm_and_hand_eno1.py`
  **không hề gọi** (`grep go_home` ra rỗng) → sau khi Ctrl+C, trọng số **kẹt ở 1.0**, arm_sdk vẫn giữ hai
  tay, onboard controller không bao giờ lấy lại được.
  Tệ hơn: bản thân `ctrl_dual_arm_go_home()` cũng sai — vòng ramp 1→0 bị **lồng bên trong** nhánh
  `if np.all(np.abs(current_q) < tolerance)`, nên nếu tay không về được tư thế home trong 5s
  (`max_attempts=100` × `0.05s`) thì hàm thoát mà **không hề hạ trọng số**.
  Đã vá 3 chỗ: (1) `robot_arm.py` — tách vòng chờ ra khỏi bước ramp, thêm method
  `release_arm_sdk_weight()` **luôn** được gọi trên mọi đường thoát, có `try/finally` ép trọng số về `0.0`
  kể cả khi ramp bị Ctrl+C cắt ngang, rồi `sleep(0.05)` để luồng publish 250Hz kịp đẩy giá trị cuối lên
  wire; áp dụng cho **cả `G1_29` lẫn `G1_23`** (G1_23 cùng lỗi y hệt, chưa test vì không có phần cứng).
  (2)(3) thêm `try/finally` gọi `ctrl_dual_arm_go_home()` lúc thoát cho cả ba script eval/replay.
  **Đã verify bằng test không cần phần cứng** (`scratchpad/test_weight_release.py`, dựng controller bằng
  `object.__new__` nên không đụng DDS): 4 case đều pass trên bản vá; chạy lại chính test đó trên bản gốc
  (`git show HEAD:`) thì **case "tay không về được home" để trọng số = 1.0** và **case "ramp bị Ctrl+C"
  để trọng số = 0.91** — đúng lỗi cần sửa. **Chưa verify trên robot thật.**

- **`eval_g1.py` — luồng bấm phím đã đổi thành 2 cổng như replay** (2026-09-20, theo yêu cầu).
  Trước đó `eval_g1.py` chỉ có **1** `input()`: nhấn `s` → tay về tư thế đầu → `time.sleep(1.0)` →
  **policy chạy luôn**. Không có chốt nghỉ nào để kiểm tra robot, trong khi script này **không có phím
  dừng** (`grep listen_keyboard` → 0, chỉ Ctrl+C) và action policy không bị ràng buộc bởi quỹ đạo đã ghi.
  Đã sửa 3 chỗ: (1) thêm cổng thứ hai `Enter 's' to START POLICY INFERENCE:` — không phải `s` thì thoát,
  robot nằm yên ở tư thế đầu; (2) thay `time.sleep(1.0)` cứng bằng `move_to_start_pose()` **poll trạng
  thái khớp thật** (giống `replay_robot.py`; sleep cố định không đảm bảo tới nơi vì `clip_arm_q_target`
  giới hạn tốc độ); (3) tư thế đầu giờ seed **cả bàn tay** (`send_ee_action(init_state)`) — trước đây chỉ
  gọi `ctrl_dual_arm()`, tay nằm nguyên chỗ cũ tới khi action policy đầu tiên làm nó **nhảy**.
  `send_ee_action()` là helper dùng chung cho cả seed lẫn vòng lặp, thay cho đoạn ghi shared-mem bị lặp.
  (4) thêm **phím `q` dừng inference** — `threading.Event` + `listen_keyboard` daemon thread, khởi động
  **sau** cả hai `input()` (vì `input()` và `listen_keyboard` cùng đọc stdin, không được chạy đồng thời),
  kiểm tra `stop_requested` ở đầu vòng lặp. Trước đó eval chỉ dừng được bằng Ctrl+C.
  **Đã verify bằng test mock không cần phần cứng** (`scratchpad/test_two_gate.py`): hủy ở cổng 2 → tay về
  đúng tư thế đầu, hand seed đúng slice `[14:20]`/`[20:26]`, **policy không chạy**; xác nhận → policy chạy;
  từ chối cổng 1 → không lệnh nào được gửi. **Chưa chạy trên robot thật.**

- **⚠️ NGHIÊM TRỌNG — bug thứ 8: bản vá bug 6 CHƯA ĐỦ, tay phải vẫn bị kéo về 0 trong dry-run**
  (phát hiện + vá 2026-09-20, lộ ra ngay lần đầu chạy dry-run thật có monitor).
  Vòng chờ trong `Inspire_FTP_Controller.__init__` dùng **`or`**:
  `while not (any(left_hand_state_array) or any(right_hand_state_array))` → thoát ngay khi **một** tay
  có state. Đo thật: log `Waiting to subscribe dds` → `Subscribe dds ok` cách nhau đúng **0,04s**. Lúc đó
  `right_hand_state_array` vẫn toàn 0, nên bước seed (bản vá bug 6) copy **số 0** vào target tay phải, và
  `control_process()` kéo tay phải thật về góc 0 ở ~100Hz — đúng y hệt bug 6, chỉ đổi tay.
  **Bằng chứng đo trong lúc chạy** (`--send_real_robot=false`, 25s): `R_ang` từ `[2,1,1,4,244,149]` xuống
  `[2,0,1,2,2,0]`, dòng điện lên **411/521/704/652/744** suốt ~28s, trở lại khi script thoát. Tay trái
  (được seed đúng) **không nhúc nhích** — chính sự bất đối xứng này chỉ thẳng ra nguyên nhân.
  Đã vá: (1) thêm `left_state_seen`/`right_state_seen` (`threading.Event`) do luồng subscribe set khi
  nhận được tin hợp lệ — **không** suy ra từ `any(state_array)` nữa, vì một bàn tay nắm hết cỡ (góc 0
  cả 6 khớp) đọc ra toàn 0, không phân biệt được với "chưa có dữ liệu"; (2) chờ **cả hai** tay (`and`);
  (3) quá 5s mà thiếu tay nào thì **raise RuntimeError**, không còn "Proceeding anyway" — vì chạy tiếp
  đồng nghĩa với actuation thật trên phần cứng thật, và **bridge bị liệt nhánh state (lỗi đã biết của
  rig này) trông y hệt trường hợp này**.
  **Đã re-verify bằng dry-run thứ ba có monitor**: `R_ang[4]` giữ nguyên 233 (trước: 244→2),
  `R_ang[5]` 123→111 (lệch 1,2%), dòng điện ~107 đều thay vì 744. Phần còn lại 1,2% + dòng ~107 là hệ quả
  bình thường của việc tay **chủ động giữ** vị trí đo được thay vì buông tự do, không phải lỗi.
  **Bài học lặp lại lần thứ hai**: bug 6 từng được tuyên bố "đã verify" dựa trên monitor chỉ nhìn **tay
  trái**. Tay phải mới là tay bị hỏng. **Monitor phải bao trùm mọi bộ phận có thể chuyển động, không chỉ
  cái vừa sửa.**

---

## 7. Nhật ký cập nhật file này

- 2026-09-20: Tạo file. Trạng thái: 63-ep đã train+push, 32-ep đã kiểm tra chất lượng nhưng chưa convert,
  checkpoint 050000 đã push, 4 checkpoint trung gian dùng để so sánh MAE nhưng chưa push.
- 2026-09-20: Thêm bug thứ 7 (mục 6) — xác thực robot bị đẩy về development mode do thiếu cờ `--motion`,
  và vá lỗi arm_sdk không bao giờ trả tay lại cho onboard controller khi thoát. Sửa `robot_arm.py`
  (`release_arm_sdk_weight()`, cả G1_29 và G1_23) + `eval_g1.py`, `replay_robot.py`,
  `replay_arm_and_hand_eno1.py` (`try/finally` gọi `ctrl_dual_arm_go_home()`). Đã test không cần phần
  cứng, **chưa chạy trên robot thật**.
- 2026-09-23: Train v4 TỪ ĐẦU trên dataset mới `pick_place_bottle_122ep` (106-ep v2 + 16 episode thật của
  0922_1, không bản sao), 50k step, ~4h49m. MAE tốt nhất `050000`=0,010787 — vẫn chưa vượt v2 (0,006862),
  nghi do v2 có lợi thế tích luỹ ~100k step qua chuỗi fine-tune trong khi v4 chỉ có 50k step từ đầu. MAE
  v4 chưa bão hoà, có thể train thêm. v2 `050000` vẫn là checkpoint tốt nhất hiện có.
- 2026-09-23: Thí nghiệm đối chứng v3_clean (5000 step, dataset 16-ep sạch không bản sao, cùng
  hyperparameter v3) — MAE tốt nhất `004000`=0,010299, tốt hơn v3 (0,013008) nhưng vẫn tệ hơn v2
  (0,006862). Kết luận: bản sao là một phần nguyên nhân nhưng không phải chính — batch fine-tune quá
  nhỏ mới là vấn đề chính (catastrophic forgetting). Khuyến nghị: gộp dữ liệu mới vào tập đầy đủ trước
  khi fine-tune, không fine-tune riêng trên batch nhỏ. v2 `050000` vẫn là checkpoint tốt nhất hiện có.
- 2026-09-22: Push 2 dataset mới lên HF (private, có dataset card cảnh báo rõ ràng): `g1-pick-bottle-43ep`
  (43 ep, phần quay sau 63-ep, tách riêng) và `g1-pick-bottle-0922-1` (31 ep, cảnh báo 15 bản sao). Quyết
  định: không push nguyên khối `pick_place_bottle_v2` (106-ep) để tránh re-upload trùng 63-ep đã có.
- 2026-09-22: Fine-tune v3 (5000 step) từ checkpoint v2/050000, dataset `local/pick_bottle_0922_1`
  (31 ep: 16 thật + 15 bản sao `episode_0016`). MAE offline (episode 0, thật) tốt nhất `005000`=0,013008 —
  **tệ hơn cả v2 (0,006862) lẫn v1 (0,0092)**, nghi catastrophic forgetting/overfit vào dataset nhỏ bị
  nhân bản. **Chưa dùng v3 để infer robot thật**, chờ xác minh/thử phương án khác.
- 2026-09-22: Resume fine-tune v2 từ checkpoint 040000 (đúng từ step 40K), chạy hết tới step 50000.
  Train v2 HOÀN TẤT — loss cuối ~0,050-0,051. Còn thiếu: đo MAE offline để chọn checkpoint tốt nhất và
  so sánh với v1, chưa push HF.
- 2026-09-21: Convert dataset mới `local/pick_place_bottle_v2` (106 ep / 55.533 frame = 63-ep gốc +
  43 episode mới quay 0916_1/2/3 + 2109_1). Khởi động fine-tune ACT v2 từ checkpoint 050000
  (`--policy.path`, KHÔNG phải `--resume` thật vì optimizer state đã mất), 50k step, output riêng
  `act_pick_bottle_v2`. Đang chạy, ETA ~5 giờ.
- 2026-09-20: Phát hiện + vá bug 8 (`or` → `and` khi chờ state hai tay trong `Inspire_FTP_Controller`,
  raise thay vì "Proceeding anyway"). Đã chạy dry-run thật 3 lần trên robot, có monitor: hai cổng `s`,
  phím `q`, và nhả arm_sdk đều hoạt động đúng trên phần cứng thật.
- 2026-09-20: `eval_g1.py` đổi sang luồng 2 cổng (`s` về tư thế đầu → `s` lần hai mới chạy policy),
  thay sleep cứng bằng poll khớp thật, seed cả bàn tay ở tư thế đầu, thêm phím `q` dừng inference. Test mock pass, **chưa chạy robot thật**.
