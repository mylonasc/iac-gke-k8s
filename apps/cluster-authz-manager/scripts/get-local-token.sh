#!/usr/bin/env bash
set -euo pipefail

OIDC_URL="${OIDC_URL:-http://127.0.0.1:19002}"
AUDIENCE="${AUDIENCE:-authz-manager-local}"
SUBJECT="${SUBJECT:-local-dev-user}"
EMAIL="${EMAIL:-mylonas.charilaos@gmail.com}"
GROUPS="${GROUPS:-sra-admins}"

json_escape() {
  python3 - <<'PY' "$1"
import json
import sys
print(json.dumps(sys.argv[1]))
PY
}

groups_json="[]"
if [[ -n "${GROUPS}" ]]; then
  groups_json="$(python3 - <<'PY' "$GROUPS"
import json
import sys
groups = [item.strip() for item in sys.argv[1].split(',') if item.strip()]
print(json.dumps(groups))
PY
)"
fi

payload="$(cat <<EOF
{
  "subject": $(json_escape "$SUBJECT"),
  "email": $(json_escape "$EMAIL"),
  "audience": $(json_escape "$AUDIENCE"),
  "groups": ${groups_json}
}
EOF
)"

response="$(curl -fsS -X POST "${OIDC_URL}/token" -H "Content-Type: application/json" -d "$payload")"
python3 - <<'PY' "$response"
import json
import sys
print(json.loads(sys.argv[1])["access_token"])
PY
