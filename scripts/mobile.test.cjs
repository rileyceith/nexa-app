const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const script = path.join(root, "scripts", "build-mobile.cjs");
const output = path.join(root, "mobile-dist");

function build(api) {
  const env = { ...process.env };
  if (api === undefined) delete env.NEXA_MOBILE_API_URL;
  else env.NEXA_MOBILE_API_URL = api;
  return spawnSync(process.execPath, [script], { cwd: root, env, encoding: "utf8" });
}

test("mobile bundle uses local React and requires an explicit HTTPS API", () => {
  try {
    let result = build();
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stderr, /not set/);
    assert.match(fs.readFileSync(path.join(output, "mobile-config.js"), "utf8"), /window\.NEXA_API = ""/);
    const html = fs.readFileSync(path.join(output, "index.html"), "utf8");
    assert.match(html, /src="react\.production\.min\.js"/);
    assert.match(html, /src="react-dom\.production\.min\.js"/);
    assert.ok(html.indexOf('src="mobile-config.js"') < html.indexOf('src="Nexa.js"'));
    assert.doesNotMatch(html, /cdnjs\.cloudflare\.com\/ajax\/libs\/react/);
    for (const file of ["Nexa.css", "Nexa.js", "react.production.min.js", "react-dom.production.min.js"]) {
      assert.ok(fs.statSync(path.join(output, file)).size > 0);
    }

    result = build("https://example.test/api/");
    assert.equal(result.status, 0, result.stderr);
    assert.match(fs.readFileSync(path.join(output, "mobile-config.js"), "utf8"),
      /window\.NEXA_API = "https:\/\/example\.test\/api"/);
    for (const invalid of ["http://example.test/api", "https://example.test", "https://example.test/api?x=1"]) {
      assert.notEqual(build(invalid).status, 0, invalid);
    }
  } finally {
    const result = build();
    assert.equal(result.status, 0, result.stderr);
  }
});
