const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const frontend = path.join(root, "frontend");
const output = path.join(root, "mobile-dist");
const input = (process.env.NEXA_MOBILE_API_URL || "").trim();
let api = "";
if (input) {
  let url;
  try {
    url = new URL(input);
  } catch {
    throw new Error("NEXA_MOBILE_API_URL must be an absolute HTTPS URL ending in /api.");
  }
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash ||
      !/\/api\/?$/.test(url.pathname)) {
    throw new Error("NEXA_MOBILE_API_URL must be an HTTPS URL ending in /api, without credentials, query, or fragment.");
  }
  api = url.href.replace(/\/$/, "");
} else {
  console.warn("NEXA_MOBILE_API_URL is not set; the mobile app cannot connect until it is configured and rebuilt.");
}

fs.mkdirSync(output, { recursive: true });
let html = fs.readFileSync(path.join(frontend, "Nexa.html"), "utf8");
const replacements = [
  ['https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js', 'react.production.min.js'],
  ['https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.production.min.js', 'react-dom.production.min.js'],
  ['<script src="Nexa.js"></script>', '<script src="mobile-config.js"></script>\n<script src="Nexa.js"></script>'],
];
for (const [from, to] of replacements) {
  if (!html.includes(from)) throw new Error(`Frontend template is missing: ${from}`);
  html = html.replace(from, to);
}
fs.writeFileSync(path.join(output, "index.html"), html);
fs.writeFileSync(path.join(output, "mobile-config.js"),
  `window.NEXA_MOBILE = true;\nwindow.NEXA_API = ${JSON.stringify(api)};\n`);
for (const name of ["Nexa.css", "Nexa.js"]) {
  fs.copyFileSync(path.join(frontend, name), path.join(output, name));
}
for (const [pkg, name] of [["react", "react.production.min.js"], ["react-dom", "react-dom.production.min.js"]]) {
  fs.copyFileSync(path.join(root, "node_modules", pkg, "umd", name), path.join(output, name));
}
