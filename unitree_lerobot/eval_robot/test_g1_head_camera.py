#!/usr/bin/env python3
"""Smoke-test G1 head/front camera access.

Two paths are supported:
- unitree-video: direct Unitree SDK VideoClient, useful for checking the robot camera service.
- image-client: repo ImageClient/ZMQ path, useful after starting image_server on the camera host.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


def decode_jpeg_frame(data: Any) -> np.ndarray:
    import cv2

    raw = bytes(data)
    if not raw:
        raise RuntimeError("Unitree VideoClient returned an empty image buffer.")
    image_data = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(
            f"Unitree VideoClient returned {len(raw)} bytes, but OpenCV could not decode it as an image."
        )
    return image


def save_frame(frame_bgr: np.ndarray, output_path: Path) -> None:
    import cv2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), frame_bgr):
        raise RuntimeError(f"Failed to write image to {output_path}")


def maybe_display(frame_bgr: np.ndarray, window_name: str, delay_ms: int) -> bool:
    import cv2

    cv2.imshow(window_name, frame_bgr)
    return cv2.waitKey(delay_ms) == 27


def run_unitree_video(args: argparse.Namespace, output_dir: Path) -> None:
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.go2.video.video_client import VideoClient

    if args.network_interface:
        ChannelFactoryInitialize(0, args.network_interface)
    else:
        ChannelFactoryInitialize(0)

    client = VideoClient()
    client.SetTimeout(args.timeout_s)
    client.Init()

    saved = 0
    attempts = 0
    max_attempts = max(args.frames, 1) + max(args.warmup_attempts, 0)
    while saved < args.frames and attempts < max_attempts:
        attempts += 1
        code, data = client.GetImageSample()
        data_len = len(bytes(data)) if data is not None else 0
        print(f"attempt={attempts} code={code} bytes={data_len}")
        if code != 0:
            raise RuntimeError(f"GetImageSample failed with code={code}")
        if data_len == 0:
            continue

        frame = decode_jpeg_frame(data)
        output_path = output_dir / f"unitree_video_frame_{saved:03d}.jpg"
        save_frame(frame, output_path)
        print(f"frame={saved} shape={frame.shape} saved={output_path}")
        saved += 1

        if args.display and maybe_display(frame, "g1_head_camera_unitree_video", args.display_delay_ms):
            break

    if saved == 0:
        raise RuntimeError(
            "No non-empty image buffer was received from Unitree VideoClient. "
            "Check whether the robot camera/videohub service is enabled and reachable on this interface."
        )

    if args.display:
        import cv2

        cv2.destroyAllWindows()
    print(f"Unitree VideoClient camera check passed. saved_frames={saved}")


def frame_to_bgr(frame: Any) -> np.ndarray:
    import cv2

    if hasattr(frame, "bgr") and frame.bgr is not None:
        return np.asarray(frame.bgr)
    if hasattr(frame, "rgb") and frame.rgb is not None:
        return cv2.cvtColor(np.asarray(frame.rgb), cv2.COLOR_RGB2BGR)
    if isinstance(frame, np.ndarray):
        return frame
    raise RuntimeError(f"Unsupported ImageClient frame type: {type(frame)!r}")


def run_image_client(args: argparse.Namespace, output_dir: Path) -> None:
    from unitree_lerobot.eval_robot.image_server.image_client import ImageClient

    client = ImageClient(host=args.host, request_port=args.request_port, request_bgr=True)
    config = client.get_cam_config()
    print(f"ImageClient camera config: {config}")

    saved = 0
    try:
        for idx in range(args.frames):
            frame = client.get_head_frame()
            if frame is None:
                raise RuntimeError("ImageClient returned None for head camera frame.")

            frame_bgr = frame_to_bgr(frame)
            output_path = output_dir / f"image_client_head_frame_{idx:03d}.jpg"
            save_frame(frame_bgr, output_path)
            saved += 1
            print(f"frame={idx} shape={frame_bgr.shape} saved={output_path}")

            if args.display and maybe_display(frame_bgr, "g1_head_camera_image_client", args.display_delay_ms):
                break
    finally:
        client.close()
        if args.display:
            import cv2

            cv2.destroyAllWindows()
    print(f"ImageClient camera check passed. saved_frames={saved}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("unitree-video", "image-client"),
        default="unitree-video",
        help="Camera access path to test.",
    )
    parser.add_argument("--network-interface", default="", help="DDS network interface for Unitree VideoClient.")
    parser.add_argument("--host", default="192.168.123.164", help="ImageServer host for --source=image-client.")
    parser.add_argument("--request-port", type=int, default=60000, help="ImageServer config request port.")
    parser.add_argument("--timeout-s", type=float, default=3.0, help="Unitree VideoClient timeout.")
    parser.add_argument("--frames", type=int, default=5, help="Number of frames to capture.")
    parser.add_argument("--warmup-attempts", type=int, default=30, help="Extra GetImageSample attempts for empty warmup frames.")
    parser.add_argument("--output-dir", type=Path, default=Path("camera_test_results"), help="Output directory.")
    parser.add_argument("--display", action="store_true", help="Show frames with OpenCV while capturing.")
    parser.add_argument("--display-delay-ms", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = args.output_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.source == "unitree-video":
        run_unitree_video(args, run_dir)
    else:
        run_image_client(args, run_dir)


if __name__ == "__main__":
    main()
