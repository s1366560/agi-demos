# bcs-db-postgres

Production PostgreSQL implementation of `bcs-db-api`.

- Uses a bounded async client pool.
- Executes native PostgreSQL `$1..$n` statements without rewriting SQL.
- Does not create or migrate schema at runtime.
- Converts `DbValue::Null` using the server-inferred parameter type.
- Rejects `u64` values that cannot be represented by PostgreSQL signed integer types.
