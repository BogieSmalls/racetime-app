# Compose health JSON parser design

## Goal

Make integration readiness accept both Docker Compose `ps --format json` output formats used by supported environments while failing closed on invalid status input. Preserve the existing endpoint check and exact six-service health requirement.

## Design

Add a dependency-free, dot-sourceable `scripts/integration-health.ps1` containing two public functions:

- `ConvertFrom-IntegrationComposePsJson` accepts one string. If its first non-whitespace character is `[`, it parses the entire value as one legacy JSON array. Otherwise, it parses every non-empty line as one current JSONL object. It rejects empty input, empty arrays, malformed JSON, scalars, nested arrays, and mixed array/object records.
- `Test-IntegrationServicesHealthy` accepts parsed records and the expected service names. It returns true only when records contain exactly the six unique expected services and every record reports `State=running` and `Health=healthy`. Missing, duplicate, extra, unhealthy, or structurally incomplete records return false.

`scripts/integration-up.ps1` dot-sources the helper, parses the Compose output through it, applies the exact-service predicate, and only then performs the existing HTTPS endpoint check. `.ready` remains downstream of both gates.

## Testing

Add a dependency-free PowerShell behavioral test script that dot-sources and calls the real helper functions. It covers:

- legacy JSON array acceptance;
- current JSONL acceptance;
- malformed, mixed, and empty input rejection;
- exact-six healthy acceptance;
- duplicate, missing, extra, unhealthy, and incomplete status rejection.

A small unittest wrapper executes the PowerShell test so existing `unittest discover` workflows include it. Static substring assertions for parser implementation details are removed; topology/readiness ordering contracts remain only where they assert external configuration structure.

## Error handling and scope

Parser errors are terminating and are caught by the existing readiness retry boundary, so malformed status can never produce `.ready`. No production test flags, external dependencies, Docker/NAS calls, or unrelated interfaces are added.
