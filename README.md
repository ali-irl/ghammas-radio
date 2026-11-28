# Ghammas Baladi — Central Broadcast Radio

A centralized 24/7 online radio system built for **Al Qubtan For Restaurants (Ghammas Baladi) — CDR Group**. It streams synchronized background music across all restaurant branches from a single web link, managed remotely through a PIN-protected HQ Studio dashboard.

---

## Live Links

* **Branch Web Player:** https://84.8.113.107.sslip.io
* **Direct Audio Mount (128 kbps MP3):** https://84.8.113.107.sslip.io/stream.mp3
* **HQ Studio Controls:** Switch to **B: HQ STUDIO** on the player *(Admin PIN provided in the evaluation submission document)*

---

## How It Works (Architecture)

The system runs as four lightweight Docker containers behind automatic HTTPS:

```text
[HQ Admin UI] ──(REST API)──▶ [FastAPI Backend] ──(Telnet / M3U)──▶ [Liquidsoap AutoDJ]
                                     │                                      │
                                (WebSockets)                          (128 kbps MP3)
                                     ▼                                      ▼
[Branch Devices] ◀──(HTTPS)── [Caddy Reverse Proxy] ◀──────────── [Icecast2 Stream Server]
```

* **Liquidsoap (`v2.2.5`):** Automated studio DJ that reads `/music/playlist.m3u`, normalizes volume, applies 2-second crossfades, and feeds a continuous stream to Icecast.
* **Icecast2:** Broadcasts the single live `/stream.mp3` feed to all branches over HTTP with `<burst-size>0</burst-size>` so every listener receives the live edge simultaneously rather than cached audio.
* **FastAPI + WebSockets (`Python 3.11`):** Powers the vintage receiver UI, pushes real-time "Now Playing" metadata and connected branch counts, and handles PIN-protected playlist management (upload, reorder, delete, skip, and global force-sync).
* **Caddy (`v2`):** Serves the UI, WebSockets, and audio stream over a single encrypted HTTPS domain (`sslip.io` + Let's Encrypt) to prevent browser mixed-content blocks.

---

## Project Structure

```text
ghammas-radio/
├── backend/
│   ├── static/index.html   # Vintage branch radio UI & HQ Studio console
│   ├── main.py             # FastAPI control plane & WebSocket state broadcaster
│   ├── Dockerfile
│   └── requirements.txt
├── config/
│   ├── icecast.xml         # Stream server limits & burst-size tuning
│   └── radio.liq           # Liquidsoap AutoDJ crossfade & playlist rules
├── music/                  # Royalty-free MP3 tracks & playlist.m3u
├── Caddyfile               # HTTPS reverse proxy routing
├── docker-compose.yml      # Multi-container orchestration
└── .env.example            # Environment variable template
```

---

## Run Locally

1. **Clone the repository and create your `.env` file:**
   ```bash
   git clone [https://github.com/ali-irl/ghammas-radio.git](https://github.com/ali-irl/ghammas-radio.git)
   cd ghammas-radio
   cp .env.example .env
   ```
2. **Start all services with Docker:**
   ```bash
   docker compose up -d --build
   ```
3. **Open the player:**
   * Local URL: `http://localhost:8080`
   * HQ Studio PIN: Configured via `ADMIN_PIN` in your `.env` file

---

## HQ Studio Operations

* **Branch Playback:** Open the link on any phone, tablet, or PC and click anywhere on the radio cabinet to tune in. Volume and Bass EQ knobs adjust audio locally per branch, and a watchdog automatically reconnects if Wi-Fi drops.
* **Central Management (`B: HQ STUDIO`):** Unlock with the Admin PIN to upload new `.mp3` tracks, reorder the queue (`▲` / `▼`), delete tracks, skip the current song, or trigger **Force Sync All Branches** to realign active players to the live stream tip.