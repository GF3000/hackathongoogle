# Checklist de Seguridad, Infraestructura y Ciberseguridad

Guía para la **Persona 4 (Sec & Ciber)** antes de los tests del hackathon:

## 1. Perimetro y Red
- [ ] En `prod`, el frontend tiene `ingress = INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER` (no accesible saltándose el WAF por la URL `*.run.app`).
- [ ] El backend tiene `ingress = INGRESS_TRAFFIC_INTERNAL_ONLY` y `roles/run.invoker` concedido únicamente a la Service Account del frontend.
- [ ] **Cloud Armor** aplicado al `BackendService` del Load Balancer con reglas OWASP (`sqli-v33-stable`, `xss-v33-stable`) y *rate limiting* por IP.
- [ ] **Cloud SQL** sin IP pública (`ipv4_enabled = false`), accesible solo por red privada VPC y con `ssl_mode = ENCRYPTED_ONLY`.
- [ ] **Cloud Storage** de imágenes con `public_access_prevention = "enforced"` y `uniform_bucket_level_access = true`.

## 2. Identidad y Secretos
- [ ] Cero archivos `.json` de claves de Service Account en el repositorio o portátiles.
- [ ] Secretos (`db-password`, `payment-secret`) almacenados en **Secret Manager** y leídos con `roles/secretmanager.secretAccessor` por recurso.
- [ ] En `prod`, los 5 desarrolladores tienen como máximo `roles/viewer`; solo Cloud Build despliega.

## 3. Aplicacion y Contenedores
- [ ] Ambos `Dockerfile` ejecutan con usuario sin privilegios (`USER appuser` / `USER node`).
- [ ] Cabeceras HTTP en el frontend: `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`.
- [ ] Sin datos de tarjeta (PAN) almacenados: solo `payment_token` validado en backend.
- [ ] Escaneo de vulnerabilidades en **Artifact Registry** + **Web Security Scanner** ejecutado sobre la URL pública del Load Balancer.
