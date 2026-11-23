# LifeJacket Camera

A foreground iPhone companion for a motors-off DJI Mini 2 / RC-N1 bench test.
The app sends camera H.264 to a paired laptop relay and shows motor status,
horizontal speed and altitude on the phone. The relay forwards the feed to an
existing LifeJacket observation. The coordinator confirms frames in LifeJacket.

## Build on a Mac

From this directory run `xcodegen generate` and `pod install`, then open
`LifeJacketCamera.xcworkspace` in Xcode. Select an Apple signing team and bundle
identifier, register that same identifier with DJI, and set the target's
`DJI_SDK_APP_KEY` build setting. Install to a physical iPhone and use Internet
access for SDK registration. Close DJI Fly before connecting the iPhone to the
RC-N1 with the companion open.

## Run the bench

Follow the [LifeJacket stream setup](../../docs/drone_live_workflow.md) on the
laptop. Leave RTMP on loopback and set `DRONE_STREAM_PUBLISH_BASE` to
`rtmp://127.0.0.1:19350/live`. Open a fresh observation session and save its
publishing address in a local text file with permissions 600. The relay does
not require entering that RTMP address on the phone.

From the repo root and the backend Python environment, run:

~~~sh
python scripts/dji_iphone_relay.py \
  --bind <laptop-private-ip> \
  --grant-url-file <private-address-file>
~~~

On the same trusted Wi-Fi, enter the displayed WebSocket address and pairing
code on the iPhone. Tap **Start camera relay** and confirm the camera preview
moves in LifeJacket. Save one suggestion, stop the relay and confirm the stale
preview clears. Start again while the grant remains valid. Use `--fps 24`
or `--fps 25` when that is the nominal source rate. The relay accepts just
one paired publisher and uses cleartext WebSocket on the private LAN.

Keep the aircraft powered with the motors off. Compare the time to first
preview, a Tim suggestion and reconnect against DJI Fly on the same network.
The companion does not control flight or send telemetry off the phone. The
iOS build and real camera compatibility require Xcode and a device bench test.

[DJI iOS SDK 4.16.2](https://github.com/dji-sdk/Mobile-SDK-iOS)
