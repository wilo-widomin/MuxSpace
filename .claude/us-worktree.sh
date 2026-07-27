#!/usr/bin/env bash
# Prepara el worktree de una US del pipeline.
#
#   .claude/us-worktree.sh US-002 contrato-de-autenticacion
#
# Enlaza `backend/venv` y `frontend/node_modules` al repo principal en vez de
# reinstalarlos: un worktree es efímero y duplicarlos por historia son cientos
# de megas para nada. Ambos están en .gitignore también en su forma sin barra
# (US-001), así que los symlinks no ensucian `git status`.
set -euo pipefail

US="$1"          # US-002
SLUG="$2"        # contrato-de-autenticacion
REPO="$(git rev-parse --show-toplevel)"
WT="$REPO/.trees/$US"
RAMA="feature/$US-$SLUG"

if [ -d "$WT" ]; then
  echo "El worktree $WT ya existe: se reutiliza (política del pipeline)."
else
  git -C "$REPO" worktree add "$WT" -b "$RAMA"
fi

ln -sfn "$REPO/backend/venv" "$WT/backend/venv"
ln -sfn "$REPO/frontend/node_modules" "$WT/frontend/node_modules"

echo "--- worktree listo ---"
echo "rama:  $(git -C "$WT" branch --show-current)"
echo "base:  $(git -C "$WT" log --oneline -1)"
echo "estado: $(git -C "$WT" status --short | wc -l) archivos sin seguir/modificados"
"$WT/backend/venv/bin/python" -m pytest -q --collect-only 2>&1 | tail -1
