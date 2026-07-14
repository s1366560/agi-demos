from typing import Any

import pytest

from scripts.verify_e2e_backend import verify_backend


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._payload


class _Client:
    def __init__(self, responses: list[_Response]) -> None:
        self._responses = iter(responses)
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.requests.append(("POST", url, kwargs))
        return next(self._responses)

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.requests.append(("GET", url, kwargs))
        return next(self._responses)


def test_verify_backend_authenticates_and_requires_a_tenant() -> None:
    client = _Client(
        [
            _Response(200, {"access_token": "test-token"}),
            _Response(200, {"tenants": [{"id": "tenant-1"}]}),
        ]
    )

    verify_backend("http://api.test", client=client)

    assert client.requests[0][0:2] == ("POST", "http://api.test/api/v1/auth/token")
    assert client.requests[1][0:2] == ("GET", "http://api.test/api/v1/tenants/")
    assert client.requests[1][2]["headers"] == {"Authorization": "Bearer test-token"}


@pytest.mark.parametrize(
    "responses,match",
    [
        ([_Response(200, {})], "access token"),
        (
            [
                _Response(200, {"access_token": "test-token"}),
                _Response(200, {"tenants": []}),
            ],
            "tenant",
        ),
    ],
)
def test_verify_backend_rejects_incomplete_bootstrap(
    responses: list[_Response],
    match: str,
) -> None:
    with pytest.raises(RuntimeError, match=match):
        verify_backend("http://api.test", client=_Client(responses))
