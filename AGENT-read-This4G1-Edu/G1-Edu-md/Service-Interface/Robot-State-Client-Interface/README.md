# RobotStateClient class

Source URL: `https://support.unitree.com/home/en/G1_developer/robot_state_client_interface -->
<html lang="en" class="mdl-js"><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><style data-emotion="css" data-s=""></style><link rel="icon" type="image/svg+xml" href="https://support.unitree.com/favicon-front.svg"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no"><title>宇树科技 文档中心</title><script charset="utf-8" src="./宇树科技 文档中心_files/UrlChangeTracker.js"></script><script src="./宇树科技 文档中心_files/hm.js"></script><script>var _hmt = _hmt || [];
    (function (`

Original HTML: `Service-Interface/Robot-State-Client-Interface/宇树科技 文档中心.html`

Last updated: ``

## Agent Notes

- No extra repo-specific note beyond the extracted document content.

## Extracted Document Content

## RobotStateClient class

RobotStateClient is a client provided by the device state service. Through RobotClient, it is convenient to control the internal services of G1, obtain service status, device status, and system resource usage information through RPC (some functional interfaces are not yet open).

This interface is reused from the device status service interface of B2. You can find the relevant resources at the following location in the SDK.

```
unitree_sdk2\include\unitree\robot\b2\robot_state //C++
unitree_sdk2py\b2\robot_state #Python
unitree_ros2\example\src\include\common\ros2_robot_state_client.h //ROS2
```

### List of interface error codes:

| Error number | Error description | Remarks |
| --- | --- | --- |
| 5201 | Service switch execution error | Server return |
| 5202 | The service is protected and cannot be turned on or off | Server return |

### Class and interface description:

| Class Name | Creation and Deconstruction |
| --- | --- |
| RobotStateClient | explicit RobotStateClient(); ~RobotStateClient(); |

| Function name | ServiceSwitch |
| --- | --- |
| Function prototype | int32_t ServiceSwitch(const std::string& name, int32_t swit, int32_t& status) |
| Function overview | Service switch. |
| Parameter | name : service name swit : switch, value 1 for on, 0 for off. status : service status after the operation is executed (0: on, 1: off) |
| Return value | Return 0 if the call is successful, otherwise return the relevant error code. |
| Remark |  |

| Function Name | SetReportFreq |
| --- | --- |
| Function Prototype | int32_t SetReportFreq(int32_t interval, int32_t duration) |
| Function Overview | Set the frequency of service status reporting |
| Parameter | interval : Set the reporting time interval in seconds duration : Set the duration in seconds |
| Return Value | If the call is successful, 0 will be returned. Otherwise, relevant error codes will be returned |
| Note | Currently, the app's service status function is used and the refresh frequency is set |

### Service Name List

| Service Name | Description |
| --- | --- |
| ai_sport | Main Motion Control Service |
| basic_service | Basic Service |
| g1_arm_example | Upper Limb Motion Service |
| vui_service | Audio and Lighting Control Service |
| unitree_slam | Navigation Service |
