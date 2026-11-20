# Sahil security design and threat model

Scope: the Sahil API, database, assistant and Flutter client in this repository, run locally with
Docker Compose. Data is fictional. This document describes what is implemented and tested. It is
**not** a claim of banking-grade or production-ready security; no independent audit has been done.

## Assets and trust boundaries

| Asset | Why it matters |
|---|---|
| Account balances and ledger | Integrity: money must never be created, lost or double-spent |
| Credentials and session tokens | Whoever holds them acts as the customer |
| Personal and transaction data | Confidentiality between customers |
| Audit log | Evidence; must not be silently changed |
| `JWT_SECRET`, `GEMINI_API_KEY`, DB password | Server secrets |

Boundaries: (1) app ↔ API over the network, (2) API ↔ PostgreSQL, (3) API ↔ Google Gemini,
(4) text written by one customer and later read by another customer's assistant.

## Threats and mitigations (STRIDE)

| # | Threat | Mitigation | Test |
|---|---|---|---|
| S1 | Password guessing / credential stuffing | Argon2id; 20 logins/min per IP, 10 per 5 min per e-mail; lock after 5 failures for 15 min (stored in DB) | `test_login_is_rate_limited_per_ip`, `test_account_locks_after_repeated_failures…` |
| S2 | Finding out who has an account | Identical error and equal work for unknown e-mail vs wrong password; vague duplicate-registration error | `test_login_errors_do_not_reveal…`, `test_duplicate_registration_gives_no_hint` |
| S3 | Forged or altered token | HS256 pinned, issuer/audience/expiry/type required, `alg=none` rejected, session row must be live and match the user | `test_forged_and_malformed_tokens_are_rejected` |
| S4 | Stolen refresh token | Single-use rotation; reuse revokes the whole session; only SHA-256 hashes stored | `test_reusing_a_refresh_token_revokes_the_whole_session` |
| S5 | Session lives on after sign-out | Access tokens are checked against the `sessions` table on every request | `test_logout_invalidates_the_access_token_immediately` |
| T1 | Overspending through parallel requests | Row locks taken in sorted order, balance re-read under lock, DB `CHECK (balance >= 0)` | `test_parallel_transfers_cannot_overspend`, `test_opposite_transfers_do_not_deadlock` |
| T2 | Duplicate transfer (double tap, retry) | `Idempotency-Key` required; unique `(user, key)` row is locked; same key + different body is refused | `test_same_idempotency_key_in_parallel_sends_once` |
| T3 | Tampering with amounts | Amounts are ASCII decimal text parsed to integer fils; floats, exponents, negatives, >3 decimals, non-ASCII digits refused; unknown JSON fields refused | `test_invalid_amounts_are_rejected_by_the_server` |
| T4 | Ledger or audit edited after the fact | Append-only triggers; deferred trigger requires each transfer's entries to sum to zero; audit rows hash-chained | `test_ledger_is_append_only`, `test_audit_chain_verifies_and_detects_tampering` |
| T5 | SQL injection | SQLAlchemy bound parameters everywhere; no string-built SQL | `test_sql_injection_attempts_are_inert` |
| R1 | Customer denies an action | Audit entry for sign-ins, failures, lockouts, transfers, card changes, assistant drafts and confirmations | `test_security_events_are_audited` |
| I1 | Reading another customer's data (IDOR) | Ownership is part of every query; foreign ids return 404 | `test_authorization.py` (all) |
| I2 | Leaking internals or secrets | One error format, no stack traces; hashes/secrets never serialised; card shows last 4 only; API responses `no-store` | `test_errors_never_leak_internals`, `test_unexpected_failures_stay_generic…`, `test_responses_never_contain…` |
| I3 | Customer enumeration via recipient lookup | Authenticated, 20/min, returns only "First L." | `test_recipient_lookup_reveals_only_a_short_display_name` |
| I4 | Gemini key exposed to the client | Key read from `GEMINI_API_KEY` on the server only; never in responses or the app | `test_gemini_key_is_never_returned_by_any_endpoint` |
| E3 | Paying, declining or cancelling someone else's money request | Requests are loaded only for the requester or payer; each action is limited to the right one of them; others get 404 | `test_only_the_right_person_can_act_on_a_request` |
| T6 | A request paid twice from two devices | Request row locked before paying; status checked under the lock; DB constraint ties `paid` to exactly one transfer | `test_parallel_pay_taps_with_different_keys_pay_only_once` |
| T7 | Formula injection through the CSV statement (a sender writes `=HYPERLINK(...)` in a note) | Text cells starting with `= + - @` are prefixed with `'` | `test_statement_csv_is_mine_only_and_formula_safe` |
| D1 | Flooding | Per-endpoint rate limits, 32 KB body cap, bounded page sizes and text lengths | `test_oversized_request_is_refused`, `test_registration_and_chat_are_rate_limited`, `test_request_spam_is_limited` |
| E1 | Calling protected routes without signing in | Single auth dependency; a test walks every route in the OpenAPI schema | `test_every_api_route_rejects_anonymous_callers` |
| E2 | Mass-assignment (setting `kind`, `initiated_by`…) | Pydantic models with `extra="forbid"` | `test_unknown_fields_are_rejected` |
| A1 | Assistant reads other customers' data | Tools are bound to the authenticated user in server code; model-supplied ids are ignored | `test_model_cannot_reach_other_customers_even_if_it_tries` |
| A2 | Assistant moves money by itself or via prompt injection in a transaction note | There is no money-moving tool. `propose_transfer` writes a 5-minute draft; only the user's authenticated Confirm call executes it, re-validated and idempotent | `test_prompt_injection_in_a_transaction_note_cannot_move_money`, `test_confirming_sends_exactly_once` |
| A3 | Too much personal data sent to Google | Only masked account numbers, names as shown in-app, amounts; no e-mail, ids or full numbers | `test_gemini_tool_loop_returns_only_the_callers_data` |

## Decisions worth explaining

- **Tokens in memory on the client.** The Flutter app never writes tokens to disk or browser
  storage, so script injection or a shared computer cannot lift a long-lived token. Cost: you sign
  in again after closing the app.
- **Bearer header, not cookies.** No ambient credentials means no CSRF surface; CORS is an explicit
  allow-list with credentials disabled.
- **Stateful check on a JWT.** A pure JWT cannot be revoked. Each request does one indexed lookup of
  the session so sign-out, password change and theft detection take effect immediately.
- **Database as the last line of defence.** Overdraft, unbalanced ledger writes and log edits are
  rejected by PostgreSQL even if application code is wrong.
- **A bug the tests caught.** The first version locked rows correctly but SQLAlchemy returned a
  cached, stale balance, and the 40-request race test overspent. The fix (`populate_existing`) is in
  `transfers.py`; the test stays as a regression guard.
- **Compose hardening.** API container runs as a non-root user, read-only filesystem, all
  capabilities dropped; the database port is not published; the API binds to `127.0.0.1`.

## Known limits (honest list)

- No independent penetration test or code audit.
- Local demo uses plain HTTP on localhost. A real deployment needs TLS, a reverse proxy and HSTS
  (the header is already sent when `ENVIRONMENT=production`).
- Rate-limit counters are in process memory (one API instance). Lockout is in the database.
- No multi-factor authentication, device binding, or e-mail verification.
- `Idempotency-Key` records are kept indefinitely; a real system would expire them.
- The audit chain detects edits but its head hash is not anchored outside the database.
- Requests without a `Content-Length` header rely on the web server's own limits.
- The live call to Google Gemini was not exercised in the build environment (no network route);
  that path is tested with a scripted stand-in for Google's client.
- On Google's free tier, prompts may be used by Google to improve its products. Use fictional data.
