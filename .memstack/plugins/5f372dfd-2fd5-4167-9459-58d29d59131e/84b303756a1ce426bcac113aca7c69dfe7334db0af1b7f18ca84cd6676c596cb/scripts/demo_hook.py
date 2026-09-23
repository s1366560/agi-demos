"""Credential-free lifecycle hook example. Never writes to the user's workspace."""

import json
import sys

payload = json.load(sys.stdin)
print(json.dumps({"event": payload.get("event"), "status": "ok"}))
