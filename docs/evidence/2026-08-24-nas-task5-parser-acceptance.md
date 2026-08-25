# RaceTime Synology Task 5 final parser acceptance (redacted)

**Durable import:** 2026-08-24 Task 6 qualification.
**Sanitized source artifact:** `nas-task5-final-parser-acceptance-20260825T012329Z.md`.
**Source artifact SHA-256:** `f01458250a443777ea4ccd675e978a956dc85f1da095524f3a4cc2403937cd67`.

- Disposition: `DONE`.
- Authorized and executed commit: `81ff60187ce1b7f310393636f9218fe8ea11e866`.
- Scope: dedicated Compose project `z1rr-racetime-integration` only.
- NAS workspace: `/volume1/docker/z1rr-racetime-integration-55833b7e5710-20260824T205537Z`.
- SSH host identity: pinned `ssh-ed25519` fingerprint `SHA256:6H/Jz0/mm5QZV8mHAV+5NAZOVqtXqc6e+uBp0Ea/1p8=` matched before every connection.

## Exact source custody

- The local readiness worktree began and ended clean at exact HEAD `81ff60187ce1b7f310393636f9218fe8ea11e866`.
- Exact git-archive SHA-256: `9f8b3c09f5c616bffeed1b58b658433f41713f2e7e41f12918f96ab59cf8905c` (2,611,200 bytes).
- Archive-byte-derived SHA-256 manifest digest: `148c6fab0015d01db4e8233d0674b41cc7fee71a9790dc8ac2fd2343a9cf916d`.
- Commit `81ff6018` contains 480 tracked regular files. This is three more than `69449f0`: the commit adds `scripts/integration-health.ps1`, `tests/e2e/integration_health.Tests.ps1`, and `tests/e2e/test_integration_health_parser.py`.
- Host-pinned legacy SCP transferred the archive and manifest to the already validated dedicated source workspace; Synology SFTP was not used.
- The NAS archive and manifest digests matched before extraction. All 480 archive-derived file hashes and the exact file-name set passed remotely after extraction.
- Remote `scripts/integration-health.ps1` SHA-256: `bfcf35b0aa61f6b787e957d850e0d6a723f65de1fef360050d1bf55954fa315b`, matching the exact archive.
- Remote upload archive, manifest, and comparison temporaries were deleted before runtime qualification.
- Two preliminary manifest-verification attempts stopped before runtime: the first exposed CRLF manifest lines and the second exposed 19 worktree/archive line-ending differences. The final manifest was derived from the exact git archive; both preliminary attempts removed their remote transfer temporaries.

## Actual startup path and health gate

- Executed the actual unmodified repository `scripts/integration-up.ps1`; exit code `0`.
- A temporary credential-free local Docker CLI bridge rewrote only the exact local Compose/environment paths to the validated NAS workspace and rejected commands outside project `z1rr-racetime-integration` or the script's allowlisted operations.
- Every Compose operation used `/volume1/@appstore/ContainerManager/usr/bin/docker`; the supplied password was consumed directly from SSH stdin by `sudo -S` and was never written, printed, placed in argv/environment, or retained in evidence.
- Native NAS web/racebot builds completed with image IDs `sha256:2dd70b562054f4dcf645f23adf7b6946dcfa8ba4ea4a41329d445114a758bace` and `sha256:b185c1a28e795e262bd3a40372df3bc0b861f94d46b943de879e04c70747b717`.
- Database migrations completed through `racetime.0082_externalidentity`; static collection copied 201 files; deterministic owner `1001`, category `z1rr`, goal, and public loopback OAuth fixture were prepared.
- The live Synology `docker compose ps --format json` result was independently confirmed to be the legacy JSON-array format.
- The new dual-format parser accepted that real legacy array. Exactly six records were present and all were `running` / `healthy`: `caddy`, `db`, `fixture-provider`, `racebot`, `redis`, and `web`.
- The pinned tunnel HTTPS probe returned status 200 and exact body `{"status":"ok"}`.
- Local `.ready` matched schema `1`, project `z1rr-racetime-integration`, and origin `https://integration.racetime.test:8443`.
- Redacted startup-log SHA-256 before deletion: `769268b2817cdd9d3b2cb2e733270598768ab978b8cb4f2cecd2ec6e4b8f6148`.

## Mandatory E2E qualification

- Exact command: `venv\Scripts\python.exe -m unittest discover -s tests\e2e -v`.
- Result: 13 tests ran in 39.548 seconds; `OK`; zero failures, errors, or skips.
- `test_two_entrants_finish_and_leaderboard_records` completed `ok`, proving the full headless-Chromium two-entrant race and leaderboard-record lifecycle without a skip.
- `test_dual_format_parser_and_exact_health_gate` completed `ok`.

## Exact-project teardown and residue proof

- Executed the actual unmodified repository `scripts/integration-down.ps1`; exit code `0` after `down --volumes --remove-orphans` for the exact guarded project.
- Redacted teardown-log SHA-256 before deletion: `8f39fe08b1321f818fc26eaef951e3b280c1394be194184e8cd929599ce3bb91`.
- Independent label-filtered checks proved exact-project containers, networks, and volumes absent.
- Independent exact-name inspection proved networks `z1rr-racetime-integration-proxy` and `z1rr-racetime-integration-data` absent.
- Independent exact-name inspection proved volumes `z1rr-racetime-integration-db`, `-redis`, `-media`, `-static`, `-caddy-data`, and `-caddy-config` absent.
- Local and remote `artifacts/integration/.ready` were absent; the pinned local loopback tunnel was stopped.
- Remote upload temporaries were absent, and the dedicated NAS source workspace retained the exact 480-file source tree.
- Temporary local bridge source/shim/bytecode, source archive/manifest/extraction, and raw runtime logs were deleted after producing this redacted evidence.

Remaining by design: the dedicated NAS source workspace and unpushed locally built web/racebot images. Teardown did not use `--rmi`, and no image was published. No NAS package, binfmt, daemon, socket, group, sudoers, DNS, OAuth scheduler, public service, or unrelated system configuration was changed.
