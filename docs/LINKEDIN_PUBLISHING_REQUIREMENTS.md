# LinkedIn publishing — what the platform actually requires

Read this first if the Content Studio says publishing is unavailable. The short
version: **posting on a member's behalf requires an authorized LinkedIn developer
app and the member's explicit OAuth consent.** Nothing else will do, and this
codebase will not pretend otherwise.

---

## 1. Why the existing LinkedIn integration cannot publish

The automation side of this product talks to LinkedIn through
[`app/linkedin/voyager.py`](../api/app/linkedin/voyager.py) — the private mobile
("Voyager") API, authenticated with a `li_at` session cookie the user supplies.
That is how invitations, messages and profile reads are performed.

Publishing is **not** built on it, deliberately. Creating posts through an
undocumented endpoint with a harvested session cookie would mean:

- using a private API LinkedIn does not publish or support;
- acting with a credential the member gave us for a different purpose;
- no audit trail LinkedIn recognises, and no recourse when a post fails.

So the Content Studio uses a second, entirely separate credential: an OAuth 2.0
access token the member grants through LinkedIn's own consent screen. The two
never mix. `app/linkedin/publishing.py` contains no cookie, fingerprint or proxy
code at all.

## 2. What must exist

| Requirement | Detail |
|---|---|
| A LinkedIn app | Created at <https://www.linkedin.com/developers/apps>, associated with a Company Page you administer. |
| Product: **Share on LinkedIn** | Request it on the app's *Products* tab. This is what grants `w_member_social`. |
| Product: **Sign In with LinkedIn using OpenID Connect** | Grants `openid` and `profile`, which is how we learn the member's `urn:li:person:…` — the author every post must be attributed to. |
| Redirect URL | Must match `LINKEDIN_REDIRECT_URI` **exactly**, including scheme, host, port and path. Default: `http://localhost:8010/api/v1/linkedin/oauth/callback`. |
| Verification | LinkedIn requires a Page admin to verify the app before the products activate. |

### Scopes

| Scope | Needed for | Status here |
|---|---|---|
| `openid` | OIDC sign-in | requested |
| `profile` | member name, picture, and the `sub` that becomes the author URN | requested |
| `w_member_social` | **creating posts, and uploading their images/video/documents** | requested — without it nothing publishes |
| `r_member_social` | reading impressions, reactions, comments on a member's own posts | **not requested; not generally granted.** This is why post analytics report as unavailable rather than showing numbers. |

`r_member_social` is restricted and is not part of the standard *Share on
LinkedIn* product. The Content Studio is wired for it — `analytics_capability()`
checks for it on every request — so if a deployment is ever granted the scope,
analytics begin working without a code change. Until then the UI says
"Analytics unavailable" and explains why. It never displays a zero it invented.

## 3. Configuration

```bash
# .env
LINKEDIN_CLIENT_ID=<app client id>
LINKEDIN_CLIENT_SECRET=<app client secret>
LINKEDIN_REDIRECT_URI=http://localhost:8010/api/v1/linkedin/oauth/callback
LINKEDIN_API_VERSION=202409          # the LinkedIn-Version header sent on REST calls
LINKEDIN_PUBLISHING_SCOPES=openid profile w_member_social
```

These are read in [`app/config.py`](../api/app/config.py) and are already wired
through `docker-compose.yml`. The client secret is a `SecretStr` and is never
logged or returned by the API.

## 4. Endpoints this feature calls

All documented, all versioned with the `LinkedIn-Version` header:

| Purpose | Call |
|---|---|
| Consent screen | `GET https://www.linkedin.com/oauth/v2/authorization` |
| Token exchange | `POST https://www.linkedin.com/oauth/v2/accessToken` |
| Member identity | `GET https://api.linkedin.com/v2/userinfo` |
| Create a post | `POST https://api.linkedin.com/rest/posts` |
| Image upload | `POST /rest/images?action=initializeUpload`, then `PUT` to the returned URL |
| Document upload | `POST /rest/documents?action=initializeUpload`, then `PUT` |
| Video upload | `POST /rest/videos?action=initializeUpload`, `PUT` each part, `POST /rest/videos?action=finalizeUpload` |

Nothing here scrapes HTML, drives a browser, replays a session cookie, or calls
an endpoint LinkedIn has not documented.

## 5. Media limits enforced before upload

Taken from LinkedIn's upload API documentation and enforced in
[`media_service.py`](../api/app/services/media_service.py), so a file LinkedIn
would reject is refused while the user is still in the composer:

| Kind | Types | Size | Per post |
|---|---|---|---|
| Image | JPG, PNG, GIF | 10 MB | up to 20 |
| Video | MP4 | 200 MB (see note) | 1 |
| Document | PDF, DOC, DOCX, PPT, PPTX | 100 MB | 1 |

A post carries images, **or** one video, **or** one document — never a mix.

*Video note:* LinkedIn's own ceiling is 500 MB. We cap at 200 MB because the
publish worker buffers the file in memory to stream it upstream. Raising the cap
means switching that path to a streaming read first.

Post text is capped at **3,000 characters**, which is LinkedIn's limit for post
commentary. The composer shows the count live and blocks Schedule/Publish above
it rather than letting LinkedIn reject the post hours later.

## 6. What the product does when the capability is missing

`capability_for(account)` returns one of these on every relevant request, and the
UI renders it verbatim — there is no silent degradation and no fake success.

| Code | Meaning | What the user is offered |
|---|---|---|
| `ready` | Publishing works | — |
| `not_configured` | Deployment has no LinkedIn app | Explanation + pointer to this document |
| `not_authorized` | Member has never consented | **Connect for publishing** button → consent screen |
| `missing_scope` | Consented, but without `w_member_social` | **Reauthorize**, with the specific permission named |
| `expired` | Grant lapsed | **Reconnect for publishing** |
| `revoked` | LinkedIn rejected the stored token | Grant is cleared, notification raised, reconnect offered |

Consequences that follow from this, all covered by tests:

- `POST /posts/{id}/publish` and `/schedule` return **409** with the capability
  code in `error.details` when publishing is not possible. The post stays a draft.
- A scheduled post whose grant lapsed before its slot is marked `FAILED` with the
  reason, and a `publishing_auth_expired` notification is raised. It is never
  reported as published.
- A `401`/`403` from LinkedIn mid-publish clears the stored grant, so the UI stops
  offering to publish with a credential that no longer works.

## 7. Token handling

- Stored as Fernet ciphertext in `linkedin_accounts.publishing_token_ciphertext`
  via `app.core.crypto`, decrypted only inside a worker process.
- Never returned by any endpoint. The API exposes a *verdict*
  (`available`, `code`, `message`, `scopes`) and never the credential.
- Never placed in `localStorage`; the frontend holds no LinkedIn secret at all.
- The OAuth callback is public by necessity (the browser arrives from
  linkedin.com with no session of ours) and is authenticated by a signed,
  15-minute `state` JWT carrying the workspace, account and user. A forged state
  cannot be constructed without the server's signing key.
- Revoking from the accounts page clears the ciphertext, the refresh token, the
  scopes and the member URN.

## 8. Checklist for enabling publishing on a deployment

1. Create the LinkedIn app and associate it with a verified Company Page.
2. Add **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect**.
3. Register the redirect URL, matching `LINKEDIN_REDIRECT_URI` character for character.
4. Set `LINKEDIN_CLIENT_ID` / `LINKEDIN_CLIENT_SECRET`; restart the API and worker.
5. In the app: **Accounts → Connect for publishing**, accept the posting permission.
6. The account card should read *Authorized* and list `w_member_social`.
