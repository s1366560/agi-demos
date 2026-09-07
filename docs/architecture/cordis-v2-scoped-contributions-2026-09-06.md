# Cordis V2 scoped contribution closure

Scoped service projection now retains explicitly declared registry contributors. Previously the production Agent projection kept the tool resolver and catalog but omitted the modules that registered its tools, yielding an empty tool set.

## Contract and projection

`ServiceRequiredV2.contributes` is an optional boolean. True declares registration into that required service; omission and false remain ordinary dependency consumption. It is included in canonical contract digests when present. Generated Python, Rust and TypeScript DTOs retain the field; the TypeScript parser validates its type without making it mandatory for older contracts.

The projector resolves each matching contribution to the actual provider using service/version, contributor scope and isolation identity. It includes only contributors bound to a selected provider, then follows their dependencies and parents. Disabled entries and foreign scopes remain excluded. Contribution membership is not a reverse initialization dependency: normal dependency ordering continues to place providers before contributors.

29 builtin module contracts now declare audited registrations into tool, command, definition, capability and channel catalogs. This is static metadata in the signed/digested contract, not a runtime module-name classification. Read-only consumers are excluded. System prompt sections have no registry contribution API and remain configuration-backed.

## Validation and limits

- Python protocol, runtime contract, projection and production Loader tests: 51 passed.
- Web tests including true/false/omitted flags and malformed values: 34 passed.
- Rust plugin-host crate: 59 tests passed; the earlier filtered invocation matched zero tests and is not counted.
- Full Desktop on feature HEAD `471834dd6`: 4,133 tests, 4,131 passed, 2 skipped, zero failures (99.98 seconds).
- Pyright: zero errors and warnings. Generator and completeness checks passed.
- Production Loader test confirms actual tool contributions are installed and an incomplete prepared tool set reaches contribution validation instead of silently returning empty. It does not execute a real Agent or provider operation.

Shared DTO impact was CRITICAL (129 direct and 559 upstream relationships). GitNexus did not index the newer projector; its UNKNOWN result is not low-risk evidence. Full Desktop testing is required because the first run caught the renderer parser's unknown-field rejection. Web regression also caught an initially accidental required-field change; both parser errors were corrected before final acceptance.

The next batch must connect authenticated fresh-DB Agent streaming to scoped prepare/publication/reservation. Workspace prompt-context remains unavailable in the enabled production profile. Governance revocation fencing, historical migration recovery, V1 retirement and final native acceptance remain open.

Evidence: `/var/tmp/cordis-scoped-contributions-af_pkud1` contains final and failed-run logs, SHA-256 checksums and the next consumer audit. Feature commits: `b1126a22f`, `edbab67d6`, `471834dd6`.
