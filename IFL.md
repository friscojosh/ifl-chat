# IFL Chat

IFL Chat is the International Fantasy League's chat service: a fork of Mattermost Team Edition v12.1.0 (`ifl/main`). The league site, iflgm.com, is the identity provider; chat has no sign-up of its own. The fork keeps upstream code as unchanged as possible. Every IFL change is either new code under `server/channels/app/ifl/` and `server/channels/api4/ifl.go` or a small hook marked `// IFL:` in an upstream file.

## What the fork changes

- **Sign-in through iflgm.com.** The site's sign-in is presented as a GitLab-shaped OAuth provider, so the standard GitLab option signs members in. After the site confirms a member's eligibility, the member is reactivated if needed, provisioned, and joined to the league team.
- **Login page goes straight to iflgm.com.** The web login and signup pages show the GitLab option with no GitLab icon and the label "Sign in with iflgm.com" (`GitLabButtonText` still wins when set). When it is the only sign-in method, the login page navigates to `/oauth/gitlab/login` on load and shows "Signing in with iflgm.com…". The automatic URL is built from an allowlist: only `redirect_to`, and only a relative path (`^\/([^/]|$)`, the check login.tsx uses). The decision is made once, in an effect after the session-expiry check, with the store initialized and `currentUser` resolved. It shows the button instead when the query has any other parameter (`extra`, `error`, `t`, `id`, `desktop_token`, `login_hint`, …) or a non-relative or repeated `redirect_to`; when the session expired (`wasLoggedIn`) or a user is signed in; in the desktop app or an embedded view; within two minutes of the last attempt in this tab (an OAuth refusal ends on `/error`, whose link leads back here, so it cannot loop); and after a user-initiated sign-out (`ifl_signed_out` in localStorage, set in `emitUserLoggedOutEvent`, cleared by clicking the button or by loading the app signed in). Storage fails closed: if reading localStorage or sessionStorage throws, the page shows the button; an in-memory mirror keeps marks for the page's lifetime when storage cannot be written. Rules and strings: `webapp/channels/src/components/login/ifl_signin.ts`. The mobile apps draw their own login screen and are unaffected.
- **Panel sessions.** `POST /api/v4/ifl/session` accepts a signed, single-use panel token from the site and opens a chat session for the embedded panel (with a CSRF token).
- **Email sync.** `PUT /api/v4/ifl/users/{user_id}/email` (system admin only) lets the site's relay set a site-linked member's email. The upstream patch route cannot: chat keeps an OAuth user's old email on an untrusted update. It answers 400 for an account that does not sign in through iflgm.com and 409 `ifl.email.conflict` when another account holds the address. A panel session also brings an existing member's email and name up to date from the panel token, as an OAuth sign-in does (an email held by another account is skipped).
- **Panel WebSocket.** `GET /api/v4/ifl/websocket` is `/api/v4/websocket` for the iflgm.com panel: the session a chat cookie gives the handshake is dropped, so the panel's authentication challenge decides (browsers send chat.iflgm.com cookies with every handshake, and the stock route would ignore the challenge). Connections never resume, so each starts at sequence 0. When metrics are on, these connections are recorded as long requests in the API duration histogram, because `recordMetrics` exempts only the exact path `/api/v4/websocket` (`web/handlers.go:391`); harmless, and Team Edition has no metrics server.
- **Linked suspensions.** Banning or deactivating a user in chat is reported to iflgm.com, so a ban in chat is a ban on the site.
- **Site client.** Server-to-server calls to the site go through `server/channels/app/ifl/site_client.go` using the internal secret. Redirects are never followed.

## Hooks into upstream files

Found with `grep -rn "// IFL" server webapp`. Keep every one when merging upstream.

| Location | Purpose |
| --- | --- |
| `server/channels/api4/api.go:430` | Registers the IFL routes (`api.InitIFL()`). |
| `server/channels/api4/user.go:1704` | Linked suspension: ban in chat is a ban on iflgm.com. |
| `server/channels/api4/user.go:1844` | Linked suspension (second path). |
| `server/channels/api4/user_local.go:337` | Linked suspension for local-mode (mmctl) changes. |
| `server/channels/app/oauth.go:769` | `CompleteOAuth` signup action (bypasses `LoginByOAuth`): the same reactivation and provisioning. |
| `server/channels/app/oauth.go:873` | `LoginByOAuth`, after the site confirms eligibility: reactivate, provision, join the team. |
| `server/config/client.go:454` | Shows the iflgm.com sign-in as a GitLab-shaped provider. |
| `webapp/channels/src/actions/global_actions.tsx:43` | Imports the iflgm.com sign-in helper. |
| `webapp/channels/src/actions/global_actions.tsx:276` | A user-initiated sign-out marks the browser signed out, so the login page does not sign straight back in. |
| `webapp/channels/src/components/logged_in/logged_in.tsx:15` | Imports the iflgm.com sign-in helper. |
| `webapp/channels/src/components/logged_in/logged_in.tsx:72` | Signed in again: clears the signed-out mark. |
| `webapp/channels/src/components/login/login.tsx:58` | Imports the iflgm.com sign-in helper (replaces the GitLab icon import). |
| `webapp/channels/src/components/login/login.tsx:155` | Decides whether the login page goes straight to iflgm.com. |
| `webapp/channels/src/components/login/login.tsx:173` | GitLab option: no icon, "Sign in with iflgm.com" label, click clears the signed-out mark. |
| `webapp/channels/src/components/login/login.tsx:554` | Decides once (after session-expiry detection, store ready, user resolved) and navigates to iflgm.com. |
| `webapp/channels/src/components/login/login.tsx:874` | Card title "Sign in with your iflgm.com account" when iflgm.com is the only method. |
| `webapp/channels/src/components/login/login.tsx:961` | "Signing in with iflgm.com…" status in place of the form. |
| `webapp/channels/src/components/login/login.test.tsx:318` | Upstream GitLab button test: no icon in the accessible name. |
| `webapp/channels/src/components/login/login.test.tsx:772` | IFL login page tests. |
| `webapp/channels/src/components/signup/signup.tsx:39` | Imports the iflgm.com label (replaces the GitLab icon import). |
| `webapp/channels/src/components/signup/signup.tsx:164` | GitLab signup option: no icon, iflgm.com label. |
| `webapp/channels/src/components/login/ifl_signin.ts:1` | New file: iflgm.com sign-in strings and redirect rules. |
| `server/channels/api4/ifl.go:1` | New file: the panel session, email sync and panel WebSocket routes. |
| `server/channels/app/ifl_app.go:1` | New file: app-level glue for `server/channels/app/ifl`. |

New, IFL-only code: `server/channels/app/ifl/` (config, panel token, site client, actor, profile, tests), `server/channels/api4/ifl.go`, `server/channels/api4/ifl_test.go`, `server/channels/api4/ifl_websocket_test.go`, `server/channels/app/ifl_app.go`, `server/build/Dockerfile.ifl`, `webapp/channels/src/components/login/ifl_signin.ts`, `.github/workflows/ifl-*.yml`, `tools/slack-migration/` (Slack migration tools, Python; not part of the server build), this file.

### The `en.json` exception

`server/i18n/en.json` carries nine `ifl.*` message strings (`ifl.email.*`, `ifl.panel.*` and `ifl.suspension.*`). It is the one upstream edit with no `// IFL:` marker because JSON has no comments. When merging, keep all `ifl.*` entries; merge conflicts here are usually adjacent-line additions, so keep both sides.

`webapp/channels/src/i18n/en.json` drops `login.gitlab` (the iflgm.com option no longer uses it, and upstream's `i18n-extract:check` fails on unused strings). Keep it out when merging; if an upstream change uses it again, run `npm run i18n-extract` in `webapp/channels`.

Likewise `webapp/channels/src/components/signup/__snapshots__/signup.test.tsx.snap` records the iflgm.com GitLab option (no icon, "Sign in with iflgm.com"); on a conflict, regenerate it with jest `-u` and check that only that changed.

## Configuration

All are environment variables read by `server/channels/app/ifl/config.go`.

| Variable | Meaning |
| --- | --- |
| `IFL_SESSION_SECRET` | Shared secret for panel tokens; the site's `CHAT_SESSION_SECRET`. |
| `IFL_SITE_INTERNAL_URL` | Internal base URL of the site, for example `http://10.98.0.1:8081`. |
| `IFL_INTERNAL_SECRET` | Secret for server-to-server calls; the site's `CHAT_INTERNAL_SECRET`. |
| `IFL_TEAM_NAME` | Team every member joins. |
| `IFL_SERVICE_USERNAME` | The relay's admin account. |

## Build and deploy

- `server/build/Dockerfile.ifl` is upstream's `Dockerfile` with the package download replaced by a COPY of `mattermost-team-linux-amd64.tar.gz` from the build context.
- On every push to `ifl/main`, `.github/workflows/ifl-image.yml` runs the IFL tests, builds the webapp and Team Edition package, builds the image, smoke-tests `mattermost version`, and pushes `ghcr.io/friscojosh/ifl-chat:<commit sha>`.
- Local build:
  ```
  cd server && make setup-go-work
  make build-client build-linux-amd64 package-linux-amd64 BUILD_ENTERPRISE=false
  cp dist/mattermost-team-linux-amd64.tar.gz build/
  docker build -f build/Dockerfile.ifl -t ifl-chat:local build
  docker run --rm --entrypoint /mattermost/bin/mattermost ifl-chat:local version
  ```
  Do not commit the tarball.
- Deploy by pulling the `<sha>` image on CT 122 and recreating the container with the `IFL_*` variables above.
- `.github/workflows/ifl-upstream.yml` runs weekly (Monday 09:00 UTC), finds the newest upstream release not yet in `ifl/main`, trial-merges it, runs tests, builds and pushes a candidate image `ghcr.io/friscojosh/ifl-chat:candidate-<tag>`, and opens or updates an issue titled `Upstream <tag>`. It never pushes a branch.

## Upstream releases

Done on a workstation, after an `Upstream <tag>` issue appears:

1. `git fetch upstream --tags`
2. `git checkout ifl/main`
3. `git merge <tag>`; resolve any conflicts keeping every `// IFL:` hook and every `ifl.*` string in `en.json`. Take in the release's own `Dockerfile` changes by hand if relevant to `Dockerfile.ifl`.
4. `cd server && make setup-go-work && go build ./... && go test ./channels/app/ifl/`
   The route tests in `server/channels/api4/ifl_test.go` are not run by CI: upstream's API test helper needs a Postgres and a Redis on `localhost:6379`. To run them, start both (for example `docker run -d -p 127.0.0.1:55620:5432 -e POSTGRES_USER=mmuser -e POSTGRES_PASSWORD=mostest_password -e POSTGRES_DB=mattermost_test postgres:16` and `docker run -d -p 127.0.0.1:6379:6379 redis:7`), then `TEST_DATABASE_POSTGRESQL_DSN='postgres://mmuser:mostest_password@127.0.0.1:55620/mattermost_test?sslmode=disable' go test ./channels/api4/ -run '^TestIFL' -count=1` (about a minute once compiled).
5. Push `ifl/main`; CI builds the image.
6. Deploy that image to CT 122 and run the acceptance checks (sign-in, panel session, linked suspension).
7. Close the `Upstream <tag>` issue.

Merge, do not rebase: it keeps `ifl/main` linear for CI and preserves conflict resolutions across releases.

## License (AGPL)

Mattermost server code is licensed under the GNU AGPL v3 (see `LICENSE.txt`); IFL Chat is a modified version. The source of the running service is this repository at the deployed commit: the image tag is the commit SHA, so `https://github.com/friscojosh/ifl-chat/tree/<sha>` is the corresponding source for the service built from that image.
