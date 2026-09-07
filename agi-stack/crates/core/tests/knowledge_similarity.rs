use agistack_core::knowledge::{
    index::{IndexSource, IndexedVector},
    processing::ProcessingSource,
    similarity::rank_index_vectors,
};

fn candidate(id: &str, sequence: u64, vector: Vec<f32>) -> IndexedVector {
    IndexedVector {
        input: IndexSource {
            source: ProcessingSource {
                tenant_id: "tenant".into(),
                project_id: "project".into(),
                memory_id: id.into(),
                revision: 1,
                change_sequence: sequence,
            },
            audit_attempt: 1,
            input_digest: "a".repeat(64),
        },
        vector,
    }
}

#[test]
fn ranks_by_angle_without_a_relevance_threshold() {
    let input = vec![
        candidate("opposite", 1, vec![-2.0, 0.0]),
        candidate("orthogonal", 2, vec![0.0, 3.0]),
        candidate("same", 3, vec![8.0, 0.0]),
        candidate("diagonal", 4, vec![1.0, 1.0]),
    ];
    let result = rank_index_vectors(&[2.0, 0.0], &input).unwrap();
    assert_eq!(
        result
            .iter()
            .map(|r| r.input.source.memory_id.as_str())
            .collect::<Vec<_>>(),
        ["same", "diagonal", "orthogonal", "opposite"]
    );
    for (actual, expected) in result
        .iter()
        .map(|r| r.score)
        .zip([1.0, 0.5_f64.sqrt(), 0.0, -1.0])
    {
        assert!((actual - expected).abs() < 1e-14);
    }
    assert_eq!(result[0].input, input[2].input);
}

#[test]
fn keeps_extreme_and_subnormal_f32_vectors_finite() {
    for scale in [f32::MAX, f32::MIN_POSITIVE, f32::from_bits(1)] {
        let input = [candidate("same", 1, vec![scale, scale])];
        let result = rank_index_vectors(&[scale, scale], &input).unwrap();
        assert!(result[0].score.is_finite());
        assert!((result[0].score - 1.0).abs() < 1e-14);
        assert!(result[0].score <= 1.0);
    }
}

#[test]
fn rejects_invalid_query_even_without_candidates() {
    for query in [
        vec![],
        vec![0.0, -0.0],
        vec![f32::NAN],
        vec![f32::INFINITY],
        vec![f32::NEG_INFINITY],
    ] {
        assert!(rank_index_vectors(&query, &[]).is_err());
    }
    assert!(rank_index_vectors(&[1.0], &[]).unwrap().is_empty());
}

#[test]
fn rejects_the_entire_batch_if_any_candidate_is_invalid() {
    for invalid in [
        vec![],
        vec![1.0],
        vec![0.0, 0.0],
        vec![f32::NAN, 1.0],
        vec![1.0, f32::INFINITY],
    ] {
        let input = [
            candidate("valid", 1, vec![1.0, 0.0]),
            candidate("invalid", 2, invalid),
        ];
        assert!(rank_index_vectors(&[1.0, 0.0], &input).is_err());
    }
}

#[test]
fn tie_order_is_independent_of_input_order_and_signed_zero() {
    let mut input = vec![
        candidate("b", 2, vec![0.0, 1.0]),
        candidate("a", 2, vec![-0.0, 1.0]),
        candidate("c", 1, vec![0.0, 1.0]),
    ];
    let first = rank_index_vectors(&[1.0, 0.0], &input).unwrap();
    input.reverse();
    assert_eq!(first, rank_index_vectors(&[1.0, 0.0], &input).unwrap());
    assert_eq!(
        first
            .iter()
            .map(|r| r.input.source.memory_id.as_str())
            .collect::<Vec<_>>(),
        ["c", "a", "b"]
    );
}

#[test]
fn refuses_to_mix_project_or_tenant_vectors() {
    for cross_tenant in [false, true] {
        let first = candidate("first", 1, vec![1.0]);
        let mut second = candidate("second", 2, vec![1.0]);
        if cross_tenant {
            second.input.source.tenant_id = "other".into();
        } else {
            second.input.source.project_id = "other".into();
        }
        assert!(rank_index_vectors(&[1.0], &[first, second]).is_err());
    }
}
