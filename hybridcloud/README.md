## About
In this folder I keep notes and manifests related to the on-prem services hosted.

Some links might be innaccessible to the public. 

## Services

| service  | link to further notes | integration pattern |
|----------|-----------------------|---------|
| postgres | [Kubernetes integration](postgres/README.md) | service mesh with wireguard as a sidecar (s2s VPN) |
| opencode | [On-prem web + SSH setup](https://github.com/mylonasc/homelab/tree/main/agentic-coding/opencode-wireguard) | shares the on-prem DB WireGuard namespace; web/API `10.8.0.4:4096`, key-only SSH `10.8.0.4:2222` |

## OpenCode access

Connect your client to WireGuard, then open `http://10.8.0.4:4096` or run
`ssh -p 2222 opencode@10.8.0.4` with an authorized key. SSH enters the same
unprivileged container as the web server, including its persistent configuration.
Authorize public keys and start/stop the stack with `manage.sh` in the homelab
folder linked above. Open `/workspace` as a project before creating web sessions.

No Kubernetes ingress, LoadBalancer, or new manifest is needed for this setup.
The VPN hub must forward between peers and client routes must include the VPN
subnet. An independent OpenCode WireGuard peer is also available; do not duplicate
the DB peer's identity. For Docker context and rootless bind-mount permissions,
see [homelab VPN notes](https://github.com/mylonasc/homelab/blob/main/vpn/NOTE.md).
