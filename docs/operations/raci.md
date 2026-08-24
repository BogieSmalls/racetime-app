# RaceTime operating roles

The primary technical operator is the sole routine OCI, DNS, deploy, backup,
monitoring, secret-rotation, and cutover executor. Technical and cost choices are
recorded, not routed through artificial multi-operator approval. Council retains
organizational outcome/launch/risk/public-message decisions.

| Activity | Responsible | Accountable/decision | Consulted | Informed |
| --- | --- | --- | --- | --- |
| Architecture/IaC/shape/cost forecast | Primary technical operator | Primary technical operator | Tech/Restream as useful | Council |
| G1 Plan-B activation | Primary technical operator records | Council decision owner | Program leads | Community as appropriate |
| Deploy/rollback/backup/monitoring | Primary technical operator | Primary technical operator | Integrity on race impact | Council on P0/P1 |
| G2 functional/integrity acceptance | Primary technical operator | Competitive Integrity representative | TTP/Restream/League/TC/TT | Council |
| G3 public Go/Hold | Primary technical operator executes | Council decision owner | Integrity/component leads | Community |
| TTP scheduler and room workflow | TTP/Major Tourney lead | TTP/Major Tourney lead | Primary technical operator | Discord Moderation |
| Restream/provider acceptance | Tech and Restream lead | Tech and Restream lead | Primary technical operator | Council |
| Category/race rulings | Competitive Integrity lead | Competitive Integrity lead | Council | Affected racers |
| Public/community moderation | Discord Moderation lead | Discord Moderation lead | Council/Integrity | Community |
| Sealed recovery custody | Recovery custodian | Council designates holder/replacement | Primary technical operator | Council (metadata only) |

The recovery custodian holds the tamper-evident escrow recovery account, recovery
SSH key, and separate backup-key copy. They release the package only to the
primary technical operator or formally designated replacement and never receive
routine host/admin/allowlist access or a technical approval duty.

Account-level recovery must reach OCI tenancy administration, GitHub organization
and GHCR ownership, and authoritative DNS through a verified second account,
sealed route, or documented platform recovery process. It creates no standing
second technical approver.

Last reviewed: 2026-08-24 by the primary technical operator.
