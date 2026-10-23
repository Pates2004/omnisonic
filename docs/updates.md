# Verified source updates

OmniSonic1.1 introduces an opt-in source updater for the official repository,
not a second Python/package installer. Start normally with `start_desktop.bat`.
The updater runs before the desktop and Python bootstrap, using Windows
PowerShell5.1 and the system HTTPS stack. It never installs Git or Python globally.

## What qualifies as an update

The candidate is the current `Pates2004/omnisonic` `master` SHA. The most recent
matching push run of `.github/workflows/quality.yml` must be completed and
successful, with the same repository, branch and exact SHA. An older green run,
pull-request check or different branch is insufficient. HTTPS requests and
archive sizes have explicit limits; redirects to other hosts are not followed.
No credentials are collected for public update discovery.
Git fetches have a90-second deadline and cannot open invisible credential prompts.
The restarted launcher keeps installation/repair prompts visible; a saved ready
installation uses the normal hidden-launch path when requested in settings.

The dialog shows the source version/revision/date and at most ten recent commit
subjects, not an automatically translated or exhaustive release changelog. Close
or No declines. Offline, rate-limited or untested candidates do not prevent
ordinary startup. `OMNISONIC_SKIP_UPDATE=1` skips discovery; maintenance/test
arguments skip it too.

## Preserved files and refused cases

The complete source ownership list is `update_manifest.json`, generated from
reviewed tracked files. It excludes itself, local instructions, configurations,
presets, environments, logs, backups, models and the nested launcher. Source
hashes normalize only CRLF to LF; rollback hashes preserve exact original bytes.
An incoming file cannot overwrite an unknown existing file. Changed/deleted
maintained files, links/junctions, unsafe ZIP names, unsupported/binary source,
or a changed bootstrap BAT stop the update rather than discard local data.

A source ZIP can update without Git or an installed Python, but needs this
version's shipped manifest first. A Git checkout must use the ordinary clean
official `master` layout. The updater validates fast-forward ancestry and the
exact target tree, then updates both source and Git state. Custom hooks/filters,
redirected indexes/worktrees, alternate origins and local changes require a
normal manual Git workflow instead; protected workflows are not bypassed.

Close other OmniSonic processes before accepting. The updater shares
`.launcher/runtime.lock` with runtime preparation and Power Switch and rechecks
running applications after the confirmation. It never force-closes a window,
recording or generation. A rootless external Python module instance may be
conservatively treated as busy when its installation cannot be identified.

## Recovery and temporary copies

Downloads are staged under `.launcher/updates/`; an exact previous-source backup,
journal and frozen recovery runner live under `.launcher/update-recovery/`.
These copies exist only to recover the current update. No preset, setting,
runtime, model or audio directory is copied into them. File replacement is
atomic and journaled. Unknown/concurrently changed files prevent rollback or
cleanup and are reported, never guessed away.

The bootstrap invokes the frozen recovery runner before possibly mixed live
source. An applying transaction is rolled back where safe; a committed one
waits for the new application's successful launch. Only then are the verified
backup/download files removed. If cleanup cannot be verified, the app remains
usable and reports the retained recovery path. Preserve that folder when
reporting an interrupted update. Do not manually delete an unknown recovery
folder or run a guessed hard reset. Existing user data and runtime backups are
separate and are not cleaned by the source updater.
A failure while preparing backups, before any source writes or recovery pointer,
can retain incomplete diagnostic files. The current application remains usable;
another update refuses that nonempty recovery area and reports its exact path
for manual review instead of piling up copies or deleting unrecorded data.

## Maintaining a release

After all source changes are finalized, regenerate the source manifest and
review its paths/hashes before publishing. `tools/update_manifest.py` prints
the proposed JSON to stdout; `--include-new <exact-path>` includes a reviewed
new file before staging. `--check` is read-only and verifies the checked-in
manifest against tracked source. CI runs that check plus updater, archive,
rollback, consent, bootstrap and ordinary application regressions. Updating
the source without regenerating its manifest is rejected by CI.

The bootstrap BAT is intentionally stable. A future bootstrap change requires
a manual package update before later automatic source updates can proceed.
Source testing does not guarantee every GPU driver, model file or audio device;
normal runtime validation and explicit accelerator fallback remain independent.
