# Features

What lunch-money-k8s ships today.

## MCP server

- Full Lunch Money API surface: user profile, transactions (list/get/insert/
  update/split/unsplit/groups), categories (CRUD and groups), tags, recurring
  items, budgets, manual assets, Plaid accounts and fetch, crypto.
- v1 and v2 API support, v1 by default, `LUNCH_MONEY_API_VERSION=v2` for the
  open alpha, `LUNCH_MONEY_API_BASE` to override the URL.
- stdio transport for local clients and streamable HTTP for a Kubernetes
  service, with env-driven host and origin allowlists against DNS rebinding.
- API client with 429 rate-limit backoff.
- Crashes, and only crashes, go to Sentry when `SENTRY_DSN` is set (`errors.py`).
- `scripts/categorize.py` seeds categories and assigns transactions by
  payee-prefix rules from a gitignored `rules.yaml`.

## Deployment

- Dockerfile building a slim uv-based image. GitHub Actions
  (`.github/workflows/build-publish.yml`) runs app tests, validates the Helm
  chart, and publishes the single-architecture fleet image as
  `ghcr.io/coilyco/lunch-money-mcp:<full-source-sha>` on every push to main.
  The publisher verifies the remote manifest.
- Generic Helm chart with a Deployment, Service, ServiceAccount, optional
  Secret, rules ConfigMap, Ingress, autoscaling, disruption budget, network
  policy, probes, and a connection test.
- Fleet deploy bundle in `coilyco-bridge/deploy/services/lunch-money-mcp/`
  owns Kai's secret wiring, tailnet exposure, and rollout.

## See also

- [README.md](../README.md) - quick start.
- [AGENTS.md](../AGENTS.md) - agent instructions.
- [justfile](../justfile) - dev verbs (`just <verb>`).
- [.ward/ward.yaml](../.ward/ward.yaml) - catalog metadata only.

Cross-reference convention from [coilysiren/agentic-os-kai#313](https://github.com/coilyco-bridge/agentic-os-kai/issues/313).
