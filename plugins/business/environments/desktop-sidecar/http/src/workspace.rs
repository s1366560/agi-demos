use serde_json::{json, Value};

// The native broker binds paths, byte limits and data to the current request.
pub(super) fn read_plan(path: &str) -> Option<Value> {
    let (operation, body) = match path {
        "sandbox/capabilities" => ("status", json!({
        "service_version": "$host_version",
        "contract_version": 2,
        "terminal_interactive": {
            "availability": "available",
            "contract_version": 1,
            "reason_code": null,
        },
        "terminal_resume": {
            "availability": "unavailable",
            "contract_version": 2,
            "reason_code": "local_terminal_resume_unavailable",
        },
        "files": {
            "availability": "available",
            "contract_version": 1,
            "reason_code": null,
        },
        "kasm_vnc": {
            "availability": "not_applicable",
            "contract_version": 1,
            "reason_code": "local_kasm_vnc_not_applicable",
        },
    })),
        "sandbox/files" => ("directory", json!({})),
        "sandbox/files/content" => ("text", json!({})),
        "sandbox/files/download" => ("download", json!({})),
        _ => return None,
    };
    let contract = json!({"contract_version":1,"authority":"native_workspace","isolation":"not_applicable"});
    Some(json!({"workspace_read":{"operation":operation,"body":body,"contract":contract,
        "download_headers":[["X-MemStack-File-Contract-Version","1"],["X-MemStack-File-Authority","native_workspace"],["X-MemStack-File-Isolation","not_applicable"]],
        "errors":{"reserved":[403,"sandbox_file_reserved_path","sandbox file path is reserved for the local runtime"],"cursor":[422,"sandbox_file_cursor_invalid","sandbox file cursor is invalid"],
        "list_limit": [
                422,
                "sandbox_file_limit_invalid",
                "sandbox file list limit is invalid"
        ],
        "encoding": [
                415,
                "sandbox_file_text_read_unsupported",
                "sandbox file is not valid UTF-8 text"
        ],
        "symlink": [
                403,
                "sandbox_file_symlink_not_allowed",
                "sandbox file path contains a symbolic link"
        ],
        "outside": [
                403,
                "sandbox_file_path_outside_workspace",
                "sandbox file path is outside the native workspace"
        ],
        "bytes_limit": [
                422,
                "sandbox_file_limit_invalid",
                "sandbox file byte limit is invalid"
        ],
        "mime": [
                415,
                "sandbox_file_text_read_unsupported",
                "sandbox file MIME type is not supported by the text reader"
        ],
        "scope": [
                403,
                "sandbox_file_scope_mismatch",
                "sandbox file request is outside the active project"
        ],
        "query": [
                422,
                "sandbox_file_query_invalid",
                "sandbox file query is invalid"
        ],
        "path": [
                422,
                "sandbox_file_path_invalid",
                "sandbox file path is invalid"
        ],
        "not_found": [
                404,
                "sandbox_file_not_found",
                "sandbox file was not found"
        ],
        "type": [
                422,
                "sandbox_file_type_unsupported",
                "sandbox file type is not supported"
        ],
        "too_large": [
                413,
                "sandbox_file_too_large",
                "sandbox file exceeds the allowed byte limit"
        ],
        "root": [
                503,
                "native_workspace_unavailable",
                "native workspace is unavailable"
        ],
        "io": [
                500,
                "sandbox_file_io_error",
                "sandbox file operation failed"
        ]
}}}))
}
