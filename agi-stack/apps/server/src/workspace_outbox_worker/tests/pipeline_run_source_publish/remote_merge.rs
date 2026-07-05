use super::*;

#[tokio::test]
async fn pipeline_run_handler_merges_advanced_remote_branch_before_drone_source_publish() {
    let Some(fixture) = git_publish_fixture() else {
        return;
    };
    run_git_ok(
        &fixture.repo,
        &[
            "push",
            fixture.remote.to_str().unwrap(),
            "HEAD:refs/heads/main",
        ],
    );

    let remote_checkout = fixture.root.join("remote-checkout");
    run_git_ok(
        &fixture.root,
        &[
            "clone",
            fixture.remote.to_str().unwrap(),
            remote_checkout.to_str().unwrap(),
        ],
    );
    run_git_ok(&remote_checkout, &["checkout", "-B", "main", "origin/main"]);
    run_git_ok(
        &remote_checkout,
        &["config", "user.email", "remote@example.test"],
    );
    run_git_ok(&remote_checkout, &["config", "user.name", "Remote Test"]);
    std::fs::write(remote_checkout.join("remote.txt"), "remote-only\n").unwrap();
    run_git_ok(&remote_checkout, &["add", "remote.txt"]);
    run_git_ok(&remote_checkout, &["commit", "-m", "remote advance"]);
    let remote_commit = run_git_ok(&remote_checkout, &["rev-parse", "HEAD"])
        .trim()
        .to_string();
    run_git_ok(
        &remote_checkout,
        &["push", "origin", "HEAD:refs/heads/main"],
    );

    std::fs::write(fixture.repo.join("candidate.txt"), "candidate-only\n").unwrap();
    run_git_ok(&fixture.repo, &["add", "candidate.txt"]);
    run_git_ok(&fixture.repo, &["commit", "-m", "candidate change"]);
    let candidate_commit = run_git_ok(&fixture.repo, &["rev-parse", "HEAD"])
        .trim()
        .to_string();

    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    store.insert_workspace(workspace_with_drone_pipeline_contract_git_publish(
        &fixture.repo,
        &fixture.remote,
    ));
    store.insert_plan(plan());
    let mut node = plan_node();
    node.execution = "reported".to_string();
    node.current_attempt_id = Some("attempt-test".to_string());
    node.feature_checkpoint_json = Some(json!({"commit_ref": candidate_commit.clone()}));
    store.insert_node(node);
    let handler = pipeline_run_handler(Arc::clone(&store));

    let outcome = handler.handle(pipeline_run_item()).await.unwrap();

    assert_eq!(outcome, WorkspacePlanOutboxHandlerOutcome::Complete);
    let pushed = run_git_ok(
        &fixture.root,
        &[
            "--git-dir",
            fixture.remote.to_str().unwrap(),
            "rev-parse",
            "refs/heads/main",
        ],
    )
    .trim()
    .to_string();
    assert_ne!(pushed, candidate_commit);
    run_git_ok(
        &fixture.root,
        &[
            "--git-dir",
            fixture.remote.to_str().unwrap(),
            "merge-base",
            "--is-ancestor",
            &candidate_commit,
            "refs/heads/main",
        ],
    );
    run_git_ok(
        &fixture.root,
        &[
            "--git-dir",
            fixture.remote.to_str().unwrap(),
            "merge-base",
            "--is-ancestor",
            &remote_commit,
            "refs/heads/main",
        ],
    );
    assert_eq!(
        run_git_ok(
            &fixture.root,
            &[
                "--git-dir",
                fixture.remote.to_str().unwrap(),
                "show",
                "refs/heads/main:candidate.txt",
            ],
        ),
        "candidate-only\n"
    );
    assert_eq!(
        run_git_ok(
            &fixture.root,
            &[
                "--git-dir",
                fixture.remote.to_str().unwrap(),
                "show",
                "refs/heads/main:remote.txt",
            ],
        ),
        "remote-only\n"
    );

    let run = store.pipeline_runs().into_iter().next().unwrap();
    assert_eq!(run.provider, DRONE_PROVIDER);
    assert_eq!(run.status, "failed");
    assert_eq!(run.commit_ref.as_deref(), Some(candidate_commit.as_str()));
    assert_eq!(run.metadata_json["source_publish_status"], "published");
    assert_eq!(run.metadata_json["source_publish_commit_ref"], pushed);
    assert_eq!(
        run.metadata_json["source_publish_source_commit_ref"],
        candidate_commit
    );
    assert!(run.metadata_json["source_publish_reason"]
        .as_str()
        .is_some_and(|reason| reason.contains("merged remote branch before publish")));

    let contract = store.pipeline_contract("workspace-test", "plan-test");
    assert_eq!(
        contract.metadata_json["provider_config"]["source_publish"]["commit"],
        pushed
    );
    assert_eq!(
        contract.metadata_json["provider_config"]["source_publish"]["source_commit_ref"],
        candidate_commit
    );
    let node = store.node("node-test");
    assert_eq!(node.metadata_json["source_publish_status"], "published");
    assert_eq!(node.metadata_json["source_publish_commit_ref"], pushed);
    assert_eq!(
        node.metadata_json["source_publish_source_commit_ref"],
        candidate_commit
    );
}
