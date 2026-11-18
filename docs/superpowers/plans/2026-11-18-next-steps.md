# Next Steps after the Blizzard Switch

Date: 2026-11-18. Follows `2026-11-18-blizzard-source.md` (WP0 to WP5 done, WP7.1 done with this plan).

## Where things stand

- The hourly and nightly workflows are live in the private data repo. Two manual hourly runs have succeeded (hours 14:00 and 16:00 UTC on `main`, `window` exists). No scheduled run has fired yet, and the first nightly run is due at 00:50 UTC.
- The public tree has no mention of the old source left: `tests/test_no_old_source.py` guards it. The `collector/legacy/` package, its test, the probe scripts, the own-scans note and the finished 2026-11-17 plans are deleted. CLAUDE.md and CHANGELOG describe only the Blizzard setup.
- Still open from the old plan: the old source is still in the public repo's **git history** (origin `main` and `dev`), in 13 `claude/*` branches and worktrees, in the old `private/` clone, and in the auto-memory.

## Phase A: finish the purge (Jack confirms each step in chat)

Each step can't be undone, so each one waits for Jack's yes.

1. **Worktrees and branches.** Remove the 13 `.claude/worktrees/*` checkouts and their `claude/*` / `worktree-agent-*` branches. All work from `wp1` to `wp4` is merged into `dev`; the older ones are from before the switch.
2. **History rewrite (plan task 7.2).** One new root commit of the current `dev` tree on `main` and `dev`, a force-push of both, then `git reflog expire` and `git gc`. Check: `git log --all --oneline` prints one line. Afterwards every other clone must re-clone.
3. **Local folders.** Delete the old `private/` clone (old data repo, now gone on GitHub), `data/`, `build/` and `dist/`. Then move `private-next/` to `private/` (it is already the new repo's clone) and drop the `private-next/` line from `.gitignore`.
4. **Memory.** Delete the archive-cutoff memory and add one on the Blizzard source (house 111, the 30-day rule and Jack's reading of it).
5. **Left to Jack:** old session transcripts under `~/.claude`, his own AH-check skill, and GitHub's 90-day restore window for the deleted repo.

## Phase B: prove the live pipeline (plan task 7.3)

1. **Scheduled hourly runs.** Confirm that the `35 * * * *` cron fires on its own (new repos sometimes start late) and that runs at :35 find the :22 snapshot. Look for "not modified" exits and gaps in `hourly/`.
2. **First nightly run.** It should write `selection/<day>.parquet`, and `git log` on `window` should show one commit. Check that the force-push leaves `window/` working after a GUI pull.
3. **Logs.** `gh run view --log` holds no prices and no secrets (grep for `unit_price`, `buyout`, `client_secret`).
4. **GUI on real data.** Pull in the app, then check that the data age is under 2 h, item names show, the credit is visible, and every pattern tab shows either results or a correct "ready on" date.
5. **Actions minutes.** After 3 days, read the minutes actually used. The estimate is about 1,500 of 2,000 a month, which leaves little headroom. If it runs higher, options are a lighter hourly job (cache `uv`), skipping hours with no change, or the Raspberry Pi.

## Phase C: check the new data (as history builds up)

| When (approx.) | What becomes possible | Check |
|---|---|---|
| after 1 day | spreads, mispricings, buyouts, vendor floor, builds | sales estimate: gone and partial units look plausible, cancels inflate it (upper bound); compare `sold_est` with listing churn |
| 2026-11-21 (3 days) | inflation, supply shocks, progression | `house` totals are continuous and `gold_listed` has no jumps from missed hours (`span_hours > 1`) |
| 2026-11-25 (7 days) | daily rhythm; selection ranking uses its full `rank_days` | selection churn per night, cap reached or not (1,642 items today) |
| 2026-12-09 (21 days) | correlations, mean reversion | first full results; sanity check against in-game prices |
| 2026-12-16 (28 days) | weekday and raid reset | all 12 patterns live |

The old baseline numbers were deleted with the old source. Once 7 days exist, record a new baseline from `python -m coppertrail.patterns baseline` in the handover, so later changes can be compared against it.

## Phase D: product follow-ups (each its own session, after Phase B)

1. **Spec refresh.** The 2026-11-17 GUI and pattern specs still name the old tables (`snapshot`, `scans`, `economy`). Add a short note at the top of each pointing to the Blizzard spec, or update the table names.
2. **Exe on the new data.** Rebuild `Coppertrail.exe` and smoke-test it against the new `private/` with its `window/` checkout (pull, cold start, all views).
3. **First release.** Merge `dev` into `main`, tag, and let the workflow attach the exe. Only on Jack's call, with the CHANGELOG under the version he names.
4. **Later, out of scope for now:** a listing archive on the Raspberry Pi, month files once the data repo nears 1 GB, and a second house (the config is ready for it).

## Open decisions for Jack

- Go-ahead for each Phase A step (they can't be undone).
- Whether to switch the workflow's code checkout from `dev` to `main` once a release exists, so data collection doesn't follow unreleased code.
- What happens if the Actions minutes run short.
