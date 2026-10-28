---
ward:
  workflow: pull-request-and-merge
---
# Agent instructions

Repo-local subset. Full operating context for Kai lives in `coilysiren/agentic-os-kai/AGENTS.md`.

## Scope

MCP server for the Lunch Money personal-finance API. Containerized, served over streamable HTTP, and packaged with a generic Helm chart. Fleet deployment is handled from `coilyco-bridge/deploy`.

## Project shape

- `lunch_money_mcp/` - Python package, the MCP server itself.
- `Dockerfile` - image build for the MCP server.
- `chart/` - generic Helm chart for standalone Kubernetes installs.
- `examples/` - example values for chart consumers.
- `scripts/categorize.py` - auto-categorization driver.
- `docs/` - flat documentation (chart, deploy, FEATURES).

## Repo boundaries

This repo owns the MCP server source, image build, generic Helm chart, and auto-categorization script. Fleet-specific values, secrets, exposure, and rollout stay in `coilyco-bridge/deploy`. The Lunch Money API and its v1/v2 shape live upstream and are not maintained here.

## Commands

Route every dev command through the [`justfile`](justfile) (run verbs with `just <verb>`).

## Validation

Pre-commit suite shipped from `coilysiren/agentic-os` plus local mypy and ruff hooks. Run via `pre-commit run --all-files`. CI mirrors the same gates.

## Safety

Never commit a real `rules.yaml` or LUNCH_MONEY_TOKEN. Token lives in a Kubernetes Secret or environment variable.

## Cross-repo contracts

The generic chart defaults to `docker.io/coilysiren/lunch-money-k8s`. Forgejo
CI publishes the private single-architecture fleet image as
`forgejo.coilysiren.me/coilyco-flight-deck/lunch-money-mcp:<full-source-sha>`.
The trusted deploy runner owns the write credential and verifies the remote
manifest. `coilyco-bridge/deploy/services/lunch-money-mcp/` consumes that exact
reference through a separate read-only credential and owns its rollout.

## Release

Every push to `main` runs tests, validates the Helm chart, and publishes one
source-SHA fleet image to Forgejo OCI. Chart behavior changes bump
`chart/Chart.yaml` in the same commit. Fleet deploy changes land in the deploy
repo, not here.

## Agent rules

<!-- BEGIN managed by agentic-os/scripts/apply-git-workflow.py -->
### Git workflow

**This repo runs the `pull-request-and-merge` lane**, declared as `ward.workflow` in this file's frontmatter. The agent commits to a task branch, pushes it, opens a Forgejo pull request, and **merges that pull request itself** once it is green. The author of the code is the one who merges it. Opening the pull request is a step, never the stopping point.

The fleet runs two lanes, and both authorize the same core actions:

* `merge-remote-main` - the agent commits, pushes to `main`, and closes the issue. No branch and no pull request.
* `pull-request-and-merge` - the agent commits to a task branch, pushes it, opens a pull request, and merges that pull request itself once it is green.

**Every lane slug names what the AGENT does, never what someone else does.** `pull-request-and-merge` carries the merge because the agent that authored the code merges its own pull request. `pull-request` drops `-and-merge` because the author stops at the pull request and the director merge lane takes over. Reading `pull-request-and-merge` as "someone else merges it later" inverts the two lanes and leaves finished work sitting unmerged.

**These actions are pre-authorized on every lane, and the agent MUST take them without asking first.** Committing, creating a branch, pushing a branch, pushing the lane's own destination, and opening a pull request are ordinary reversible work, not the destructive wall that earns a question. Stopping to ask is how a turn ends with the work stranded in a dirty worktree.

* **ALWAYS commit** in-scope work and **ALWAYS push** it to the canonical remote before pausing, reporting a checkpoint, handing off, or ending a turn. A local-only commit is not a checkpoint.
* **ALWAYS open the pull request** in the same turn as the branch's first push, on every lane except `remote-branch-only`. A pushed branch with no pull request is litter nobody reviews.
* **NEVER `--no-verify`** and **NEVER force-push**. Those two are the real walls, and they stay closed.
* **ALWAYS merge your own pull request on `pull-request-and-merge`**, in the same turn, as soon as it is green. Reporting it as open and awaiting someone is the failure this lane exists to prevent.
* **NEVER merge on `pull-request` or `remote-branch-only`.** Those two stop where they stop, and the director merge lane carries a `pull-request` from there.
<!-- END managed by agentic-os/scripts/apply-git-workflow.py -->

Commit to `main`, push after each commit. Every commit closes a same-repo issue with `closes #N`. Conventional Commits subject format. The commit-msg hooks enforce both.

## Checkout residency

This repo is not in Agent Compose's `repository-plan.yaml`, so it has no
resident checkout under `~/projects/<owner>/`. That is intentional. Work it
from a task-scoped temporary clone, and remove that clone once the work lands.

A temporary root can be purged at any time, so commit and push before pausing,
switching tasks, or ending a session. The remote is the only durable artifact.

## See also

- [README.md](README.md) - human-facing intro and quick start.
- [docs/FEATURES.md](docs/FEATURES.md) - inventory of what ships today.
- [justfile](justfile) - dev verbs (`just <verb>`).
- [.ward/ward.yaml](.ward/ward.yaml) - catalog metadata only.

Cross-reference convention from [coilysiren/agentic-os-kai#313](https://github.com/coilyco-bridge/agentic-os-kai/issues/313).
