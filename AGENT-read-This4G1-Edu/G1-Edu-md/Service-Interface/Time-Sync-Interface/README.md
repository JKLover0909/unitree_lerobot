# Installing and Configuring Chrony Clock Source

Source URL: `https://support.unitree.com/home/en/G1_developer/time_sync_interface -->
<html lang="en" class="mdl-js"><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><style data-emotion="css" data-s=""></style><link rel="icon" type="image/svg+xml" href="https://support.unitree.com/favicon-front.svg"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no"><title>宇树科技 文档中心</title><script charset="utf-8" src="./宇树科技 文档中心_files/UrlChangeTracker.js"></script><script src="./宇树科技 文档中心_files/hm.js"></script><script>var _hmt = _hmt || [];
    (function (`

Original HTML: `Service-Interface/Time-Sync-Interface/宇树科技 文档中心.html`

Last updated: ``

## Agent Notes

- No extra repo-specific note beyond the extracted document content.

## Extracted Document Content

The PC1 inside G1 features a built-in time synchronization source. Every time G1 is set to WiFi mode, this clock source performs network time synchronization. You can use Chrony (recommended) or Systemd-Timesyncd to synchronize the clock with G1's PC1.

This document applies to G1 robots with firmware version greater than 1.5.1 .

Fluctuations caused by time synchronization

When PC1 performs network time synchronization, it may cause short-term time fluctuations. Therefore, it is recommended to disable G1's WiFi mode when using programs that rely on system time.

## Installing and Configuring Chrony Clock Source

First, you need to install Chrony:

```
sudo apt-get install chrony
```

Modify the configuration file /etc/chrony/chrony.conf and add the following configuration:

```
# Use internal network NTP server
server 192.168.123.161 iburst prefer

# If the network is not ready at startup, allow subsequent synchronization
makestep 1.0 3

# Allow hardware clock synchronization
rtcsync

# Logs (useful for debugging)
log tracking measurements statistics
logdir /var/log/chrony
```

![https://doc-cdn.unitree.com/static/2026/1/16/e9a384c97324408f800cb0931a3ba83e_765x689.png](./宇树科技 文档中心_files/e9a384c97324408f800cb0931a3ba83e_765x689.png)

## Restarting Chrony and Verifying Sync Status

```
sudo systemctl restart chrony
chronyc sources -v
```

During the step of restarting Chrony, you may encounter this issue:

```
(base) supportcbh@supportcbh-MDF-XX:~$ sudo systemctl status chrony.service
● chrony.service - chrony, an NTP client/server
     Loaded: loaded (/lib/systemd/system/chrony.service; enabled; vendor preset: enabled)
     Active: failed (Result: core-dump) since Wed 2026-01-07 20:24:23 CST; 5s ago
       Docs: man:chronyd(8)
             man:chronyc(1)
             man:chrony.conf(5)
    Process: 36514 ExecStart=/usr/lib/systemd/scripts/chronyd-starter.sh $DAEMON_OPTS (code=exited, status=0/SUCCESS)
    Process: 36522 ExecStartPost=/usr/lib/chrony/chrony-helper update-daemon (code=exited, status=0/SUCCESS)
   Main PID: 36519 (code=dumped, signal=SYS)

Jan 07 20:24:23 supportcbh-MDF-XX systemd[1]: Starting chrony, an NTP client/server...
Jan 07 20:24:23 supportcbh-MDF-XX chronyd-starter.sh[36516]: WARNING: libcap needs an update (cap=40 should have a name).
Jan 07 20:24:23 supportcbh-MDF-XX chronyd[36519]: chronyd version 3.5 starting (+CMDMON +NTP +REFCLOCK +RTC +PRIVDROP +SCFILTER +SIGND +ASYNCDNS +SECHASH +IPV6 -DEBUG)
Jan 07 20:24:23 supportcbh-MDF-XX chronyd[36519]: Loaded seccomp filter
Jan 07 20:24:23 supportcbh-MDF-XX systemd[1]: Started chrony, an NTP client/server.
Jan 07 20:24:23 supportcbh-MDF-XX systemd[1]: chrony.service: Main process exited, code=dumped, status=31/SYS
Jan 07 20:24:23 supportcbh-MDF-XX systemd[1]: chrony.service: Failed with result 'core-dump'.
```

Chrony called instructions that are prohibited by the system security filter. Solution: Disable Seccomp filtering. Modify /etc/default/chrony to fix this issue.

```
DAEMON_OPTS="-F 0"
```

To verify whether Chrony has established synchronization with the PC1 synchronization source, use the following commands.

```
chronyc sources -V
chronyc tracking
```

![https://doc-cdn.unitree.com/static/2026/1/16/0cfbcd0eeca647e4bd31eb9a6625b503_801x494.png](./宇树科技 文档中心_files/0cfbcd0eeca647e4bd31eb9a6625b503_801x494.png)

## Installing and Configuring Systemd-Timesyncd Clock Source

Mutually exclusive relationship between Chrony and Systemd-Timesyncd

Chrony and systemd-timesyncd are mutually exclusive; installing chrony will automatically uninstall systemd-timesyncd. You can switch back to the Systemd-Timesyncd clock source using apt install (not recommended).

```
sudo systemctl unmusk systemd-timesyncd
sudo apt install systemd-timesyncd
sudo systemctl enable --now systemd-timesyncd
```

Edit the configuration file /etc/systemd/timesyncd.conf with the following content:

```
[Time]
NTP=192.168.123.161
FallbackNTP=
PollIntervalMinSec=32
PollIntervalMaxSec=2048
```

![https://doc-cdn.unitree.com/static/2026/1/16/9b50e7f8440945bea5f18c827b4fb5c0_750x417.png](./宇树科技 文档中心_files/9b50e7f8440945bea5f18c827b4fb5c0_750x417.png)

Subsequently, enable and restart the service:

```
sudo systemctl enable systemd-timesyncd
sudo systemctl restart systemd-timesyncd
```

Verify synchronization status:

![https://doc-cdn.unitree.com/static/2026/1/16/b12e852c0e2a44faab432aa022ffa61f_741x515.png](./宇树科技 文档中心_files/b12e852c0e2a44faab432aa022ffa61f_741x515.png)
