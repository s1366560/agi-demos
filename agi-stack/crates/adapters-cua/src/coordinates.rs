//! Coordinate conversion is arithmetic over the exact, scoped native observation.
use crate::client::CuaCallContext;
use agistack_core::{CoreError, CoreResult};
use serde_json::{Value, json};

#[derive(Clone, Debug)]
pub(crate) struct ObservationCoordinates {
    pub context: CuaCallContext,
    pub snapshot: String,
    pub window: String,
    app: String,
    requested_app: String,
    bounds: Option<(f64, f64)>,
    image: Option<(u32, u32)>,
}
fn invalid(reason: &str) -> CoreError {
    let hint = if matches!(reason, "snapshot_stale" | "snapshot_window_mismatch") {
        ": call computer_get_app_state again and use its fresh snapshot_id and window_id"
    } else {
        ""
    };
    CoreError::Tool(format!("cua_{reason}{hint}"))
}
impl ObservationCoordinates {
    pub fn new(
        context: CuaCallContext,
        requested_app: &str,
        result: &Value,
        image: Option<(u32, u32)>,
    ) -> CoreResult<Self> {
        let required = |field| {
            result[field]
                .as_str()
                .filter(|v| !v.is_empty())
                .map(str::to_owned)
                .ok_or_else(|| invalid("observation_identity_missing"))
        };
        let raw = result.get("window_bounds").or_else(|| result.get("bounds"));
        let bounds = raw
            .and_then(|bounds| bounds["width"].as_f64().zip(bounds["height"].as_f64()))
            .filter(|(w, h)| {
                w.is_finite()
                    && h.is_finite()
                    && *w > 0.0
                    && *h > 0.0
                    && *w <= 1_000_000.0
                    && *h <= 1_000_000.0
            });
        Ok(Self {
            context,
            snapshot: required("snapshot_id")?,
            window: required("window_id")?,
            app: result["app"].as_str().unwrap_or(requested_app).to_owned(),
            requested_app: requested_app.into(),
            bounds,
            image,
        })
    }
    pub fn declaration(&self) -> Value {
        let mut value =
            json!({"default":"window","window_id":self.window,"snapshot_id":self.snapshot});
        if let Some((width, height)) = self.bounds {
            value["window"] = json!({"width":width,"height":height,"origin":"top_left_of_window"});
        }
        if let Some((width, height)) = self.image {
            value["screenshot"] =
                json!({"width":width,"height":height,"unit":"pixel","origin":"top_left_of_image"});
        }
        value
    }
    pub fn transform(&self, context: &CuaCallContext, params: &mut Value) -> CoreResult<()> {
        if &self.context != context {
            return Err(invalid("snapshot_scope_mismatch"));
        }
        if params["snapshot_id"].as_str() != Some(self.snapshot.as_str()) {
            return Err(invalid("snapshot_stale"));
        }
        let app = params["app"]
            .as_str()
            .ok_or_else(|| invalid("snapshot_app_missing"))?;
        if app != self.app && app != self.requested_app {
            return Err(invalid("snapshot_app_mismatch"));
        }
        if params["window_id"]
            .as_str()
            .is_some_and(|window| window != self.window)
        {
            return Err(invalid("snapshot_window_mismatch"));
        }
        params["window_id"] = json!(self.window);
        let action = params["action"]
            .as_object_mut()
            .ok_or_else(|| invalid("invalid_action"))?;
        let space = action
            .remove("coordinate_space")
            .and_then(|space| space.as_str().map(str::to_owned))
            .unwrap_or_else(|| "window".into());
        if !matches!(space.as_str(), "window" | "screenshot") {
            return Err(invalid("coordinate_space_invalid"));
        }
        for (x_key, y_key) in [("x", "y"), ("from_x", "from_y"), ("to_x", "to_y")] {
            if !action.contains_key(x_key) && !action.contains_key(y_key) {
                continue;
            }
            let x = action
                .get(x_key)
                .and_then(Value::as_f64)
                .ok_or_else(|| invalid("coordinates_incomplete"))?;
            let y = action
                .get(y_key)
                .and_then(Value::as_f64)
                .ok_or_else(|| invalid("coordinates_incomplete"))?;
            let (window_width, window_height) = self
                .bounds
                .ok_or_else(|| invalid("window_geometry_missing"))?;
            let (width, height) = if space == "screenshot" {
                let (width, height) = self
                    .image
                    .ok_or_else(|| invalid("screenshot_coordinates_unavailable"))?;
                (width as f64, height as f64)
            } else {
                (window_width, window_height)
            };
            if !x.is_finite() || !y.is_finite() || x < 0.0 || y < 0.0 || x >= width || y >= height {
                return Err(invalid("coordinate_outside_observation"));
            }
            action.insert(x_key.into(), json!(x * window_width / width));
            action.insert(y_key.into(), json!(y * window_height / height));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn context() -> CuaCallContext {
        CuaCallContext {
            user_id: "u".into(),
            tenant_id: "t".into(),
            project_id: "p".into(),
            device_id: "d".into(),
            conversation_id: "c".into(),
            run_id: "r".into(),
            session_id: "s".into(),
        }
    }
    fn observation(width: f64, height: f64, pixels: (u32, u32)) -> ObservationCoordinates {
        ObservationCoordinates::new(context(),"pid:1",&json!({"app":"native-app","snapshot_id":"observation","window_id":"window","window_bounds":{"x":100,"y":200,"width":width,"height":height}}),Some(pixels)).unwrap()
    }
    fn action(space: &str) -> Value {
        json!({"app":"pid:1","snapshot_id":"observation","action":{"kind":"drag","coordinate_space":space,"from_x":400,"from_y":200,"to_x":800,"to_y":600}})
    }
    #[test]
    fn retina_screenshot_maps_to_window_points_without_global_origin() {
        let mut params = action("screenshot");
        observation(500.0, 400.0, (1000, 800))
            .transform(&context(), &mut params)
            .unwrap();
        assert_eq!(params["action"]["from_x"], json!(200.0));
        assert_eq!(params["action"]["to_y"], json!(300.0));
        assert_eq!(params["window_id"], json!("window"));
        assert!(params["action"].get("coordinate_space").is_none());
    }
    #[test]
    fn resized_observation_uses_its_own_actual_dimensions() {
        let mut params = action("screenshot");
        observation(250.0, 200.0, (1000, 800))
            .transform(&context(), &mut params)
            .unwrap();
        assert_eq!(params["action"]["from_x"], json!(100.0));
        assert_eq!(params["action"]["to_y"], json!(150.0));
    }
    #[test]
    fn default_window_space_and_identity_boundaries_are_exact() {
        let record = observation(1000.0, 800.0, (2000, 1600));
        let mut params = action("window");
        record.transform(&context(), &mut params).unwrap();
        assert_eq!(params["action"]["from_x"], json!(400.0));
        for (field, value) in [
            ("snapshot_id", "other"),
            ("window_id", "other"),
            ("app", "other"),
        ] {
            let mut params = action("window");
            params[field] = json!(value);
            assert!(record.transform(&context(), &mut params).is_err());
        }
        let mut other = context();
        other.device_id = "other".into();
        assert!(record.transform(&other, &mut action("window")).is_err());
    }
    #[test]
    fn image_edges_and_missing_geometry_fail_closed() {
        let record = observation(1000.0, 800.0, (2000, 1600));
        let mut params = action("screenshot");
        params["action"]["from_x"] = json!(2000);
        assert!(record.transform(&context(), &mut params).is_err());
        let mut no_image = record.clone();
        no_image.image = None;
        assert!(
            no_image
                .transform(&context(), &mut action("screenshot"))
                .is_err()
        );
    }
}
