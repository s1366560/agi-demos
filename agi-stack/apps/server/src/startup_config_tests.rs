use std::{
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
    sync::{atomic::AtomicU64, atomic::Ordering, Mutex, MutexGuard},
};

use super::*;

const FILE_DATABASE_URL: &str = "postgresql://file.example/memstack";
const AMBIENT_DATABASE_URL: &str = "postgresql://ambient.example/other";
const AGISTACK_MAKEFILE: &str = include_str!("../../../Makefile");
static NEXT_FILE_ID: AtomicU64 = AtomicU64::new(0);
static DATABASE_URL_ENV_LOCK: Mutex<()> = Mutex::new(());

struct TempEnvFile {
    path: PathBuf,
}

impl TempEnvFile {
    fn new(contents: &str) -> Self {
        let id = NEXT_FILE_ID.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "agistack-server-startup-{}-{id}.env",
            std::process::id()
        ));
        fs::write(&path, contents).expect("temporary .env should be writable");
        Self { path }
    }

    fn missing() -> Self {
        let id = NEXT_FILE_ID.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "agistack-server-startup-missing-{}-{id}.env",
            std::process::id()
        ));
        let _ = fs::remove_file(&path);
        Self { path }
    }

    fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for TempEnvFile {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

struct ScopedDatabaseUrlEnv {
    previous: Option<OsString>,
    _guard: MutexGuard<'static, ()>,
}

impl ScopedDatabaseUrlEnv {
    fn set(value: &str) -> Self {
        let guard = DATABASE_URL_ENV_LOCK
            .lock()
            .expect("DATABASE_URL test lock should be available");
        let previous = std::env::var_os("DATABASE_URL");
        std::env::set_var("DATABASE_URL", value);
        Self {
            previous,
            _guard: guard,
        }
    }
}

impl Drop for ScopedDatabaseUrlEnv {
    fn drop(&mut self) {
        if let Some(previous) = self.previous.take() {
            std::env::set_var("DATABASE_URL", previous);
        } else {
            std::env::remove_var("DATABASE_URL");
        }
    }
}

#[test]
fn repository_env_path_targets_the_repository_root() {
    let expected = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../.env");

    assert_eq!(Path::new(REPOSITORY_ENV_PATH), expected);
}

#[test]
fn repository_env_database_url_is_loaded() {
    let env_file = TempEnvFile::new(&format!("DATABASE_URL={FILE_DATABASE_URL}\n"));

    let database_url =
        database_url_from_path(env_file.path()).expect("DATABASE_URL should load from file");

    assert_eq!(database_url.0, FILE_DATABASE_URL);
}

#[test]
fn repository_env_database_url_expands_only_file_assignments() {
    let env_file = TempEnvFile::new(
        "POSTGRES_HOST=file.example\nPOSTGRES_DB=memstack\n\
         DATABASE_URL=postgresql://${POSTGRES_HOST}/${POSTGRES_DB}\n",
    );

    let database_url =
        database_url_from_path(env_file.path()).expect("file variables should resolve");

    assert_eq!(database_url.0, FILE_DATABASE_URL);
}

#[test]
fn missing_repository_env_file_fails_closed() {
    let env_file = TempEnvFile::missing();

    let error = database_url_from_path(env_file.path()).expect_err("missing file must fail");

    assert_eq!(
        error,
        DatabaseUrlConfigError::EnvFileUnavailable {
            path: env_file.path().to_path_buf()
        }
    );
}

#[test]
fn missing_database_url_does_not_synthesize_postgres_fallback() {
    let env_file =
        TempEnvFile::new("POSTGRES_HOST=localhost\nPOSTGRES_PORT=5432\nPOSTGRES_DB=memstack\n");

    let error = database_url_from_path(env_file.path())
        .expect_err("POSTGRES parts must not synthesize DATABASE_URL");

    assert_eq!(
        error,
        DatabaseUrlConfigError::MissingDatabaseUrl {
            path: env_file.path().to_path_buf()
        }
    );
}

#[test]
fn empty_database_url_fails_closed() {
    let env_file = TempEnvFile::new("DATABASE_URL='   '\n");

    let error = database_url_from_path(env_file.path()).expect_err("empty DATABASE_URL must fail");

    assert_eq!(
        error,
        DatabaseUrlConfigError::EmptyDatabaseUrl {
            path: env_file.path().to_path_buf()
        }
    );
}

#[test]
fn non_postgres_database_url_fails_closed_without_echoing_the_value() {
    let env_file = TempEnvFile::new("DATABASE_URL=https://secret.example/private\n");

    let error =
        database_url_from_path(env_file.path()).expect_err("non-PostgreSQL DATABASE_URL must fail");

    assert_eq!(
        error,
        DatabaseUrlConfigError::InvalidDatabaseUrl {
            path: env_file.path().to_path_buf()
        }
    );
    assert!(!error.to_string().contains("secret.example"));
}

#[test]
fn postgresql_asyncpg_url_is_normalized_for_the_rust_driver() {
    let env_file = TempEnvFile::new("DATABASE_URL=postgresql+asyncpg://file.example/memstack\n");

    let database_url = database_url_from_path(env_file.path())
        .expect("Python asyncpg URL should be usable by the Rust server");

    assert_eq!(database_url.0, FILE_DATABASE_URL);
}

#[test]
fn ambient_database_url_cannot_override_repository_env() {
    let _ambient = ScopedDatabaseUrlEnv::set(AMBIENT_DATABASE_URL);
    let env_file = TempEnvFile::new(&format!("DATABASE_URL={FILE_DATABASE_URL}\n"));

    let database_url =
        database_url_from_path(env_file.path()).expect("repository value should win");

    assert_eq!(database_url.0, FILE_DATABASE_URL);
    assert_ne!(database_url.0, AMBIENT_DATABASE_URL);
}

#[test]
fn database_url_debug_output_is_redacted() {
    let database_url = DatabaseUrl(FILE_DATABASE_URL.to_owned());

    let debug_output = format!("{database_url:?}");

    assert_eq!(debug_output, "DatabaseUrl(\"[redacted]\")");
    assert!(!debug_output.contains(FILE_DATABASE_URL));
}

#[test]
fn run_server_recipe_delegates_database_loading_to_rust() {
    let (_, recipe_and_rest) = AGISTACK_MAKEFILE
        .split_once("run-server:")
        .expect("run-server target should exist");
    let (recipe, _) = recipe_and_rest
        .split_once("# ---- Web")
        .expect("run-server target should precede the Web section");

    assert!(recipe.contains("cargo") || recipe.contains("$(CARGO)"));
    assert!(!recipe.contains("DATABASE_URL="));
    assert!(!recipe.contains("POSTGRES_"));
    assert!(!recipe.contains("DEV_ENV"));
    assert!(!recipe.contains("RUN_SERVER_DEV_STUB"));
}
