variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "vpc_name" {
  type = string
}

variable "subnet_name" {
  type = string
}

variable "backend_sa_email" {
  type = string
}

variable "frontend_sa_email" {
  type = string
}

variable "waf_policy_id" {
  type = string
}

variable "frontend_image" {
  type = string
}

variable "backend_image" {
  type = string
}

variable "frontend_ingress" {
  type    = string
  default = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
}

resource "google_artifact_registry_repository" "docker_repo" {
  project       = var.project_id
  location      = var.region
  repository_id = "muebles-repo"
  format        = "DOCKER"
  description   = "Imagenes Docker de frontend y backend"
}

resource "google_cloud_run_v2_service" "backend" {
  project  = var.project_id
  name     = "${var.name_prefix}-backend"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = var.backend_sa_email

    vpc_access {
      network_interfaces {
        network    = var.vpc_name
        subnetwork = var.subnet_name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.backend_image
      ports {
        container_port = 8080
      }
    }
  }
}

# Solo el frontend puede invocar al backend privado
resource "google_cloud_run_v2_service_iam_member" "frontend_invokes_backend" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.frontend_sa_email}"
}

resource "google_cloud_run_v2_service" "frontend" {
  project  = var.project_id
  name     = "${var.name_prefix}-frontend"
  location = var.region
  ingress  = var.frontend_ingress

  template {
    service_account = var.frontend_sa_email

    vpc_access {
      network_interfaces {
        network    = var.vpc_name
        subnetwork = var.subnet_name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.frontend_image
      ports {
        container_port = 8080
      }
      env {
        name  = "BACKEND_URL"
        value = google_cloud_run_v2_service.backend.uri
      }
      env {
        name  = "USE_GCP_OIDC"
        value = "true"
      }
    }
  }
}

# Acceso publico al frontend SOLO a traves del Load Balancer + Cloud Armor
resource "google_cloud_run_v2_service_iam_member" "public_frontend" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_compute_region_network_endpoint_group" "frontend_neg" {
  project               = var.project_id
  name                  = "${var.name_prefix}-frontend-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region

  cloud_run {
    service = google_cloud_run_v2_service.frontend.name
  }
}

resource "google_compute_backend_service" "frontend_lb_backend" {
  project         = var.project_id
  name            = "${var.name_prefix}-frontend-bs"
  protocol        = "HTTP"
  security_policy = var.waf_policy_id

  backend {
    group = google_compute_region_network_endpoint_group.frontend_neg.id
  }
}

resource "google_compute_url_map" "frontend_url_map" {
  project         = var.project_id
  name            = "${var.name_prefix}-url-map"
  default_service = google_compute_backend_service.frontend_lb_backend.id
}

resource "google_compute_target_http_proxy" "frontend_http_proxy" {
  project = var.project_id
  name    = "${var.name_prefix}-http-proxy"
  url_map = google_compute_url_map.frontend_url_map.id
}

resource "google_compute_global_forwarding_rule" "frontend_forwarding" {
  project    = var.project_id
  name       = "${var.name_prefix}-http-rule"
  target     = google_compute_target_http_proxy.frontend_http_proxy.id
  port_range = "80"
}

output "load_balancer_ip" {
  value = google_compute_global_forwarding_rule.frontend_forwarding.ip_address
}

output "frontend_url" {
  value = google_cloud_run_v2_service.frontend.uri
}

output "backend_url" {
  value = google_cloud_run_v2_service.backend.uri
}
