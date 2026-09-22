# The Safety Engine

Read this before touching `app/linkedin/`, `app/scheduler/`, or anything that can
emit an outbound action.

LinkedIn does not ban accounts for using automation per se. It bans accounts
whose *signals* look non-human. The engine exists to keep three signal families
clean: identity, cadence, and volume. Every rule here is enforced server-side in
the dispatcher. The UI may only ever request something more conservative.

## Why this shape

Detection, as documented by the Linked Helper 2026 study of LinkedIn page code:

| Surface | What LinkedIn does | Our answer |
|---|---|---|
| Extension scanner | Probes 6,167 known extension IDs on page load | We ship no extension |
| DOM scanner | Walks the DOM for `chrome-extension://` substrings | No injected resources |
| Device fingerprint | 48 signals: GPU, audio, fonts, WebRTC local IP, screen, timezone measured twice, automation flags; encrypted and attached to API requests | No browser. One stable, plausible mobile client identity per account, frozen for life |
| Network scoring | Parallel sessions on different IPs, geo mismatch, datacenter IP reputation | One sticky residential IP per account, geo and timezone matched |
| Behavioural | Rolling weekly invite ceiling near 100, bulk patterns, high "I do not know this person" rate | Ramp-up, rolling 7-day cap, log-normal pacing, read/write action mixing |

The single most important consequence: **an account has exactly one execution
slot, forever.** Two concurrent requests for one account, especially from two
IPs, is the strongest ban signal available to LinkedIn. Enforced by a
TTL-guarded Redis lock, never by worker concurrency settings.

## Identity binding

Each `linkedin_accounts` row owns for life:

1. **One sticky proxy.** Residential or mobile, geo-matched to the profile
   country, sticky session so the exit IP is stable for days.
2. **One frozen fingerprint.** The mobile client identity: client version,
   device model, OS name and version, form factor, display metrics, user agent,
   accept-language, timezone. Generated once at connect time and never rotated.
   Rotating a fingerprint is itself the anomaly.
3. **One encrypted session.** Cookies and CSRF token, stored as ciphertext via
   `app.core.crypto`, decrypted only inside a worker, never logged, never
   returned by the API.

Sessions are kept alive by use, not by re-login. Re-login is a risk event:
at most once per 24h per account, always through the same proxy.

## Cadence

- **Ramp-up, not flat caps.** Week 1: 10-15 invites/day. Week 2: 25. Week 3: 40.
  Week 4+: the plan cap. Applied per action type.
- **Rolling weekly invite cap (~100)** over a trailing 7-day window, on top of
  the daily cap. This is LinkedIn's real constraint and the one most tools miss.
- **Log-normal inter-action delays**, median ~4 min, floor 45s, ceiling 25 min.
  Uniform jitter is itself detectable: its histogram is flat, human behaviour is
  not.
- **Working hours in the account timezone**, weekday toggle, plus randomly
  skipped slots and occasional whole-day gaps.
- **Session warming.** A human session starts with feed, notifications, and own
  profile reads, then performs 3-8 actions, then goes idle. Actions never arrive
  as a naked burst of invites.
- **Action mixing.** Cheap reads are interleaved among writes so the write/read
  ratio stays plausible.
- **Test mode.** A per-account override capping the day at 3-5 invites, for
  dogfooding on a real account without risk.

## Health and the circuit breaker

Every driver response is classified:

| Class | Trigger | Response |
|---|---|---|
| `OK` | normal | proceed |
| `SOFT_LIMIT` | 429, invite quota modal, weekly limit | halve remaining daily quota, back off 4-12h |
| `AUTH_LOST` | 401, CSRF mismatch | open circuit, pause campaigns, ask user to reconnect |
| `CHALLENGE` | checkpoint redirect | open circuit, user resolves on their phone |
| `BLOCKED` | 999, unusual-activity page | open circuit, never auto-retry |
| `UNKNOWN_SHAPE` | response did not parse | count toward a drift alarm; if many accounts see it, LinkedIn shipped a change and an operator is paged |

Opening a circuit pauses every campaign on that account, freezes its queue, and
notifies the customer with a resolution path. **Never auto-retry into a block.**

## Hygiene

- Withdraw pending invites after 21 days. A large pending pile depresses
  acceptance and flags the account.
- Workspace-wide dedupe: a lead contacted by any account in the workspace is
  never contacted again. Enforced by a unique index, not by application checks.
- Reply detection: poll conversations every 3-10 minutes, jittered. An inbound
  message halts that lead sequence immediately.
- Kill switches: per workspace (`workspaces.outreach_paused`) and per account.

## Testing obligations

A change to this engine is not done until these pass:

1. **Simulated clock**: 30 days times 200 accounts through the dispatcher. No
   day over the daily cap, no trailing 7-day window over the weekly cap, ramp
   curve respected, and zero instances of two concurrent actions on one account.
2. **Distribution check**: emitted inter-action delays are log-normal-ish and no
   two accounts share a schedule.
3. **Chaos**: kill a worker mid-action; the idempotency key must prevent a
   duplicate invite on redelivery.
4. **Fault injection**: feed the driver 429, 999, and checkpoint HTML; assert
   quota halving, circuit opening, campaign pause, and user notification.
