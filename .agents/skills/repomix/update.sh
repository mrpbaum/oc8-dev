#!/usr/bin/env bash
# Refresh the generated OC8 Repomix packs bundled with this project skill.
#
# Usage:
#   .agents/skills/repomix/update.sh
#   CAPA=microsoft365 .agents/skills/repomix/update.sh
#   OC8_ROOT=/path/to/oc8 .agents/skills/repomix/update.sh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

find_repo_root() {
  local dir="$1"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/ARCHITECTURE.md" && -d "$dir/backend" && -d "$dir/frontend" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname -- "$dir")"
  done
  return 1
}

ROOT="${OC8_ROOT:-}"
if [[ -z "$ROOT" ]]; then
  ROOT="$(find_repo_root "$PWD" || find_repo_root "$SCRIPT_DIR" || true)"
fi
if [[ -z "$ROOT" || ! -f "$ROOT/ARCHITECTURE.md" || ! -d "$ROOT/backend" || ! -d "$ROOT/frontend" ]]; then
  echo "Could not find the oc8 repo root. Run from the repo, or set OC8_ROOT=/path/to/oc8." >&2
  exit 1
fi

cd "$ROOT"

if command -v repomix >/dev/null 2>&1; then
  REPOMIX=(repomix)
elif command -v npx >/dev/null 2>&1; then
  REPOMIX=(npx -y repomix)
else
  echo "Need repomix or npx on PATH." >&2
  exit 1
fi

OUT_DIR="$SCRIPT_DIR"
CONFIG="$SCRIPT_DIR/repomix.config.json"
DOT_IGNORE="$SCRIPT_DIR/.repomixignore"
if [[ ! -f "$CONFIG" ]]; then
  echo "Missing bundled Repomix config: $CONFIG" >&2
  exit 1
fi

# Avoid recursively packing this skill's generated context artifacts and helper files.
IGNORE_PATTERNS=(".agents/skills/repomix/**")
if [[ -s "$DOT_IGNORE" ]]; then
  while IFS= read -r pattern || [[ -n "$pattern" ]]; do
    [[ -z "$pattern" || "$pattern" =~ ^[[:space:]]*# ]] && continue
    IGNORE_PATTERNS+=("$pattern")
  done < "$DOT_IGNORE"
fi
GENERATED_IGNORE="$(IFS=,; echo "${IGNORE_PATTERNS[*]}")"

# First-party capa to pack when CAPA is unset. Keep this aligned with AI_CONTEXT_INDEX.md.
CAPA="${CAPA:-odoo_mcp}"
if [[ ! -d "capas/${CAPA}" ]]; then
  echo "Warning: capas/${CAPA} missing. Set CAPA=<folder> to a real capa." >&2
fi

pack() {
  local name="$1"
  shift
  local dest="${OUT_DIR}/${name}"
  echo "==> ${name}"
  "${REPOMIX[@]}" --quiet --config "$CONFIG" --ignore "$GENERATED_IGNORE" -o "$dest" "$@"
  echo "    wrote ${dest}"
}

# Comprehensive tree snapshot. Repomix also prints the token-count tree to stdout.
pack token-count-tree.xml --token-count-tree 1000

# Architecture / onboarding.
pack architecture-map.xml --include-full-directory-structure \
  --include "README.md,ARCHITECTURE.md,SECURITY.md,AGENTS.md,CONTRIBUTING.md,docs/**,docker-compose*.yml,.env.example,backend/pyproject.toml,backend/src/oc8/main.py,backend/src/oc8/config.py,backend/src/oc8/cli.py,backend/src/oc8/api/**,backend/src/oc8/capas/**,capas/README.md,frontend/src/lib/**,frontend/src/router.tsx,deploy/helm/oc8/values.yaml"

# Backend domain (approvals + seams).
pack backend.xml \
  --include "backend/src/oc8/approvals/**,backend/src/oc8/api/**,backend/src/oc8/authz/**,backend/src/oc8/runtime/intake.py,backend/src/oc8/runtime/queue.py,backend/src/oc8/channels/**,ARCHITECTURE.md"

# Frontend.
pack frontend.xml \
  --include "frontend/src/routes/**,frontend/src/components/**,frontend/src/lib/**,frontend/src/hooks/**,frontend/src/router.tsx,frontend/package.json"

# UI + API contract.
pack UI-API-contract.xml \
  --include "frontend/src/lib/**,frontend/src/hooks/**,frontend/src/routes/**,backend/src/oc8/api/**,backend/src/oc8/realtime/**,backend/src/oc8/schemas/**"

# One capa + loader.
pack capas.xml \
  --include "backend/src/oc8/capas/**,capas/README.md,capas/${CAPA}/**"

# Deploy.
pack deployment.xml \
  --include "docker-compose*.yml,.env.example,scripts/quickstart.sh,docs/DEPLOY.md,docs/GETTING_STARTED.md,deploy/helm/**,backend/docker/**"

# Refresh the compact discovery catalog used by AI_CONTEXT_INDEX.md.
python3 - "$OUT_DIR" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
packs = sorted(p for p in out_dir.glob('*.xml'))
file_re = re.compile(r'<file path="([^"]+)">\n(.*?)\n</file>', re.S)
symbol_re = re.compile(r'^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|const|let|var|interface|type)\s+([A-Za-z_][\w$]*)', re.M)
heading_re = re.compile(r'^(#{1,3})\s+(.+)$', re.M)
files = {}
pack_info = {}
for pack in packs:
    text = pack.read_text(errors='replace')
    matches = list(file_re.finditer(text))
    pack_info[pack.name] = {
        'bytes': pack.stat().st_size,
        'file_count': len(matches),
    }
    for match in matches:
        path, body = match.group(1), match.group(2)
        entry = files.setdefault(path, {
            'path': path,
            'packs': [],
            'lines': body.count('\n') + (1 if body else 0),
            'sha': hashlib.sha256(body.encode()).hexdigest()[:10],
            'kind': Path(path).suffix.lstrip('.') or 'noext',
            'symbols': [],
            'headings': [],
        })
        entry['packs'].append(pack.name)
        if not entry['symbols']:
            entry['symbols'] = list(dict.fromkeys(symbol_re.findall(body)))[:20]
        if not entry['headings']:
            entry['headings'] = [m.group(2).strip() for m in heading_re.finditer(body)][:20]

catalog = {
    'generated_from': [p.name for p in packs],
    'pack_info': pack_info,
    'files': [files[path] for path in sorted(files)],
}
(out_dir / 'file-catalog.json').write_text(json.dumps(catalog, indent=2) + '\n')
print(f"==> file-catalog.json ({len(catalog['files'])} unique files)")
PY

echo
echo "Done. Packs in ${OUT_DIR}:"
ls -lh "$OUT_DIR"/*.xml "$OUT_DIR/file-catalog.json"
