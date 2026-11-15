# Sahil API

Base URL `http://localhost:8000`. Interactive docs: `/docs`. Machine-readable: [openapi.json](openapi.json).

All routes except register, login, refresh and `/health` need `Authorization: Bearer <access token>`.
Money-moving routes need an `Idempotency-Key` header. Amounts are decimal text in BHD (`"12.500"`).
Errors always look like `{"error": {"code": "...", "message": "..."}}`.

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Health |
| POST | `/api/v1/auth/register` | Register |
| POST | `/api/v1/auth/login` | Login |
| POST | `/api/v1/auth/refresh` | Rotate the refresh token. Presenting an already-used token is treated as theft. |
| POST | `/api/v1/auth/logout` | Logout |
| POST | `/api/v1/auth/logout-all` | Logout All |
| GET | `/api/v1/auth/me` | Me |
| GET | `/api/v1/auth/sessions` | Sessions |
| DELETE | `/api/v1/auth/sessions/{session_id}` | Revoke Session |
| POST | `/api/v1/auth/change-password` | Change Password |
| GET | `/api/v1/accounts` | Accounts |
| GET | `/api/v1/transactions` | Transactions |
| GET | `/api/v1/insights` | Insights |
| GET | `/api/v1/recipients/lookup` | Lookup |
| GET | `/api/v1/recipients/recent` | Recent Recipients |
| POST | `/api/v1/transfers` | Create Transfer |
| POST | `/api/v1/accounts/{account_id}/top-up` | Add fictional money from the demo funding account (still a real double-entry transfer). |
| GET | `/api/v1/card` | Card |
| PATCH | `/api/v1/card` | Update Card |
| GET | `/api/v1/security/activity` | The signed-in user's own security events (never anyone else's). |
| POST | `/api/chat` | Send a message to the signed-in user's personal assistant and get its text reply. |
| GET | `/api/chat/history` | History |
| DELETE | `/api/chat/history` | Clear History |
| POST | `/api/v1/assistant/actions/{action_id}/confirm` | The explicit, human confirmation step. Only this call can turn a draft into a transfer. |
| POST | `/api/v1/assistant/actions/{action_id}/cancel` | Cancel Action |

## Example: chat

```sh
curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message": "How much did I spend this month?"}'
# {"reply": "...", "proposal": null, "engine": "gemini"}
```

If the reply contains a `proposal`, nothing has been sent. The app shows it with Confirm / Cancel, which call
`POST /api/v1/assistant/actions/{id}/confirm` or `/cancel`.
