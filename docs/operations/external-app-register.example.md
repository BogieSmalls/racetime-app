# External application register (secret-free example)

The populated register is private and root/operator controlled. Evidence may
refer to its version/hash but never copy client secrets, tokens, webhooks,
credentials, allowlist CIDRs, or unnecessary Discord IDs.

| Field | Example safe value |
| --- | --- |
| Record ID | `APPREG-PRODUCTION-DISCORD-001` |
| Environment | `qualification` or `production` |
| Provider/type | `Discord OAuth`, `Twitch OAuth`, `category bot`, `alert webhook` |
| Public application name | reviewed non-secret name |
| Owner role | primary technical operator |
| Purpose/consumers | RaceTime, TTPBot, Restream, LiveSplit |
| Public client ID | include only when necessary for interoperability |
| Redirect URIs | exact canonical public values |
| Scopes/grants | least-privilege names |
| Credential store locator | non-secret locator, never value |
| Secret fingerprint | one-way fingerprint safe for rotation comparison |
| Created/rotated/expires | UTC timestamps |
| Revocation URL/procedure | provider page/runbook reference |
| Recovery route | role/process, no recovery data |
| Qualification revoked | date/result |
| Last probe/review | UTC, result, evidence ID |

Qualification and production entries are distinct. Late G2 revokes qualification
credentials while the application is stopped behind the hard barrier; production
evidence proves the old entries cannot authenticate.

Last reviewed: 2026-08-24 by the primary technical operator.
