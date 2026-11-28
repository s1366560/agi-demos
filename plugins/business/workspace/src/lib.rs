//! Export a page of member-visible Workspace Core workspaces to UTF-8 CSV.
#[cfg(target_arch = "wasm32")]
mod abi;

use serde::Deserialize;
use serde_json::json;

const ARCHIVE_COLUMN: (&str, &str, &str) = ("archived", "true", "false");

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Page {
    header: bool,
    rows: Vec<Workspace>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Workspace {
    id: String,
    name: String,
    office_status: String,
    is_archived: bool,
}

fn field(value: &str, output: &mut String) {
    output.push('"');
    // Keep user-controlled names literal when a spreadsheet opens the attachment.
    if value.trim_start().starts_with(['=', '+', '-', '@']) || value.starts_with(['\t', '\r', '\n'])
    {
        output.push('\'');
    }
    for ch in value.chars() {
        if ch == '"' {
            output.push('"');
        }
        output.push(ch);
    }
    output.push('"');
}

fn export(input: &[u8]) -> Option<Vec<u8>> {
    let page: Page = serde_json::from_slice(input).ok()?;
    let mut csv = if page.header {
        format!("workspace_id,name,office_status,{}\r\n", ARCHIVE_COLUMN.0)
    } else {
        String::new()
    };
    for row in page.rows {
        for part in [&row.id, &row.name, &row.office_status] {
            field(part, &mut csv);
            csv.push(',');
        }
        csv.push_str(if row.is_archived {
            ARCHIVE_COLUMN.1
        } else {
            ARCHIVE_COLUMN.2
        });
        csv.push_str("\r\n");
    }
    serde_json::to_vec(&json!({"csv":csv})).ok()
}

#[cfg(test)]
mod tests {
    use super::export;
    use serde_json::{json, Value};

    #[test]
    fn protects_spreadsheet_cells_and_preserves_csv_quoting() {
        let input = json!({"header":false,"rows":[{"id":"w","name":" =1,\"x\"\n二","office_status":"active","is_archived":false}]});
        let data: Value =
            serde_json::from_slice(&export(input.to_string().as_bytes()).unwrap()).unwrap();
        assert_eq!(
            data["csv"],
            "\"w\",\"' =1,\"\"x\"\"\n二\",\"active\",false\r\n"
        );
    }
}
