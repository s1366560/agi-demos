# First-use scoped configuration initialization

`ScopedProfileInitializationServiceV2` initializes a non-ROOT scope only after its caller
has authorized the target. Existing exact desired/source records are validated and returned
without ancestor locks or overwrite. A missing configuration takes the ROOT-to-leaf scope
head locks, rechecks the target, and copies the nearest existing ancestor's complete desired
and source. Missing ancestor head rows are created as part of that transaction.

The copy preserves all layers and ordered Bundle references. It gets private source/desired
identities and revision 1, with canonical provenance recording the parent scope, desired
revision/digest, source revision/digest and original provenance. Source and desired commit
together. A broken nearest source rejects rather than skipping to another ancestor.
Only an exact ROOT builtin source reference may use the trusted repository baseline when
the historical ROOT source has not been stored in the newer source table.

This is first-use snapshot initialization, not live inheritance or a merge of independent
ancestor desired sets. Parent changes do not silently overwrite an initialized child.
`ScopedProfileRuntimeV2.prepare_current` composes this step with verified publication;
the publication's existing desired fence still protects the actual apply transaction.

The production-component test now initializes an absent session from actual ROOT builtin
configuration before real Loader publication and operation admission. Real PostgreSQL tests
run two independent initializer/session instances concurrently and prove one shared desired
revision with a readable exact source. Unit tests also cover atomic rollback and lock order.

Actual Agent service requirements are now explicitly declared: 16 ordinary-turn roots and
one additional workspace root, used only by the existing workspace-conversation condition.
The diagnostic tests expose two remaining production gaps: the workspace profile has no
enabled prompt-context provider, and forward service closure omits tool registration
contributors. Real Loader resolution succeeds but the resulting tool set is empty. The
current contract has no explicit contribution relationship; treating every service consumer
as a contributor would be incorrect. A declared relationship and closure support are required
before switching the real Agent entry. These tests are not Agent/model/native acceptance.

V1 retirement, historical migration-chain recovery and final native acceptance remain open.

Validation: final combined regression passed 23 tests; real PostgreSQL regression passed
14 tests and cleaned its container. PostgreSQL uses the established migration slice, not
the full historical chain. Protocol generation/check, contract completeness, Ruff and
whitespace checks passed. Evidence SHA-256 inventory: `/var/tmp/cordis-scoped-initialization-ht1e014n`.
