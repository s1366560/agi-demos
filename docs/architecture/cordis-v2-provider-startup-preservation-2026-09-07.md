# Preserve existing providers during startup

The final real-service acceptance exposed an unsafe startup path: when the running
process could not decrypt an existing provider, the initializer recursively enabled
`force_recreate` and deleted the registry. The Cordis checkout lacked the historical
LLM encryption key, so the first attempt replaced three existing providers.

The task-owned API and Core were stopped. The verified custom PostgreSQL archive
was restored with the standard `pg_restore --clean --create` workflow after checking
that no clients remained connected. The restored database returned to revision
`822cd9402ce6`, with all three original providers. Their ciphertexts were checked
using the existing encryption key from the original workspace, only in memory.
All three decrypted successfully. The identity-and-ciphertext digest is
`287744585debbadbb871d0ab1c045c98febb2dd9dcf8ed3980c075c3ba4d946a`.
Recovery evidence is private under `/var/tmp/cordis-final-retirement-ufhyv7hu`.

Normal startup now preserves any stored provider records, including inactive ones.
Failed verification returns without clearing or creating records. Only an explicit
`force_recreate=True` call retains the destructive reset behavior. The inaccessible
credential warning no longer logs an exception payload or promises recreation.

Six isolated regressions exercise inaccessible credentials, missing encryption
configuration, healthy and inactive registries, empty initialization, and explicit
reset. Before the change, three failed and three passed. After the change, these
and the five existing local-fallback tests passed: 11 passed in 0.22 seconds.
They replace storage and encryption dependencies and do not connect to a database.
Ruff passed; Pyright reported zero errors and five existing warnings.

Source tracing identified API startup, agent
worker startup, runtime bootstrap and project actors. The change preserves the public boolean return contract and explicit reset entry
point. The index is supplemented by this direct call-site review.

The operator launcher resolves the database credential from the existing local
container while retaining the repository's endpoint, user and database identity.
It supplies the original workspace's existing LLM encryption key to child processes
in memory. Repository dotenv files and database passwords are unchanged. A fresh
Alembic upgrade and real-service acceptance follow recovery; the initial provider-
replacing startup is not counted as successful final acceptance.
