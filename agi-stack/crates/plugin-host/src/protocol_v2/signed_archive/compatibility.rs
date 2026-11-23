//! Host ABI compatibility of a verified package, independent from its business version.
use super::{reject, BundleArchiveV2Error};
use serde::Deserialize;

const HOST_ABI: [u32; 3] = [2, 0, 0];
const LEGACY_V2_ABI: [u32; 3] = [2, 0, 0];

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Range {
    schema: String,
    min_inclusive: String,
    max_exclusive: String,
}

fn invalid() -> BundleArchiveV2Error {
    reject("invalid_host_abi", "invalid package host ABI declaration")
}

fn version(raw: &str) -> Result<[u32; 3], BundleArchiveV2Error> {
    let mut parts = raw.split('.');
    let mut version = [0; 3];
    for field in &mut version {
        let part = parts.next().ok_or_else(invalid)?;
        if part.is_empty()
            || (part.len() > 1 && part.starts_with('0'))
            || !part.bytes().all(|b| b.is_ascii_digit())
        {
            return Err(invalid());
        }
        *field = part.parse().map_err(|_| invalid())?;
    }
    if parts.next().is_some() {
        return Err(invalid());
    }
    Ok(version)
}

pub(super) fn require_compatible(descriptor: Option<&[u8]>) -> Result<(), BundleArchiveV2Error> {
    let supported = match descriptor {
        None => HOST_ABI == LEGACY_V2_ABI,
        Some(raw) => {
            if raw.len() > 1024 {
                return Err(invalid());
            }
            let range: Range = serde_json::from_slice(raw).map_err(|_| invalid())?;
            let lower = version(&range.min_inclusive)?;
            let upper = version(&range.max_exclusive)?;
            if range.schema != "memstack.host-compatibility/1" || lower >= upper {
                return Err(invalid());
            }
            (lower..upper).contains(&HOST_ABI)
        }
    };
    if !supported {
        return Err(reject(
            "incompatible_host_abi",
            "signed package is incompatible with this host ABI",
        ));
    }
    Ok(())
}
