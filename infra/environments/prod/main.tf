terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "network" {
  source      = "../../modules/network"
  project_id  = var.project_id
  region      = var.region
  name_prefix = "muebles-prod"
}

module "security" {
  source      = "../../modules/security"
  project_id  = var.project_id
  name_prefix = "muebles-prod"
}

module "data" {
  source                    = "../../modules/data"
  project_id                = var.project_id
  region                    = var.region
  name_prefix               = "muebles-prod"
  vpc_id                    = module.network.vpc_id
  private_vpc_connection_id = module.network.private_vpc_connection_id
  backend_sa_email          = module.security.backend_sa_email
  deletion_protection       = true
}

module "compute" {
  source            = "../../modules/compute"
  project_id        = var.project_id
  region            = var.region
  name_prefix       = "muebles-prod"
  vpc_name          = module.network.vpc_name
  subnet_name       = module.network.subnet_name
  backend_sa_email  = module.security.backend_sa_email
  frontend_sa_email = module.security.frontend_sa_email
  waf_policy_id     = module.security.waf_policy_id
  frontend_image    = var.frontend_image
  backend_image     = var.backend_image
  # En prod todo el trafico entra obligatoriamente por Load Balancer + Cloud Armor
  frontend_ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
}

output "load_balancer_ip" {
  value = module.compute.load_balancer_ip
}
