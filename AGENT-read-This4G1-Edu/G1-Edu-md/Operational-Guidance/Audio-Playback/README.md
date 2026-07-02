# G1 - Audio Playback Instructions

Source URL: `https://support.unitree.com/home/en/G1_developer/audio_playback -->
<html lang="en" class="mdl-js"><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><style data-emotion="css" data-s=""></style><link rel="icon" type="image/svg+xml" href="https://support.unitree.com/favicon-front.svg"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no"><title>宇树科技 文档中心</title><script charset="utf-8" src="./宇树科技 文档中心_files/UrlChangeTracker.js"></script><script src="./宇树科技 文档中心_files/hm.js"></script><script>var _hmt = _hmt || [];
    (function (`

Original HTML: `Operational-Guidance/Audio-Playback/宇树科技 文档中心.html`

Last updated: ``

## Agent Notes

- No extra repo-specific note beyond the extracted document content.

## Extracted Document Content

# G1 - Audio Playback Instructions

The G1 audio playback function supports audio from either recording directly within the mobile app or importing external audio files . This document primarily covers the usage method for importing external audio .

## Function Location

[Unitree Explore APP] → [go] → [More Functions] → [Player]

## Version Information

### APP Version

- Android: V1.6.1 or above
- IOS: V1.6.1 or above

### Firmware Version

Upgrade the following three components:

- Vul Service: Version 2.0.4.4 or above
- Webrtc Bridge: Version 1.0.7.5 or above
- Audio Hub: Version 1.0.1.0 or above

## Audio File Specifications

### Format Requirements

- Format : WAV
- Sample Rate : 16kHz
- Channels : Mono (The device only supports mono audio; stereo may cause playback issues)
- Speaker : Stanley (All device audio uniformly uses this speaker)

### Recommendations

- When synthesizing audio, set the volume to 100% to ensure maximum playback volume.

### Constraints

- Audio file size must not exceed 10MB
- Recording duration must not exceed 3 minutes
