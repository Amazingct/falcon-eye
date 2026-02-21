# Public Test Cameras for Falcon-Eye

Verified working as of 2026-02-20. Use these for testing HTTP/MJPEG camera support.

## ✅ Working

| # | Name | URL | Resolution | Protocol | Notes |
|---|------|-----|-----------|----------|-------|
| 1 | Kaiskuru Skistadion, Norway | `http://77.222.181.11:8080/mjpg/video.mjpg` | 800x500 | HTTP/MJPEG | Snow/houses view. Stable, consistent across multiple tests. |
| 2 | Hotel Lobby (EU) | `http://158.58.130.148/mjpg/video.mjpg` | 640x480 | HTTP/MJPEG | Flaky — rate-limits after a few connections. Returns 503 under load. |

## ❌ Dead (as of 2026-02-20)

| URL | Notes |
|-----|-------|
| `http://camera.buffalotrace.com/mjpg/video.mjpg` | Buffalo Trace Factory — no response |
| `http://pendelcam.kip.uni-heidelberg.de/mjpg/video.mjpg` | Kirchhoff Institute — no response |
| `http://webcam01.ecn.purdue.edu/mjpg/video.mjpg` | Purdue Engineering — no response |
| `http://webcam.mchcares.com/mjpg/video.mjpg` | Hospital San Bernardino — no response |
| `http://195.196.36.242/mjpg/video.mjpg` | Soltorget Pajala, Sweden — redirects |
| `http://takemotopiano.aa1.netvolante.jp:8190/nphMotionJpeg?Resolution=640x480&Quality=Standard&Framerate=30` | Piano Factory — no response |
| `http://61.211.241.239/nphMotionJpeg?Resolution=320x240&Quality=Standard` | Tokyo House — returns data but no frames |
| `http://honjin1.miemasu.net/nphMotionJpeg?Resolution=640x480&Quality=Standard` | Tsumago Hills — returns data but no frames |
| `rtsp://170.93.143.139/rtplive/470011e600ef003a004ee33696235daa` | Highway RTSP — no response |
| `rtsp://wowzaec2demo.streamlock.net/vod/mp4:BigBuckBunny_115k.mp4` | Wowza demo — no response |
| `rtsp://62.109.19.230:554/myaanee` | Anime loop — connection refused |

## Tips
- Public cameras go offline frequently — always test before demo
- HTTP/MJPEG cameras work best with Falcon-Eye's HTTP proxy mode (no ffmpeg needed)
- RTSP public cameras are nearly extinct — most require auth now
- For reliable testing, use your own cameras (USB webcam or Tuya/ONVIF IP cam)
