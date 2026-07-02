# SDK-Overview

Source URL: `https://support.unitree.com/home/en/G1_developer/sdk_overview -->
<html lang="en" class="mdl-js"><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><style data-emotion="css" data-s=""></style><link rel="icon" type="image/svg+xml" href="https://support.unitree.com/favicon-front.svg"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no"><title>宇树科技 文档中心</title><script charset="utf-8" src="./宇树科技 文档中心_files/UrlChangeTracker.js"></script><script src="./宇树科技 文档中心_files/hm.js"></script><script>var _hmt = _hmt || [];
    (function (`

Original HTML: `Application-Development/SDK-Overview/宇树科技 文档中心.html`

Last updated: ``

## Agent Notes

- No extra repo-specific note beyond the extracted document content.

## Extracted Document Content

![](./宇树科技 文档中心_files/85b2dfd399ed4a96b06952d28fde02f7_8000x4500.png)

> The current software version does not support GST video streaming yet.

G1 uses DDS as the message middleware, and the main data interaction adopts two modes: subscription/publish and request/response .

- Subscription/Publish: The receiver subscribes to a message, and the sender sends messages to the receiver according to the subscription list. It is mainly used for medium-to-high frequency or continuous data interaction.
- Request/Response: Question and answer mode, data acquisition or operation is achieved through requests. Used for data interaction at low frequency or function switching.

The calling method of the request response interface: API call , Functional call

- API call: Similar to restapi, fill in the request content and request topic when sending the request, and accept the reply in the corresponding response topic. The reply adopts broadcast mode and determines the corresponding relationship between the request and the response according to the UUID.
- Functional call: The syntactic sugar of API call mode, which encapsulates API calls into function calls to facilitate user use.

Development Kit:

unitree_sdk2: C++ development library
