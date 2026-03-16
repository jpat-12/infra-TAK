# HLS fix: client vs server (for Conner)

Claude’s feedback in the “video firis feedback” doc said to **“serve an HLS.js player page.”** That wording can sound like the **server** is doing the HLS work. It isn’t.

## What “serve” means here

- **Server:** Serves two things:
  1. The **web page** (HTML + JS) that contains the HLS.js player code.
  2. The **HLS stream** (m3u8 + .ts segments), which is MediaMTX (or your stream server) as it already does.

- **Browser (client):** Does all the HLS “smart” work:
  - Loads the HLS.js script.
  - Fetches the m3u8 and segments from the server.
  - **Buffers** with the tuned settings (e.g. `maxBufferLength`, `liveSyncDurationCount`, `liveMaxLatencyDurationCount`, `lowLatencyMode: false`).
  - Decodes and plays video.

So “serve an HLS.js player page” = **host that page on the server** so users can open it. The **buffer behavior and playback logic run entirely in the viewer’s browser**, not on the server.

## What does NOT run on the server

- Buffer length limits.
- “Stay 4 segments behind live.”
- Deciding when to purge or refill the buffer.
- Any of the HLS.js tuning that fixes the ~35s stall.

All of that is **client-side** (HLS.js in the browser).

## What the server keeps doing

- Delivering the **player page** (our watch page with HLS.js).
- Delivering the **stream** (MediaMTX serving m3u8 and segments).

No new server-side HLS processing or “buffer work” was added. So Conner doesn’t need to expect the server to “do something” extra for this fix; the change is in what the **client** does with the same stream.
