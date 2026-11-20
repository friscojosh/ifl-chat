# IFL Chat

IFL Chat is the International Fantasy League's chat service: a fork of Mattermost Team Edition v12.1.0 (`ifl/main`). The league site, iflgm.com, is the identity provider; chat has no sign-up of its own. The fork keeps upstream code as unchanged as possible. Every IFL change is either new code under `server/channels/app/ifl/` and `server/channels/api4/ifl.go` or a small hook marked `// IFL:` in an upstream file.

## What the fork changes

- **Sign-in through iflgm.com.** The site's sign-in is presented as a GitLab-shaped OAuth provider, so the standard "GitLab" button signs members in. After the site confirms a member's eligibility, the member is reactivated if needed, provisioned, and joined to the league team.
- **Panel sessions.** `POST /api/v4/ifl/session` accepts a signed, single-use panel token from the site and opens a chat session for the embedded panel (with a CSRF token).
- **Linked suspensions.** Banning or deactivating a user in chat is reported to iflgm.com, so a ban in chat is a ban on the site.
- **Site client.** Server-to-server calls to the site go through `server/channels/app/ifl/site_client.go` using the internal secret. Redirects are never followed.

## Hooks into upstream files

Found with `grep -rn "// IFL:" server`. Keep every one when merging upstream.

| Location | Purpose |
| --- | --- |
| `server/channels/api4/api.go:430` | Registers the IFL routes (`api.InitIFL()`). |
| `server/channels/api4/user.go:1704` | Linked suspension: ban in chat is a ban on iflgm.com. |
| `server/channels/api4/user.go:1844` | Linked suspension (second path). |
| `server/channels/api4/user_local.go:337` | Linked suspension for local-mode (mmctl) changes. |
| `server/channels/app/oauth.go:769` | `CompleteOAuth` signup action (bypasses `LoginByOAuth`): the same reactivation and provisioning. |
| `server/channels/app/oauth.go:873` | `LoginByOAuth`, after the site confirms eligibility: reactivate, provision, join the team. |
| `server/config/client.go:454` | Shows the iflgm.com sign-in as a GitLab-shaped provider. |
| `server/channels/api4/ifl.go:1` | New file: the panel session route. |
| `server/channels/app/ifl_app.go:1` | New file: app-level glue for `server/channels/app/ifl`. |

New, IFL-only code: `server/channels/app/ifl/` (config, panel token, site client, actor, tests), `server/channels/api4/ifl.go`, `server/channels/app/ifl_app.go`, `server/build/Dockerfile.ifl`, `.github/workflows/ifl-*.yml`, `tools/slack-migration/` (Slack migration tools, Python; not part of the server build), this file.

### The `en.json` exception

`server/i18n/en.json` carries six `ifl.*` message strings (`ifl.panel.*` and `ifl.suspension.*`). It is the one upstream edit with no `// IFL:` marker because JSON has no comments. When merging, keep all `ifl.*` entries; merge conflicts here are usually adjacent-line additions, so keep both sides.

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
5. Push `ifl/main`; CI builds the image.
6. Deploy that image to CT 122 and run the acceptance checks (sign-in, panel session, linked suspension).
7. Close the `Upstream <tag>` issue.

Merge, do not rebase: it keeps `ifl/main` linear for CI and preserves conflict resolutions across releases.

## License (AGPL)

Mattermost server code is licensed under the GNU AGPL v3 (see `LICENSE.txt`); IFL Chat is a modified version. The source of the running service is this repository at the deployed commit: the image tag is the commit SHA, so `https://github.com/friscojosh/ifl-chat/tree/<sha>` is the corresponding source for the service built from that image.
