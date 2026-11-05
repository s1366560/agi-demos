use super::*;
use rusqlite::Connection;

fn owner() -> Owner {
    Owner {
        user_id: "user".into(),
        tenant_id: "tenant".into(),
        project_id: "project".into(),
        device_id: "device".into(),
    }
}
fn session() -> Session {
    Session {
        owner: owner(),
        audio_session_id: uuid::Uuid::new_v4().to_string(),
        generation: 1,
        mode: "meeting".into(),
        source: "mixed".into(),
        state: "recording".into(),
        started_at: chrono::Utc::now().to_rfc3339(),
        captured_ms: 30_000,
        max_duration_ms: 28_800_000,
        segments: vec![],
        transcript: vec![],
        summary: None,
        provider_profile_id: Some("speech-profile".into()),
        sync_audio: false,
        private_root: Some("/private/meeting".into()),
        error_code: None,
    }
}

#[test]
fn meetings_are_owner_bound_and_old_generations_cannot_replace_current() {
    let db = Connection::open_in_memory().unwrap();
    store::initialize(&db).unwrap();
    let mut first = session();
    store::save(&db, &first).unwrap();
    let old = first.clone();
    first.generation = 2;
    store::save(&db, &first).unwrap();
    assert!(store::save(&db, &old).is_err());
    let mut foreign = owner();
    foreign.user_id = "foreign".into();
    assert!(store::get(&db, &foreign, &first.audio_session_id).is_err());
    assert!(store::list(&db, &foreign).unwrap().is_empty());
}
#[test]
fn restart_retains_segments_and_requires_explicit_resume_without_recapture() {
    let db = Connection::open_in_memory().unwrap();
    store::initialize(&db).unwrap();
    let mut original = session();
    original.segments = vec![
        json!({"segment_id":"1:microphone:0","url":"file:///private/meeting/0.wav","path":"/private/meeting/0.wav"}),
    ];
    store::save(&db, &original).unwrap();
    store::recover(&db).unwrap();
    let restored = store::get(&db, &owner(), &original.audio_session_id).unwrap();
    assert_eq!(restored.state, "interrupted");
    assert_eq!(restored.segments, original.segments);
    assert_eq!(restored.generation, 1);
    assert!(!restored.sync_audio);
    assert!(!restored.public().to_string().contains("/private/meeting"));
}
#[test]
fn speech_jobs_are_segment_scoped_and_idempotent() {
    let db = Connection::open_in_memory().unwrap();
    store::initialize(&db).unwrap();
    let row = session();
    store::save(&db, &row).unwrap();
    let segment = json!({"segment_id":"1:system:0"});
    store::enqueue(&db, &row, &segment).unwrap();
    store::enqueue(&db, &row, &segment).unwrap();
    let count: i64 = db
        .query_row("SELECT count(*) FROM desktop_speech_jobs_v1", [], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(count, 1);
}
