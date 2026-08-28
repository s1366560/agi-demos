"""Package-level authority gates for agent permissions."""

import pytest

from src.infrastructure.agent import permission as permission_package


@pytest.mark.unit
@pytest.mark.parametrize(
    "authority_name",
    ("_permission_manager_instance", "get_permission_manager"),
)
def test_process_global_permission_manager_authority_is_retired(authority_name: str) -> None:
    assert not hasattr(permission_package, authority_name)
