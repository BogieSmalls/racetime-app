# RaceTime Dedicated-Subnet Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stopped, empty `racetime` instance on a dedicated OCI subnet with no inherited public SSH and give it a stable reserved public IPv4 address.

**Architecture:** Create and verify the RaceTime-only subnet/security list before terminating anything. Reconcile the manually removed empty instance through a reviewed refresh-only plan, then create the replacement and reserved public IP through a separate reviewed normal plan. Existing Restream resources and shared VCN plumbing remain read-only.

**Tech Stack:** Terraform 1.12.2, Oracle OCI provider 8.27.0, OCI CLI `API_KEY` profile, Python `unittest`, PowerShell 7.

**Spec:** [Dedicated-subnet correction design](../specs/2026-08-25-racetime-dedicated-subnet-correction-design.md)

**Control documents:** [Architecture](../specs/2026-08-12-plan-b-racetime-architecture-design.md), [requirements and decisions](../../racetime-z1rr/requirements-and-decisions.md), [master plan](2026-08-22-z1rr-racetime-launch-master.md)

**Execution boundary:** G1 reversible infrastructure bootstrap only. No DNS mutation, image publication, production credentials, OAuth/Discord changes, or G3 launch.

---

## File map

- Modify `.gitignore`: keep all `.tmp` raw evidence and helper material outside Git.
- Create `scripts/oci/verify_saved_plan.py`: fail-closed phase-specific Terraform plan verifier with redacted output.
- Create `tests/platform/test_oci_saved_plan_verifier.py`: synthetic behavior tests for all four saved-plan phases and evidence hygiene.
- Modify `tests/platform/test_terraform_contract.py`: assert the dedicated subnet, custom security list, stable public-IP graph, and continued Restream read-only boundary.
- Modify `infra/oci/data.tf`: read the existing Bastion subnet and resolve the replacement VNIC's primary private-IP object.
- Modify `infra/oci/network.tf`: own the RaceTime security list/subnet and, in the recreation phase, the reserved public IP.
- Modify `infra/oci/compute.tf`: switch only the replacement instance to the dedicated subnet, disable ephemeral public-IP assignment, and bind provider 8.27's separate create/update encryption fields.
- Modify `infra/oci/variables.tf`: add the explicit RaceTime subnet CIDR contract.
- Modify `infra/oci/terraform.tfvars.example`: document the non-secret subnet value.
- Modify `infra/oci/tests/activation_gate.tftest.hcl`: supply the subnet CIDR and deterministic mocked private-IP data if required by the precondition.
- Modify `infra/oci/outputs.tf`: make the reserved IP the canonical DNS output.
- Modify `infra/oci/README.md`: document the dedicated network, staged correction, reserved address, and verification commands.
- Create `docs/evidence/2026-08-25-oci-subnet-correction.md`: redacted exposure, plan, termination, replacement, and verification evidence.

## Global constraints

- Keep the original `racetime` instance stopped until its explicit termination step.
- Never change the existing Restream subnet, default security list, route table, DHCP
  options, instances, VNICs, or volumes. Existing duty-cycle automation may independently
  start or stop a Restream instance; accept such a lifecycle-only difference only when
  OCI Audit proves the exact action occurred outside Terraform, every other captured
  field remains identical, and the post-transition inventory is retained as the
  continuing baseline.
- Do not remove `prevent_destroy` from any Terraform resource.
- Use saved plans for every state-changing Terraform action and record each plan SHA-256 before apply.
- Reject public TCP/22, 3306, or 6379 at the live OCI boundary.
- Keep all OCIDs, IPs other than the final public DNS target, state files, plans, and raw CLI output in ignored local evidence; commit only redacted summaries and hashes.
- Before each commit, compare `git diff --cached --name-only` to that task's exact file allowlist and stop on any extra path.
- Redirect every unredacted `terraform show -json`, `terraform state pull`, and OCI JSON response directly to an ignored file. Never echo, `tee`, or include the raw response in terminal/evidence output; only a parser-generated redacted summary may be displayed.
- Require PowerShell 7.4 or newer for native-command evidence capture. Use direct native
  `>` redirection, which preserves stdout bytes; never pipe custody JSON through
  `Set-Content`, `Out-File`, or text decoding/re-encoding.

## Interruption and failure handling

- On any nonzero plan/apply/OCI command, stop and preserve the backend plus ignored raw evidence. Never apply or reuse a stale saved plan.
- Inventory the live state, generate a new saved plan, rerun the phase verifier, and review its hash before continuing.
- Never remove `prevent_destroy`, relax the shared Restream network, attach the VCN default security list, or publish DNS to recover from a partial action.
- Task 3's live additive verification is a hard prerequisite for Task 4 termination; no evidence-only judgment may bypass it.
- If replacement partially succeeds, retain the instance, reserved address, subnet, and security list; block DNS and bootstrap and forward-repair through another reviewed plan.
- If Terraform state and live OCI disagree, use a saved refresh-only plan or the documented narrow imports. Do not use `terraform refresh`, broad state removal, or name-based discovery.

---

### Task 1: Build evidence and saved-plan safety gates

**Files:**
- Modify: `.gitignore`
- Create: `scripts/oci/verify_saved_plan.py`
- Create: `tests/platform/test_oci_saved_plan_verifier.py`

- [ ] **Step 1: Write failing evidence-hygiene and plan-verifier tests**

Require `/.tmp/` in `.gitignore` and prove `git check-ignore -q
.tmp/evidence/probe.json` succeeds. Use synthetic Terraform JSON fixtures to require:

- common: `applyable=true`, `errored=false`, Terraform `1.12.2`, no
  unexpected resource/action/address, binary plan SHA-256 equal to the reviewed digest,
  exact Git HEAD equal to the supplied source commit, and a clean worktree including no
  non-ignored untracked files;
- `subnet-add`: `complete=false` only when expected JSON contains the exact boolean
  `targeted_plan=true`; otherwise `complete=true`. Require exactly two creates, exact
  CIDR/DNS/public/route/DHCP/zero-ingress/
  one-egress values, omission of an `availability_domain` configuration expression
  (planned null or computed-unknown are both valid), and a configuration reference from
  subnet `security_list_ids` to `oci_core_security_list.racetime.id`;
- `refresh-only`, `replacement`, and `launch-encryption`: always `complete=true`; a
  targeted marker cannot relax these phases. `refresh-only`: `resource_drift` exactly
  `oci_core_instance.racetime:["delete"]`, empty live `resource_changes`, and exactly
  `instance_id`, `instance_public_ip`, `instance_private_ip`, and `boot_volume_id`
  output changes;
- `replacement`: exact instance/public-IP creates, only dynamic-group `matching_rule` and
  CPU-alarm `query` in-place changes, VNIC dedicated-subnet/NSG/no-ephemeral/no-IPv6
  values, and `RESERVED` public-IP lifetime/private-IP reference.
- `launch-encryption`: exact instance in-place update, dependency-pending private-IP
  data read, and deferred reserved-public-IP binding; only nested launch encryption may
  change from `false` to `true`, with provider-native computed `public_ip` drift exactly
  empty-string to the expected reserved IPv4.

Negative fixtures cover a non-ignored untracked Terraform file, wrong CIDR,
default-list attachment, non-null availability
domain, extra ingress, unexpected Restream action, refresh-only live mutation, extra
output change, dynamic-group extra field, and malformed/incomplete/errored plans.

- [ ] **Step 2: Run tests and verify RED**

```powershell
venv\Scripts\python.exe -m unittest tests.platform.test_oci_saved_plan_verifier -v
```

Expected: FAIL because the ignored boundary and verifier do not exist.

- [ ] **Step 3: Implement the minimal fail-closed verifier**

Implement a stdlib-only CLI:

```text
python scripts/oci/verify_saved_plan.py \
  --phase subnet-add|refresh-only|replacement|launch-encryption \
  --terraform-bin .tmp/tools/terraform-1.12.2/terraform.exe \
  --plan-file infra/oci/<phase>.tfplan \
  --plan-json .tmp/evidence/<phase>-plan.json \
  --expected-json .tmp/evidence/<phase>-expected.json \
  --source-commit <exact-clean-head> \
  --terraform-version 1.12.2
```

The expected file carries live OCIDs/IDs, phase, source commit, Terraform version, the
reviewed Terraform-binary digest, saved-plan digest, and exact `show -json` byte digest;
it remains ignored. Hash the Terraform binary and binary plan internally, run that exact
binary's `version -json` and `show -json <plan-file>`, and require generated bytes to
match both the expected JSON digest and custody `--plan-json` file. Parse only those
bound bytes. Reject import/generated-config metadata before no-op normalization and
require `format_version = "1.2"`. Use `git status --porcelain` to require exact HEAD,
no tracked changes, and no non-ignored untracked files. Print only a
redacted summary containing phase, source commit, plan hash, Terraform version, and
action/result counts; never print raw values or plan JSON.

- [ ] **Step 4: Run focused tests and ignore checks**

```powershell
venv\Scripts\python.exe -m unittest tests.platform.test_oci_saved_plan_verifier -v
git check-ignore -q .tmp/evidence/probe.json
git diff --check
```

- [ ] **Step 5: Commit only the safety-gate files**

```powershell
git add .gitignore scripts/oci/verify_saved_plan.py tests/platform/test_oci_saved_plan_verifier.py
$expected = @('.gitignore','scripts/oci/verify_saved_plan.py','tests/platform/test_oci_saved_plan_verifier.py') | Sort-Object
$actual = @(git diff --cached --name-only) | Sort-Object
if (Compare-Object $expected $actual) { throw 'unexpected staged path' }
git commit -m "test: gate OCI saved plan actions"
```

---

### Task 2: Add the RaceTime-only network boundary

**Files:**
- Modify: `tests/platform/test_terraform_contract.py`
- Modify: `infra/oci/data.tf`
- Modify: `infra/oci/network.tf`
- Modify: `infra/oci/variables.tf`
- Modify: `infra/oci/terraform.tfvars.example`
- Modify: `infra/oci/tests/activation_gate.tftest.hcl`
- Modify: `infra/oci/README.md`

- [ ] **Step 1: Replace the obsolete no-subnet test with a failing dedicated-boundary contract**

Require exactly one `oci_core_subnet` and one `oci_core_security_list`, both named
`racetime`; CIDR `var.racetime_subnet_cidr`; `dns_label = "racetime"`;
`prohibit_public_ip_on_vnic = false`; `prohibit_internet_ingress = false`; exact
`security_list_ids = [oci_core_security_list.racetime.id]`; route/DHCP IDs read from
`data.oci_core_subnet.bastion`; zero `ingress_security_rules`; one all-IPv4 egress rule;
and `prevent_destroy` on both resources. Continue rejecting any Terraform-managed
Restream-named network resource. Extract the RaceTime subnet block and reject any
`availability_domain` argument so the subnet is provably regional. The plan verifier
permits provider-computed unknown or planned null but rejects a configured/non-null
availability domain; the live gate still requires null.
Require README recovery/import entries for `oci_core_security_list.racetime` and
`oci_core_subnet.racetime` by exact OCID before either resource is applied.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
venv\Scripts\python.exe -m unittest tests.platform.test_terraform_contract.TerraformContractTests.test_network_exposes_only_http_https_and_uses_bastion_for_ssh -v
```

Expected: FAIL because the current contract forbids the required subnet/security-list resources.

- [ ] **Step 3: Implement the minimal additive Terraform graph**

Add the existing-subnet data source:

```hcl
data "oci_core_subnet" "bastion" {
  subnet_id = var.subnet_ocid
}
```

Add `racetime_subnet_cidr` as an explicit string variable validated as an IPv4 CIDR and
set the example/live ignored tfvars value to `10.1.1.0/24`.

Add to `network.tf` without changing `compute.tf` yet:

```hcl
resource "oci_core_security_list" "racetime" {
  compartment_id = var.compartment_ocid
  vcn_id         = var.vcn_ocid
  display_name   = "racetime"
  freeform_tags  = local.common_tags

  egress_security_rules {
    destination      = "0.0.0.0/0"
    destination_type = "CIDR_BLOCK"
    protocol         = "all"
    stateless        = false
  }

  lifecycle { prevent_destroy = true }
}

resource "oci_core_subnet" "racetime" {
  cidr_block                     = var.racetime_subnet_cidr
  compartment_id                 = var.compartment_ocid
  vcn_id                         = var.vcn_ocid
  display_name                   = "racetime-public"
  dns_label                      = "racetime"
  prohibit_public_ip_on_vnic     = false
  prohibit_internet_ingress      = false
  route_table_id                 = data.oci_core_subnet.bastion.route_table_id
  dhcp_options_id                = data.oci_core_subnet.bastion.dhcp_options_id
  security_list_ids              = [oci_core_security_list.racetime.id]
  freeform_tags                  = local.common_tags

  lifecycle { prevent_destroy = true }
}
```

Document that this first phase leaves `oci_core_instance.racetime` on
`var.subnet_ocid`; only the two additive network resources may be applied.
Add the narrow recovery commands before apply:

```powershell
terraform -chdir=infra/oci import oci_core_security_list.racetime <security-list-ocid>
terraform -chdir=infra/oci import oci_core_subnet.racetime <subnet-ocid>
```

- [ ] **Step 4: Run formatting and local tests**

Run:

```powershell
$terraform = ".\.tmp\tools\terraform-1.12.2\terraform.exe"
& $terraform "-chdir=infra/oci" fmt -check -recursive
& $terraform "-chdir=infra/oci" validate
& $terraform "-chdir=infra/oci" test
venv\Scripts\python.exe -m unittest tests.platform.test_terraform_contract -v
```

Expected: Terraform validation succeeds, activation tests pass 2/2, and the Python suite passes with no new skip.

- [ ] **Step 5: Commit the additive network implementation**

```powershell
git add tests/platform/test_terraform_contract.py infra/oci/data.tf infra/oci/network.tf infra/oci/variables.tf infra/oci/terraform.tfvars.example infra/oci/tests/activation_gate.tftest.hcl infra/oci/README.md
$expected = @('infra/oci/README.md','infra/oci/data.tf','infra/oci/network.tf','infra/oci/terraform.tfvars.example','infra/oci/tests/activation_gate.tftest.hcl','infra/oci/variables.tf','tests/platform/test_terraform_contract.py') | Sort-Object
$actual = @(git diff --cached --name-only) | Sort-Object
if (Compare-Object $expected $actual) { throw 'unexpected staged path' }
git commit -m "fix: isolate RaceTime subnet security"
```

---

### Task 3: Review and apply only the additive network resources

**Files:**
- Create ignored: `infra/oci/racetime-subnet-add.tfplan`
- Create ignored: `infra/oci/racetime-subnet-diagnostic.tfplan`
- Create ignored: `.tmp/evidence/racetime-subnet-add-plan.json`
- Create ignored: `.tmp/evidence/racetime-subnet-diagnostic-plan.json`
- Create ignored: `.tmp/evidence/subnet-add-expected.json`
- Create ignored: `.tmp/evidence/racetime-restream-baseline.json`
- Create: `docs/evidence/2026-08-25-oci-subnet-correction.md`

- [ ] **Step 1: Capture and commit the field-for-field Restream baseline before planning**

Using only the explicit instance and boot-volume OCIDs from ignored
`production.tfvars`, capture normalized JSON for each Restream instance, VNIC
attachment/VNIC, boot attachment/boot volume, lifecycle state, shape/OCPU/RAM, subnet,
NSGs/security lists, route/DHCP IDs, size, and VPUs. Save it directly to ignored
`.tmp/evidence/racetime-restream-baseline.json`; do not discover by display name. Create
the redacted evidence document with its SHA-256 and field/count summary, explicitly
stating no Task 3 plan/apply has run. Stage exactly that one evidence file, verify the
allowlist, and commit. The resulting clean evidence commit is the plan source commit.

- [ ] **Step 2: Review a full diagnostic plan, then create the exact targeted saved plan**

First create and inspect a full diagnostic plan, but never apply it. After the narrow
Bastion `bastion_type` normalization ignore, it may contain only the two intended
creates and the already-classified in-transit-encryption update on the stopped,
disposable old instance. Any Bastion replacement, Restream action, destroy, or other
address/action blocks. Preserve the redacted action summary in evidence.

```powershell
$terraform = ".\.tmp\tools\terraform-1.12.2\terraform.exe"
$tracked = @(git status --porcelain)
if ($tracked.Count -ne 0) { throw 'tracked worktree must be clean before plan' }
$sourceCommit = (git rev-parse HEAD).Trim()
& $terraform "-chdir=infra/oci" plan -input=false `
  -var-file=production.tfvars -out=racetime-subnet-diagnostic.tfplan *> .tmp/evidence/racetime-subnet-diagnostic.log
if ($LASTEXITCODE -ne 0) { throw 'full diagnostic plan failed; do not create an actionable plan' }
& $terraform "-chdir=infra/oci" show -json racetime-subnet-diagnostic.tfplan `
  2> .tmp/evidence/racetime-subnet-diagnostic-show.err `
  > .tmp/evidence/racetime-subnet-diagnostic-plan.json
if ($LASTEXITCODE -ne 0) { throw 'full diagnostic show failed; do not create an actionable plan' }
```

Then create the actionable saved plan with exactly the two exceptional `-target`
arguments below. This isolates the additive correction from the unrelated update on
the instance that will be terminated:

```powershell
& $terraform "-chdir=infra/oci" plan -input=false `
  -target=oci_core_security_list.racetime `
  -target=oci_core_subnet.racetime `
  -var-file=production.tfvars -out=racetime-subnet-add.tfplan *> .tmp/evidence/racetime-subnet-add-plan.log
if ($LASTEXITCODE -ne 0) { throw 'subnet-add plan failed; inspect ignored log' }
& $terraform "-chdir=infra/oci" show -json racetime-subnet-add.tfplan 2> .tmp/evidence/racetime-subnet-add-show.err > .tmp/evidence/racetime-subnet-add-plan.json
if ($LASTEXITCODE -ne 0) { throw 'subnet-add show failed; inspect ignored error' }
```

Verify all raw paths with `git check-ignore` and do not print their contents.

- [ ] **Step 3: Run the subnet-add saved-plan verifier**

Create ignored `subnet-add-expected.json` containing the exact reviewed CIDR,
route/DHCP IDs, phase/source/version, Terraform-binary SHA-256, binary-plan SHA-256, and
exact custody JSON SHA-256, plus the exact top-level boolean `targeted_plan=true`, then
run:

```powershell
venv\Scripts\python.exe scripts/oci/verify_saved_plan.py --phase subnet-add `
  --terraform-bin $terraform `
  --plan-file infra/oci/racetime-subnet-add.tfplan `
  --plan-json .tmp/evidence/racetime-subnet-add-plan.json `
  --expected-json .tmp/evidence/subnet-add-expected.json `
  --source-commit $sourceCommit `
  --terraform-version 1.12.2
```

Require exactly the security-list/subnet creates, exact CIDR, omitted availability-domain
configuration with planned null or computed unknown, DNS/public/route/DHCP values, zero
ingress, one all-IPv4 egress, custom-list reference, no drift/output changes, and no
other/Restream action. For this phase alone, require Terraform's targeted-plan
`complete=false` marker; a complete plan paired with `targeted_plan=true` also fails.

- [ ] **Step 4: Rerun verification and apply without changing HEAD**

Rerun the exact verifier immediately before apply; it must reprove binary hash, clean
exact HEAD, action/attributes, and reviewed digest. Then:

```powershell
& $terraform "-chdir=infra/oci" apply -input=false racetime-subnet-add.tfplan *> .tmp/evidence/racetime-subnet-add-apply.log
if ($LASTEXITCODE -ne 0) { throw 'subnet-add apply failed; enter forward-repair handling' }
```

- [ ] **Step 5: Verify the live additive boundary**

Require the new subnet `AVAILABLE`, `10.1.1.0/24`, DNS label `racetime`, public flags
false, regional `availability-domain` null, inherited route/DHCP IDs exact, and exactly
the custom list. Require zero ingress and one all-IPv4 egress. Confirm the original
instance remains `STOPPED` on `subnet-restream-public`. Recapture Restream inventory by
the same explicit IDs and compare every field to the exact ignored baseline; any
difference blocks Task 4. A single lifecycle-only difference on a duty-cycled Restream
instance may be classified as out-of-band only when OCI Audit records the exact
`START`/`SOFTSTOP` action after the baseline, the caller is not Terraform, and every
other captured field matches. Record the action and caller family without credentials,
retain both inventories, and promote the post-transition inventory as the continuing
baseline. Any other difference remains a hard stop.

- [ ] **Step 6: Commit redacted additive-plan evidence**

Add source commit, plan hash/verifier result, apply/live checks, and redacted resource
identity hashes to the evidence document. Stage exactly that file and enforce the
one-file allowlist before committing.

---

### Task 4: Prove the pre-termination boundary and remove the exposed empty instance

**Files:**
- Create ignored: `.tmp/evidence/racetime-pre-termination.tfstate`
- Create ignored: `.tmp/evidence/racetime-pre-termination.json`
- Modify: `docs/evidence/2026-08-25-oci-subnet-correction.md`

- [ ] **Step 1: Verify Bastion egress and shared public routing before termination**

Require Bastion type `STANDARD`, lifecycle `ACTIVE`, its exact original target-subnet OCID, exact restricted client
CIDR allowlist, and its current private endpoint. Enumerate the live RaceTime NSG and
require exactly one TCP/22 ingress rule whose source is that endpoint `/32`; reject every
additional public or private SSH source. Read the unchanged Bastion subnet security
lists and require a stateful rule whose
destination/protocol covers `10.1.1.0/24:22` (the live all-protocol `0.0.0.0/0` rule is
sufficient). Read the inherited route table and require `0.0.0.0/0` to an `AVAILABLE`
Internet Gateway in the same VCN. Reconfirm the DHCP-options OCID. Stop immediately on mismatch.

- [ ] **Step 2: Pull and hash state, then verify exact deletion targets**

```powershell
& $terraform "-chdir=infra/oci" state pull 2> .tmp/evidence/racetime-pre-termination-state.err > .tmp/evidence/racetime-pre-termination.tfstate
if ($LASTEXITCODE -ne 0) { throw 'state pull failed; inspect ignored error' }
```

Save the state only to ignored evidence, calculate SHA-256, and record only the hash.
Require the target instance display name `racetime`, state `STOPPED`, shape
`VM.Standard.A1.Flex`, 1 OCPU/6 GB, exactly one VNIC, no secondary VNICs, no block-volume
attachments, and one 50-GB/10-VPU boot volume created with this instance. Reconfirm that
no application bootstrap ever ran.

- [ ] **Step 3: Record the exposure window and risk boundary**

Use OCI creation/audit timestamps plus the operator action record to document: creation
at `2026-08-25T12:01:45.185-04:00`, public-SSH discovery/stop timestamps, source rule,
key-only Ubuntu access, absence of app/secrets/data, and the exact stopped instance/boot
identities represented only by safe hashes or short suffixes.

- [ ] **Step 4: Re-read the exact target and acquire a concurrency token**

Immediately before termination, re-read the exact instance OCID with response headers,
plus VNICs, attachments, and exact boot-volume OCID. Reprove `STOPPED`, one VNIC, no
secondary/block attachments, and the same empty 50-GB/10-VPU boot target. Capture the
response ETag only in ignored evidence. Any identity, state, attachment, or ETag mismatch
stops without termination.

Use `oci raw-request --http-method GET` against the regional Compute instance URI and
redirect its entire body/header response to ignored evidence. Parse `headers.etag` from
that file without printing it; never use CLI debug output to obtain the header.

- [ ] **Step 5: Terminate only the verified target with ETag protection**

Run the OCI CLI termination with the exact instance OCID, `--if-match <captured-etag>`,
`--preserve-boot-volume false`, `--force`, and `--wait-for-state TERMINATED` (the installed
OCI CLI waits on instance lifecycle states, not work-request states). Redirect the full
response to ignored evidence and do not use display-name selection. Re-read the exact
instance OCID after the waiter and require `TERMINATED`; require the exact boot-volume
get/list result to show `TERMINATED` or absent and prove it is not among retained volumes.
A 412/ETag mismatch is a clean stop.

- [ ] **Step 6: Update and commit redacted termination evidence**

```powershell
git add docs/evidence/2026-08-25-oci-subnet-correction.md
$actual = @(git diff --cached --name-only)
if ($actual.Count -ne 1 -or $actual[0] -ne 'docs/evidence/2026-08-25-oci-subnet-correction.md') { throw 'unexpected staged path' }
git commit -m "docs: record exposed instance disposal"
```

---

### Task 5: Reconcile Terraform state with a saved refresh-only plan

**Files:**
- Create ignored: `infra/oci/racetime-refresh-only.tfplan`
- Create ignored: `.tmp/evidence/racetime-refresh-only-plan.json`
- Create ignored: `.tmp/evidence/refresh-only-expected.json`
- Modify: `docs/evidence/2026-08-25-oci-subnet-correction.md`

- [ ] **Step 1: Create the saved refresh-only plan**

```powershell
$tracked = @(git status --porcelain)
if ($tracked.Count -ne 0) { throw 'tracked worktree must be clean before plan' }
$sourceCommit = (git rev-parse HEAD).Trim()
& $terraform "-chdir=infra/oci" plan -refresh-only -input=false -var-file=production.tfvars -out=racetime-refresh-only.tfplan *> .tmp/evidence/racetime-refresh-only-plan.log
if ($LASTEXITCODE -ne 0) { throw 'refresh-only plan failed; inspect ignored log' }
& $terraform "-chdir=infra/oci" show -json racetime-refresh-only.tfplan 2> .tmp/evidence/racetime-refresh-only-show.err > .tmp/evidence/racetime-refresh-only-plan.json
if ($LASTEXITCODE -ne 0) { throw 'refresh-only show failed; inspect ignored error' }
```

- [ ] **Step 2: Review the refresh-only action set and hash**

Run the verifier with phase `refresh-only`. Require `resource_drift` to contain exactly
`oci_core_instance.racetime:["delete"]`, `resource_changes` to be empty, and output
changes to contain exactly `instance_id`, `instance_public_ip`, `instance_private_ip`,
and `boot_volume_id`. No live OCI create/update/delete action and no Restream change is
permitted. Record source/state/plan hashes and redacted verifier output.

```powershell
venv\Scripts\python.exe scripts/oci/verify_saved_plan.py --phase refresh-only `
  --terraform-bin $terraform `
  --plan-file infra/oci/racetime-refresh-only.tfplan `
  --plan-json .tmp/evidence/racetime-refresh-only-plan.json `
  --expected-json .tmp/evidence/refresh-only-expected.json `
  --source-commit $sourceCommit `
  --terraform-version 1.12.2
```

- [ ] **Step 3: Recompute the hash and apply the exact refresh-only plan**

Rerun the exact verifier command immediately before apply, then:

```powershell
& $terraform "-chdir=infra/oci" apply -input=false racetime-refresh-only.tfplan *> .tmp/evidence/racetime-refresh-only-apply.log
if ($LASTEXITCODE -ne 0) { throw 'refresh-only apply failed; preserve state and stop' }
```

Require `terraform state list` to omit only the terminated instance while retaining the
subnet, security list, NSG, Bastion, bucket, IAM, alarms, and Restream data sources.

- [ ] **Step 4: Commit redacted reconciliation evidence**

```powershell
git add docs/evidence/2026-08-25-oci-subnet-correction.md
$actual = @(git diff --cached --name-only)
if ($actual.Count -ne 1 -or $actual[0] -ne 'docs/evidence/2026-08-25-oci-subnet-correction.md') { throw 'unexpected staged path' }
git commit -m "docs: reconcile RaceTime instance state"
```

---

### Task 6: Bind the replacement and stable public address test-first

**Files:**
- Modify: `tests/platform/test_terraform_contract.py`
- Modify: `infra/oci/data.tf`
- Modify: `infra/oci/network.tf`
- Modify: `infra/oci/compute.tf`
- Modify: `infra/oci/outputs.tf`
- Modify: `infra/oci/tests/activation_gate.tftest.hcl`
- Modify: `infra/oci/README.md`

- [ ] **Step 1: Write failing tests for the replacement graph**

Require `compute.tf` to use `oci_core_subnet.racetime.id` and
`assign_public_ip = false`. Require `data.oci_core_private_ips.racetime` to constrain
both `subnet_id` and `ip_address`, the reserved public-IP resource to use the uniquely
resolved primary private-IP OCID, `lifetime = "RESERVED"`, and `prevent_destroy`.
Require `instance_public_ip` output to use `oci_core_public_ip.racetime.ip_address` and
forbid `oci_core_instance.racetime.public_ip` throughout tracked Terraform/docs consumers.
Require the remaining README recovery/import entry for
`oci_core_public_ip.racetime` by exact OCID; subnet and security-list recovery was
already documented before their Task 3 apply.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
venv\Scripts\python.exe -m unittest tests.platform.test_terraform_contract -v
```

Expected: FAIL on old subnet, ephemeral address, missing private-IP lookup, and old output.

- [ ] **Step 3: Implement the minimal replacement/reserved-IP graph**

Use:

```hcl
data "oci_core_private_ips" "racetime" {
  subnet_id  = oci_core_subnet.racetime.id
  ip_address = oci_core_instance.racetime.private_ip
}

resource "oci_core_public_ip" "racetime" {
  compartment_id = var.compartment_ocid
  display_name   = "racetime"
  lifetime       = "RESERVED"
  private_ip_id  = one(data.oci_core_private_ips.racetime.private_ips).id
  freeform_tags  = local.common_tags

  lifecycle {
    prevent_destroy = true
    precondition {
      condition = (
        length(data.oci_core_private_ips.racetime.private_ips) == 1 &&
        one(data.oci_core_private_ips.racetime.private_ips).is_primary
      )
      error_message = "The reserved RaceTime public IP requires exactly one primary private IP."
    }
  }
}
```

Change `create_vnic_details.subnet_id` and `assign_public_ip`, then update the output.
If the mock provider cannot satisfy the collection precondition automatically, add
deterministic `mock_data "oci_core_private_ips"` defaults representing one primary
private-IP object; do not weaken the production precondition.

Extend README recovery with the remaining narrow import:

```powershell
terraform -chdir=infra/oci import oci_core_public_ip.racetime <public-ip-ocid>
```

- [ ] **Step 4: Run all Terraform and contract checks**

```powershell
& $terraform "-chdir=infra/oci" fmt -check -recursive
& $terraform "-chdir=infra/oci" validate
& $terraform "-chdir=infra/oci" test
venv\Scripts\python.exe -m unittest tests.platform.test_terraform_contract -v
```

- [ ] **Step 5: Commit the replacement graph**

```powershell
git add tests/platform/test_terraform_contract.py infra/oci/data.tf infra/oci/network.tf infra/oci/compute.tf infra/oci/outputs.tf infra/oci/tests/activation_gate.tftest.hcl infra/oci/README.md
$expected = @('infra/oci/README.md','infra/oci/compute.tf','infra/oci/data.tf','infra/oci/network.tf','infra/oci/outputs.tf','infra/oci/tests/activation_gate.tftest.hcl','tests/platform/test_terraform_contract.py') | Sort-Object
$actual = @(git diff --cached --name-only) | Sort-Object
if (Compare-Object $expected $actual) { throw 'unexpected staged path' }
git commit -m "fix: reserve RaceTime public network identity"
```

---

### Task 7: Create and verify the safe replacement

**Files:**
- Create ignored: `infra/oci/racetime-replacement.tfplan`
- Create ignored: `.tmp/evidence/racetime-replacement-plan.json`
- Create ignored: `.tmp/evidence/replacement-expected.json`
- Create ignored: `infra/oci/racetime-launch-encryption.tfplan`
- Create ignored: `.tmp/evidence/racetime-launch-encryption-plan.json`
- Create ignored: `.tmp/evidence/launch-encryption-expected.json`
- Modify: `docs/evidence/2026-08-25-oci-subnet-correction.md`
- Modify: `docs/racetime-z1rr/launch-readiness-checklist.md`

- [ ] **Step 1: Create, capture, and verify the saved replacement plan**

Create the saved plan and write `terraform show -json` directly to the ignored plan JSON
without printing it. Run the phase `replacement` verifier. Require one RaceTime instance
create, one reserved public-IP create, and only in-place updates to
`oci_identity_dynamic_group.racetime.matching_rule` and
`oci_monitoring_alarm.instance_cpu.query`. Require the VNIC's exact dedicated-subnet and
RaceTime NSG bindings, `assign_public_ip=false`, `assign_ipv6ip=false`, reserved lifetime,
and private-IP data reference. Data reads are allowed. Require zero deletes/replacements
and zero Restream action. Record exact clean source commit and plan SHA-256.

```powershell
$tracked = @(git status --porcelain)
if ($tracked.Count -ne 0) { throw 'tracked worktree must be clean before plan' }
$sourceCommit = (git rev-parse HEAD).Trim()
& $terraform "-chdir=infra/oci" plan -input=false -var-file=production.tfvars -out=racetime-replacement.tfplan *> .tmp/evidence/racetime-replacement-plan.log
if ($LASTEXITCODE -ne 0) { throw 'replacement plan failed; inspect ignored log' }
& $terraform "-chdir=infra/oci" show -json racetime-replacement.tfplan 2> .tmp/evidence/racetime-replacement-show.err > .tmp/evidence/racetime-replacement-plan.json
if ($LASTEXITCODE -ne 0) { throw 'replacement show failed; inspect ignored error' }
venv\Scripts\python.exe scripts/oci/verify_saved_plan.py --phase replacement `
  --terraform-bin $terraform `
  --plan-file infra/oci/racetime-replacement.tfplan `
  --plan-json .tmp/evidence/racetime-replacement-plan.json `
  --expected-json .tmp/evidence/replacement-expected.json `
  --source-commit $sourceCommit `
  --terraform-version 1.12.2
```

- [ ] **Step 2: Recompute the hash and apply the exact saved plan**

Rerun the exact verifier command immediately before apply, then:

```powershell
& $terraform "-chdir=infra/oci" apply -input=false racetime-replacement.tfplan *> .tmp/evidence/racetime-replacement-apply.log
if ($LASTEXITCODE -ne 0) { throw 'replacement apply failed; enter forward-repair handling' }
```

A partial/nonzero apply enters the forward-repair path; do not publish DNS or bootstrap.

- [ ] **Step 3: Verify compute, storage, and reserved-IP identity**

Require `racetime` RUNNING on `VM.Standard.A1.Flex`, 1 OCPU/6 GB, standard ARM64 Ubuntu
24.04, one 50-GB boot volume at 10 VPUs/GB, one VNIC in `racetime-public`, only the
RaceTime NSG, and no secondary/block attachments. Require the reserved address to report
`RESERVED`, `REGION`, `ASSIGNED`, `PRIVATE_IP`, and the exact primary private-IP OCID.

- [ ] **Step 4: Verify effective network rules and DNS identity**

Require the dedicated subnet to reference exactly the custom zero-ingress list and not
the VCN default list. Enumerate the subnet-list plus VNIC-NSG union and prove public
TCP/22, 3306, and 6379 absent; public TCP/80 and 443 present only through the RaceTime
NSG; IPv6 absent. Require exactly one TCP/22 ingress rule in the NSG, sourced from the
current Bastion private endpoint `/32`, and reject every additional public or private SSH
source. Verify the private FQDN equals
`racetime.racetime.restream.oraclevcn.com`.

- [ ] **Step 5: Prove Bastion SSH functionality**

Create a time-limited OCI Bastion port-forwarding session from the approved operator
CIDR to the replacement private IP port 22 using only the operator public key. Complete
an authenticated SSH session as Ubuntu; require the tunnel client's actual public source
to fall within the approved CIDR, require `hostname` to return `racetime`, require
`hostname -A` to include `racetime.racetime.restream.oraclevcn.com`, and reject any
non-comment `/etc/hosts` token equal to that full FQDN. Require
`resolvectl query --type=A --legend=yes racetime.racetime.restream.oraclevcn.com` to
report DNS protocol through OCI's `169.254.169.254` VCN resolver, with the deduplicated A
address set equal to exactly the single live primary VNIC address. Independently require
the deduplicated first-column address set from
`getent ahostsv4 racetime.racetime.restream.oraclevcn.com` to equal that same singleton.
Do not use `hostname --fqdn` as the OCI network-identity gate: Ubuntu may prefer its
short local `/etc/hosts` canonical entry even when OCI private DNS is correct. Record
only the host-key fingerprint and system identity. Re-enumerate the NSG and reconfirm
the exact single Bastion `/32` SSH source after the test, then delete/expire the session
and prove no local listener remains.

- [ ] **Step 6: Apply the reviewed in-place encryption correction**

Provider 8.27.0 uses the top-level encryption field only when creating an instance and
the nested `launch_options` field when updating one. Retain both as `true`; protect only
the top-level create-only field with the exact lifecycle ignore so adding it cannot
replace the current VM. Never ignore the nested field.

Only after the source commit passes spec and quality review, create a fresh full saved
plan and custody JSON from that exact clean commit. Run the verifier with phase
`launch-encryption`; require complete/applyable/non-errored source-bound evidence and
only the known instance update, dependency-pending private-IP read, and deferred
reserved-public-IP binding. The instance update must be only nested encryption
`false -> true`, with every other launch option identical and no unknown launch value.
The sole drift is provider-native computed `public_ip` `""` to the expected reserved
IPv4; no null or omitted substitute is accepted. Rerun the verifier immediately before
applying the exact saved plan. Do not apply a different or stale plan.
Bind the ignored expected manifest to the exact reserved IPv4, dedicated-subnet ID,
current primary-private-IP ID, source commit, Terraform binary, saved plan, and custody
JSON digests.

```powershell
venv\Scripts\python.exe scripts/oci/verify_saved_plan.py --phase launch-encryption `
  --terraform-bin $terraform `
  --plan-file infra/oci/racetime-launch-encryption.tfplan `
  --plan-json .tmp/evidence/racetime-launch-encryption-plan.json `
  --expected-json .tmp/evidence/launch-encryption-expected.json `
  --source-commit $sourceCommit `
  --terraform-version 1.12.2
```

The update is expected to reboot the A1 instance. Wait for `RUNNING`, then require the
live OCI launch option to report paravirtualized in-transit encryption `true`. Any
replacement/delete, extra action, failed reboot, or live `false` result blocks the
remaining task.

- [ ] **Step 7: Prove no drift and unchanged Restream inventory**

Run the exact command below and require exit 0; never treat exit 2 as success:

```powershell
& $terraform "-chdir=infra/oci" plan -input=false -var-file=production.tfvars -detailed-exitcode *> .tmp/evidence/racetime-final-no-drift.log
if ($LASTEXITCODE -ne 0) { throw "final Terraform drift or error: $LASTEXITCODE" }
```

Recompare all
normalized Restream instance, VNIC attachment/VNIC, boot attachment/volume, state, shape,
subnet, shared-network, size, and VPU fields to the exact ignored pre-mutation baseline.
If Task 3 recorded an audited lifecycle-only duty-cycle transition, compare instead to
the retained post-transition continuing baseline and preserve the original baseline plus
the transition proof.

- [ ] **Step 8: Finalize and commit redacted correction evidence**

Record all four saved-plan hashes/action sets, original instance/volume terminal proof,
replacement/reserved-IP/network/Bastion proof, final public IPv4 DNS target, and no-drift
result. Update only truthful checklist items.

```powershell
git add docs/evidence/2026-08-25-oci-subnet-correction.md docs/racetime-z1rr/launch-readiness-checklist.md
$expected = @('docs/evidence/2026-08-25-oci-subnet-correction.md','docs/racetime-z1rr/launch-readiness-checklist.md') | Sort-Object
$actual = @(git diff --cached --name-only) | Sort-Object
if (Compare-Object $expected $actual) { throw 'unexpected staged path' }
git commit -m "docs: verify safe RaceTime replacement"
```

---

### Task 8: Completion review and handoff

**Files:**
- Review all files changed since `cea1d767dc782d643de16b196cb7fced8b1e989f`

- [ ] **Step 1: Run fresh local verification**

Run Terraform format/validate/test, the complete platform Terraform contract suite,
operations evidence/traceability link tests, `git diff --check`, and the pinned Gitleaks
runner at exact final HEAD. G0 traceability may remain the documented HOLD; do not claim
G0 completion.

- [ ] **Step 2: Request spec and code-quality review**

Reviewers must compare the final graph and evidence to the approved spec, verify the
four-stage state sequence (subnet add, refresh-only reconciliation, replacement, and
launch-encryption update), and confirm no public SSH or Restream mutation.

- [ ] **Step 3: Correct findings and repeat verification**

Any executable change after live qualification requires a proportionate re-plan or live
recheck before acceptance.

- [ ] **Step 4: Give the DNS handoff**

Provide the exact reserved address with this provider-neutral record:

```text
Type: A
Name/Host: racetime
Value: <verified oci_core_public_ip.racetime.ip_address>
TTL: 300 seconds (or provider Automatic during qualification)
```

State explicitly: create no AAAA record, remove any conflicting A/CNAME/URL-forward for
`racetime`, and keep the record DNS-only. DNS creation remains the user's action unless
separately authorized.
