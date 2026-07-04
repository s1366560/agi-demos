use super::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum SkillEvolutionPublishMode {
    Review,
    Direct,
}

impl SkillEvolutionPublishMode {
    pub(super) fn parse(raw: &str) -> Option<Self> {
        match raw {
            "review" => Some(Self::Review),
            "direct" => Some(Self::Direct),
            _ => None,
        }
    }

    pub(super) fn as_str(self) -> &'static str {
        match self {
            Self::Review => "review",
            Self::Direct => "direct",
        }
    }
}

#[derive(Debug, Clone)]
pub(super) struct SkillEvolutionConfig {
    pub(super) enabled: bool,
    pub(super) min_sessions_per_skill: i64,
    pub(super) scoring_min_sessions_per_skill: i64,
    pub(super) min_avg_score: f64,
    pub(super) max_sessions_per_batch: i64,
    pub(super) evolution_interval_minutes: i64,
    pub(super) publish_mode: SkillEvolutionPublishMode,
    pub(super) auto_apply: bool,
}

impl SkillEvolutionConfig {
    pub(super) fn from_env() -> Self {
        Self {
            enabled: env_bool("SKILL_EVOLUTION_ENABLED", true),
            min_sessions_per_skill: env_i64("SKILL_EVOLUTION_MIN_SESSIONS", 5),
            scoring_min_sessions_per_skill: env_i64("SKILL_EVOLUTION_SCORING_MIN_SESSIONS", 5),
            min_avg_score: env_f64("SKILL_EVOLUTION_MIN_AVG_SCORE", 0.6),
            max_sessions_per_batch: env_i64("SKILL_EVOLUTION_MAX_SESSIONS_PER_BATCH", 50),
            evolution_interval_minutes: env_i64("SKILL_EVOLUTION_INTERVAL_MINUTES", 60),
            publish_mode: std::env::var("SKILL_EVOLUTION_PUBLISH_MODE")
                .ok()
                .and_then(|value| SkillEvolutionPublishMode::parse(value.as_str()))
                .unwrap_or(SkillEvolutionPublishMode::Review),
            auto_apply: env_bool("SKILL_EVOLUTION_AUTO_APPLY", false),
        }
    }

    pub(super) fn with_overrides(
        mut self,
        body: &SkillEvolutionConfigUpdatePayload,
    ) -> Result<Self, SkillApiError> {
        if let Some(value) = body.enabled {
            self.enabled = value;
        }
        if let Some(value) = body.min_sessions_per_skill {
            self.min_sessions_per_skill = value;
        }
        if let Some(value) = body.scoring_min_sessions_per_skill {
            self.scoring_min_sessions_per_skill = value;
        }
        if let Some(value) = body.min_avg_score {
            self.min_avg_score = value;
        }
        if let Some(value) = body.max_sessions_per_batch {
            self.max_sessions_per_batch = value;
        }
        if let Some(value) = body.evolution_interval_minutes {
            self.evolution_interval_minutes = value;
        }
        if let Some(mode) = body.publish_mode.as_deref() {
            self.publish_mode = SkillEvolutionPublishMode::parse(mode).ok_or_else(|| {
                SkillApiError::bad_request("Invalid skill evolution publish mode")
            })?;
        }
        if let Some(value) = body.auto_apply {
            self.auto_apply = value;
        }
        Ok(self)
    }

    pub(super) fn with_stored_overrides(mut self, value: &Value) -> Self {
        let Value::Object(map) = value else {
            return self;
        };
        if let Some(value) = stored_bool(map, "enabled") {
            self.enabled = value;
        }
        if let Some(value) = stored_i64(map, "min_sessions_per_skill") {
            self.min_sessions_per_skill = value.max(1);
        }
        if let Some(value) = stored_i64(map, "scoring_min_sessions_per_skill") {
            self.scoring_min_sessions_per_skill = value.max(1);
        }
        if let Some(value) = stored_f64(map, "min_avg_score") {
            self.min_avg_score = value.clamp(0.0, 1.0);
        }
        if let Some(value) = stored_i64(map, "max_sessions_per_batch") {
            self.max_sessions_per_batch = value.max(1);
        }
        if let Some(value) = stored_i64(map, "evolution_interval_minutes") {
            self.evolution_interval_minutes = value.max(1);
        }
        if let Some(mode) = map
            .get("publish_mode")
            .and_then(Value::as_str)
            .and_then(SkillEvolutionPublishMode::parse)
        {
            self.publish_mode = mode;
        }
        if let Some(value) = stored_bool(map, "auto_apply") {
            self.auto_apply = value;
        }
        self
    }
}

impl SkillEvolutionConfigUpdatePayload {
    pub(super) fn validate(&self) -> Result<(), SkillApiError> {
        validate_i64_bounds(self.min_sessions_per_skill, 1, 100)?;
        validate_i64_bounds(self.scoring_min_sessions_per_skill, 1, 100)?;
        validate_i64_bounds(self.max_sessions_per_batch, 1, 100)?;
        validate_i64_bounds(self.evolution_interval_minutes, 1, 10_080)?;
        if self
            .min_avg_score
            .is_some_and(|value| !(0.0..=1.0).contains(&value))
        {
            return Err(SkillApiError::unprocessable(
                "Invalid skill evolution config",
            ));
        }
        if self
            .publish_mode
            .as_deref()
            .is_some_and(|mode| SkillEvolutionPublishMode::parse(mode).is_none())
        {
            return Err(SkillApiError::bad_request(
                "Invalid skill evolution publish mode",
            ));
        }
        Ok(())
    }
}

fn validate_i64_bounds(value: Option<i64>, min: i64, max: i64) -> Result<(), SkillApiError> {
    if value.is_some_and(|value| value < min || value > max) {
        return Err(SkillApiError::unprocessable(
            "Invalid skill evolution config",
        ));
    }
    Ok(())
}

pub(super) fn validate_overview_limit(value: Option<i64>) -> Result<i64, SkillApiError> {
    match value {
        Some(value) if !(1..=200).contains(&value) => Err(SkillApiError::unprocessable(
            "Invalid skill evolution overview query",
        )),
        Some(value) => Ok(value),
        None => Ok(50),
    }
}

pub(super) fn validate_evolution_detail_limit(value: Option<i64>) -> Result<i64, SkillApiError> {
    match value {
        Some(value) if !(1..=100).contains(&value) => Err(SkillApiError::unprocessable(
            "Invalid skill evolution detail query",
        )),
        Some(value) => Ok(value),
        None => Ok(20),
    }
}

fn env_bool(name: &str, default: bool) -> bool {
    std::env::var(name)
        .map(|value| value.eq_ignore_ascii_case("true"))
        .unwrap_or(default)
}

fn env_i64(name: &str, default: i64) -> i64 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<i64>().ok())
        .unwrap_or(default)
}

fn env_f64(name: &str, default: f64) -> f64 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<f64>().ok())
        .unwrap_or(default)
}

fn stored_bool(map: &Map<String, Value>, key: &str) -> Option<bool> {
    map.get(key).and_then(|value| match value {
        Value::Bool(value) => Some(*value),
        Value::Number(value) => value.as_i64().map(|value| value != 0),
        Value::String(value) => Some(value.eq_ignore_ascii_case("true")),
        _ => None,
    })
}

fn stored_i64(map: &Map<String, Value>, key: &str) -> Option<i64> {
    map.get(key).and_then(|value| match value {
        Value::Number(value) => value
            .as_i64()
            .or_else(|| value.as_f64().map(|value| value as i64)),
        Value::String(value) => value.parse::<i64>().ok(),
        Value::Bool(value) => Some(i64::from(u8::from(*value))),
        _ => None,
    })
}

fn stored_f64(map: &Map<String, Value>, key: &str) -> Option<f64> {
    map.get(key).and_then(|value| match value {
        Value::Number(value) => value.as_f64(),
        Value::String(value) => value.parse::<f64>().ok(),
        Value::Bool(value) => Some(f64::from(u8::from(*value))),
        _ => None,
    })
}
