#!/usr/bin/env python3
"""Headless Modbus-TCP <-> DDS bridge for Inspire FTP hands.

The Inspire hand does not publish DDS state by itself. This process reads the
hand over Modbus TCP, publishes:

    rt/inspire_hand/state/l|r
    rt/inspire_hand/touch/l|r

and subscribes to:

    rt/inspire_hand/ctrl/l|r

This avoids importing inspire_sdkpy.__init__, which may require PyQt GUI
packages that are not needed for headless robot control.
"""

from __future__ import annotations

import argparse
import signal
import struct
import sys
import threading
import time
from pathlib import Path

import numpy as np
from pymodbus.client import ModbusTcpClient


STATE_REGISTERS = [
    ("pos_act", 1534, 6, "short"),
    ("angle_act", 1546, 6, "short"),
    ("force_act", 1582, 6, "short"),
    ("current", 1594, 6, "short"),
    ("err", 1606, 3, "byte"),
    ("status", 1612, 3, "byte"),
    ("temperature", 1618, 3, "byte"),
]

TOUCH_REGISTERS = [
    ("fingerone_tip_touch", 3000, 9, (3, 3)),
    ("fingerone_top_touch", 3018, 96, (12, 8)),
    ("fingerone_palm_touch", 3210, 80, (10, 8)),
    ("fingertwo_tip_touch", 3370, 9, (3, 3)),
    ("fingertwo_top_touch", 3388, 96, (12, 8)),
    ("fingertwo_palm_touch", 3580, 80, (10, 8)),
    ("fingerthree_tip_touch", 3740, 9, (3, 3)),
    ("fingerthree_top_touch", 3758, 96, (12, 8)),
    ("fingerthree_palm_touch", 3950, 80, (10, 8)),
    ("fingerfour_tip_touch", 4110, 9, (3, 3)),
    ("fingerfour_top_touch", 4128, 96, (12, 8)),
    ("fingerfour_palm_touch", 4320, 80, (10, 8)),
    ("fingerfive_tip_touch", 4480, 9, (3, 3)),
    ("fingerfive_top_touch", 4498, 96, (12, 8)),
    ("fingerfive_middle_touch", 4690, 9, (3, 3)),
    ("fingerfive_palm_touch", 4708, 96, (12, 8)),
    ("palm_touch", 4900, 112, (14, 8)),
]


def add_inspire_idl_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    inspire_idl_root = repo_root / "inspire_hand_ws" / "inspire_hand_sdk" / "inspire_sdkpy"
    if inspire_idl_root.exists():
        sys.path.insert(0, str(inspire_idl_root))


def load_dds():
    add_inspire_idl_path()
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelPublisher, ChannelSubscriber
    from inspire_dds import inspire_hand_ctrl, inspire_hand_state, inspire_hand_touch

    return ChannelFactoryInitialize, ChannelPublisher, ChannelSubscriber, inspire_hand_ctrl, inspire_hand_state, inspire_hand_touch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network-interface", default=None, help="DDS NIC, e.g. enp1s0.")
    parser.add_argument("--hand", choices=["left", "right"], required=True)
    parser.add_argument("--ip", required=True, help="Inspire hand Modbus TCP IP.")
    parser.add_argument("--port", type=int, default=6000)
    parser.add_argument("--device-id", type=int, default=1)
    parser.add_argument("--frequency", type=float, default=20.0)
    parser.add_argument("--no-touch", action="store_true", help="Do not read/publish tactile registers.")
    return parser.parse_args()


def hand_suffix(hand: str) -> str:
    return "l" if hand == "left" else "r"


def read_registers(client: ModbusTcpClient, address: int, count: int, device_id: int, data_type: str):
    response = client.read_holding_registers(address, count, device_id)
    if response.isError():
        raise RuntimeError(f"Modbus read failed: addr={address}, count={count}, device={device_id}")
    if data_type == "short":
        packed = struct.pack(">" + "H" * count, *response.registers)
        return list(struct.unpack(">" + "h" * count, packed))
    if data_type == "byte":
        values = []
        for reg in response.registers:
            values.append((reg >> 8) & 0xFF)
            values.append(reg & 0xFF)
        return values
    raise ValueError(f"Unsupported data type: {data_type}")


class InspireFtpBridge:
    def __init__(self, args: argparse.Namespace):
        (
            ChannelFactoryInitialize,
            ChannelPublisher,
            ChannelSubscriber,
            inspire_hand_ctrl,
            inspire_hand_state,
            inspire_hand_touch,
        ) = load_dds()

        try:
            if args.network_interface:
                ChannelFactoryInitialize(0, args.network_interface)
            else:
                ChannelFactoryInitialize(0)
        except TypeError:
            ChannelFactoryInitialize(0)

        self.args = args
        self.inspire_hand_state = inspire_hand_state
        self.inspire_hand_touch = inspire_hand_touch
        self.lock = threading.Lock()
        self.client = ModbusTcpClient(args.ip, port=args.port)
        if not self.client.connect():
            raise ConnectionError(f"Could not connect to Inspire hand Modbus server at {args.ip}:{args.port}")
        self.client.write_register(1004, 1, args.device_id)  # reset errors, same as vendor SDK

        suffix = hand_suffix(args.hand)
        self.state_pub = ChannelPublisher(f"rt/inspire_hand/state/{suffix}", inspire_hand_state)
        self.state_pub.Init()
        self.touch_pub = None
        if not args.no_touch:
            self.touch_pub = ChannelPublisher(f"rt/inspire_hand/touch/{suffix}", inspire_hand_touch)
            self.touch_pub.Init()
        self.ctrl_sub = ChannelSubscriber(f"rt/inspire_hand/ctrl/{suffix}", inspire_hand_ctrl)
        self.ctrl_sub.Init(self._on_ctrl, 10)

    def _on_ctrl(self, msg) -> None:
        with self.lock:
            if msg.mode & 0b0001:
                self.client.write_registers(1486, list(msg.angle_set), self.args.device_id)
            if msg.mode & 0b0010:
                self.client.write_registers(1474, list(msg.pos_set), self.args.device_id)
            if msg.mode & 0b0100:
                self.client.write_registers(1498, list(msg.force_set), self.args.device_id)
            if msg.mode & 0b1000:
                self.client.write_registers(1522, list(msg.speed_set), self.args.device_id)

    def read_state_msg(self):
        kwargs = {}
        with self.lock:
            for name, address, count, data_type in STATE_REGISTERS:
                kwargs[name] = read_registers(self.client, address, count, self.args.device_id, data_type)
        return self.inspire_hand_state(**kwargs)

    def read_touch_msg(self):
        kwargs = {}
        with self.lock:
            for name, address, count, _shape in TOUCH_REGISTERS:
                kwargs[name] = read_registers(self.client, address, count, self.args.device_id, "short")
        return self.inspire_hand_touch(**kwargs)

    def run(self, should_stop) -> None:
        period_s = 1.0 / self.args.frequency
        count = 0
        start_s = time.monotonic()
        while not should_stop():
            loop_s = time.monotonic()
            state_msg = self.read_state_msg()
            self.state_pub.Write(state_msg)
            if self.touch_pub is not None:
                self.touch_pub.Write(self.read_touch_msg())

            count += 1
            if count % max(1, int(self.args.frequency)) == 0:
                elapsed = time.monotonic() - start_s
                angle = np.asarray(state_msg.angle_act)
                print(
                    f"{self.args.hand} bridge: {count / elapsed:.2f} Hz, "
                    f"angle_act={np.array2string(angle, precision=0, suppress_small=True)}"
                )
            time.sleep(max(0.0, period_s - (time.monotonic() - loop_s)))


def main() -> None:
    args = parse_args()
    if args.frequency <= 0:
        raise ValueError("--frequency must be positive")

    stop = False

    def _handle_signal(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    bridge = InspireFtpBridge(args)
    print(
        f"Started {args.hand} Inspire FTP bridge: ip={args.ip}, "
        f"state=rt/inspire_hand/state/{hand_suffix(args.hand)}, "
        f"ctrl=rt/inspire_hand/ctrl/{hand_suffix(args.hand)}"
    )
    bridge.run(lambda: stop)


if __name__ == "__main__":
    main()
