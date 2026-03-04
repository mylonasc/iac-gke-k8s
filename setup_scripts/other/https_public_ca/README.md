# HTTPS Public CA Notes

This folder contains helper manifests and scripts for issuing public TLS certificates
and wiring DNS for ingress endpoints.

## Local files in this directory

- `01_cluster-ca-issuer.yaml`
- `02_challenge_website_deployment.yaml`
- `PublicCA_signed_TLS_instructions.md`
- `manual_update_dns.sh`
- `noip-duc/` (optional dynamic DNS automation)

## Recommended references

- cert-manager docs:
  - `https://cert-manager.io/docs/`
- ingress-nginx TLS docs:
  - `https://kubernetes.github.io/ingress-nginx/user-guide/tls/`

## Notes

- Keep DNS provider credentials out of source control.
- Validate certificate issuance in the target namespace after applying manifests.
