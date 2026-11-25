variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "europe-west1"
}

variable "frontend_image" {
  type = string
}

variable "backend_image" {
  type = string
}
