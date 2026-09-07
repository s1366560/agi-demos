use std::{error::Error, io};

use agistack_plugin_contract_completeness_v2::{scan_rust_contract_v2, ScanRequestV2};

fn main() -> Result<(), Box<dyn Error>> {
    let request: ScanRequestV2 = serde_json::from_reader(io::stdin().lock())?;
    let response = scan_rust_contract_v2(&request);
    serde_json::to_writer(io::stdout().lock(), &response)?;
    Ok(())
}
