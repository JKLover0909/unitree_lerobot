# Remote Controller Introduction

Source URL: `https://support.unitree.com/home/en/G1_developer/remote_control_data -->
<html lang="en" class="mdl-js"><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><style data-emotion="css" data-s=""></style><link rel="icon" type="image/svg+xml" href="https://support.unitree.com/favicon-front.svg"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no"><title>宇树科技 文档中心</title><script charset="utf-8" src="./宇树科技 文档中心_files/UrlChangeTracker.js"></script><script src="./宇树科技 文档中心_files/hm.js"></script><script>var _hmt = _hmt || [];
    (function (`

Original HTML: `Basic-Motion-Development/Remote-Control-Data/宇树科技 文档中心.html`

Last updated: ``

## Agent Notes

- No extra repo-specific note beyond the extracted document content.

## Extracted Document Content

# Remote Controller Introduction

The remote controller’s various buttons are explained as shown in the diagram. The functionality of the remote controller mainly consists of left and right joysticks and function buttons. Each joystick has two degrees of freedom and can output joystick values in the x and y directions, ranging from [-1.0~1.0] . Each function button/function button combination corresponds to a unique integer key value. The underlying service rt/lowstate stores a 40-byte raw data of the remote controller, which users can convert into a remote controller data structure for use.

![](./宇树科技 文档中心_files/5a0057f38e464df3a1bdfb806edb1334_1600x819.png)

# Remote Controller Data

Data Structures

```
typedef union {
  struct {
    uint8_t R1 : 1;
    uint8_t L1 : 1;
    uint8_t start : 1;
    uint8_t select : 1;
    uint8_t R2 : 1;
    uint8_t L2 : 1;
    uint8_t F1 : 1;
    uint8_t F2 : 1;
    uint8_t A : 1;
    uint8_t B : 1;
    uint8_t X : 1;
    uint8_t Y : 1;
    uint8_t up : 1;
    uint8_t right : 1;
    uint8_t down : 1;
    uint8_t left : 1;
  } components;
  uint16_t value;
} xKeySwitchUnion;

typedef struct {
  uint8_t head[2];
  xKeySwitchUnion btn;
  float lx;
  float rx;
  float ry;
  float L2;
  float ly;

  uint8_t idle[16];
} xRockerBtnDataStruct;
```

xRockerBtnDataStruct represents the data structure corresponding to the complete 40-byte remote controller data, and xKeySwitchUnion represents the button states.

## Data Structure Conversion

```
unitree_go::msg::dds_::LowState_ dds_low_state;
xRockerBtnDataStruct remote_key_data;
memcpy(&remote_key_data, &dds_low_state.wireless_remote()[0], 40);
```

Using the above code snippet, the raw data of the remote controller in rt/lowstate can be decoded into the remote_key_data structure.
