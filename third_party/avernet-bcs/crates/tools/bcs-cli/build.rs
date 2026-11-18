fn main() {
    let host_revision = host_revision();
    let upstream_revision = upstream_revision();
    let date = build_date();
    println!("cargo:rustc-env=GIT_COMMIT_HASH={upstream_revision}");
    println!("cargo:rustc-env=MEMSTACK_HOST_GIT_REVISION={host_revision}");
    println!("cargo:rustc-env=AVERNET_UPSTREAM_GIT_REVISION={upstream_revision}");
    println!("cargo:rustc-env=BUILD_DATE={date}");
    println!("cargo:rerun-if-env-changed=MEMSTACK_HOST_GIT_REVISION");
    println!("cargo:rerun-if-env-changed=SOURCE_DATE_EPOCH");
    println!("cargo:rerun-if-env-changed=BCS_CLI_DEFAULT_PRE_URL");
    println!("cargo:rerun-if-env-changed=BCS_CLI_DEFAULT_PROD_URL");
}

fn host_revision() -> String {
    std::env::var("MEMSTACK_HOST_GIT_REVISION").unwrap_or_else(|_| "unknown".to_string())
}

fn upstream_revision() -> &'static str {
    "e470fb3d88979b9da8dc11c63f9d9c4b73343c9d"
}

fn build_date() -> String {
    let Ok(raw_epoch) = std::env::var("SOURCE_DATE_EPOCH") else {
        return "unknown".to_string();
    };
    let epoch = raw_epoch
        .parse::<i64>()
        .unwrap_or_else(|error| panic!("SOURCE_DATE_EPOCH must be a signed integer: {error}"));
    time::OffsetDateTime::from_unix_timestamp(epoch)
        .expect("SOURCE_DATE_EPOCH exceeds the supported date range")
        .format(time::macros::format_description!("[year]-[month]-[day]"))
        .expect("valid timestamp format")
}
