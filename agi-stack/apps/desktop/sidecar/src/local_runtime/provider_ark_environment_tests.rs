use super::*;

#[test]
fn ark_environment_keys_are_bound_to_the_explicit_protocol_and_official_destination() {
    for variable in ["ARK_API_KEY", "VOLCENGINE_API_KEY"] {
        for endpoint in [
            "https://ark.cn-beijing.volces.com/api/v3",
            "https://ark.cn-beijing.volces.com:443/api/v3/",
        ] {
            assert_eq!(
                normalized_provider_environment_variable("openai_compatible", endpoint, variable)
                    .unwrap(),
                variable,
            );
        }
        for endpoint in [
            "http://ark.cn-beijing.volces.com/api/v3",
            "https://ark.cn-beijing.volces.com:444/api/v3",
            "https://ark.cn-beijing.volces.com.attacker.test/api/v3",
            "https://other.ark.cn-beijing.volces.com/api/v3",
            "https://api.kimi.com/coding/v1",
            "https://ark.cn-beijing.volces.com/v1",
            "https://ark.cn-beijing.volces.com/api/v3/other",
            "https://ark.cn-beijing.volces.com/api%2Fv3",
            "https://user@ark.cn-beijing.volces.com/api/v3",
            "https://ark.cn-beijing.volces.com/api/v3?key=other",
            "https://ark.cn-beijing.volces.com/api/v3#other",
            "http://127.0.0.1:8000/api/v3",
        ] {
            assert!(
                normalized_provider_environment_variable("openai_compatible", endpoint, variable)
                    .is_err(),
                "{endpoint}"
            );
        }
        for provider in ["openai", "anthropic", "volcengine"] {
            assert!(normalized_provider_environment_variable(
                provider,
                "https://ark.cn-beijing.volces.com/api/v3",
                variable
            )
            .is_err());
        }
    }
    for variable in [
        "KIMI_API_KEY",
        "OPENAI_API_KEY",
        "PATH",
        "CUSTOM_ARK_API_KEY",
    ] {
        assert!(normalized_provider_environment_variable(
            "openai_compatible",
            "https://ark.cn-beijing.volces.com/api/v3",
            variable
        )
        .is_err());
    }
}
