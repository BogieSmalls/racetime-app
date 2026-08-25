# Plan B activation — 2026-08-25

## Decision

`PLAN_B_ACTIVATED`: authorize the G1 external prerequisites for
`https://racetime.z1rracing.com`.

The primary technical operator activated Plan B after the Racetime.gg category
request remained unresolved long enough to threaten the implementation window.
The operator explicitly authorized provisioning a dedicated OCI instance named
`racetime`, initially `VM.Standard.A1.Flex` at 1 OCPU / 6 GB with one new 50-GB
Balanced boot volume. The expected approximately $0.48 prorated August boot
volume cost and approximately $2.13 full-month incremental boot-volume cost are
accepted routine operating expenses.

## Ownership and window

- Decision and primary technical operator: bogie.
- Decision date: 2026-08-25.
- Qualification window: begins 2026-08-25 and continues while the instance is
  duty-cycled between active development sessions.
- Public launch window: unscheduled and no earlier than complete G2 evidence and
  an explicit G3 go decision.
- Rollback authority: primary technical operator.
- Recovery custodian: not yet designated. The sealed recovery receipt remains a
  G1 completion blocker and does not prevent this explicitly authorized,
  reversible infrastructure bootstrap.
- Canonical hostname: `racetime.z1rracing.com`.

## Authorized bootstrap boundary

This activation authorizes the reviewed Terraform plan for the dedicated
RaceTime VM and its named NSG, Bastion, private versioned backup bucket,
instance-principal policy, notification topic, and alarms. It also authorizes a
separate private versioned Terraform-state bucket required by the approved
native OCI backend.

The development instance may be stopped through the OCI API/CLI whenever it is
not in use. An operating-system shutdown alone is not the recorded stop method.

This record does **not** authorize public launch, production OAuth or bot
credentials, scheduler changes, a public announcement, or G3 access removal.
DNS is not created until the reserved public IP is known and the qualification
routing sequence is ready. Qualification data and credentials cannot be
promoted into fresh production state.

## Gate disposition

- G0: **HOLD** pending the remaining native ARM64/amd64 qualification, service,
  recovery, provenance, and release-identity evidence.
- G1: **HOLD** until the reviewed apply, host bootstrap, DNS/restricted-routing,
  recovery-custody, backup, alert, and checklist evidence are complete.
- G2/G3: not authorized by this activation record.

The OCI ARM64 host may be used to close the native ARM64 portion of the G0
qualification blocker. The Synology remains the native amd64 worker. This
worker selection does not waive either architecture's required evidence.
