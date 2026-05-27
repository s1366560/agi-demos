# Drone Pipeline Plugin

This local plugin provides the `pipeline:drone` runtime provider and the
ordinary-chat `cicd_run_pipeline` tool.

Start the optional local Drone stack with:

```bash
make drone-up
```

Required runtime values follow the Drone CLI model. The plugin reads the Drone
server URL and personal access token from environment variables and passes them
to the `drone` executable as `DRONE_SERVER` and `DRONE_TOKEN`.

Workspace metadata remains compatible with the existing shape:

```json
{
  "delivery_cicd": {
    "provider": "drone",
    "drone": {
      "drone_server_env": "DRONE_SERVER",
      "drone_token_env": "DRONE_TOKEN",
      "poll_interval_seconds": 5
    }
  }
}
```

`server_url_env` remains accepted for older workspace metadata and falls back to
`DRONE_SERVER_URL` when present, but new plugin configuration should use
`drone_server_env`.
