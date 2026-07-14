//! Repository-owned startup configuration for the native server.
//!
//! Variable references are resolved only against assignments in the same file;
//! the process environment is deliberately outside this configuration boundary.

use std::{
    collections::{HashMap, HashSet},
    fmt, fs,
    path::{Path, PathBuf},
};

use url::Url;

const REPOSITORY_ENV_PATH: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../.env");

#[derive(Debug, Eq, PartialEq)]
pub(crate) enum DatabaseUrlConfigError {
    EnvFileUnavailable { path: PathBuf },
    EnvFileInvalid { path: PathBuf },
    MissingDatabaseUrl { path: PathBuf },
    EmptyDatabaseUrl { path: PathBuf },
    InvalidDatabaseUrl { path: PathBuf },
}

#[derive(Clone, Eq, PartialEq)]
pub(crate) struct DatabaseUrl(String);

impl DatabaseUrl {
    pub(crate) fn expose(&self) -> &str {
        &self.0
    }

    #[cfg(test)]
    pub(crate) fn for_test(value: &str) -> Self {
        Self(value.to_owned())
    }
}

impl fmt::Debug for DatabaseUrl {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_tuple("DatabaseUrl")
            .field(&"[redacted]")
            .finish()
    }
}

impl fmt::Display for DatabaseUrlConfigError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EnvFileUnavailable { path } => {
                write!(
                    formatter,
                    "repository .env is unavailable at {}",
                    path.display()
                )
            }
            Self::EnvFileInvalid { path } => {
                write!(
                    formatter,
                    "repository .env is invalid at {}",
                    path.display()
                )
            }
            Self::MissingDatabaseUrl { path } => write!(
                formatter,
                "DATABASE_URL is required in repository .env at {}",
                path.display()
            ),
            Self::EmptyDatabaseUrl { path } => write!(
                formatter,
                "DATABASE_URL must not be empty in repository .env at {}",
                path.display()
            ),
            Self::InvalidDatabaseUrl { path } => write!(
                formatter,
                "DATABASE_URL must be a valid PostgreSQL URL in repository .env at {}",
                path.display()
            ),
        }
    }
}

impl std::error::Error for DatabaseUrlConfigError {}

#[derive(Clone)]
struct EnvValue {
    value: String,
    interpolate: bool,
}

pub(crate) fn repository_database_url() -> Result<DatabaseUrl, DatabaseUrlConfigError> {
    database_url_from_path(Path::new(REPOSITORY_ENV_PATH))
}

fn database_url_from_path(path: &Path) -> Result<DatabaseUrl, DatabaseUrlConfigError> {
    let contents =
        fs::read_to_string(path).map_err(|_| DatabaseUrlConfigError::EnvFileUnavailable {
            path: path.to_path_buf(),
        })?;
    let assignments =
        parse_assignments(&contents).map_err(|()| DatabaseUrlConfigError::EnvFileInvalid {
            path: path.to_path_buf(),
        })?;
    let value = assignments.get("DATABASE_URL").ok_or_else(|| {
        DatabaseUrlConfigError::MissingDatabaseUrl {
            path: path.to_path_buf(),
        }
    })?;
    let resolved = resolve_value("DATABASE_URL", value, &assignments, &mut HashSet::new())
        .map_err(|()| DatabaseUrlConfigError::EnvFileInvalid {
            path: path.to_path_buf(),
        })?;
    if resolved.trim().is_empty() {
        return Err(DatabaseUrlConfigError::EmptyDatabaseUrl {
            path: path.to_path_buf(),
        });
    }
    let mut parsed =
        Url::parse(resolved.trim()).map_err(|_| DatabaseUrlConfigError::InvalidDatabaseUrl {
            path: path.to_path_buf(),
        })?;
    match parsed.scheme() {
        "postgres" | "postgresql" => {}
        "postgresql+asyncpg" => {
            parsed.set_scheme("postgresql").map_err(|()| {
                DatabaseUrlConfigError::InvalidDatabaseUrl {
                    path: path.to_path_buf(),
                }
            })?;
        }
        _ => {
            return Err(DatabaseUrlConfigError::InvalidDatabaseUrl {
                path: path.to_path_buf(),
            });
        }
    }
    if parsed.path().trim_matches('/').is_empty() {
        return Err(DatabaseUrlConfigError::InvalidDatabaseUrl {
            path: path.to_path_buf(),
        });
    }
    Ok(DatabaseUrl(parsed.into()))
}

fn parse_assignments(contents: &str) -> Result<HashMap<String, EnvValue>, ()> {
    let mut assignments = HashMap::new();
    for line in contents.lines() {
        let line = line.trim_start();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let line = line.strip_prefix("export ").unwrap_or(line);
        let (key, raw_value) = line.split_once('=').ok_or(())?;
        let key = key.trim();
        if !is_valid_key(key) {
            return Err(());
        }
        assignments.insert(key.to_owned(), parse_value(raw_value)?);
    }
    Ok(assignments)
}

fn is_valid_key(key: &str) -> bool {
    let mut chars = key.chars();
    chars
        .next()
        .is_some_and(|character| character.is_ascii_alphabetic() || character == '_')
        && chars.all(|character| character.is_ascii_alphanumeric() || character == '_')
}

fn parse_value(raw_value: &str) -> Result<EnvValue, ()> {
    let value = raw_value.trim();
    if let Some(quoted) = value.strip_prefix('\'') {
        return parse_quoted_value(quoted, '\'', false);
    }
    if let Some(quoted) = value.strip_prefix('"') {
        return parse_quoted_value(quoted, '"', true);
    }
    let comment = value
        .char_indices()
        .find(|(index, character)| {
            *character == '#'
                && value[..*index]
                    .chars()
                    .next_back()
                    .is_some_and(char::is_whitespace)
        })
        .map_or(value.len(), |(index, _)| index);
    Ok(EnvValue {
        value: value[..comment].trim_end().to_owned(),
        interpolate: true,
    })
}

fn parse_quoted_value(value: &str, quote: char, interpolate: bool) -> Result<EnvValue, ()> {
    let mut escaped = false;
    let mut closing_index = None;
    for (index, character) in value.char_indices() {
        if escaped {
            escaped = false;
            continue;
        }
        if character == '\\' && quote == '"' {
            escaped = true;
            continue;
        }
        if character == quote {
            closing_index = Some(index);
            break;
        }
    }
    let closing_index = closing_index.ok_or(())?;
    let trailing = value[closing_index + quote.len_utf8()..].trim();
    if !trailing.is_empty() && !trailing.starts_with('#') {
        return Err(());
    }
    let value = &value[..closing_index];
    let value = if quote == '"' {
        unescape_double_quoted(value)?
    } else {
        value.to_owned()
    };
    Ok(EnvValue { value, interpolate })
}

fn unescape_double_quoted(value: &str) -> Result<String, ()> {
    let mut output = String::with_capacity(value.len());
    let mut characters = value.chars();
    while let Some(character) = characters.next() {
        if character != '\\' {
            output.push(character);
            continue;
        }
        match characters.next().ok_or(())? {
            '\\' => output.push('\\'),
            '"' => output.push('"'),
            '$' => output.push('$'),
            'n' => output.push('\n'),
            _ => return Err(()),
        }
    }
    Ok(output)
}

fn resolve_value(
    key: &str,
    value: &EnvValue,
    assignments: &HashMap<String, EnvValue>,
    resolving: &mut HashSet<String>,
) -> Result<String, ()> {
    if !value.interpolate {
        return Ok(value.value.clone());
    }
    if !resolving.insert(key.to_owned()) {
        return Err(());
    }
    let resolved = substitute_variables(&value.value, assignments, resolving);
    resolving.remove(key);
    resolved
}

fn substitute_variables(
    value: &str,
    assignments: &HashMap<String, EnvValue>,
    resolving: &mut HashSet<String>,
) -> Result<String, ()> {
    let mut output = String::with_capacity(value.len());
    let mut remaining = value;
    while let Some(dollar_index) = remaining.find('$') {
        output.push_str(&remaining[..dollar_index]);
        remaining = &remaining[dollar_index + 1..];
        let (name, consumed) = variable_name(remaining)?;
        let variable = assignments.get(name).ok_or(())?;
        output.push_str(&resolve_value(name, variable, assignments, resolving)?);
        remaining = &remaining[consumed..];
    }
    output.push_str(remaining);
    Ok(output)
}

fn variable_name(value: &str) -> Result<(&str, usize), ()> {
    if let Some(value) = value.strip_prefix('{') {
        let closing_index = value.find('}').ok_or(())?;
        let name = &value[..closing_index];
        if !is_valid_key(name) {
            return Err(());
        }
        return Ok((name, closing_index + 2));
    }
    let length = value
        .find(|character: char| !(character.is_ascii_alphanumeric() || character == '_'))
        .unwrap_or(value.len());
    let name = &value[..length];
    if !is_valid_key(name) {
        return Err(());
    }
    Ok((name, length))
}

#[cfg(test)]
#[path = "startup_config_tests.rs"]
mod tests;
