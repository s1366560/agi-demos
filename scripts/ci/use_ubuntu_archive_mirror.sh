#!/usr/bin/env bash
# GitHub-hosted Ubuntu lists azure.archive.ubuntu.com first. When that name
# does not resolve, apt retries it until the job timeout, and Playwright
# --with-deps exits before any browser test runs. Point apt at the public
# archive instead. Package installation still has to succeed.
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "ubuntu archive mirror: not linux"
  exit 0
fi

rewrite() {
  local path="$1"
  sudo sed -i \
    -e 's|https://azure.archive.ubuntu.com/ubuntu/|http://archive.ubuntu.com/ubuntu/|g' \
    -e 's|http://azure.archive.ubuntu.com/ubuntu/|http://archive.ubuntu.com/ubuntu/|g' \
    "$path"
}

if [[ -f /etc/apt/apt-mirrors.txt ]]; then
  rewrite /etc/apt/apt-mirrors.txt
  echo "ubuntu archive mirror: $(tr '\n' ' ' < /etc/apt/apt-mirrors.txt)"
else
  echo "ubuntu archive mirror: apt-mirrors.txt absent"
fi

if [[ -f /etc/apt/sources.list ]]; then
  rewrite /etc/apt/sources.list
fi

shopt -s nullglob
for path in /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  rewrite "$path"
done
