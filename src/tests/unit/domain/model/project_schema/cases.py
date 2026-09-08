"""Boundary payloads sent unchanged to both runtimes by the differential test."""

from __future__ import annotations

from copy import deepcopy


def boundary_cases(base):
    cases = []

    def case(name, valid, mutate):
        document = deepcopy(base)
        mutate(document)
        cases.append({"name": name, "document": document, "valid": valid})

    for field, maximum in (("name", 512), ("description", 4096), ("source", 128)):
        for extra in (0, 1):
            case(
                f"{field}_byte_limit_{extra}",
                extra == 0,
                lambda d, f=field, n=maximum + extra: d["entity_types"][0].update(
                    {f: "界" * (n // 3) + "a" * (n % 3)}
                ),
            )
    for extra in (0, 1):
        case(
            f"scope_byte_limit_{extra}",
            extra == 0,
            lambda d, n=512 + extra: d.update(tenant_id="a" * n),
        )
        case(
            f"schema_text_limit_{extra}",
            extra == 0,
            lambda d, n=16383 + extra: d["entity_types"][0].update(schema={"x": "a" * n}),
        )
        case(
            f"schema_nodes_limit_{extra}",
            extra == 0,
            lambda d, n=1022 + extra: d["entity_types"][0].update(schema={"x": [None] * n}),
        )
        nested = 0
        for _ in range(16 + extra):
            nested = {"x": nested}
        case(
            f"schema_depth_limit_{extra}",
            extra == 0,
            lambda d, value=nested: d["entity_types"][0].update(schema=value),
        )

    def members(document, count):
        document["mappings"] = []
        document["entity_types"] = []
        document["edge_types"] = []
        document["tombstones"] = [
            {
                "id": f"00000000-0000-4000-8000-{index + 100:012d}",
                "kind": "entity_type",
                "deleted_revision": 1,
            }
            for index in range(count)
        ]

    case("member_count_limit", True, lambda d: members(d, 1024))
    case("member_count_overflow", False, lambda d: members(d, 1025))
    case("scope_ascii_padding", False, lambda d: d.update(project_id=" project-a"))
    case("scope_unicode_label", True, lambda d: d.update(project_id="项目"))
    case("scope_nul", False, lambda d: d.update(tenant_id="a\0b"))
    case("schema_nul_key", False, lambda d: d["entity_types"][0].update(schema={"\0": 0}))
    case("schema_nul_value", False, lambda d: d["entity_types"][0].update(schema={"x": "\0"}))
    case("schema_surrogate", False, lambda d: d["entity_types"][0].update(schema={"x": "\ud800"}))
    case(
        "negative_safe_number",
        True,
        lambda d: d["entity_types"][0].update(schema={"x": -9007199254740991}),
    )
    case(
        "negative_unsafe_number",
        False,
        lambda d: d["entity_types"][0].update(schema={"x": -9007199254740992}),
    )
    case(
        "max_safe_float",
        True,
        lambda d: d["entity_types"][0].update(schema={"x": 9007199254740991.0}),
    )
    case("subnormal_float", True, lambda d: d["entity_types"][0].update(schema={"x": 5e-324}))
    case("empty_name", False, lambda d: d["entity_types"][0].update(name=""))
    case("invalid_status", False, lambda d: d["entity_types"][0].update(status=[]))

    def numeric_members(document, count):
        document["mappings"] = []
        document["edge_types"] = []
        member = deepcopy(document["entity_types"][0])
        document["entity_types"] = [
            {
                **member,
                "id": f"00000000-0000-4000-8000-{index + 100:012d}",
                "schema": {"x": [0] * 1022},
            }
            for index in range(count)
        ]

    case("numeric_document_weight_valid", True, lambda d: numeric_members(d, 30))
    case("numeric_document_weight_overflow", False, lambda d: numeric_members(d, 32))
    return cases
