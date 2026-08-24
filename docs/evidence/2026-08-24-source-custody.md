# G0 upstream source custody evidence — 2026-08-24

## Result

**PASS.** The accepted RaceTime upstream source and wiki bundles, manifest, and
checksums have a verified off-workstation copy in OCI Object Storage. The four
objects were downloaded by immutable version ID into a new empty temporary
location, their SHA-256 values were recomputed, and the downloaded archive
restored exact upstream `master` commit
`4dbe61fb06d2a132f2e1212e34ac2ae3a6d18069`.

## Authorized boundary

The primary technical operator authorized one narrow G0 source-preservation
exception on 2026-08-24. It permits only a private custody bucket and these four
public source-preservation objects. It is not G1 Plan-B activation and did not
create or change Compute, networking, DNS, OAuth applications, secrets,
schedulers, public releases, production backups, or `z1rr-production`.

## Storage controls

- Custody role: off-workstation upstream-source archive; custodian: primary
  technical operator.
- Bucket: `z1rr-racetime-source-custody` in the existing `z1rracing`
  compartment.
- Public access: `NoPublicAccess`.
- Versioning: `Enabled`.
- Storage tier: `Standard`.
- Encryption: Oracle-managed server-side encryption.
- Object events: disabled.
- Bucket creation time: `2026-08-24T20:40:09Z`.
- Total accepted object bytes: 2,406,593 (approximately 2.30 MiB); incremental
  Object Storage cost is immaterial at current OCI pricing and usage.

## Immutable object record

| Object | Version ID | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `source-preservation/2026-08-24/racetime-app-20260824T003609Z.bundle` | `ce12f801-3616-42de-bb00-bee01ff789b1` | 1,859,653 | `f5d57276f281a7ed80c322aab8bf874df95d03366649329daf3e74b42644cb1e` |
| `source-preservation/2026-08-24/racetime-app-wiki-20260824T003609Z.bundle` | `b8ae4f41-4114-4e6e-9151-690245651409` | 545,227 | `d462e141ad5e772561251098e3a93110d56a5519bbeaedd40375b35dfee668b4` |
| `source-preservation/2026-08-24/UPSTREAM_BASELINE.json` | `7ed72370-7b5d-4b89-986f-749505465c70` | 1,483 | `ca41ad0a0e5ea07ba567ac087cdc9d29b0909b9e0572fd7482a6f659784c3e15` |
| `source-preservation/2026-08-24/SHA256SUMS` | `8c653935-8072-43f0-ac75-9d2c2d9f4e1f` | 230 | `6caa81d4c833b4c77bf37ad7ede25648344728dd43e50973e105742bbc595beb` |

## Independent re-read and restore

At `2026-08-24T20:43:30Z`, all four objects were fetched by the version IDs
above into a new uniquely named directory outside the repository. Every
downloaded SHA-256 matched the accepted local source. The exact documented
verifier then returned:

```text
PASS: restored 4dbe61fb06d2a132f2e1212e34ac2ae3a6d18069 on master
RESTORED_BRANCH=master
RESTORED_HEAD=4dbe61fb06d2a132f2e1212e34ac2ae3a6d18069
```

The verifier also checked bundle sizes and hashes before Git access, verified
both bundles and every recorded ref, restored the wiki, and ran the required Git
integrity checks. No cached local bundle was used for this restore.
