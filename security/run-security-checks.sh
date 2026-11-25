#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAILURES=0

echo "==> [1/4] Verificando que no existan secretos o claves JSON en el repo..."
if find "${ROOT_DIR}" -maxdepth 4 -type f \( -name "*.pem" -o -name "*.key" -o -name "*service-account*.json" \) | grep -q .; then
  echo "ERROR: Se encontraron posibles archivos de clave privada en el repositorio."
  FAILURES=$((FAILURES + 1))
else
  echo "OK: Sin archivos de clave privada."
fi

echo "==> [2/4] Verificando ejecucion no-root en Dockerfiles..."
for df in "${ROOT_DIR}/services/backend/Dockerfile" "${ROOT_DIR}/services/frontend/Dockerfile"; do
  if grep -qE '^USER[[:space:]]+' "${df}"; then
    echo "OK: ${df} define usuario no-root."
  else
    echo "ERROR: ${df} no define directiva USER."
    FAILURES=$((FAILURES + 1))
  fi
done

echo "==> [3/4] Verificando hardening basico en modulos Terraform..."
if grep -q 'ipv4_enabled\s*=\s*false' "${ROOT_DIR}/infra/modules/data/main.tf"; then
  echo "OK: Cloud SQL sin IP publica."
else
  echo "ERROR: Cloud SQL podria tener IP publica."
  FAILURES=$((FAILURES + 1))
fi

if grep -q 'INGRESS_TRAFFIC_INTERNAL_ONLY' "${ROOT_DIR}/infra/modules/compute/main.tf"; then
  echo "OK: Backend Cloud Run con ingress interno."
else
  echo "ERROR: Backend Cloud Run no restringe ingress."
  FAILURES=$((FAILURES + 1))
fi

echo "==> [4/4] Verificacion opcional en GCP (si se pasa PROJECT_ID)..."
if [ -n "${1:-}" ] && command -v gcloud >/dev/null 2>&1; then
  PROJECT_ID="$1"
  echo "Auditando politicas Cloud Armor en ${PROJECT_ID}..."
  gcloud compute security-policies list --project="${PROJECT_ID}" --limit=20 --format="table(name,description)"
  echo "Auditando servicios Cloud Run en ${PROJECT_ID}..."
  gcloud run services list --project="${PROJECT_ID}" --limit=20 --format="table(metadata.name,status.url)"
else
  echo "Omitido (pasa PROJECT_ID como primer argumento para auditar GCP en vivo)."
fi

if [ "${FAILURES}" -gt 0 ]; then
  echo "FALLO: Se detectaron ${FAILURES} problema(s) de seguridad."
  exit 1
fi
echo "EXITO: Verificaciones estaticas de seguridad superadas."
