const assert = require("assert");
const http = require("http");
const { createServer } = require("./server");

async function run() {
  const server = createServer({ backendUrl: "http://127.0.0.1:65500" });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  try {
    const res = await new Promise((resolve, reject) => {
      http.get(`http://127.0.0.1:${port}/healthz`, resolve).on("error", reject);
    });
    assert.strictEqual(res.statusCode, 200);
    assert.strictEqual(res.headers["x-frame-options"], "DENY");
    assert.strictEqual(res.headers["x-content-type-options"], "nosniff");
    assert.ok(res.headers["content-security-policy"].includes("default-src 'self'"));

    const traversalRes = await new Promise((resolve, reject) => {
      const req = http.request({ host: "127.0.0.1", port, path: "/%2e%2e/server.js" }, resolve);
      req.on("error", reject);
      req.end();
    });
    assert.strictEqual(traversalRes.statusCode, 403);
    console.log("Frontend tests passed");
  } finally {
    server.close();
  }
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
