# Remote host deployment

## Windows/LAN

Run `setup_windows.bat`, then `start_host.bat`. The script binds to all interfaces, generates a cryptographically random per-session token if none is configured, prints usable LAN addresses, and does not open a browser. Put a stable `SKETCHARM_API_TOKEN` in the environment or `.env` for a persistent client configuration.

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

Developed by maggogerka.

