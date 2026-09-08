use super::*;

#[test]
fn active_view_hides_stale_output_but_preserves_historical_results() {
    let (repo, s, build) = setup();
    let (lease, input) = begin(&repo, &s, &build);
    apply(&repo, &s, &lease, &input, true);
    let selected = repo
        .select_community_build_durable(&s, &build.build_id, 0, &|| Ok(103))
        .unwrap();
    assert!(repo
        .activate_community_build_durable(&s, &build.build_id, selected.revision, &|| Ok(104))
        .unwrap());
    assert!(repo
        .activate_community_build_durable(&s, &build.build_id, selected.revision, &|| Ok(105))
        .unwrap());
    let historical = repo.community_results_durable(&s, &build.build_id).unwrap();
    let mut memory = block_on(repo.get(&s, "source")).unwrap().unwrap();
    memory.title = "New title".into();
    block_on(repo.update(&s, memory, 1)).unwrap();
    let active = repo.active_community_build_durable(&s).unwrap();
    assert!(active.current.is_none());
    assert_eq!(active.stale_build_id, Some(build.build_id.clone()));
    assert_eq!(
        repo.community_results_durable(&s, &build.build_id).unwrap(),
        historical
    );
    assert!(repo
        .activate_community_build_durable(&s, &build.build_id, selected.revision, &|| Ok(106))
        .is_err());
}

#[test]
fn empty_build_activates_without_a_semantic_verdict() {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    let s = scope("tenant", "project");
    let build = new_build(&repo, &s, "empty");
    let selected = repo
        .select_community_build_durable(&s, &build.build_id, 0, &|| Ok(103))
        .unwrap();
    assert!(repo
        .activate_community_build_durable(&s, &build.build_id, selected.revision, &|| Ok(104))
        .unwrap());
    let active = repo
        .active_community_build_durable(&s)
        .unwrap()
        .current
        .unwrap();
    assert_eq!(active.status.state, CommunityProgressState::CompletedEmpty);
    assert!(active.results.is_empty());
}

#[test]
fn partial_build_cannot_activate_and_selection_cas_is_checked() {
    let (repo, s, _) = setup();
    block_on(create(
        &repo,
        &s,
        "second",
        "Bob's team",
        "Bob joined his team.",
    ));
    block_on(finish(&repo, &s, true));
    let build = new_build(&repo, &s, "two-candidates");
    assert_eq!(build.candidate_count, 2);
    let selected = repo
        .select_community_build_durable(&s, &build.build_id, 0, &|| Ok(100))
        .unwrap();
    assert!(repo
        .select_community_build_durable(&s, &build.build_id, 0, &|| Ok(100))
        .is_err());
    let (lease, input) = begin(&repo, &s, &build);
    apply(&repo, &s, &lease, &input, true);
    assert!(!repo
        .activate_community_build_durable(&s, &build.build_id, selected.revision, &|| Ok(103))
        .unwrap());
    assert!(repo
        .active_community_build_durable(&s)
        .unwrap()
        .current
        .is_none());
    let (lease, input) = begin(&repo, &s, &build);
    apply(&repo, &s, &lease, &input, false);
    assert!(repo
        .activate_community_build_durable(&s, &build.build_id, selected.revision, &|| Ok(103))
        .unwrap());
    let current = repo
        .active_community_build_durable(&s)
        .unwrap()
        .current
        .unwrap();
    assert_eq!(current.status.ready_count, 1);
    assert_eq!(current.status.insufficient_evidence_count, 1);
}

#[test]
fn activation_admission_failure_preserves_previous_active_build() {
    let (repo, s, first) = setup();
    let (lease, input) = begin(&repo, &s, &first);
    apply(&repo, &s, &lease, &input, true);
    let selected = repo
        .select_community_build_durable(&s, &first.build_id, 0, &|| Ok(103))
        .unwrap();
    repo.activate_community_build_durable(&s, &first.build_id, selected.revision, &|| Ok(104))
        .unwrap();
    let second = new_build(&repo, &s, "second");
    let selected = repo
        .select_community_build_durable(&s, &second.build_id, selected.revision, &|| Ok(104))
        .unwrap();
    let (lease, input) = begin(&repo, &s, &second);
    apply(&repo, &s, &lease, &input, true);
    let calls = std::cell::Cell::new(0);
    let clock = || {
        calls.set(calls.get() + 1);
        if calls.get() == 1 {
            Ok(105)
        } else {
            Err(KnowledgeError::Conflict)
        }
    };
    assert!(repo
        .activate_community_build_durable(&s, &second.build_id, selected.revision, &clock)
        .is_err());
    assert_eq!(
        repo.active_community_build_durable(&s)
            .unwrap()
            .current
            .unwrap()
            .status
            .build_id,
        first.build_id
    );
}
