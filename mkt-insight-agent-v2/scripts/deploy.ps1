# scripts/deploy.ps1 — One-command deploy
param(
  [Parameter(Mandatory)][string]$Version,
  [string]$RuntimeId
)
$ErrorActionPreference = "Stop"

$REGISTRY = "vcr.vngcloud.vn"
$REPO = (bash .claude/skills/agentbase/scripts/cr.sh repo get | jq -r '.name')
$IMAGE = "$REGISTRY/$REPO/mkt-insight-agent-v2"

# 1. Gate kiểm chứng (TRƯỚC khi build)
python scripts/validate_artifacts.py
python scripts/verify_metrics_duckdb.py
ruff check .
mypy app/semantic app/verify app/analytics
pytest tests/ -q
python -m evals.run_eval --split dev --profile test

# 2. Build
docker build --platform linux/amd64 -t "$IMAGE:$Version" .

# 3. Login + push
bash .claude/skills/agentbase/scripts/cr.sh credentials docker-login
docker push "$IMAGE:$Version"

# 4. Update runtime
bash .claude/skills/agentbase/scripts/runtime.sh update $RuntimeId `
  --image "$IMAGE:$Version" --from-cr --env-file .env

# 5. Chờ ACTIVE + verify
bash .claude/skills/agentbase/scripts/runtime.sh get $RuntimeId
$url = bash .claude/skills/agentbase/scripts/runtime.sh endpoints url --runtime-id $RuntimeId
curl -fsS "$url/health"
curl -fsS "$url/readyz"
Write-Host "==> Deployed: $url"
