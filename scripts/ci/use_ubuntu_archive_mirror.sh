#!/usr/bin/env bash
# GitHub-hosted Ubuntu reads /etc/apt/apt-mirrors.txt. On 2026-11-11 Canonical
# DNS stopped resolving ubuntu.com, so azure.archive.ubuntu.com,
# archive.ubuntu.com, and security.ubuntu.com all failed. apt retried until
# the job cap and Playwright never reached a test. These mirrors are outside
# that zone. apt still verifies Ubuntu's signed InRelease; nothing is marked
# trusted.
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "ubuntu archive mirror: not linux"
  exit 0
fi

if [[ ! -f /etc/apt/apt-mirrors.txt ]]; then
  echo "ubuntu archive mirror: apt-mirrors.txt absent" >&2
  exit 1
fi

sudo tee /etc/apt/apt-mirrors.txt >/dev/null <<'EOF'
http://mirror.math.princeton.edu/pub/ubuntu/	priority:1
http://mirror.us.leaseweb.net/ubuntu/	priority:2
http://ubuntu.osuosl.org/ubuntu/	priority:3
EOF

sudo tee /etc/apt/apt.conf.d/99-ci-mirror-failover >/dev/null <<'EOF'
Acquire::Retries "0";
Acquire::http::Timeout "15";
Acquire::https::Timeout "15";
EOF

echo "ubuntu archive mirror: $(tr '\n' ' ' < /etc/apt/apt-mirrors.txt)"
