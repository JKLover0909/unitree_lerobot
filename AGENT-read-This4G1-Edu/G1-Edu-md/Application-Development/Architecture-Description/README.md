# System architecture diagram

Source URL: `https://support.unitree.com/home/en/G1_developer/architecture_description -->
<html lang="en" class="mdl-js"><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><style data-emotion="css" data-s=""></style><link rel="icon" type="image/svg+xml" href="https://support.unitree.com/favicon-front.svg"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no"><title>宇树科技 文档中心</title><script charset="utf-8" src="./宇树科技 文档中心_files/UrlChangeTracker.js"></script><script src="./宇树科技 文档中心_files/hm.js"></script><script>var _hmt = _hmt || [];
    (function (`

Original HTML: `Application-Development/Architecture-Description/宇树科技 文档中心.html`

Last updated: ``

## Agent Notes

- No extra repo-specific note beyond the extracted document content.

## Extracted Document Content

# System architecture diagram

![](./宇树科技 文档中心_files/5da5c8fdc8f84b59aa3f2f5d45add0e4_8000x6106.jpg)

> G1 will connect to the cloud service only after user authorization

# cloud service

Cloud services have several main functions :

1. Collect G1 operating data (not involving privacy), conduct fault detection and statistics.
2. Help users achieve remote operations, mainly through WebRTC. Image and control traffic can be forwarded point-to-point or through the turn server, which is not collected or analyzed by the server.
3. System upgrade iteration.

Communication for cloud services :

1. mqtt is used to establish IoT communication with each device and is responsible for monitoring faults, system upgrades, and transmitting WebRTC signaling.
2. The http service connects the App and Web front-end to establish a binding relationship between the user and the robot.
3. The turn/stun server is used to facilitate WebRTC point-to-point connections and provide server data forwarding when point-to-point connections cannot be achieved.

# G1

1. The OTA module communicates with the cloud server through mqtt and is responsible for uploading fault information, system upgrades, and forwarding WebRTC signaling.
2. The WebRTC module implements the main data pipeline with the App, including audio and video streams, radar point clouds, motion status and control instructions.
3. The Bluetooth (BLE) part is used to establish contact with the App and is mainly used for network configuration and security verification.
4. The communication between each functional module is mainly implemented by DDS. DDS IDL is compatible with ROS2 (you need to select the adapted RMW). The EDU version can call the interface through DDS or ROS2.
5. Sensor data such as motors and radars are collected through the serial port and then forwarded to the DDS middle layer.
6. G1 edu has 2 built-in computing units. PC1 is dedicated to the Unitree motion control program and is not open to the public. Developers can only use PC2 for secondary development. The IP addresses for PC2 is 192.168.123.164. Please contact our support engineers for the initial user name and password.

# App

1. User management module, connecting to Yushu management platform through HTTP Web API. Responsible for binding robot, WebRTC connection establishment and other functions.
2. G1’s Bluetooth module is used to configure the network.
3. WebRTC module, the main data traffic is realized through WebRTC, including image transmission, point cloud, motion status and control command issuance.

# Development interface

1. DDS, supports C++ and Python.
2. ROS2 interface.
3. GST, for image transmission only.
