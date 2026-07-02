# G1 D435i C++ Camera Stream

Chạy trên máy NX của Unitree G1 EDU. Code đọc camera đầu RealSense D435i bằng `librealsense2`, encode JPEG bằng OpenCV, rồi mở MJPEG HTTP server.

Camera đã kiểm tra:

```text
Intel RealSense D435I
serial: 243122071229
usb: 3.2
```

## Copy Sang Robot

Từ laptop:

```bash
cd /home/jkl0909/code/Son/unitree_lerobot
scp -r robot_camera_cpp unitree@192.168.123.164:/home/unitree/
```

## Build Trên Robot

SSH vào robot:

```bash
ssh unitree@192.168.123.164
```

Không dùng conda Python ở đây, nhưng build C++ không phụ thuộc Python:

```bash
cd /home/unitree/robot_camera_cpp
mkdir -p build
cd build
cmake ..
make -j"$(nproc)"
```

Nếu thiếu OpenCV dev:

```bash
sudo apt update
sudo apt install -y libopencv-dev
```

`librealsense2` đã có sẵn nếu `rs-enumerate-devices` và `realsense-viewer` đang chạy được.

## Chạy Stream Trên Robot

```bash
cd /home/unitree/robot_camera_cpp/build

./g1_d435i_mjpeg_server \
  --serial=243122071229 \
  --width=848 \
  --height=480 \
  --fps=30 \
  --port=8080 \
  --jpeg-quality=80 \
  --frame-timeout-ms=5000 \
  --restart-delay-ms=1000
```

Mở trực tiếp từ laptop nếu route tới robot OK:

```text
http://192.168.123.164:8080/
http://192.168.123.164:8080/stream.mjpg
http://192.168.123.164:8080/snapshot.jpg
```

Hoặc dùng SSH tunnel từ laptop:

```bash
ssh -L 8080:127.0.0.1:8080 unitree@192.168.123.164
```

Sau đó mở trên laptop:

```text
http://127.0.0.1:8080/
```

## Test Lấy Snapshot Bằng Laptop

```bash
curl -o g1_d435i_snapshot.jpg http://192.168.123.164:8080/snapshot.jpg
```

Hoặc qua tunnel:

```bash
curl -o g1_d435i_snapshot.jpg http://127.0.0.1:8080/snapshot.jpg
```

## Ghi Chú

- Đây là hướng C++/SDK đúng tinh thần tài liệu Unitree `Depth-Camera-Routine`.
- Chương trình chỉ stream RGB. Có flag `--enable-depth` để bật thêm depth stream cho sync/test, nhưng hiện chưa stream depth ra HTTP.
- Nếu RealSense bị timeout kiểu `Frame didn't arrive within ...`, bản hiện tại sẽ tự restart pipeline và giữ HTTP server sống. Client có thể thấy frame đứng trong vài giây rồi chạy tiếp.
- Nếu timeout lặp liên tục ngay sau khi start, thử giảm mode:

```bash
./g1_d435i_mjpeg_server \
  --serial=243122071229 \
  --width=640 \
  --height=480 \
  --fps=30 \
  --port=8080 \
  --jpeg-quality=75 \
  --frame-timeout-ms=5000 \
  --restart-delay-ms=1000
```

- Trước khi chạy lại, nếu camera bị process cũ chiếm:

```bash
pkill -f g1_d435i_mjpeg_server
pkill -f realsense-viewer
pkill -f pyrealsense2
```

- Nếu cần lấy RGB/depth/IR/IMU đầy đủ để train dataset, mở rộng từ file `g1_d435i_mjpeg_server.cpp` hoặc viết recorder riêng.
