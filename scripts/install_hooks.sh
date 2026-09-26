#!/usr/bin/env bash
# (Re)install this repo's git hooks. .git/hooks/ is not tracked by git, so
# hooks are lost on every fresh clone — re-run this after cloning, or any
# time a hook seems to be missing.
set -euo pipefail

hooks_dir="$(git rev-parse --show-toplevel)/.git/hooks"

cat > "$hooks_dir/commit-msg" <<'EOF'
#!/usr/bin/env bash
exec python3 "$(git rev-parse --show-toplevel)/scripts/check_commit_msg.py" "$1"
EOF

rm -f "$hooks_dir/pre-commit"  # the docstring check moved into commit-msg
chmod +x "$hooks_dir/commit-msg"
echo "Installed commit-msg hook -> $hooks_dir"
