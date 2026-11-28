"""Run billing revisions against the package's assigned deployment connection."""

from alembic import context
from plugins.business.billing.backend.invoices import Invoice

context.configure(
    connection=context.config.attributes["connection"],
    target_metadata=Invoice.metadata,
    include_name=lambda name, kind, parents: kind != "table" or name == Invoice.__tablename__,
    include_object=lambda item, name, kind, reflected, other: (
        kind != "table" or name == Invoice.__tablename__
    ),
    version_table="billing_alembic_version",
)
with context.begin_transaction():
    context.run_migrations()
