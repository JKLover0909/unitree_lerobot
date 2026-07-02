# Message publishing example

Source URL: `https://support.unitree.com/home/en/G1_developer/dds_communication_routine -->
<html lang="en" class="mdl-js"><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><style data-emotion="css" data-s=""></style><link rel="icon" type="image/svg+xml" href="https://support.unitree.com/favicon-front.svg"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no"><title>宇树科技 文档中心</title><script charset="utf-8" src="./宇树科技 文档中心_files/UrlChangeTracker.js"></script><script src="./宇树科技 文档中心_files/hm.js"></script><script>var _hmt = _hmt || [];
    (function (`

Original HTML: `More-Cases/DDS-Communication-Rountine/宇树科技 文档中心.html`

Last updated: ``

## Agent Notes

- No extra repo-specific note beyond the extracted document content.

## Extracted Document Content

DDS related knowledge and communication interface description, please refer to the above 《DDS Services Interface》 The following is an example of message publishing/subscription after unitree_sdk2 has done a layer of encapsulation on DDS.

### Message publishing example

Routine path: unitree_sdk2/example/helloworld/publisher.cpp

```
#include <unitree/robot/channel/channel_publisher.hpp>
#include <unitree/common/time/time_tool.hpp>
#include "HelloWorldData.hpp"

#define TOPIC "TopicHelloWorld"

using namespace unitree::robot;
using namespace unitree::common;

int main(int argc, char **argv)
{
    if (argc < 2)
    {
      std::cout << "Usage: " << argv[0] << " networkInterface" << std::endl;
      exit(-1);
    }
    unitree::robot::ChannelFactory::Instance()->Init(0, argv[1]);
    //argv [1]  is network interface of the robot

    /*
     * New ChannelPublisherPtr
     */
    ChannelPublisherPtr<HelloWorldData::Msg> publisher = ChannelPublisherPtr<HelloWorldData::Msg>(new ChannelPublisher<HelloWorldData::Msg>(TOPIC));

    /*
     * Init channel
     */
    publisher->InitChannel();

    while (true)
    {
        /*
         * Send message
         */
        HelloWorldData::Msg msg(unitree::common::GetCurrentTimeMillisecond(), "HelloWorld.");
        publisher->Write(msg);
        sleep(1);
    }

    return 0;
}
```

### Message subscription example

Routine path: unitree_sdk2/example/helloworld/subscriber.cpp

```
#include <unitree/robot/channel/channel_subscriber.hpp>
#include "HelloWorldData.hpp"

#define TOPIC "TopicHelloWorld"

using namespace unitree::robot;
using namespace unitree::common;

void Handler(const void* msg)
{
    const HelloWorldData::Msg* pm = (const HelloWorldData::Msg*)msg;

    std::cout << "userID:" << pm->userID() << ", message:" << pm->message() << std::endl;
}

int main(int argc, char **argv)
{
    if (argc < 2)
    {
      std::cout << "Usage: " << argv[0] << " networkInterface" << std::endl;
      exit(-1);
    }
    unitree::robot::ChannelFactory::Instance()->Init(0, argv[1]);
    //argv [1]  is network interface of the robot

    /*
     * New ChannelSubscriberPtr
     */
    ChannelSubscriberPtr<HelloWorldData::Msg> subscriber = ChannelSubscriberPtr<HelloWorldData::Msg>(new ChannelSubscriber<HelloWorldData::Msg>(TOPIC));

    /*
     * Init channel
     */
    subscriber->InitChannel(std::bind(Handler, std::placeholders::_1), 1);

    sleep(5);

    /*
     * Close channel
     */
    subscriber->CloseChannel();

    std::cout << "reseted. sleep 3" << std::endl;

    sleep(3);

    /*
     * Init channel use last input parameter.
     */
    subscriber->InitChannel();

    /*
     * Loop wait message.
     */
    while (true)
    {
        sleep(10);
    }

    return 0;
}
```
