// Cached cloud generations from an older client never prevent validated current publication.
use super::*;

fn outdated_distribution() -> ControlPlaneDistributionV2 {
    let mut wire = serde_json::to_value(bootstrap_distribution(8, "old-client-catalog")).unwrap();
    for manifest in wire["snapshot"]["manifests"].as_array_mut().unwrap() {
        for module in manifest["modules"].as_array_mut().unwrap() {
            if module["module_ref"] == "builtin://memstack/desktop-sidecar/http-routes" {
                module["artifact"]["digest"] = json!(format!("sha256:{}", "a".repeat(64)));
            }
        }
    }
    let mut payload = wire["snapshot"].clone();
    payload.as_object_mut().unwrap().remove("digest");
    let digest = format!("{:x}", Sha256::digest(serde_jcs::to_vec(&payload).unwrap()));
    wire["snapshot"]["digest"] = json!(digest);
    wire["descriptor"]["digest"] = json!(digest);
    wire["envelope"]["snapshot_digest"] = json!(digest);
    parse_control_plane_distribution_v2(&wire.to_string()).unwrap()
}

fn seed_prior_client_receipt(
    state: &LocalRuntimeState,
    fingerprint: &str,
    prior: &ControlPlaneDistributionV2,
) {
    // This models a receipt persisted by the older client whose catalog matched this artifact.
    let receipt = SnapshotApplyReceiptV2 {
        status: ApplyStatusV2::Ack,
        requested_version: prior.envelope.version,
        requested_digest: prior.snapshot.digest.clone(),
        applied_version: Some(prior.envelope.version),
        applied_digest: Some(prior.snapshot.digest.clone()),
        error_code: None,
        error_message: None,
    };
    let mut db = state.session_store.connection().unwrap();
    plugin_snapshots_v2::initialize_schema(&db).unwrap();
    plugin_snapshots_v2::record_requested(&db, fingerprint, prior).unwrap();
    plugin_snapshots_v2::record_receipt(&mut db, fingerprint, &prior.envelope.nonce, &receipt)
        .unwrap();
}

#[tokio::test]
async fn rejected_cached_catalog_allows_authenticated_fresh_fetch_and_retains_cache_until_ack() {
    for candidate in ["current", "invalid", "older"] {
        let fresh = match candidate {
            "current" => bootstrap_distribution(9, "current-client-catalog"),
            "invalid" => {
                bootstrap_distribution_without_route_provider(9, "invalid-current-catalog")
            }
            _ => bootstrap_distribution(7, "older-client-catalog"),
        };
        let (base, server, shutdown, task) = spawn_data_plane_v2(&fresh).await;
        let state = test_state();
        let credentials = plugin_data_plane_credentials_v2();
        let record = plugin_data_plane_record_v2(&base, 'b', false);
        credentials.save(&record).unwrap();
        let authority = load_plugin_data_plane_authority_v2(&credentials)
            .unwrap()
            .unwrap();
        let prior = outdated_distribution();
        seed_prior_client_receipt(&state, &authority.fingerprint, &prior);
        let mut reconciler = desktop_reconciler(&state);
        activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
            .await
            .unwrap();
        assert!(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .is_ok()
        );
        let expected = PlatformPluginAuthoritySelectionV2 {
            mode: PlatformPluginAuthorityModeV2::Cloud,
            epoch: 1,
        };
        let selection = Mutex::new(expected);
        let mut active = Some(DesktopAuthoritySourceV2::Local);
        let outcome = reconcile_selected_authority(
            &state,
            &credentials,
            &selection,
            expected,
            &mut reconciler,
            &mut active,
        )
        .await
        .unwrap();
        assert_eq!(outcome, SelectionReconcileOutcomeV2::Applied);
        assert!(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .is_err()
        );
        assert_eq!(
            restore_last_good(&state, &authority.fingerprint).unwrap(),
            Some(prior.clone())
        );
        assert!(server.requests().is_empty());
        poll_selected_authority(&state, &credentials, &selection, expected, &mut reconciler)
            .await
            .unwrap();
        let requests = server.requests();
        assert_eq!(requests.len(), 1);
        assert_eq!(requests[0].method, Method::GET);
        assert_eq!(
            requests[0].authorization,
            Some(format!("Bearer {}", record.credential))
        );
        let current = state.platform_plugin_authority_v2.acquire_generation();
        if candidate == "current" {
            assert_eq!(current.unwrap().descriptor().publication_version, Some(9));
            assert_eq!(
                restore_last_good(&state, &authority.fingerprint).unwrap(),
                Some(fresh)
            );
        } else {
            assert!(current.is_err());
            assert_eq!(
                restore_last_good(&state, &authority.fingerprint).unwrap(),
                Some(prior)
            );
        }
        state.platform_plugin_authority_v2.deactivate().await;
        shutdown.send(()).unwrap();
        task.await.unwrap();
    }
}
