#!/usr/bin/env bash
# Enforce that scripts resolve the environment only via scripts/utils/with-env.sh.
# Fails when a shell script under scripts/ sources a dotenv directly or defaults
# a tenant knob to a concrete value.
#
# Usage:
#   check_env_resolution.sh [file ...]   # files default to all scripts/**/*.sh
# Pre-commit passes the staged *.sh paths; a bare run scans the whole tree.

set -euo pipefail

# with-env.sh (the loader), with-env.local.sh (sources env.d/<env>.env), and this
# guard (which names the patterns it bans) may contain a dotenv read literally.
ALLOW_RE='scripts/utils/(with-env(\.local)?|check_env_resolution)\.sh$'

# Direct dotenv load: `source <x>.env`, `. <x>.env`, `source ".../.env"`.
SOURCE_RE='(^|[[:space:]])(source|\.)[[:space:]]+[^[:space:]]*\.env([[:space:]]|"|$)'

# Tenant knob with a concrete default: ${ENVIRONMENT:-dev}, etc. The char after
# `:-` must be non-empty and non-space, so the bare ${VAR:-} nounset guard is
# not flagged.
DEFAULT_RE='\$\{(ENVIRONMENT|PROJECT_NAME|AWS_REGION):-[^}[:space:]]'

if [ "$#" -gt 0 ]; then
  files=("$@")
else
  files=()
  while IFS= read -r _f; do files+=("$_f"); done \
    < <(find scripts -name '*.sh' -type f | sort)
fi

status=0
for f in "${files[@]}"; do
  case "$f" in *.sh) ;; *) continue ;; esac
  [[ "$f" =~ $ALLOW_RE ]] && continue
  [ -f "$f" ] || continue

  while IFS= read -r match; do
    lineno=${match%%:*}
    content=${match#*:}
    trimmed=${content#"${content%%[![:space:]]*}"}
    case "$trimmed" in '#'*) continue ;; esac   # skip comment-only lines
    status=1
    echo "✗ ${f}:${lineno}: ${trimmed}"
  done < <(grep -nE "${SOURCE_RE}|${DEFAULT_RE}" "$f" || true)
done

if [ "$status" -ne 0 ]; then
  cat >&2 <<'EOF'

❌ Scripts must resolve the environment via scripts/utils/with-env.sh.
   Do not `source .env` by hand and do not default the tenant knobs to a
   concrete value (${ENVIRONMENT:-dev}). Source the one helper instead:

       source scripts/utils/with-env.sh

   It loads .env (a per-command override wins over the file) and account-guards.
EOF
  exit 1
fi
