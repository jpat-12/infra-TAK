# CloudTAK — Video from CoT (RTSP / SRT / RTMP): upstream brief

**Audience:** CloudTAK / dfpc-coe maintainers  
**Intent:** Describe failed playback in the field, what we think is wrong in software, and what we’d like the product to do. We are happy to test fixes or contribute PRs if direction aligns.

---

## Executive summary

We need **standard live ingest URLs** carried in CoT (**`rtsp://` / `rtsps://` / `rtmp://` / `rtmps://` / `srt://`**) to **play in the built-in map video player** (HLS.js) **without** a separate “video channel” or manual lease workflow. **If an operator can see the asset on the map from CoT, they should be allowed to open its video** (same trust boundary as the track).

In deployments we’ve tried, **video from CoT never successfully played** end-to-end. We’re not sure whether the failure was config, MediaMTX integration, or client URL construction — but code review suggests **hardcoded ports / URLs in `video-service.ts`** and **inconsistent handling of `proxy` by scheme** are likely contributors behind TLS and reverse-proxy setups.

**Ideal:** CloudTAK talks to **our** MediaMTX only (see below). **Minimum acceptable:** Your bundled MediaMTX behaves as a **pull relay**: CoT carries a URL; on **Play**, you create a path whose **`source`** is that **external** URL (our RTSP/SRT endpoint, or whatever we put in CoT). **Leases and your existing player are fine** — we’re asking for **reliable “external source” ingest** and **correct HLS URLs** back to the browser, not a UX rewrite.

---

## Reference flow (how we expect it to work)

1. **Drone → our MediaMTX** — We ingest, record, and enforce **our** public/private / token / LDAP story on **our** stack.
2. **TAK Server / CoT** — The marker carries **our video URL** (e.g. **`rtsp://…`** or **`srt://…`** pointing at our side, or another **normal** ingest URL).
3. **Operator in CloudTAK** — Sees the asset on the map, hits **Play**.
4. **Your stack** — **Your** MediaMTX (bundled is OK for this story) adds a path with **`source` = that CoT URL** (external pull), runs it through **your** lease/path machinery if you want, and the **same HLS player** plays the relayed stream.

So from your perspective it’s **“external source”** — not special-casing our product name, just **any** RTSP/SRT/RTMP URL CoT hands you. **That** path should work end-to-end.

---

## Lease-first publish vs “whatever media server they already use”

**What you have today (and it’s useful):** create a **lease**, put **your** publish/read URLs into the **drone / encoder**, and video flows into **your** MediaMTX story. That’s great for teams who standardize on CloudTAK’s video pipeline.

**What we need for real TAK Server sharing:** many users on **the same TAK Server** will **not** all use the same media stack. One unit runs **their** MediaMTX, another uses **a different** host, a vendor pushes **RTSP** from their own appliance — and **CoT already carries a URL** that points at **their** server, not yours.

We want **anyone** who can use that TAK Server to **keep publishing to whatever media server they use**; CloudTAK should **not** require “re-home the drone to our lease” as the **only** path to watch. **Play** should mean: **read the URL from CoT** (or linked detail) and **pull** it as **external `source`** (plus your leases internally if you still want bookkeeping). Same map, **heterogeneous** video backends — that’s normal for coalition / multi-tenant / multi-vendor TAK.

**Authorization:** If a track is visible in CloudTAK, the user **already authenticated** to your app and **already passed whatever TAK / mission / server access** applies. Requiring a **separate** video-only channel or lease gate for “can I watch this CoT URL?” is redundant for our use case — **credentials and server policy already decided who sees the map.**

**Parity with other TAK clients:** **ATAK / WinTAK** don’t make operators jump through a **separate CloudTAK-style lease / video-channel** model to watch video that’s already tied to a track and CoT. Operators expect **the same mental model** in the browser: **see asset → open video from what CoT already says**. CloudTAK should **converge** on that expectation for field adoption.

---

## Operator-owned MediaMTX (preferred longer term)

*The **reference flow** above still uses your MediaMTX as the playback edge. Here we ask to skip that relay entirely when possible.*

### What we already have

- **One** MediaMTX deployment we control: **recordings**, **viewer vs admin**, **public/private (e.g. group-scoped) streams**, **short-lived or revocable links** from active streams, reverse-proxy–friendly HLS URLs, etc.

### What we need from CloudTAK

1. **Pluggable media backend** — Treat **`media::url` (or equivalent)** as “**the only MediaMTX this CloudTAK instance uses**”: all **path add/remove**, **config queries**, and **playback URL generation** target **our** API and **our** public HLS base (TLS, path prefix, query tokens if any).
2. **No dependency on the compose `media` service** for operators who opt in to **external media** — or a documented, supported path to **disable** bundled media and **point** exclusively at an external base URL.
3. **Auth contract** — Today the API appears to use **JWT / internal media auth** against **dfpc-coe media-infra**. We need either:
   - **Documented compatibility** with **stock MediaMTX API** + our auth (API token, mTLS, reverse-proxy headers, etc.), or  
   - A **small adapter** interface we can run in front of our MediaMTX that speaks whatever CloudTAK’s API client expects, **or**  
   - **Pluggable auth** in CloudTAK (configurable headers / token for MediaMTX management calls).
4. **Correct HLS URLs for the browser** — Whatever `protocols.hls` returns must be URLs **our** edge already serves (e.g. **HTTPS**, **same-site cookies / auth**, **share tokens**), not hardwired host:port assumptions from the bundled stack.

### Why we’re asking

We **won’t** give up **recordings, ACL model, and share links** to get video on the map. The goal is **CloudTAK for map + TAK UX**, **our stack for video policy and operations**.

---

## Desired behavior (product)

1. CoT (or equivalent detail on the marker) exposes a **single, parseable** stream URL using **normal protocols** (RTSP, SRT, RTMP as supported by your MediaMTX stack).
2. User opens **Watch / video** from that marker.
3. Backend ensures a **MediaMTX path** exists with **`source`** set to that URL (pull), and the UI receives a correct **`protocols.hls`** URL for **HLS.js**.
4. **Authorization:** Tied to **already being able to see that CoT / marker**, not to a **separate lease channel** or second permission product. (Optional **strict mode** for customers who want stronger separation.)

---

## What we think is wrong (technical)

These points refer to the current **dfpc-coe/CloudTAK** layout (e.g. `api/lib/control/video-service.ts`, `FloatingVideo.vue`, `routes/video-lease.ts`).

### 1. HLS / API URLs and hardcoded ports

In **`protocols()`**, HLS playback URLs are built with **fixed port `9997`** (and API calls elsewhere assume fixed MediaMTX API port). In real deployments, MediaMTX often sits behind **HTTPS on 443**, **different host ports**, or **path-based reverse proxies**. Result: a path may be **created** on MediaMTX, but the **browser is given a wrong HLS URL** → player never starts or 404s.

**Ask:** Build **public** playback (and API) URLs from **configured media base URL + actual `VideoConfig` addresses** (or explicit settings), not literals.

### 2. `proxy` handling differs by scheme

For **`lease.proxy`**, **non-HTTP(S)** sources trigger a **POST** to register a path with `source: proxy` (good for RTSP/SRT/RTMP-style URLs if MediaMTX accepts them). For **HTTP(S)**, the code path **validates with `fetch`** but **does not** register the same **MediaMTX `source`** pattern as RTSP — so behavior is **not uniform** across “normal” stream URLs vs HLS manifests.

**Ask:** Document intended behavior per scheme; align implementation (either **always** register pull sources when MediaMTX supports them, or **explicitly** support **direct `.m3u8`** for HTTPS without broken intermediate state).

### 3. Lease model vs operator expectation

The implementation uses **VideoLease** (ephemeral or not) to tie **paths, credentials, channel ACL, recording, and TAK video connection publishing**. Operators experience that as **“why do I need a lease when I already see the drone?”**

**Ask:** Not necessarily remove leases internally — consider **auto ephemeral lease from CoT URL** with **authorization derived from map/CoT visibility**, and **no requirement** for a separate “video channel” for the basic case.

### 4. `/api/video/active` and “leasable”

Logic depends on **URL shape and hostname** relative to configured media URL. CoT URLs that are **valid RTSP/SRT** but don’t match expected patterns may fail **leasable** checks, so the client never creates the proxy path.

**Ask:** Clear rules and tests for: external host RTSP/SRT/RTMP URLs, same-host paths, and credentials in URL.

---

## What worked / didn’t work for us

- **Never achieved:** Reliable **CoT-provided RTSP/SRT** → **in-map player** playback in the field (after prior attempts).
- **We’re open to:** Re-testing on a **tagged release** once fixes land, or **contributing a PR** for config-driven URLs + CoT-first auth if you’re willing to review.

---

## Suggested next steps for maintainers

1. Publish a **first-class “external MediaMTX”** story: config knobs, **auth model**, and **compatibility matrix** (bundled **media-infra** vs **vanilla MediaMTX** vs **proxied / tokenized HLS**).
2. Confirm **intended** support matrix: **which `proxy` schemes** work when the **management API** is not the bundled container.
3. Add **integration tests** or a **minimal repro**: CoT-like URL → path on **external** MediaMTX → **HLS URL** the browser can load → **HLS.js** play.
4. Replace **hardcoded ports** in **`video-service.ts`** with **configuration-derived** public URLs (critical for **our** reverse proxy and share links).
5. Optionally: **design note** on **map visibility = video open** vs **lease.channel** for enterprise hardening.

---

## Contact / context

This brief is from operators integrating CloudTAK with TAK Server and field video feeds. We can provide **sanitized CoT examples**, **example stream URLs**, and **network topology** (TLS termination, reverse proxy) under NDA or in a private thread if helpful.

---

*Document version: 2026-03-20 (rev. f: ATAK / WinTAK parity) — for forwarding to CloudTAK / dfpc-coe developers.*
