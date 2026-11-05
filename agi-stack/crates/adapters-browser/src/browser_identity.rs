//! Browser family selectors and opaque, connection-bound browser identities.
use crate::host::tool_err;
use agistack_core::ports::CoreResult;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub(crate) enum BrowserFamily {
    Chrome,
    Edge,
    Iab,
    Dot,
    Cdp,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub(crate) enum Backend {
    Chrome,
    Edge,
    Iab,
    Dot,
    Cdp,
    Instance {
        family: BrowserFamily,
        profile: u128,
        generation: u128,
    },
}

impl Backend {
    pub(crate) fn family(self) -> &'static str {
        match self {
            Self::Chrome
            | Self::Instance {
                family: BrowserFamily::Chrome,
                ..
            } => "chrome",
            Self::Edge
            | Self::Instance {
                family: BrowserFamily::Edge,
                ..
            } => "edge",
            Self::Iab
            | Self::Instance {
                family: BrowserFamily::Iab,
                ..
            } => "iab",
            Self::Dot
            | Self::Instance {
                family: BrowserFamily::Dot,
                ..
            } => "dot",
            Self::Cdp
            | Self::Instance {
                family: BrowserFamily::Cdp,
                ..
            } => "cdp",
        }
    }

    pub(crate) fn as_str(self) -> String {
        match self {
            Self::Instance {
                profile,
                generation,
                ..
            } => {
                format!("{}:{profile:032x}:{generation:032x}", self.family())
            }
            _ => self.family().to_string(),
        }
    }

    pub(crate) fn wire_name(self) -> String {
        match self {
            Self::Chrome => "chrome-extension".to_string(),
            Self::Edge => "edge-extension".to_string(),
            _ => self.as_str(),
        }
    }

    pub(crate) fn parse(value: &str) -> CoreResult<Self> {
        match value {
            "chrome" | "chrome-extension" => return Ok(Self::Chrome),
            "edge" | "edge-extension" => return Ok(Self::Edge),
            "iab" => return Ok(Self::Iab),
            "dot" => return Ok(Self::Dot),
            "cdp" => return Ok(Self::Cdp),
            _ => {}
        }
        let mut parts = value.split(':');
        let family = match parts.next() {
            Some("chrome") => BrowserFamily::Chrome,
            Some("edge") => BrowserFamily::Edge,
            Some("iab") => BrowserFamily::Iab,
            Some("dot") => BrowserFamily::Dot,
            Some("cdp") => BrowserFamily::Cdp,
            _ => return Err(tool_err("invalid browser identity")),
        };
        let parse_id = |part: Option<&str>| {
            part.filter(|part| {
                part.len() == 32
                    && part
                        .bytes()
                        .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
            })
            .and_then(|part| u128::from_str_radix(part, 16).ok())
            .ok_or_else(|| tool_err("invalid browser identity"))
        };
        let profile = parse_id(parts.next())?;
        let generation = parse_id(parts.next())?;
        if parts.next().is_some() {
            return Err(tool_err("invalid browser identity"));
        }
        Ok(Self::Instance {
            family,
            profile,
            generation,
        })
    }

    pub(crate) fn from_wire(name: Option<&str>) -> Self {
        name.and_then(|name| Self::parse(name).ok())
            .unwrap_or(Self::Chrome)
    }
}

/// Read only the structural provider family; the endpoint validates liveness.
pub fn browser_family(selector: &str) -> CoreResult<&'static str> {
    Backend::parse(selector).map(Backend::family)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn identities_separate_profiles_and_generations_without_changing_family() {
        let first = Backend::parse(
            "chrome:00000000000000000000000000000001:00000000000000000000000000000002",
        )
        .unwrap();
        let other_profile = Backend::parse(
            "chrome:00000000000000000000000000000003:00000000000000000000000000000002",
        )
        .unwrap();
        let reconnected = Backend::parse(
            "chrome:00000000000000000000000000000001:00000000000000000000000000000004",
        )
        .unwrap();
        assert_ne!(first, other_profile);
        assert_ne!(first, reconnected);
        assert_eq!(first.family(), "chrome");
        assert_eq!(Backend::parse(&first.as_str()).unwrap(), first);
        for invalid in [
            "chrome:1:2",
            "chrome:00000000000000000000000000000001:00000000000000000000000000000002:extra",
            "unknown",
        ] {
            assert!(Backend::parse(invalid).is_err());
        }
    }
}
