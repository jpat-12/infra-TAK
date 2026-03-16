# Ku-band link simulator — synopsis for Conner

## What it does

Simulates a **bad satellite-like link** (e.g. Viasat Ku-band) so you can test HLS playback over delay, jitter, and loss **without flying**. It only impairs traffic **coming into** the **receiver** server; the sender and the rest of the network are unchanged.

**Use case:** Receiver (B) pulls an external source from sender (A). Run the simulator **on B**. It adds delay/jitter/loss to the A→B path. You then watch the stream on B (e.g. Active Streams) and see how the player behaves on a “bad link.”

---

## Where it runs

- **Receiver box only** — the MediaMTX server that **pulls** the stream (external source). Not on the sender.
- **Tech:** Linux `tc` (traffic control) + `ifb` (intermediate functional block). Ingress traffic from `SOURCE_IP` is redirected into a virtual interface (`ifb0`), and `netem` applies delay, jitter, and loss there.

---

## Impairment specs (defaults)

| Parameter   | Default | Meaning |
|------------|---------|--------|
| **DELAY_MS**  | 600 ms | One-way delay added to each packet (Ku-band–like). |
| **JITTER_MS** | 100 ms | ±100 ms random variation around the delay. |
| **LOSS_PCT**  | 1%     | Packet loss (percent). |

- **Config:** `ku_band_simulator.conf` (copy from `ku_band_simulator.conf.example`). Optional overrides: `DELAY_MS`, `JITTER_MS`, `LOSS_PCT`; re-run the ON script to apply.
- **Rationale:** GEO Ku-band RTT is often ~500–660 ms in the wild; ~1% loss is commonly cited for moderate rain fade. These defaults are a “bad Ku-band” ballpark, not from a single flight dataset. Tune to match real metrics if you have them.

---

## UI workflow (config editor)

- **External Sources tab**
  - **Simulate link** — Per-row button (purple) on each source that has a remote host (SRT, RTSP, RTMP, HLS). Click it to:
    - Resolve the source URL’s host to an IP.
    - Write/update `ku_band_simulator.conf` with that `SOURCE_IP` and `INTERFACE` (auto-detects interface if `eth0` doesn’t exist, e.g. `ens3`, `enp3s0`).
    - Run the simulator ON script.
  - **Turn simulator OFF** — Red button in the “Ku-band link simulator” panel. It only appears **after** you’ve turned the simulator on (e.g. via Simulate link). One click stops impairment.

- No separate “Turn simulator ON” in the panel; turning on is done only via **Simulate link** for the chosen source.

---

## VPS paths and config

| Item        | Path |
|------------|------|
| Scripts dir | `/opt/mediamtx-webeditor/ku-band-simulator/` |
| Config file | `ku_band_simulator.conf` (from `ku_band_simulator.conf.example`) |
| Env override | `MEDIAMTX_SIMULATOR_DIR` — set if you use a different directory |

- **SOURCE_IP** — IP of the host **sending** the stream to this box (e.g. the SRT/RTSP server you pull from). Set automatically when you use **Simulate link** (host from the source URL is resolved to an IP).
- **INTERFACE** — Network interface on **this** VPS that receives that traffic (e.g. `eth0`, `ens3`, `enp3s0`). Auto-detected from default route when `eth0` doesn’t exist.

Scripts need to run with **sudo**; the web editor calls them via sudo (sudoers entry for the editor user and the two scripts).

---

## Verifying it’s on (SSH on receiver)

```bash
# Your interface (example: enp3s0)
ip -o link show | grep -v "lo\|ifb"

# Simulator ON?
tc qdisc show dev enp3s0    # expect "ingress"
tc qdisc show dev ifb0      # expect "netem ... delay 600ms 100ms loss 1%"

# Traffic flowing through impairment
tc -s qdisc show dev ifb0   # packet/byte counters should increase while stream is active
```

---

## Short summary

- **What:** Impairs incoming stream traffic on the receiver with 600 ms delay, ±100 ms jitter, 1% loss (Ku-band–like).
- **Where:** Receiver only; Linux `tc` + `ifb` + `netem`.
- **UI:** “Simulate link” on a source row → sets SOURCE_IP + INTERFACE, turns simulator ON. “Turn simulator OFF” in the panel when done.
- **Specs:** Defaults above; override in `ku_band_simulator.conf` and re-run ON if you want to match specific flight/link metrics.
