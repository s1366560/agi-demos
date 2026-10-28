//! Escape probes execute in real Seatbelt processes, including a compiled native addon.
use super::*;

#[tokio::test]
async fn full_access_still_blocks_native_fork_loopback_and_host_replacement() {
    let root = std::env::temp_dir().join(format!("memstack-repl-native-{}", uuid::Uuid::new_v4()));
    for directory in ["workspace", "temporary", "private", "host"] {
        std::fs::create_dir_all(root.join(directory)).unwrap();
    }
    let root = root.canonicalize().unwrap();
    let private = root.join("private/secret");
    let host = root.join("host/runtime.js");
    let native_artifacts =
        std::env::temp_dir().join(format!("memstack-cua-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir(&native_artifacts).unwrap();
    std::fs::write(
        native_artifacts.join("recording.wav"),
        b"private recording fixture",
    )
    .unwrap();
    std::os::unix::fs::symlink(
        native_artifacts.join("recording.wav"),
        root.join("workspace/native-alias"),
    )
    .unwrap();
    std::fs::write(&private, b"private fixture").unwrap();
    std::fs::write(&host, b"trusted fixture").unwrap();
    std::os::unix::fs::symlink(&private, root.join("workspace/private-alias")).unwrap();
    std::os::unix::fs::symlink(&host, root.join("workspace/host-alias")).unwrap();
    let source = root.join("workspace/addon.c");
    std::fs::write(
        &source,
        r#"
        #include <unistd.h>
        #include <errno.h>
        #include <spawn.h>
        typedef void* napi_env;
        typedef void* napi_value;
        extern int napi_create_int32(napi_env, int, napi_value*);
        extern int napi_set_named_property(napi_env, napi_value, const char*, napi_value);
        napi_value napi_register_module_v1(napi_env env, napi_value exports) {
            int value = fork();
            if (value == 0) _exit(99);
            napi_value result;
            napi_create_int32(env, value == -1 && errno == EPERM, &result);
            napi_set_named_property(env, exports, "forkDenied", result);
            char *args[] = {"/usr/bin/true", 0};
            char *envp[] = {0};
            pid_t child;
            int spawned = posix_spawn(&child, args[0], 0, 0, args, envp);
            napi_create_int32(env, spawned == EPERM, &result);
            napi_set_named_property(env, exports, "spawnDenied", result);
            execve(args[0], args, envp);
            napi_create_int32(env, errno == EPERM, &result);
            napi_set_named_property(env, exports, "execDenied", result);
            return exports;
        }
    "#,
    )
    .unwrap();
    let addon = root.join("workspace/addon.node");
    let compiled = tokio::process::Command::new("/usr/bin/clang")
        .args(["-dynamiclib", "-undefined", "dynamic_lookup"])
        .arg(&source)
        .arg("-o")
        .arg(&addon)
        .output()
        .await
        .unwrap();
    assert!(
        compiled.status.success(),
        "native addon fixture did not compile"
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let runtime = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../build/cua-repl")
        .canonicalize()
        .unwrap();
    let node = runtime.join("bin/node");
    let sandbox = Sandbox {
        profile: DesktopPermissionProfile::FullAccess,
        workspace: root.join("workspace"),
        temporary: root.join("temporary"),
        runtime,
        protected: vec![root.join("private")],
        immutable: vec![root.join("host")],
        module_roots: vec![],
    };
    let script = format!(
        r#"
        const fs = require('node:fs'), net = require('node:net');
        const deny = f => {{ try {{ f(); return false; }} catch (e) {{ return e.code === 'EPERM'; }} }};
        const connect = host => new Promise(resolve => {{
            const socket = net.connect({{host,port:{port}}});
            socket.on('connect',()=>{{socket.destroy();resolve(false)}});
            socket.on('error',error=>resolve(error.code==='EPERM'||error.code==='EACCES'));
        }});
        (async()=>{{process.stdout.write(JSON.stringify({{
            private:deny(()=>fs.readFileSync('./private-alias')),
            nativeArtifacts:deny(()=>fs.readFileSync('./native-alias')),
            host:deny(()=>fs.writeFileSync('./host-alias','changed')),
            nativeFork:require('./addon.node').forkDenied===1,
            nativeSpawn:require('./addon.node').spawnDenied===1,
            nativeExec:require('./addon.node').execDenied===1,
            detached:require('node:child_process').spawnSync(process.execPath,['-e','0'],{{detached:true}}).error?.code==='EPERM',
            loopback:await connect('127.0.0.1'),mappedLoopback:await connect('::ffff:127.0.0.1')
        }}));}})();
    "#
    );
    let output = tokio::time::timeout(
        std::time::Duration::from_secs(10),
        sandbox
            .command(&node)
            .unwrap()
            .arg("-e")
            .arg(script)
            .output(),
    )
    .await
    .unwrap()
    .unwrap();
    assert!(
        output.status.success(),
        "native sandbox probe failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        result,
        serde_json::json!({"private":true,"nativeArtifacts":true,"host":true,"nativeFork":true,"nativeSpawn":true,"nativeExec":true,"detached":true,"loopback":true,"mappedLoopback":true})
    );
    assert_eq!(std::fs::read(&host).unwrap(), b"trusted fixture");
    std::fs::remove_dir_all(root).unwrap();
    std::fs::remove_dir_all(native_artifacts).unwrap();
}
