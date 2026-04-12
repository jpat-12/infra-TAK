# Node-RED Deploy Cheat Sheet

After every `docker cp flows.json` + `docker restart nodered`, you need to reconfigure these settings in the Node-RED editor. Copy-paste from below.

---

## 1. TLS Config Node (TAK Server TLS)

Double-click any HTTP Request or TCP Out node → click the pencil icon next to the TLS config.

**Certificate:**
```
/certs/nodered-global-datasyncfeed.pem
```

**Private Key:**
```
/certs/nodered-global-datasyncfeed.key
```

Leave CA blank. Uncheck "Verify server certificate".

---

## 2. TCP Out Node (CoT stream to TAK)

Double-click the "CoT stream to TAK" tcp out node.

**Host:**
```
host.docker.internal
```

**Port:**
```
8089
```

**Type:** Connect to  
**TLS:** TAK Server TLS (same config from step 1)

---

## 3. Re-save Configurator Settings

Go to:
```
http://<server-ip>:1880/configurator
```

1. Open **TAK Settings** and hit **Save**
2. Open the feed config (e.g. CA AIR INTEL) and hit **Save**

This restores flow context that gets wiped on container restart.

---

## 4. Deploy

Hit the **Deploy** button in the Node-RED editor.

Wait ~30 seconds for the auto-poll to fire. Check the debug sidebar for:
- `SA ident sent for uid: nodered-global-airdata`
- `CA AIR INTEL: 10 CoT events built from 10 features`
- `CA AIR INTEL reconcile: 10 streamed, 0 PUT, 0 DELETE...`

---

## Full server-side deploy (SSH)

### Recommended: use deploy script (preserves TLS + TCP config)

```bash
cd ~/infra-TAK && bash nodered/deploy.sh
```

The script does: `git pull` → `build-flows.js` → reads flow context for `creatorUid` → auto-populates TLS cert paths (`/certs/{creatorUid}.pem/.key`) → preserves any existing TLS/TCP overrides → `docker cp` → `docker restart`.

**After the first time** you configure TAK Settings in the configurator (which sets `creatorUid`), every subsequent deploy auto-configures TLS. No manual steps.

Configurator configs (flow context) survive restarts on the Docker volume.

### Manual deploy (first-time or if script fails)

```bash
cd ~/infra-TAK && git pull && node nodered/build-flows.js && docker cp nodered/flows.json nodered:/data/flows.json && docker restart nodered
```

Then do steps 1-4 above in the Node-RED editor.
