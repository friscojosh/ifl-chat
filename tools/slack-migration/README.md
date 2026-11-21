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
   account's locale to the default; neither check compares locale, so reset it by hand.
9. `inventory.py reconcile`: per-channel counts against Slack.

A later export goes in with the re-import mode below, never with this
pipeline as is: with fresh snapshots it would rename every imported channel
`-slack` and refuse every imported account.

## Second import (re-import)

To bring a newer Slack export into chat on top of the first import without
duplicating channels, accounts or posts. Chat's bulk import matches a post by
channel + exact `create_at` + exact message text (a reply also needs the same
root) and updates a match in place; any other post is created. Channels match
by name and users by SSO identity or username. So the second run must give
every old message exactly the text chat already holds, and must not send
lines that would change existing channels or accounts.

The first run's work directory (`$MIG/work/prod`: `channel_map.csv`,
`prepared.zip`, `import.zip`) is the authority, together with its emoji map
(`$MIG/work/emoji-prod/emoji_map.csv`). Keep them; never write into that
directory. With `--reimport-from` the tools:

- give every channel the first run imported the same chat name and display
  name (never `-slack`; each must still be in the chat snapshot) and drop its
  channel line, so headers, purposes and archive state in chat stay as they
  are; genuinely new Slack channels get the usual naming and are created;
- give every person and bot the first run imported the same username and
  accept their chat account as existing (linked members and the deactivated
  unmatched people alike); their user and bot lines are dropped, so locale,
  password, roles and memberships are untouched. A person newly confirmed in
  `identity_map.csv` must be linked in chat first (`flask chat
  link-slack-user`). New Slack people go through the normal identity flow;
- keep the first run's emoji renames over the new map (`--prior-emoji-map`;
  `import_emoji.py --prior-map` keeps the old chat names for the upload);
- `--since-first-import` (default): emit only posts and replies newer than
  the first import's latest `create_at` in their channel, and attachments
  only for those. A new reply in an old thread goes under its root exactly as
  the first import wrote it (text and attachments from the first
  `import.zip`, no reactions), so the root matches and keeps its files.
  Old messages edited in Slack are skipped and counted;
- `--full`: emit every post. **Every message edited in Slack (or rewritten
  differently) since the first export becomes a duplicate post**, and
  reactions members removed in chat come back. Use only when you have checked
  `reimport-check`'s `possible duplicates` and accept them.

Existing people are not added to *new* channels by the import (their user
lines are dropped); new channels are public, so they can join.

Commands use the plan's helpers (`mig_py`, `ct122`, `prod`, `members_csv`,
`counts_csv`, `validate_zip`). `P="$MIG/work/prod"`, `W="$MIG/work/reimport-<date>"`
(new, mode 700).

1. Inventory the new export (`inventory.py report`, `compare` against
   `$MIG/reports/inventory-1/channel_counts.csv`: no channel lost history),
   enrich it (`fetch-emails`, `fetch-attachments`), add rows for new Slack
   people to `identity_map.csv` and have Josh confirm them.
2. Current production snapshots (read-only), and emoji:

   ```bash
   prod 'exec -T mattermost mmctl --local user list --all --json </dev/null' > "$W/chat_users.json"
   prod 'exec -T mattermost mmctl --local channel list ifl </dev/null' > "$W/chat_channels.txt"
   mig_py "$TOOLS/import_emoji.py" --slack-env ~/.config/ifl-migration/slack.env \
     --chat-url https://chat.iflgm.com --chat-env ~/.config/ifl-migration/ifl-bot.env \
     --system-emoji "$FORK/server/public/model/emoji_data.go" \
     --prior-map "$MIG/work/emoji-prod/emoji_map.csv" --out-dir "$W/emoji"
   ```

   (Run it with `--dry-run` and a different `--out-dir` first. Old emoji
   report `unchanged`; only new ones upload.)
3. Build and predict:

   ```bash
   mig_py "$TOOLS/prepare_export.py" --input "$MIG/work/export-2-enriched.zip" \
     --identity "$MIG/work/identity_map.csv" --chat-users "$W/chat_users.json" \
     --chat-channels "$W/chat_channels.txt" --emoji-map "$W/emoji/emoji_map.csv" \
     --reimport-from "$P" --prior-emoji-map "$MIG/work/emoji-prod/emoji_map.csv" \
     --archive-state "$MIG/work/archive-state.csv" \
     --output "$W/prepared.zip" --channel-map "$W/channel_map.csv" --report "$W/prepare.md"
   (cd "$W" && "$MIG/bin/mmetl" transform slack --team ifl --file prepared.zip --bot-owner josh_0 \
     --output data.jsonl --attachments-dir data) > "$W/mmetl.log" 2>&1
   mig_py "$TOOLS/rewrite_import.py" --input "$W/data.jsonl" --attachments-dir "$W/data" \
     --identity "$MIG/work/identity_map.csv" --chat-users "$W/chat_users.json" \
     --channel-map "$W/channel_map.csv" --emoji-map "$W/emoji/emoji_map.csv" \
     --system-emoji "$FORK/server/public/model/emoji_data.go" \
     --reimport-from "$P" --since-first-import --plan "$W/plan.csv" \
     --output-zip "$W/import.zip" --counts "$W/import_counts.csv" --report "$W/rewrite.md"
   mig_py "$TOOLS/inventory.py" reimport-check --prior "$P/import.zip" --new "$W/import.zip" \
     --chat-channels "$W/chat_channels.txt" --out "$W/reimport_check.csv"
   validate_zip "$W/import.zip"
   ```

   `prepare.md` lists channels, people and bots from the first import and new
   ones. `rewrite.md` and `reimport-check` predict what the import adds: new
   channels, posts, replies, reactions and attachments, plus what is skipped
   (old messages edited in Slack, reactions added to old messages, threads
   whose root chat cannot identify). `reimport-check` recomputes it from the
   finished archive with the server's match rule and exits 1 on a hazard: a
   channel line for a channel already in chat, a matched post whose
   attachments differ (the import would delete its files), or a possible
   duplicate. Josh reviews the numbers before anything is imported.
4. Backups first (production; Josh's go-ahead). Stop the nightly timer,
   take a backup and copy it out of the 72-hour cleanup, then a vzdump of
   CT 122 to the NAS (`documents`):

   ```bash
   ct122 'systemctl stop ifl-chat-backup.timer && systemctl start ifl-chat-backup.service && journalctl -u ifl-chat-backup.service -n 3 --no-pager'
   STAMP=<stamp>
   ct122 "install -d -m 700 /var/backups/ifl-chat-reimport && cp -p /var/backups/ifl-chat/db-$STAMP.dump /var/backups/ifl-chat/files-$STAMP.tar.gz /var/backups/ifl-chat-reimport/ && ls -l /var/backups/ifl-chat-reimport"
   ssh root@192.168.1.15 "set -o pipefail; vzdump 122 --storage documents --mode snapshot 2>&1 | tee /root/vzdump-122-reimport.log | tail -5"
   ```

   Record `STAMP` and the vzdump archive path. No vzdump archive, no import.
5. Record, load and import:

   ```bash
   prod 'exec -T mattermost mmctl --local user list --all --json </dev/null' > "$W/users_before.json"
   members_csv prod > "$W/members_before.csv"
   counts_csv prod > "$W/db_counts_before.csv"
   ct122 'mkdir -p /opt/ifl-chat/data/mattermost/data/ifl-import'
   ct122 'cat > /opt/ifl-chat/data/mattermost/data/ifl-import/import.zip' < "$W/import.zip"
   ct122 'cd /opt/ifl-chat/data/mattermost/data/ifl-import && chown -R 2000:2000 . && sha256sum import.zip'
   sha256sum "$W/import.zip"
   prod 'exec -T mattermost mmctl --local import process --bypass-upload /mattermost/data/ifl-import/import.zip --extract-content=false --workers 2 </dev/null'
   ```

   Follow the job with `mmctl --local import job show <id>` until `success`.
6. Reconcile:

   ```bash
   prod 'exec -T mattermost mmctl --local user list --all --json </dev/null' > "$W/users_after.json"
   mig_py "$TOOLS/inventory.py" accounts "$W/users_before.json" "$W/users_after.json"
   members_csv prod > "$W/members_after.csv"
   mig_py "$TOOLS/inventory.py" members "$W/members_before.csv" "$W/members_after.csv" > "$W/restore.csv"
   counts_csv prod > "$W/db_counts_after.csv"
   mig_py "$TOOLS/inventory.py" reimport-verify --before "$W/db_counts_before.csv" \
     --after "$W/db_counts_after.csv" --check "$W/reimport_check.csv" --out "$W/reimport_verify.csv"
   ```

   Expected: `ok: existing chat accounts unchanged`; `0 membership(s)
   changed`; `reimport-verify` 0 differ (posts members made in chat during
   the window explain any surplus). Then restart the timer
   (`ct122 'systemctl start ifl-chat-backup.timer'`) and delete the archive
   from the data volume. Rollback: the README's in-place restore with `STAMP`
   (vzdump as the fallback), as in the cutover.

Originals are never modified; every step writes a new file.
Files that hold emails or tokens are mode 600.

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q tests
```
