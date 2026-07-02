# G1 EDU Head Camera / RealSense D435i Handoff

File này bàn giao cho agent đang làm việc trực tiếp trên máy robot/NX của Unitree G1 EDU.

Mục tiêu hiện tại: kết nối và lấy ảnh từ camera đầu G1 để sau này dùng thay video dataset khi deploy policy hoặc tự thu dataset mới.

## 1. Kết Luận Quan Trọng

Camera trên đầu G1 EDU là:

```text
Intel RealSense D435I
```

Đây là camera RealSense cắm vào máy NX trên robot, không phải camera service kiểu `unitree_sdk2py.go2.video.VideoClient`.

Vì vậy:

- Không nên debug camera G1 bằng `VideoClient.GetImageSample()` như Go2/B2.
- Đường đúng là `librealsense` / `pyrealsense2` / `realsense-ros`.
- Nếu muốn laptop lấy ảnh, cần có process đọc camera chạy trên robot/NX rồi stream về laptop.

## 2. Trạng Thái Đã Kiểm Tra Trên Robot

SSH vào robot:

```bash
ssh unitree@192.168.123.164
```

Robot/NX là:

```text
Ubuntu 20.04.6 LTS
Linux 5.10.104-tegra aarch64
ROS 2 Foxy environment loaded
```

Đã kiểm tra có RealSense tools:

```bash
which rs-enumerate-devices
which realsense-viewer
```

Kết quả:

```text
/usr/local/bin/rs-enumerate-devices
/usr/local/bin/realsense-viewer
```

Đã kiểm tra camera:

```bash
rs-enumerate-devices | grep -E "Name|Serial|Firmware|USB|Product"
```

Kết quả:

```text
Name                          : Intel RealSense D435I
Serial Number                 : 243122071229
Firmware Version              : 5.15.1.55
Recommended Firmware Version  : 5.15.1
Product Id                    : 0B3A
Product Line                  : D400
Asic Serial Number            : 251843060574
Firmware Update Id            : 251843060574
```

Đã kiểm tra Python binding ban đầu bị lỗi vì conda `base` dùng Python 3.12:

```text
ImportError: Python version mismatch: module was compiled for Python 3.8,
but the interpreter version is incompatible: 3.12.12
```

Đã tìm thấy binding RealSense đã có sẵn:

```bash
sudo find /usr/local -name 'pyrealsense2*' -o -name '*realsense2*.so'
```

Kết quả quan trọng:

```text
/usr/local/lib/python3.8/dist-packages/pyrealsense2.so
/usr/local/lib/librealsense2.so
/usr/local/lib/librealsense2-gl.so
```

Sau khi thoát conda:

```bash
conda deactivate
```

Chạy Python hệ thống đã OK:

```bash
python3 - <<'PY'
import pyrealsense2 as rs

ctx = rs.context()
devices = ctx.query_devices()
print("devices:", len(devices))
for d in devices:
    print("name:", d.get_info(rs.camera_info.name))
    print("serial:", d.get_info(rs.camera_info.serial_number))
    print("usb:", d.get_info(rs.camera_info.usb_type_descriptor))
PY
```

Kết quả:

```text
devices: 1
name: Intel RealSense D435I
serial: 243122071229
usb: 3.2
```

Kết luận: **không cần cài lại RealSense SDK**. Chỉ cần không dùng conda Python 3.12 khi import `pyrealsense2`.

## 3. Python Đúng Để Chạy Camera Trên Robot

Ưu tiên dùng Python hệ thống:

```bash
/usr/bin/python3
```

Hoặc sau khi `conda deactivate`, `python3` hiện tại đã import được `pyrealsense2`.

Không dùng:

```text
conda base Python 3.12
```

vì binding hiện có được build cho Python 3.8.

Nếu cần ép path:

```bash
export PYTHONPATH=/usr/local/lib/python3.8/dist-packages:$PYTHONPATH
```

Nhưng sau khi dùng Python hệ thống thì hiện tại import đã OK.

## 4. Test RGB Frame Trực Tiếp Bằng Script Nhỏ

Nếu chỉ cần xác nhận lấy ảnh RGB từ D435i, tạo file tạm trên robot:

```bash
cat > /tmp/test_g1_d435i_rgb.py <<'PY'
import time
from pathlib import Path

import cv2
import numpy as np
import pyrealsense2 as rs

out = Path("/tmp/g1_d435i_rgb.jpg")

pipe = rs.pipeline()
cfg = rs.config()
cfg.enable_device("243122071229")
cfg.enable_stream(rs.stream.color, 848, 480, rs.format.bgr8, 30)

profile = pipe.start(cfg)
try:
    # warmup
    for _ in range(30):
        frames = pipe.wait_for_frames()
    color = frames.get_color_frame()
    if not color:
        raise RuntimeError("No color frame")
    img = np.asanyarray(color.get_data())
    print("frame shape:", img.shape, "dtype:", img.dtype)
    cv2.imwrite(str(out), img)
    print("saved:", out)
finally:
    pipe.stop()
PY

/usr/bin/python3 /tmp/test_g1_d435i_rgb.py
```

Kỳ vọng:

```text
frame shape: (480, 848, 3) dtype: uint8
saved: /tmp/g1_d435i_rgb.jpg
```

## 5. Test RGB + Depth + IR + IMU Theo Tài Liệu Unitree

Tài liệu Unitree trong repo:

```text
AGENT-read-This4G1-Edu/G1-Edu-md/More-Cases/Depth-Camera-Routine/README.md
```

Nói D435i có:

- RGB rolling shutter
- binocular infrared global shutter
- laser transmitter
- depth
- 6-axis IMU

Stream mẫu trong tài liệu:

```text
Depth      640x480 Z16   60fps
IR left    640x480 Y8    60fps
IR right   640x480 Y8    60fps
RGB        848x480 BGR8  60fps
Gyro       400Hz
Accel      200Hz
```

Nếu cần test nhẹ hơn, dùng 30fps trước để ổn định.

## 6. Có Cần Repo LeRobot Trên Robot Không?

Không bắt buộc cần cả repo.

Lý do có lúc nhắc tới repo là vì nếu muốn dùng sẵn:

```text
unitree_lerobot/eval_robot/image_server/image_server.py
```

thì `image_server.py` phải chạy trên máy đang nhìn thấy D435i, tức robot/NX.

Các lựa chọn:

### Lựa chọn A: Không cần repo, chỉ viết script pyrealsense2 nhỏ

Phù hợp để test camera hoặc tự record ảnh ra file.

### Lựa chọn B: Copy tối thiểu image_server lên robot

Nếu muốn laptop lấy ảnh realtime qua network, copy tối thiểu:

```text
unitree_lerobot/eval_robot/image_server/
unitree_lerobot/cam_config_server.yaml
```

rồi chạy `image_server.py --rs` trên robot.

### Lựa chọn C: Clone/copy cả repo lên robot

Dễ nhất nếu muốn dùng nguyên các import/package sẵn, nhưng nặng hơn.

## 7. Nếu Dùng image_server.py Của Repo

Trên robot/NX, cần chạy bằng Python 3.8 hệ thống:

```bash
/usr/bin/python3 unitree_lerobot/eval_robot/image_server/image_server.py --cf --rs
```

Flag `--cf` là camera finder.
Flag `--rs` bật hỗ trợ RealSense.

Sau đó sửa config:

```text
unitree_lerobot/cam_config_server.yaml
```

Config concept cho head camera:

```yaml
head_camera:
  type: realsense
  serial_number: "243122071229"
  image_shape: [480, 848]
  fps: 30
  enable_zmq: true
  zmq_port: 5555
  enable_webrtc: false
```

Sau đó chạy server:

```bash
/usr/bin/python3 unitree_lerobot/eval_robot/image_server/image_server.py --rs
```

Trên laptop, test client:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
conda activate unitree_lerobot

python unitree_lerobot/eval_robot/test_g1_head_camera.py \
  --source=image-client \
  --host=192.168.123.164 \
  --request-port=60000 \
  --frames=5
```

Lưu ý:

- `request-port=60000` là port lấy camera config từ ImageServer.
- `zmq_port` trong config là port stream ảnh thực tế.
- `test_g1_head_camera.py --source=unitree-video` không phải hướng chính cho D435i của G1.

## 8. Mục Tiêu Tiếp Theo Cho Agent Trên Robot

Làm theo thứ tự:

1. Không dùng conda base Python 3.12.
2. Dùng `/usr/bin/python3`.
3. Chạy test script `/tmp/test_g1_d435i_rgb.py` để lưu 1 frame RGB.
4. Nếu OK, quyết định:
   - chỉ cần record dataset đơn giản thì viết recorder nhỏ bằng `pyrealsense2`;
   - cần stream về laptop thì chạy/copy `image_server.py --rs`.
5. Nếu dùng ImageServer, tạo config `head_camera` với serial:

```text
243122071229
```

6. Từ laptop test nhận ảnh bằng `test_g1_head_camera.py --source=image-client`.

## 8A. C++ MJPEG Server

Xem chi tiết tại: [robot_camera_cpp/README.md](robot_camera_cpp/README.md)

## 8B. C++ LowState Recorder

Xem chi tiết tại: [robot_state_recorder_cpp/README.md](robot_state_recorder_cpp/README.md)

## 9. Ghi Nhớ Cho Thu Dataset

Để tự làm dataset kiểu đơn giản cho task tay/bàn tay:

```text
camera RGB từ D435i
+ arm q/state từ G1
+ Inspire hand angle/state
+ action command đã gửi cho arm/hand
```

Không cần full-body/root pose nếu chỉ train/deploy pipeline `flat26`.

Dataset nên hướng tới:

```text
observation.images.head
observation.state        shape [26]
action                   shape [26]
```

Trong đó:

```text
state[0:14]   = 14 khớp hai cánh tay G1
state[14:26]  = 12 giá trị Inspire hand
action[0:14]  = target arm q
action[14:26] = target hand command
```

## 10. Format Dataset WBT Có Sẵn Và Ý Nghĩa

Trong máy laptop hiện có 2 kiểu dataset chính đã dùng với Unitree G1 + Inspire hand.

### 10.1. Raw WBT / Full Body Format

Các dataset raw WBT gốc có trường quan trọng:

```text
action.robot_q_desired    shape [36]
action.hand_cmd           shape [12]
```

`action.robot_q_desired[36]` được hiểu là:

```text
0:7    root/base pose
7:36   29 khớp G1 body
```

Chi tiết:

```text
0 root position x
1 root position y
2 root position z
3 root quaternion w
4 root quaternion x
5 root quaternion y
6 root quaternion z

7..35 = q0..q28 của G1 29DoF
```

Mapping 29 khớp G1:

```text
q0..q5     left leg
q6..q11    right leg
q12..q14   waist
q15..q21   left arm
q22..q28   right arm
```

`action.hand_cmd[12]`:

```text
0..5    left Inspire hand
6..11   right Inspire hand
```

Lưu ý quan trọng:

```text
action.robot_q_desired là DESIRED/ACTION target
không phải observed lowstate q thật.
```

Nếu chỉ record `rt/lowstate`, ta mới có observed state:

```text
q thật hiện tại
dq thật
tau_est
IMU
```

chứ chưa chắc có command target gốc bên trong iPad replay mode.

### 10.2. flat26 Format

Đây là format nhẹ đã dùng để replay cánh tay + bàn tay:

```text
observation.state    shape [26]
action               shape [26]
```

Ý nghĩa:

```text
0:14    14 khớp hai cánh tay G1
14:26   12 giá trị Inspire hand
```

Trong đó 14 khớp cánh tay lấy từ G1 29DoF:

```text
q15..q28
```

Nói cách khác:

```text
flat26[0:14]  = lowstate q15..q28
flat26[14:26] = Inspire hand state/cmd 12D
```

Đây là format thực dụng nhất để train/deploy khi chỉ điều khiển tay và bàn tay, giữ robot ở `ai` balance mode.

## 11. Format CSV Recorder Hiện Tại

Tool:

```text
robot_state_recorder_cpp/g1_lowstate_recorder
```

ghi CSV từ `rt/lowstate` với 102 cột:

```text
sample_index,wall_time_s,elapsed_s,tick,mode_machine,
q0..q28,
dq0..dq28,
tau_est0..tau_est28,
imu_quat0..3,
imu_omega0..2,
imu_accel0..2
```

Tổng:

```text
5 metadata
+ 29 q
+ 29 dq
+ 29 tau_est
+ 4 imu_quat
+ 3 imu_omega
+ 3 imu_accel
= 102 cột
```

Ý nghĩa:

```text
q        vị trí khớp thật đang đo được
dq       vận tốc khớp thật
tau_est  mô-men/torque ước lượng
imu_quat orientation IMU của robot/body
imu_omega vận tốc góc IMU
imu_accel gia tốc IMU
```

Recorder này là **observed state logger**, chưa phải dataset training hoàn chỉnh.

## 12. Convert Recorder CSV Thành WBT-like Dataset

Có 2 hướng convert, tùy mục tiêu.

### 12.1. Convert Sang raw36 WBT-like

Mục tiêu tạo trường:

```text
robot_q_current[36]
action.robot_q_desired[36]
```

Từ recorder CSV, có thể tạo `robot_q_current[36]` như sau:

```text
robot_q_current[0:3]   = root position
robot_q_current[3:7]   = root quaternion
robot_q_current[7:36]  = q0..q28
```

Nhưng recorder hiện tại **không có root position xyz**. Có thể xử lý tạm:

```text
root position = [0, 0, 0]
root quaternion = imu_quat0..3
joint q = q0..q28
```

Tức:

```python
robot_q_current = [
    0.0, 0.0, 0.0,
    imu_quat0, imu_quat1, imu_quat2, imu_quat3,
    q0, q1, ..., q28,
]
```

Với `action.robot_q_desired[36]`, nếu không lấy được command target thật từ iPad replay mode, dùng approximation:

```text
action.robot_q_desired[t] = robot_q_current[t + 1]
```

hay nói rõ hơn:

```text
action.robot_q_desired[t][0:7]  = robot_q_current[t+1][0:7]
action.robot_q_desired[t][7:36] = q[t+1][0:29]
```

Đây là cách dùng "next observed state" làm target action. Nó không hoàn hảo bằng command gốc nhưng dùng được để imitation learning nếu replay/teleop đủ mượt.

Cần bỏ frame cuối hoặc duplicate action cuối:

```text
T observations -> T-1 actions nếu dùng next state
```

Khuyến nghị:

```text
dùng T-1 sample, bỏ sample cuối
```

### 12.2. Convert Sang flat26 Cho Cánh Tay + Inspire Hand

Đây là hướng nên ưu tiên trước vì pipeline deploy hiện đã chạy tốt.

Cần record thêm Inspire hand state/cmd. Lowstate recorder chỉ có G1 body, chưa có hand FTP state.

Tạo:

```text
observation.state[26]
action[26]
```

Từ recorder:

```text
arm_state[t] = q15..q28 tại sample t
```

Từ Inspire hand recorder/bridge:

```text
hand_state[t] = left_angle_act[0:6] + right_angle_act[0:6]
```

Rồi:

```python
observation.state[t] = concat(
    arm_state[t],
    hand_state[t],
)
```

Nếu không lấy được command target thật, dùng next-state action:

```python
action[t] = observation.state[t + 1]
```

hoặc nếu có command mình gửi ra robot/hand:

```python
action[t] = concat(
    arm_target_command[t],
    hand_target_command[t],
)
```

Ưu tiên tốt nhất:

```text
action = command target thật
```

Fallback dùng được:

```text
action = next observed state
```

### 12.3. Đồng Bộ Camera Và Joint State

Camera recorder/server và lowstate recorder cần timestamp chung.

Lowstate CSV có:

```text
wall_time_s
elapsed_s
```

Camera recorder nên lưu:

```text
frame_index
wall_time_s
image_path
```

Khi convert dataset:

```text
với mỗi frame camera, chọn lowstate sample gần nhất theo wall_time_s
```

hoặc nếu cả hai cùng bắt đầu trong một script/process:

```text
dùng elapsed_s
```

### 12.4. Dataset Output Khuyến Nghị Cho Agent Bên Robot

Để tạo raw log trước khi convert sang LeRobot, lưu dạng:

```text
episode_000/
  images/
    000000.jpg
    000001.jpg
    ...
  camera.csv
  lowstate.csv
  inspire_left.csv
  inspire_right.csv
  commands.csv          optional, nếu lấy được target command
```

`camera.csv`:

```text
frame_index,wall_time_s,elapsed_s,image_path
```

`lowstate.csv`:

```text
CSV 102 cột từ g1_lowstate_recorder
```

`inspire_left/right.csv`:

```text
sample_index,wall_time_s,elapsed_s,angle0..angle5,pos0..pos5,force0..force5,current0..current5,status0..status5,err0..err5
```

`commands.csv` nếu có:

```text
sample_index,wall_time_s,elapsed_s,arm_target0..13,hand_target0..11
```

Sau đó convert thành LeRobot dataset.

## 13. Việc Agent Bên Robot Cần Làm Tiếp

1. Ghi thử một episode ngắn:

```text
camera RGB + lowstate CSV
```

2. Nếu có Inspire hand bridge trên robot, ghi thêm hand state.

3. Kiểm tra timestamp:

```text
camera wall_time_s và lowstate wall_time_s phải cùng hệ clock
```

4. Copy raw log về laptop hoặc convert ngay trên robot.

5. Convert ưu tiên sang `flat26` trước:

```text
observation.images.head
observation.state[26]
action[26]
```

6. Chỉ convert sang raw36/full-body nếu thật sự cần full-body training, vì root position hiện chưa có nguồn chuẩn.
