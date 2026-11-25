# Hackathon Google — Tienda Online de Muebles (Arquitectura Independiente para 5 Personas)

Repositorio modular diseñado para que **5 personas trabajen en paralelo y de forma independiente** sobre Google Cloud, preparado para auditorías de **infraestructura, seguridad y ciberseguridad**.

## Principios de trabajo independiente

1. **Contratos antes que código (`contracts/openapi.yaml`)**: Frontend, Backend y QA trabajan contra el mismo contrato API sin bloquearse.
2. **Pipelines aislados (`includedFiles`)**: Cada servicio tiene su propio `cloudbuild.yaml` que despliega revisiones de preview independientes (`pr-<NUM>`) en Cloud Run.
3. **Entornos separados (`dev` vs `prod`)**: `infra/environments/dev` y `infra/environments/prod` comparten módulos Terraform pero mantienen estados, proyectos y permisos aislados.
4. **Cero secretos en el código y cero claves JSON descargadas**: Autenticación humana vía `gcloud auth login` + ADC (`gcloud auth application-default login`), y secretos de runtime en **Secret Manager**.

## Reparto de carpetas por integrante

| Persona | Carpeta | Responsabilidad | Pipeline propio |
| :--- | :--- | :--- | :--- |
| **1. Frontend** | `services/frontend/` | Catálogo de muebles, carrito, UI y cabeceras HTTP seguras | `services/frontend/cloudbuild.yaml` |
| **2. Backend** | `services/backend/` | API de catálogo, stock, pedidos y conexión privada a Cloud SQL | `services/backend/cloudbuild.yaml` |
| **3. Infra & CI/CD** | `infra/` | VPC, Load Balancer, Cloud Run, Cloud SQL, Artifact Registry | `terraform` (`dev` / `prod`) |
| **4. Sec & Ciber** | `security/` | Cloud Armor (WAF), IAM mínimo privilegio, Secret Manager, escaneos | `security/cloudbuild-sec.yaml` |
| **5. QA / Observabilidad** | `qa/` | Tests E2E contra previews, alertas y pruebas de carga | `qa/cloudbuild-qa.yaml` |

## Arranque rápido en local (cualquier miembro)

### Backend (puerto 8081)
```bash
cd services/backend
python3 -m unittest test_app.py
PORT=8081 python3 app.py
```

### Frontend (puerto 8080)
```bash
cd services/frontend
BACKEND_URL=http://localhost:8081 PORT=8080 node server.js
```

### Tests E2E de QA
```bash
BACKEND_URL=http://localhost:8081 FRONTEND_URL=http://localhost:8080 python3 -m unittest qa/test_e2e.py
```

## Puesta en marcha en Google Cloud (paso a paso)

1. Cada miembro inicia sesión con su cuenta:
   ```bash
   gcloud auth login
   gcloud auth application-default login
   ```
2. La persona de **Infra** crea los dos proyectos (`muebles-hack-dev` y `muebles-hack-prod`), vincula la facturación y aplica `infra/environments/dev` y `infra/environments/prod`.
3. La persona de **Seguridad** carga los secretos en **Secret Manager** (nunca en `.env` subidos a Git) y verifica la postura con `security/run-security-checks.sh`.
4. Cada desarrollador abre su rama (`git checkout -b feat/mi-parte`), hace push y abre Pull Request: Cloud Build generará una URL de preview aislada.
