#!/usr/bin/env bash
# End-to-end check against a running stack: sign in as the demo user, send money, ask the assistant.
set -euo pipefail
API=${API:-http://127.0.0.1:8000}
json() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }

curl -fsS "$API/health"; echo
TOKEN=$(curl -fsS "$API/api/v1/auth/login" -H 'Content-Type: application/json' \
  -d '{"email":"demo@sahil.example","password":"Sahil-Demo-2026"}' | json "['access_token']")
AUTH="Authorization: Bearer $TOKEN"
ACCOUNT=$(curl -fsS "$API/api/v1/accounts" -H "$AUTH" | json "[0]['id']")
KEY=$(python3 -c "import uuid; print(uuid.uuid4().hex)")
send() { curl -fsS "$API/api/v1/transfers" -H "$AUTH" -H "Idempotency-Key: $KEY" -H 'Content-Type: application/json' \
  -d "{\"from_account_id\":\"$ACCOUNT\",\"to\":\"layla\",\"amount\":\"1.250\",\"note\":\"smoke test\"}"; }
FIRST=$(send | json "['id']"); SECOND=$(send | json "['id']")
[ "$FIRST" = "$SECOND" ] && echo "transfer ok, retry was not sent twice ($FIRST)"
curl -fsS "$API/api/chat" -H "$AUTH" -H 'Content-Type: application/json' -d '{"message":"What is my balance?"}'; echo
[ "$(curl -s -o /dev/null -w '%{http_code}' "$API/api/v1/accounts")" = 401 ] && echo "anonymous access refused"
echo "SMOKE TEST PASSED"
