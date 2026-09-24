# Security policy

## Supported version

Security fixes currently target the latest 0.1.x release.

## Reporting

Please report vulnerabilities privately through GitHub's security advisory feature instead of opening a public issue. Do not include production API tokens or private images.

## Deployment guidance

- Local mode binds to `127.0.0.1` by default.
- Host mode refuses to start without `SKETCHARM_API_TOKEN`; all `/api/` requests require its Bearer value.
- `/health` remains unauthenticated for container health checks and reveals only status/version.
- Never expose Uvicorn directly to the internet. Prefer Tailscale or a TLS reverse proxy with firewall rules.
- Set a narrow CORS allowlist, a conservative upload limit, and a short job TTL.
- Treat uploaded images and generated output as sensitive. Use dedicated runtime volumes and host permissions.
- Tokens are read from headers/environment and are never intentionally logged by application code.
- v0.3.1 cannot control real hardware.

Developed by maggogerka.
