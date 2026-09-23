# Remote host deployment

## Windows/LAN

Run `setup_windows.bat`, then `start_host.bat`. The script binds to all interfaces, generates a cryptographically random per-session token if none is configured, prints usable LAN addresses, and does not open a browser. Put a stable `SKETCHARM_API_TOKEN` in the environment or `.env` for a persistent client configuration.

From the second PC, first open the printed URL in a browser and enter the same token under **Remote host token**. To process without a browser, copy `tools/remote_client.py` and run:

```powershell
py -3 remote_client.py photo.jpg --url http://HOST-IP:8000 --token YOUR_TOKEN
```

The results appear in `robot-sketch-result`. A checkout on the second Windows PC can use `send_to_host.bat photo.jpg` instead. The client needs Python 3 but no third-party packages.

If the second PC cannot connect on a trusted LAN, allow inbound TCP for the configured port in Windows Firewall on the host. Do not open the port on the internet router. Check `http://HOST-IP:8000/health` first; it is public and should return `{"status":"ok",...}`.

## Tailscale (recommended)

1. Install Tailscale on the server and client and sign both into the same tailnet.
2. Start Robot Sketch Studio in host mode.
3. Use the server's Tailscale IP or MagicDNS name, such as `http://drawing-pc:8000`.
4. Keep the Bearer token enabled even inside the tailnet and add tailnet ACLs that admit only intended users/devices.
5. Do not add a public router port-forward.

## Docker host

Copy `.env.example` to `.env`, set a random API token, and start either Compose file. Preserve the three named volumes when updating or moving the service. `/health` is public for health checks; `/api/v1/*` is token-protected.

For a browser hosted at another origin, set `SKETCHARM_CORS_ORIGINS` to an explicit comma-separated allowlist. Do not use `*` on an untrusted network. Terminate HTTPS in a maintained reverse proxy if traffic crosses an untrusted network. Uvicorn itself is not an internet edge server.

The API token is a shared secret, not a user/account system. Rotate it after exposure and isolate sensitive uploaded images at the filesystem/container level.

## Models on the host

Weights always belong on the host, not on the client. Use the **Optional local models** panel, `setup_models_windows.bat`, or:

```powershell
robot-sketch-studio models list
robot-sketch-studio models download lineart-realistic
```

The Web/API downloader accepts only known model IDs and verifies checksums. Install the matching Python extra shown in the model panel before selecting that engine.

Developed by maggogerka.
