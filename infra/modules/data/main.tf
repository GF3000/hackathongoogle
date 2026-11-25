variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_vpc_connection_id" {
  type = string
}

variable "backend_sa_email" {
  type = string
}

variable "deletion_protection" {
  type    = bool
  default = false
}

resource "google_sql_database_instance" "postgres" {
  project             = var.project_id
  name                = "${var.name_prefix}-pg"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = var.deletion_protection

  settings {
    tier              = "db-f1-micro"
    availability_type = "ZONAL"

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = var.vpc_id
      ssl_mode                                      = "ENCRYPTED_ONLY"
      enable_private_path_for_google_cloud_services = true
    }

    backup_configuration {
      enabled = true
    }
  }

  depends_on = [var.private_vpc_connection_id]
}

resource "google_sql_database" "store_db" {
  project  = var.project_id
  name     = "muebles"
  instance = google_sql_database_instance.postgres.name
}

# Bucket privado para imagenes de muebles (sin acceso publico directo)
resource "google_storage_bucket" "media_bucket" {
  project                     = var.project_id
  name                        = "${var.project_id}-${var.name_prefix}-media"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = !var.deletion_protection
}

resource "google_storage_bucket_iam_member" "backend_media_admin" {
  bucket = google_storage_bucket.media_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.backend_sa_email}"
}

output "sql_connection_name" {
  value = google_sql_database_instance.postgres.connection_name
}

output "sql_private_ip" {
  value = google_sql_database_instance.postgres.private_ip_address
}

output "media_bucket_name" {
  value = google_storage_bucket.media_bucket.name
}
