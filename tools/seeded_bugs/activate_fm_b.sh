#!/usr/bin/env bash
# Activate seeded bug FM-B: copy the quarantined admin module into the importable
# tree so Layer 0 (import-linter) can catch the api -> infrastructure violation.
# Never merge the result.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

cp "${script_dir}/fm_b_admin.py" "${repo_root}/payflow/api/admin.py"
echo "FM-B activated: payflow/api/admin.py created. Run: uv run lint-imports"
