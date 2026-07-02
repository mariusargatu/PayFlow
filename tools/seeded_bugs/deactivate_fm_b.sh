#!/usr/bin/env bash
# Deactivate seeded bug FM-B: remove the admin module from the importable tree.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

rm -f "${repo_root}/payflow/api/admin.py"
echo "FM-B deactivated: payflow/api/admin.py removed."
