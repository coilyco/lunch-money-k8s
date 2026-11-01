# Per-repo task manifest. Run `just` (or `just --list`) to see every verb.
#
# Recipes take trailing arguments directly: `just <verb> a b`, where the
# retired form was `ward exec <verb> -- a b`.
#
# One line of comment per recipe on purpose: just reads only the LAST comment
# line above a recipe, so a wrapped description silently truncates to its tail.
#
# `ward exec` is retired. `.ward/ward.yaml` survives carrying catalog metadata
# only, because the catalog hooks upstream in agentic-os pin that exact path.

set positional-arguments

# Default target: list every available recipe.
default:
    @just --list --unsorted

# Install deps via uv.
sync *ARGS:
    @uv sync "$@"

# Import the server and list the registered MCP tools.
smoke *ARGS:
    @uv run python scripts/smoke.py "$@"

# Live read-only smoke test against the Lunch Money API.
verify *ARGS:
    @uv run python scripts/verify.py "$@"

# Print uncategorized transactions as TSV (id, date, amount, payee).
dump *ARGS:
    @uv run python scripts/dump.py "$@"

# Seed categories from rules.yaml, then auto-categorize transactions. Rerunnable.
categorize *ARGS:
    @uv run python scripts/categorize.py "$@"

# Run the pytest suite.
test *ARGS:
    @uv run pytest "$@"

# Lint + format check (no mutations).
ruff *ARGS:
    @bash scripts/ward-quality.sh check "$@"

# Apply ruff fixes and formatting in place.
fmt *ARGS:
    @bash scripts/ward-quality.sh format "$@"

# Run all pre-commit hooks against every file.
precommit *ARGS:
    @uv run pre-commit run --all-files "$@"

# Build the container image locally.
docker *ARGS:
    @docker build -t docker.io/coilysiren/lunch-money-k8s:dev . "$@"

# Validate the trusted GHCR publisher shell contract.
check-publish *ARGS:
    @bash -n scripts/publish-image.sh "$@"

# Lint the Helm chart.
helm-lint *ARGS:
    @bash scripts/ward-helm.sh lint "$@"

# Render the Helm chart with default and example values.
helm-template *ARGS:
    @bash scripts/ward-helm.sh template "$@"
