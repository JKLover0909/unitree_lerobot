# G1 LowState Recorder

Chạy trên máy robot/NX để ghi trực tiếp trạng thái khớp G1 từ DDS topic:

```text
rt/lowstate
```

CSV output gồm:

```text
sample_index
wall_time_s
elapsed_s
tick
mode_machine
q0..q28
dq0..dq28
tau_est0..tau_est28
imu_quat0..3
imu_omega0..2
imu_accel0..2
```

Mapping G1 29DoF:

```text
0..5    left leg
6..11   right leg
12..14  waist
15..21  left arm
22..28  right arm
```

## Copy Sang Robot

Từ laptop:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
scp -r robot_state_recorder_cpp unitree@192.168.123.164:/home/unitree/
```

## Build Trên Robot

```bash
ssh unitree@192.168.123.164

cd /home/unitree/robot_state_recorder_cpp
mkdir -p build
cd build

cmake ..
make -j"$(nproc)"
```

Nếu `cmake` không tìm thấy Unitree SDK:

```bash
cmake .. -DCMAKE_PREFIX_PATH=/usr/local
make -j"$(nproc)"
```

Nếu vẫn không thấy, tìm SDK trên robot:

```bash
sudo find /usr /usr/local /home/unitree /home/unitree/Code -name 'channel_subscriber.hpp' -o -name 'libunitree_sdk2*'
```

Nếu có source/install root, ví dụ `/home/unitree/Code/unitree_sdk2`, build bằng:

```bash
cmake .. -DUNITREE_SDK2_ROOT=/home/unitree/Code/unitree_sdk2
make -j"$(nproc)"
```

Nếu robot chưa có SDK C++ nhưng laptop repo có thư mục `unitree_sdk2`, copy sang robot:

```bash
scp -r /home/jkl0909/code/Son/unitree_lerobot/unitree_sdk2 unitree@192.168.123.164:/home/unitree/Code/
```

rồi trên robot:

```bash
cmake .. -DUNITREE_SDK2_ROOT=/home/unitree/Code/unitree_sdk2
make -j"$(nproc)"
```

## Chạy Ghi 30 Giây

Trên robot, interface thường là `eth0`:

```bash
cd /home/unitree/robot_state_recorder_cpp/build

./g1_lowstate_recorder \
  --network-interface=eth0 \
  --output-csv=/home/unitree/g1_lowstate_30s.csv \
  --frequency=30 \
  --duration-s=30 \
  --print-every=30
```

Nếu không chắc interface, thử bỏ `--network-interface`:

```bash
./g1_lowstate_recorder \
  --output-csv=/home/unitree/g1_lowstate_30s.csv \
  --frequency=30 \
  --duration-s=30
```

## Ghi Cho Đến Khi Ctrl+C

```bash
./g1_lowstate_recorder \
  --network-interface=eth0 \
  --output-csv=/home/unitree/g1_lowstate_episode.csv \
  --frequency=30
```

## Copy CSV Về Laptop

Từ laptop:

```bash
scp unitree@192.168.123.164:/home/unitree/g1_lowstate_30s.csv .
```

## Ghi Cùng Camera

Có thể chạy song song:

Terminal 1 trên robot:

```bash
/home/unitree/robot_camera_cpp/build/g1_d435i_mjpeg_server \
  --serial=243122071229 \
  --width=848 \
  --height=480 \
  --fps=30 \
  --port=8080 \
  --jpeg-quality=80 \
  --frame-timeout-ms=5000 \
  --restart-delay-ms=1000
```

Terminal 2 trên robot:

```bash
/home/unitree/robot_state_recorder_cpp/build/g1_lowstate_recorder \
  --network-interface=eth0 \
  --output-csv=/home/unitree/g1_lowstate_episode.csv \
  --frequency=30
```

Sau này để làm dataset, đồng bộ bằng `wall_time_s` hoặc `elapsed_s`.
