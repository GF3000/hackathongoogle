# Entorno reproducible para Firebase Studio / Project IDX
{ pkgs, ... }: {
  channel = "stable-24.05";
  packages = [
    pkgs.nodejs_22
    pkgs.python312
    pkgs.terraform
    pkgs.google-cloud-sdk
    pkgs.gnumake
  ];
  idx = {
    extensions = [
      "hashicorp.terraform"
      "ms-python.python"
      "googlecloudtools.cloudcode"
    ];
    previews = {
      enable = true;
      previews = {
        web = {
          command = [ "node" "services/frontend/server.js" ];
          manager = "web";
          env = {
            PORT = "$PORT";
          };
        };
      };
    };
  };
}
