#!/usr/bin/env bash
# Release driver: bump version, commit, tag, push.
# The push of the `v<version>` tag triggers .github/workflows/release.yml,
# which builds all five platform binaries, creates the GitHub Release,
# and updates the Homebrew tap at zoltanf/homebrew-mondo.
#
# Usage: scripts/release.sh <version> [--skip-tests]
# Example: scripts/release.sh 0.4.0

set -euo pipefail

SKIP_TESTS=0
VERSION=""
for arg in "$@"; do
    case "$arg" in
        --skip-tests) SKIP_TESTS=1 ;;
        -h|--help)
            sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        -*)
            echo "error: unknown flag: $arg" >&2
            exit 2
            ;;
        *)
            if [ -n "$VERSION" ]; then
                echo "error: version already set to '$VERSION', got extra arg '$arg'" >&2
                exit 2
            fi
            VERSION="$arg"
            ;;
    esac
done

if [ -z "$VERSION" ]; then
    echo "usage: scripts/release.sh <version> [--skip-tests]" >&2
    exit 2
fi

# Permissive semver: MAJOR.MINOR.PATCH with optional -prerelease (e.g. 0.4.0, 0.4.0-rc1, 1.2.3-beta.2).
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
    echo "error: '$VERSION' is not a valid semver (expected X.Y.Z or X.Y.Z-pre)" >&2
    exit 2
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# --- Pre-flight checks ---------------------------------------------------

if [ -n "$(git status --porcelain)" ]; then
    echo "error: working tree is not clean. Commit or stash first." >&2
    git status --short >&2
    exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
    echo "error: not on 'main' (on '$BRANCH'). Releases cut from main only." >&2
    exit 1
fi

echo "==> Fetching origin..."
git fetch --quiet origin main

LOCAL="$(git rev-parse @)"
REMOTE="$(git rev-parse @{u})"
if [ "$LOCAL" != "$REMOTE" ]; then
    echo "error: local main is not in sync with origin/main." >&2
    echo "  local:  $LOCAL" >&2
    echo "  remote: $REMOTE" >&2
    exit 1
fi

TAG="v$VERSION"
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "error: tag $TAG already exists." >&2
    exit 1
fi

# --- Bump version ---------------------------------------------------------

VERSION_FILE="src/mondo/version.py"
PYPROJECT="pyproject.toml"

# If anything between here and the commit step fails, revert the file edits
# so the working tree ends up clean (otherwise a re-run would fail the clean-
# tree precheck and the user would be stuck doing `git checkout --` manually).
cleanup_on_error() {
    echo "==> Release aborted — restoring $VERSION_FILE and $PYPROJECT" >&2
    git checkout -- "$VERSION_FILE" "$PYPROJECT" 2>/dev/null || true
}
trap cleanup_on_error ERR


echo "==> Writing $VERSION_FILE -> $VERSION"
printf '__version__ = "%s"\n' "$VERSION" > "$VERSION_FILE"

# Keep pyproject.toml in sync. The version line is the first `version = "..."`
# under [project].
python3 - "$VERSION" <<'PY'
import pathlib
import re
import sys

version = sys.argv[1]
path = pathlib.Path("pyproject.toml")
text = path.read_text()
new, n = re.subn(
    r'^version = "[^"]+"',
    f'version = "{version}"',
    text,
    count=1,
    flags=re.MULTILINE,
)
if n != 1:
    sys.exit(f"error: could not find version line in {path}")
path.write_text(new)
PY

# --- Refresh lockfile + tests --------------------------------------------

echo "==> uv sync --all-extras"
uv sync --all-extras --quiet

if [ "$SKIP_TESTS" -eq 0 ]; then
    echo "==> uv run python -m pytest -m 'not integration'"
    uv run python -m pytest -m "not integration"
else
    echo "==> skipping tests (--skip-tests)"
fi

# --- Commit, tag, push ----------------------------------------------------

git add "$VERSION_FILE" "$PYPROJECT" uv.lock 2>/dev/null || git add "$VERSION_FILE" "$PYPROJECT"
git commit -m "chore(release): $TAG"
git tag -a "$TAG" -m "$TAG"

# Past this point, a `git checkout` would be the wrong recovery — the edits
# are already committed. Disable the rollback trap.
trap - ERR

echo "==> Pushing main and $TAG to origin..."
if ! git push origin main "$TAG"; then
    cat >&2 <<EOF

error: push failed. The commit and tag $TAG were created locally but not
pushed. Once the network / remote issue is fixed, finish the release with:

    git push origin main $TAG

Or, to undo locally:

    git tag -d $TAG
    git reset --hard HEAD~1
EOF
    exit 1
fi

# --- Done -----------------------------------------------------------------

REMOTE_URL="$(git remote get-url origin)"
# Normalize SSH or HTTPS git URL to https://github.com/<owner>/<repo>
SLUG="$(echo "$REMOTE_URL" | sed -E 's#(git@github\.com:|https?://github\.com/)##; s#\.git$##')"
ACTIONS_URL="https://github.com/$SLUG/actions"

cat <<EOF

Released $TAG.
Watch the build: $ACTIONS_URL
Release page:    https://github.com/$SLUG/releases/tag/$TAG
EOF
