#!/bin/sh
# PreToolUse hook (matcher: Bash) — block obvious writes to BEHAVIOR.md.
# The Edit/Write/NotebookEdit tools are already denied via permissions.deny.
# This closes the Bash escape route. Best-effort: pattern-based, not foolproof.

cmd=$(jq -r '.tool_input.command // ""' 2>/dev/null)

# Fast path: command does not mention BEHAVIOR.md.
case "$cmd" in
  *BEHAVIOR.md*) ;;
  *) exit 0 ;;
esac

# Mentions BEHAVIOR.md. Block if it looks like a write/delete/rename/permission change.
if printf '%s' "$cmd" | grep -qE '(>>?|sed[[:space:]]+-i|tee[[:space:]]| rm | mv | cp |^rm |^mv |^cp |chmod|chown|truncate|dd[[:space:]]+.*of=)'; then
  cat >&2 <<'MSG'
Blocked by /init_custom: BEHAVIOR.md is read-only.
To change behavior rules, edit BEHAVIOR.md manually from a terminal outside this Claude session.
MSG
  exit 2
fi

exit 0
