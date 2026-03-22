# MediaMTX: Flight feedback (HLS tuning) vs WebRTC — path forward

## What the flight feedback actually says

- **Problem:** Chrome’s **native** HLS player has a fixed buffer (~30–50 s). It fills, then stalls while purging old segments → **~35 s freeze**. Not configurable.
- **Fix:** Don’t use Chrome’s native HLS. Use an **HLS.js** player page so you control buffer behavior.
- **Suggested HLS.js config (satellite / jitter-friendly):**
  - `maxBufferLength: 30`
  - `maxMaxBufferLength: 60`
  - `liveSyncDurationCount: 4` — stay ~4 segments behind live edge (headroom for jitter)
  - `liveMaxLatencyDurationCount: 7` — match MediaMTX playlist depth (e.g. `hlsSegmentCount`)
  - `lowLatencyMode: false`

So the feedback is **not** “switch to WebRTC.” It’s “use HLS.js with this tuning so the 35 s stall goes away.”

---

## Best path forward with MediaMTX

### 1. Do the HLS.js tuning first (recommended)

- **Effort:** Low. You’re already on HLS and already use HLS.js in the share (and overlay) player. Add the options above to the Hls constructor.
- **Risk:** Low. Same protocol, same pipeline; only buffer policy changes.
- **Outcome:** Removes the Chrome-native stall and gives predictable buffering over satellite/jitter.
- **Latency:** HLS will still be segment-based (typically ~8–15 s end-to-end with 4-segment sync). Acceptable for many “live intel” use cases; not sub-second.

**Action:** Apply the flight-recommended HLS.js config everywhere viewers see the stream (share link player, watch player, overlay viewer). Ensure **no** playback path uses Chrome’s native HLS (i.e. always use the HLS.js page, including on Chrome).

### 2. WebRTC: when to consider it

- **Pros:** Sub-second latency when the path is good; good for real-time control/telemetry-style use cases.
- **Cons over satellite (Ku / Viasat):**
  - High RTT and jitter hurt WebRTC (NACK, retransmits, congestion control).
  - More sensitive to packet loss than HLS (which can hide loss in segment retries).
  - May need TURN/STUN and codec tuning; deployment is more involved.
- **Reality:** If the bottleneck is the link (satellite delay, loss, jitter), WebRTC often doesn’t improve things and can be worse than well-tuned HLS.

**Recommendation:** Treat WebRTC as a **second step**, only if:
- HLS.js tuning is in place and tested on the same flights, and
- You still need lower latency than HLS can give, and
- You’re willing to test WebRTC over the same satellite path and compare.

### 3. Summary

| Path              | Effort | Risk   | Fixes 35 s stall? | Latency        |
|-------------------|--------|--------|--------------------|----------------|
| HLS.js + tuning   | Low    | Low    | Yes                | ~8–15 s (tuned)|
| WebRTC            | Higher | Medium | N/A (different issue) | Sub-second (if link allows) |

**Best path:** Implement the flight feedback (HLS.js with the suggested buffer/live-sync params) everywhere in MediaMTX that serves the stream. Re-test on the next flight. If latency is still too high for the mission, then evaluate WebRTC on the same link with a clear before/after.

---

## Code: where to apply the tuning

- **mediamtx-installer (core):** Share link player (`/shared/<token>`) — update the `new Hls({...})` options.
- **infra-TAK overlay:** Watch and viewer pages that use HLS.js — same options so satellite users never hit Chrome native and get consistent buffering.

Optionally add a “Satellite / high jitter” preset in the config editor (or env) that flips these HLS.js options so you can turn them on only when needed.
