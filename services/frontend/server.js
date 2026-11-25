/**
 * Frontend BFF + servidor estatico seguro para la tienda de muebles.
 * - Sirve la UI desde ./public
 * - Actua como proxy hacia BACKEND_URL en /api/* (ideal cuando el backend usa ingress interno)
 * - Inyecta cabeceras de seguridad HTTP para superar auditorias OWASP/Web Security Scanner
 */
const fs = require("fs");
const http = require("http");
const https = require("https");
const path = require("path");
const { URL } = require("url");

const PUBLIC_DIR = path.join(__dirname, "public");

function setSecurityHeaders(res) {
  res.setHeader(
    "Content-Security-Policy",
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
  );
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Frame-Options", "DENY");
  res.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  res.setHeader("Permissions-Policy", "geolocation=(), microphone=(), camera=()");
}

function sendJson(res, statusCode, payload) {
  const body = Buffer.from(JSON.stringify(payload), "utf8");
  setSecurityHeaders(res);
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": body.length,
    "Cache-Control": "no-store",
  });
  res.end(body);
}

function fetchMetadataIdToken(audience) {
  return new Promise((resolve) => {
    const metaUrl = `http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=${encodeURIComponent(
      audience
    )}`;
    const req = http.get(
      metaUrl,
      { headers: { "Metadata-Flavor": "Google" }, timeout: 1500 },
      (resp) => {
        const chunks = [];
        resp.on("data", (d) => chunks.push(d));
        resp.on("end", () => {
          if (resp.statusCode === 200) {
            resolve(Buffer.concat(chunks).toString("utf8").trim());
          } else {
            resolve(null);
          }
        });
      }
    );
    req.on("error", () => resolve(null));
    req.on("timeout", () => {
      req.destroy();
      resolve(null);
    });
  });
}

function proxyToBackend(req, res, backendBaseUrl) {
  const target = new URL(req.url, backendBaseUrl);
  const client = target.protocol === "https:" ? https : http;
  const chunks = [];
  let totalBytes = 0;

  req.on("data", (chunk) => {
    totalBytes += chunk.length;
    if (totalBytes > 65536) {
      req.destroy();
      return;
    }
    chunks.push(chunk);
  });

  req.on("end", async () => {
    if (totalBytes > 65536) {
      sendJson(res, 413, { error: "Payload demasiado grande" });
      return;
    }
    const body = Buffer.concat(chunks);
    const headers = {
      "Content-Type": req.headers["content-type"] || "application/json",
    };
    if (body.length > 0) {
      headers["Content-Length"] = body.length;
    }
    if (process.env.USE_GCP_OIDC === "true" && target.protocol === "https:") {
      const token = await fetchMetadataIdToken(target.origin);
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    }

    const upstream = client.request(
      target,
      { method: req.method, headers, timeout: 8000 },
      (upstreamRes) => {
        const out = [];
        upstreamRes.on("data", (d) => out.push(d));
        upstreamRes.on("end", () => {
          const outBuf = Buffer.concat(out);
          setSecurityHeaders(res);
          res.writeHead(upstreamRes.statusCode || 502, {
            "Content-Type": upstreamRes.headers["content-type"] || "application/json; charset=utf-8",
            "Content-Length": outBuf.length,
            "Cache-Control": "no-store",
          });
          res.end(outBuf);
        });
      }
    );

    upstream.on("error", () => {
      sendJson(res, 502, { error: "Backend no disponible" });
    });

    if (body.length > 0) {
      upstream.write(body);
    }
    upstream.end();
  });
}

function createServer(options = {}) {
  const backendBaseUrl = options.backendUrl || process.env.BACKEND_URL || "http://localhost:8081";

  return http.createServer((req, res) => {
    const reqUrl = new URL(req.url, "http://localhost");

    if (reqUrl.pathname === "/healthz" && req.method === "GET") {
      sendJson(res, 200, { status: "ok", service: "frontend" });
      return;
    }

    if (reqUrl.pathname.startsWith("/api/")) {
      proxyToBackend(req, res, backendBaseUrl);
      return;
    }

    const rawPath = (req.url || "/").split("?")[0];
    let decodedRawPath;
    try {
      decodedRawPath = decodeURIComponent(rawPath);
    } catch {
      sendJson(res, 400, { error: "Ruta invalida" });
      return;
    }

    if (decodedRawPath.includes("..")) {
      sendJson(res, 403, { error: "Acceso denegado" });
      return;
    }

    const safeRelPath = decodedRawPath === "/" ? "index.html" : decodedRawPath.replace(/^\/+/, "");
    const resolved = path.resolve(PUBLIC_DIR, safeRelPath);
    if (!resolved.startsWith(PUBLIC_DIR + path.sep) && resolved !== path.join(PUBLIC_DIR, "index.html")) {
      sendJson(res, 403, { error: "Acceso denegado" });
      return;
    }

    fs.readFile(resolved, (err, content) => {
      if (err) {
        sendJson(res, 404, { error: "Recurso no encontrado" });
        return;
      }
      const ext = path.extname(resolved);
      const mimeTypes = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
      };
      setSecurityHeaders(res);
      res.writeHead(200, {
        "Content-Type": mimeTypes[ext] || "application/octet-stream",
        "Content-Length": content.length,
      });
      res.end(content);
    });
  });
}

if (require.main === module) {
  const port = Number(process.env.PORT || 8080);
  const server = createServer();
  server.listen(port, "0.0.0.0", () => {
    console.log(`Frontend escuchando en http://0.0.0.0:${port}`);
  });
}

module.exports = { createServer };
