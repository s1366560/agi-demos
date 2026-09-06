# Verified scoped execution artifacts

The scoped profile publication service now retains verified archives, not only their
manifests, and passes them through the publication coordinator into the registry.
The registry owns the candidate artifact resolver used by its actual Loader. Binding
a separate unused resolver in application code is no longer necessary or possible
through this service interface.

Verified publication uses `CandidateBundleArtifactResolverV2` to compare canonical
execution bytes with the supplied verified Bundle bytes. Empty archives still select
verified mode and cannot silently become a direct publication. Bindings are local to
each candidate task and restored after apply; concurrent scopes do not share bindings.
Receipt retries reuse the already obtained receipt without rebinding or reapplying.

A host incarnation fixes its trust mode on creation. Direct and verified modes cannot
be switched to reuse an existing generation. Same-digest fast ACK additionally resolves
the enabled Python entries under the new archive binding, because the reconciler may
otherwise skip Loader staging. Invalid fast-reuse archives raise before host apply;
if submitted through the coordinator, admission stays blocked until an explicit valid
publication recovers it. Initial candidate byte failures produce Loader NACK and retain
any previous last-good generation.

Tests exercise signed archive parsing, missing target artifact rejection, actual delegate
byte mismatch, no apply/admission on NACK, last-good retention, both forbidden trust-mode
transitions, same-digest revalidation and concurrent candidate isolation. The authenticated
source/desired-to-scoped-operation-and-child integration test now traverses this binding.

This closes the execution-byte binding gap recorded in the scoped resource factory audit.
Production archive retrieval/storage and signer configuration still need integration.
Production Agent startup, historical migration-chain recovery, V1 retirement and final
native acceptance remain incomplete; these tests do not claim those gates.

Validation: final combined regression passed 38 tests; isolated PostgreSQL regression
passed 13 tests and removed its container. PostgreSQL evidence covers the established
migration slice, not the complete historical chain. Protocol generation/check, contract
completeness, Ruff and whitespace checks passed. Evidence hashes: `/var/tmp/cordis-scoped-verified-artifacts-o_mj0sot`.
