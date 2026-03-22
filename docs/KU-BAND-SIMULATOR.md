# Ku-band link simulator

The Ku-band simulator impairs **incoming** traffic on the **receiver** (this VPS) so you can test HLS over a bad link without a flight. Scripts and config live under `/opt/mediamtx-webeditor/ku-band-simulator/` (or `MEDIAMTX_SIMULATOR_DIR`).

## Current flow (manual)

1. Copy simulator scripts to `/opt/mediamtx-webeditor/ku-band-simulator/`.
2. Copy `ku_band_simulator.conf.example` → `ku_band_simulator.conf`.
3. In `ku_band_simulator.conf` set:
   - **SOURCE_IP** — IP of the host **sending** the stream to this box (the remote SRT/RTSP server).
   - **INTERFACE** — Network interface on **this** VPS that receives that traffic (e.g. `eth0`, `ens3`).
4. Use the UI: **Turn simulator ON** / **Turn simulator OFF**.

For an **external SRT source** where MediaMTX is the **caller** (e.g. `srt://stream.test8.taktical.net:8890?...`):

- **SOURCE_IP** = IP of `stream.test8.taktical.net` (resolve with `getent hosts stream.test8.taktical.net` or `dig +short stream.test8.taktical.net`).
- **INTERFACE** = the interface on this VPS used for outbound connections to that host (often the default route; e.g. `ip route get <SOURCE_IP>` then use that interface, or the main interface like `eth0`).

## Desired flow: “Turn on for this source”

**Goal:** One click per external source to turn the simulator on for that stream, without editing the conf file by hand.

1. In **Configured External Sources**, add a per-row action: **Simulate link** (or **Turn simulator on for this source**).
2. On click:
   - Parse the source URL (e.g. SRT/RTSP) and get the **host** (e.g. `stream.test8.taktical.net`).
   - Resolve host → **SOURCE_IP** (backend or frontend).
   - **INTERFACE**: either auto-detect (e.g. route to SOURCE_IP) or prompt once and remember (e.g. in conf or browser).
   - Write `ku_band_simulator.conf` with SOURCE_IP and INTERFACE (create from example if missing).
   - Call the existing simulator ON API.
3. **Turn simulator OFF** stays global (or could show “currently impairing SOURCE_IP” in the panel).

**Where to implement:** Core logic and UI live in **mediamtx-installer** (config editor). Infra-TAK only deploys that editor and the simulator scripts directory; no changes needed in infra-TAK for the “per-source” button beyond ensuring scripts and conf path remain as above.

## Files on VPS

| Item | Path |
|------|------|
| Scripts dir | `/opt/mediamtx-webeditor/ku-band-simulator/` |
| Config | `ku_band_simulator.conf` (from `ku_band_simulator.conf.example`) |
| Env override | `MEDIAMTX_SIMULATOR_DIR` if using a different directory |
