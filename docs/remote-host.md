# Remote host deployment

This mode runs the complete Robot Sketch Studio pipeline on a powerful PC and
uses it from another computer.

## Powerful Windows PC

1. Run setup_windows.bat.
2. Run setup_models_windows.bat and choose Clean AI Sketch, or download
   Informative Drawings from the Web UI.
3. Run start_host.bat.
4. Keep the displayed Bearer token and URL open.

start_host.bat binds to 0.0.0.0, generates a cryptographically random
per-session token when none is configured, and prints usable LAN addresses. Put
a stable SKETCHARM_API_TOKEN in .env or the machine environment when clients
must reconnect after restarts.

## Client PC

Open the printed URL in a browser and enter the token under **Remote host
token**. The model, CPU/GPU work, and result files stay on the host.

For scripting, copy tools/remote_client.py and run:

~~~powershell
py -3 remote_client.py photo.jpg --url http://HOST-IP:8000 --token YOUR_TOKEN
~~~

The standard-library client needs no third-party package and downloads all
reported artifacts. A repository checkout can instead use send_to_host.bat.

Check http://HOST-IP:8000/health first if the client cannot connect. On a trusted
LAN, allow inbound TCP for the selected port in Windows Firewall. Never add a
public router port-forward directly to Uvicorn.

## Tailscale (recommended)

1. Install Tailscale on both PCs and sign them into the same tailnet.
2. Start Robot Sketch Studio in host mode.
3. Use the host's Tailscale address or MagicDNS name.
4. Keep the Bearer token enabled and restrict access with tailnet ACLs.

## Docker

Copy .env.example to .env, set a random SKETCHARM_API_TOKEN, then start
compose.cpu.yml or compose.nvidia.yml. Preserve the model/data/result volumes
between updates. /health is public; /api/v1/* is token-protected.

Set SKETCHARM_CORS_ORIGINS to an explicit comma-separated allowlist only when a
browser is served from another origin. Use a maintained TLS reverse proxy for
any untrusted network.

This host mode is separate from **Artistic Remote**. Host mode moves the whole
application to the powerful PC. Artistic Remote keeps this application local
and calls a separate image-edit server; see
[artistic-remote.md](artistic-remote.md).
