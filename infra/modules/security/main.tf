variable "project_id" {
  type = string
}

variable "name_prefix" {
  type = string
}

# Service Accounts dedicadas de minimo privilegio (nunca usar la default de Compute Engine)
resource "google_service_account" "backend_sa" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-backend-sa"
  display_name = "Muebles Backend Runtime SA"
}

resource "google_service_account" "frontend_sa" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-frontend-sa"
  display_name = "Muebles Frontend Runtime SA"
}

resource "google_project_iam_member" "backend_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.backend_sa.email}"
}

resource "google_project_iam_member" "backend_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.backend_sa.email}"
}

resource "google_project_iam_member" "frontend_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.frontend_sa.email}"
}

# Secretos gestionados en Secret Manager (los valores se cargan fuera de Terraform)
resource "google_secret_manager_secret" "db_password" {
  project   = var.project_id
  secret_id = "${var.name_prefix}-db-password"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "backend_db_secret_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend_sa.email}"
}

resource "google_secret_manager_secret" "payment_secret" {
  project   = var.project_id
  secret_id = "${var.name_prefix}-payment-secret"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "backend_payment_secret_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.payment_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend_sa.email}"
}

# Cloud Armor WAF Policy: Proteccion OWASP Top 10 + Rate Limiting
resource "google_compute_security_policy" "waf_policy" {
  project     = var.project_id
  name        = "${var.name_prefix}-waf-policy"
  description = "Politica WAF para tienda de muebles (SQLi, XSS y rate limit)"

  rule {
    action   = "deny(403)"
    priority = 1000
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('sqli-v33-stable')"
      }
    }
    description = "Bloquear intentos de SQL Injection"
  }

  rule {
    action   = "deny(403)"
    priority = 1100
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('xss-v33-stable')"
      }
    }
    description = "Bloquear intentos de Cross-Site Scripting"
  }

  rule {
    action   = "throttle"
    priority = 2000
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = 120
        interval_sec = 60
      }
    }
    description = "Limitar scraping y fuerza bruta por IP"
  }

  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Regla por defecto"
  }
}

output "backend_sa_email" {
  value = google_service_account.backend_sa.email
}

output "frontend_sa_email" {
  value = google_service_account.frontend_sa.email
}

output "db_password_secret_id" {
  value = google_secret_manager_secret.db_password.secret_id
}

output "waf_policy_id" {
  value = google_compute_security_policy.waf_policy.id
}
