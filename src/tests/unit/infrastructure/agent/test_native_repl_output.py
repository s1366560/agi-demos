import json

from src.infrastructure.agent.native_computer_use import repl_output as module

SCHEMA = {"x-agistack-display-kind": "repl_output"}
REFS = [
    {
        "native_attachment_id": "native_image",
        "artifact_id": "cloud_image",
        "mime_type": "image/png",
        "size_bytes": 30,
    },
    {
        "native_attachment_id": "native_audio",
        "artifact_id": "cloud_audio",
        "mime_type": "audio/wav",
        "size_bytes": 40,
    },
]
OUTPUT = {
    "outputs": [{"type": "text", "text": "before"}, {"type": "text", "text": "after"}],
    "artifacts": [
        {
            "kind": "image",
            "artifact_id": "native_image",
            "mime_type": "image/png",
            "size_bytes": 30,
        },
        {
            "kind": "audio",
            "artifact_id": "native_audio",
            "mime_type": "audio/wav",
            "size_bytes": 40,
        },
    ],
    "output_order": [
        {"source": "text", "index": 0},
        {"source": "media", "index": 0},
        {"source": "text", "index": 1},
        {"source": "media", "index": 1},
    ],
}


def test_mixed_order_uses_only_actual_persisted_bindings() -> None:
    display = module.repl_output_display(SCHEMA, json.dumps(OUTPUT), REFS)
    assert [e["kind"] for e in display["entries"]] == ["text", "image", "text", "audio"]
    assert display["entries"][1] == {
        "kind": "image",
        "artifactId": "cloud_image",
        "mimeType": "image/png",
        "sizeBytes": 30,
        "store": "conversation_tool_media",
    }
    assert "native_" not in json.dumps(display)


def test_requires_static_declaration_and_complete_binding() -> None:
    assert module.repl_output_display({}, OUTPUT, REFS) is None
    assert module.repl_output_display(SCHEMA, OUTPUT, []) is None
    assert module.repl_output_display(SCHEMA, OUTPUT, [*REFS, REFS[0]]) is None
    assert (
        module.repl_output_display(SCHEMA, OUTPUT, [{**REFS[0], "size_bytes": 31}, REFS[1]]) is None
    )


def test_rejects_forged_order_and_unknown_media() -> None:
    for order in [
        [{"source": "text", "index": 0}],
        OUTPUT["output_order"] + [OUTPUT["output_order"][0]],
        [{"source": "text", "index": True}, *OUTPUT["output_order"][1:]],
    ]:
        assert module.repl_output_display(SCHEMA, {**OUTPUT, "output_order": order}, REFS) is None
    assert (
        module.repl_output_display(
            SCHEMA,
            {
                **OUTPUT,
                "artifacts": [
                    {**OUTPUT["artifacts"][0], "artifact_id": "other"},
                    OUTPUT["artifacts"][1],
                ],
            },
            REFS,
        )
        is None
    )


def test_does_not_invent_mixed_order_or_expose_paths() -> None:
    assert (
        module.repl_output_display(
            SCHEMA, {k: v for k, v in OUTPUT.items() if k != "output_order"}, REFS
        )
        is None
    )
    assert module.repl_output_display(
        SCHEMA, {"outputs": [{"type": "text", "text": "hello"}], "artifacts": []}, []
    ) == {"kind": "repl_output", "entries": [{"kind": "text", "text": "hello"}]}
    assert module.repl_output_display(
        SCHEMA, {"outputs": [{"type": "text", "text": "a" * 32769}], "artifacts": []}, []
    )["entries"] == [{"kind": "text", "text": "a" * 32768}]

    assert (
        module.repl_output_display(
            SCHEMA,
            {
                **OUTPUT,
                "artifacts": [
                    {**OUTPUT["artifacts"][0], "artifact_path": "/tmp/private"},
                    OUTPUT["artifacts"][1],
                ],
            },
            REFS,
        )
        is None
    )


def test_rejects_malformed_media_without_exceptions() -> None:
    for field, value in [
        ("kind", []),
        ("mime_type", {}),
        ("size_bytes", True),
        ("artifact_id", []),
    ]:
        invalid = {
            **OUTPUT,
            "artifacts": [{**OUTPUT["artifacts"][0], field: value}, OUTPUT["artifacts"][1]],
        }
        assert module.repl_output_display(SCHEMA, invalid, REFS) is None
    assert module.repl_output_display(SCHEMA, OUTPUT, [None]) is None


def test_media_limits_preserve_order_text_and_do_not_bind_oversized_bytes() -> None:
    from src.infrastructure.agent.tools.result import ToolAttachment

    large = 10 * 1024 * 1024 + 1
    value = {
        "outputs": [{"type": "text", "text": "before"}, {"type": "text", "text": "after"}],
        "artifacts": [
            {
                "kind": "audio",
                "artifact_id": "native_large",
                "mime_type": "audio/wav",
                "size_bytes": large,
            }
        ],
        "output_order": [
            {"source": "text", "index": 0},
            {"source": "media", "index": 0},
            {"source": "text", "index": 1},
        ],
    }
    attachments = [ToolAttachment(name="native_large", content=b"x" * large, mime_type="audio/wav")]
    selected, omitted = module.select_repl_attachments(value, attachments)
    assert selected == []
    assert "artifact_id" not in omitted[0]
    display = module.repl_output_display(SCHEMA, value, omitted)
    assert display == {
        "kind": "repl_output",
        "entries": [
            {"kind": "text", "text": "before"},
            {"kind": "unavailable", "reason": "media_size_limit"},
            {"kind": "text", "text": "after"},
        ],
    }
    assert (
        module.repl_output_display(
            SCHEMA,
            {**value, "artifacts": [{**value["artifacts"][0], "mime_type": "text/html"}]},
            omitted,
        )
        is None
    )


def test_cell_limit_is_applied_in_output_order_and_does_not_count_omitted_entries() -> None:
    sizes = [10, 10, 10, 4, 2]
    media = [
        {
            "kind": "image",
            "artifact_id": f"native_{index}",
            "mime_type": "image/png",
            "size_bytes": size * 1024 * 1024,
        }
        for index, size in enumerate(sizes)
    ]
    references = [
        {
            "native_attachment_id": row["artifact_id"],
            "artifact_id": f"cloud_{index}",
            "mime_type": row["mime_type"],
            "size_bytes": row["size_bytes"],
        }
        for index, row in enumerate(media)
    ]
    value = {
        "outputs": [],
        "artifacts": media,
        "output_order": [{"source": "media", "index": index} for index in range(5)],
    }
    display = module.repl_output_display(SCHEMA, value, references)
    assert [entry["kind"] for entry in display["entries"]] == [
        "image",
        "image",
        "image",
        "unavailable",
        "image",
    ]
    value["output_order"] = [{"source": "media", "index": index} for index in [3, 0, 1, 2, 4]]
    display = module.repl_output_display(SCHEMA, value, references)
    assert [entry["kind"] for entry in display["entries"]] == [
        "image",
        "image",
        "image",
        "unavailable",
        "image",
    ]
    assert display["entries"][0]["artifactId"] == "cloud_3"
