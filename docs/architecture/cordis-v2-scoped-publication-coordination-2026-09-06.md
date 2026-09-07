# Scoped publication transaction coordination

The ledger now accepts a requested snapshot/envelope independently of a receipt.
It revalidates the wire representation and stores a reconciling publication without
creating receipt events. The compatibility publication API validates its observed
receipt before delegating to this request path.

`ScopedPublicationCoordinatorV2` owns a private registry and independent database
sessions. It commits the requested publication before calling the actual Loader,
then persists that Loader's ACK/NACK in a second transaction. Business acquisition
requires both local application and durable receipt identity. These are distinct
transactions, not an atomic PostgreSQL/in-memory commit.

A failed request commit does not apply the candidate. A failed receipt commit keeps
the original receipt pending and blocks new leases; retry submits that same receipt
without reapplying or allocating another version. This includes ambiguous failures
reported after the database committed. A NACK retains the previous locally admitted
generation. Existing leases remain valid while a replacement is reconciled.

Acquisition locks the scope head and compares the latest observed request, retained
last-good distribution and the actual local generation. Another process's ACK does
not establish a local generation. A superseded receipt is permanently rejected;
an explicit new publication can recover that process. Caller cancellation does not
cancel the owned request/apply/receipt work. Closing seals admission before waiting
for accepted work and registry cleanup.

The coordinator is an internal component for already-authorized callers. It is not
yet wired into a scoped HTTP publication endpoint, startup or Agent turns. Restart
recovery of pending requests, exact host binding for child operations, per-scope
retirement and complete consumer dependency closure remain integration work. This
batch does not complete Stage 6, V1 retirement or final native acceptance.

Validation: 29 repository/coordinator/authenticated HTTP regressions passed in
100.01 seconds. Eleven isolated PostgreSQL tests passed in 11.90 seconds, including
request/receipt commit failures, ambiguous successful receipt commit, same-digest
fast ACK, cross-process supersession and the preceding ledger/source migration
regressions. Logs and the disposable-database runner are retained with hashes under
`/var/tmp/cordis-scoped-coordinator-lx081ans`.
