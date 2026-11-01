# Deploying the MCP server

This repo ships a portable Helm chart. Kai's live service is owned by
`coilyco-bridge/deploy/services/lunch-money-mcp/`, which supplies the fleet
image, secrets, exposure, and rollout. Changes here do not deploy it.

## Generic Kubernetes install

The portable path is the Helm chart, documented in [chart.md](chart.md).

## Image

The chart defaults to `docker.io/coilysiren/lunch-money-k8s`. Override
`image.repository` and `image.tag` when using another registry.

## Continuous integration

CI runs on GitHub Actions. Every push to `main` runs the app tests, lints and
renders the chart, then publishes and verifies the single-architecture image as
`ghcr.io/coilyco/lunch-money-mcp:<full-source-sha>` with the job's `GITHUB_TOKEN`
and `packages: write`. This repo holds no cluster credentials. Flux applies the
rollout from `coilyco/deploy` and consumes that exact immutable reference.

## Categorization rules

`scripts/categorize.py` reads `rules.yaml` from the working directory. Copy
[`rules.example.yaml`](../rules.example.yaml) to `rules.yaml` and edit it for
the desired payees.

The chart can mount rules from `rules.inline`:

```sh
helm install lunch-money ./chart \
  --set lunchMoney.token="$LUNCH_MONEY_TOKEN" \
  --set-file rules.inline=rules.yaml
```
