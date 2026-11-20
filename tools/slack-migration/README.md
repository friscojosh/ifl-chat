# Slack migration tools

Move the league's Slack public-channel history and custom emoji into IFL Chat
(league chat spec §5). The full procedure, with every command, is
`docs/superpowers/plans/2026-11-20-chat-slack-migration.md` in
`friscojosh/ifl-website` (branch `docs/league-chat-spec`).

## Pinned tools

| Tool | Version | Built by |
|---|---|---|
| mmetl | v0.6.0, commit `07f81df74c218061981a97feb746231919c4f058` | `build_tools.sh` |
| slack-advanced-exporter | v0.4.0, commit `c0f7bf8230cd15d9b44af36d73ce8f0650538c67`, plus `sae-token-from-env.patch` | `build_tools.sh` |
| mmctl | the one inside the IFL Chat image production runs | `docker run --entrypoint /mattermost/bin/mmctl` |
| Python | 3.12 or newer; packages in `requirements.txt` | `python3 -m venv` |

`sae-token-from-env.patch` is maintained here; re-check each change before
moving the exporter pin. It makes slack-advanced-exporter:

- read `SLACK_API_TOKEN` from the environment (never a command line);
- exit 1 when a command fails (upstream always exits 0);
- download only `https://files.slack.com/…`, never follow a redirect, and
  skip every other host without a request, so the token reaches no other
  host;
- save a file only for HTTP 200 that is not an HTML page.

The Slack token goes nowhere else: `import_emoji.py` sends it only to
`https://slack.com/api/emoji.list`, `inventory.py check-urls` only to
`https://files.slack.com`, and `prepare_export.py` / `rewrite_import.py`
make no network requests.

## Pipeline

1. `inventory.py report` and `inventory.py users`: what the export holds.
2. `slack-advanced-exporter fetch-emails`, then `fetch-attachments`: each
   writes a new archive.
3. `flask chat slack-match` on CT 126 proposes Slack-to-site matches;
   Josh confirms them in `identity_map.csv`.
4. `import_emoji.py`: custom emoji into chat; writes `emoji_map.csv`.
5. `prepare_export.py`: final usernames, emails, channel names, bots,
   file notes and emoji names in a new Slack-format zip; writes
   `channel_map.csv`.
6. `mmetl transform slack --team ifl --bot-owner josh_0`.
7. `rewrite_import.py`: SSO links, active state, display names, checks,
   and the import zip.
8. Before the import, snapshot existing accounts and memberships
   (`mmctl --local user list --all --json`, and the members CSV the plan's
   runbook names). Then `mmctl import validate` and
   `mmctl --local import process --bypass-upload`. After it, run
   `restore-scheme-roles.sh`, take the same two snapshots again and compare
   them with `inventory.py accounts BEFORE AFTER` and
   `inventory.py members BEFORE AFTER`. The import resets an existing
   account's locale to the default; `accounts` reports that, restore it by hand.
9. `inventory.py reconcile`: per-channel counts against Slack.

Originals are never modified; every step writes a new file.
Files that hold emails or tokens are mode 600.

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q tests
```
