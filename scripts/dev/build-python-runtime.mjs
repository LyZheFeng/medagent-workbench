#!/usr/bin/env node
// Build the Python runtime that the medical skill scripts run on.
//
// The installer used to ship only `uv.exe`: the deterministic gates called
// `python`, so a machine without Python could not run any of them. This script
// stages a relocatable CPython (uv's standalone build) plus the packages the
// scripts actually use into `runtime/python-runtime/`, which Tauri bundles as
// the `python-runtime` resource and the sidecar puts first on PATH.
//
//   node scripts/dev/build-python-runtime.mjs          # idempotent
//   node scripts/dev/build-python-runtime.mjs --force  # rebuild from scratch
//
// Windows only for now: the Windows bundle is the one whose users have no
// Python. Other platforms are skipped (and the resource is only mapped in
// tauri.windows.conf.json). The output is a build artifact — never committed.
import { spawnSync } from "node:child_process";
import {
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../..");
const target = path.join(root, "runtime", "python-runtime");
const cache = path.join(root, "runtime", ".python-build-cache");
const requirements = path.join(root, "scripts", "dev", "python-runtime-requirements.txt");
const force = process.argv.includes("--force");
const PYTHON_VERSION = "3.12.13";

function fail(message) {
  console.error(`python-runtime: ${message}`);
  process.exit(1);
}

function run(bin, args, env = {}) {
  const result = spawnSync(bin, args, {
    stdio: "inherit",
    env: { ...process.env, ...env },
  });
  if (result.error) fail(`${path.basename(bin)}: ${result.error.message}`);
  if (result.status !== 0) fail(`${path.basename(bin)} ${args[0]} exited ${result.status}`);
}

function uvBinary() {
  const dir = path.join(root, "apps", "desktop", "src-tauri", "binaries");
  const triple =
    process.platform === "win32"
      ? "pc-windows-msvc"
      : process.platform === "darwin"
        ? "apple-darwin"
        : "unknown-linux-gnu";
  const candidates = existsSync(dir) ? readdirSync(dir).filter((name) => name.startsWith("uv-")) : [];
  const pick = candidates.find((name) => name.includes(triple)) ?? candidates[0];
  if (!pick) fail("bundled uv not found under apps/desktop/src-tauri/binaries");
  return path.join(dir, pick);
}

function pythonExe(dir) {
  return process.platform === "win32" ? path.join(dir, "python.exe") : path.join(dir, "bin", "python3");
}

function treeSize(dir) {
  let total = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) total += treeSize(full);
    else if (entry.isFile()) total += statSync(full).size;
  }
  return total;
}

function prune(dir) {
  const removable = ["Lib/test", "Lib/idlelib", "Lib/turtledemo", "Lib/ensurepip"];
  for (const relative of removable) {
    rmSync(path.join(dir, relative), { recursive: true, force: true });
  }
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "__pycache__") rmSync(full, { recursive: true, force: true });
      else prune(full);
    } else if (entry.isFile() && entry.name.endsWith(".pyc")) {
      rmSync(full, { force: true });
    }
  }
}

if (process.platform !== "win32") {
  console.log(`python-runtime: skipped on ${process.platform} (bundled on Windows only)`);
  process.exit(0);
}

if (existsSync(pythonExe(target)) && !force) {
  console.log(`python-runtime: already built at ${target} (use --force to rebuild)`);
  process.exit(0);
}
if (!existsSync(requirements)) fail(`missing ${requirements}`);

console.log(`python-runtime: staging CPython ${PYTHON_VERSION} + medical packages`);
rmSync(target, { recursive: true, force: true });
rmSync(cache, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
mkdirSync(cache, { recursive: true });
// Keep the tracked placeholder so a clean clone always has the resource
// directory Tauri validates at config load, before this hook runs.
writeFileSync(path.join(target, ".gitkeep"), "");

const uv = uvBinary();
run(uv, ["python", "install", PYTHON_VERSION], {
  UV_PYTHON_INSTALL_DIR: cache,
  UV_NO_PROGRESS: "1",
});

const staged = readdirSync(cache).find((name) => name.startsWith(`cpython-${PYTHON_VERSION}-`));
if (!staged) fail(`uv did not stage cpython-${PYTHON_VERSION} under ${cache}`);
cpSync(path.join(cache, staged), target, { recursive: true });

const python = pythonExe(target);
const site = spawnSync(
  python,
  ["-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
  { encoding: "utf8" },
);
if (site.status !== 0) fail(`cannot locate site-packages: ${site.stderr}`);
const sitePackages = site.stdout.trim();

// `--target` installs into the runtime itself; `--python` makes uv resolve
// wheels for 3.12 (without it the host interpreter decides and cp313 wheels
// break the runtime with "No module named numpy._core._multiarray_umath").
run(uv, [
  "pip",
  "install",
  "--python",
  python,
  "--target",
  sitePackages,
  "--requirements",
  requirements,
]);

prune(target);

const imports = spawnSync(
  python,
  [
    "-c",
    "import matplotlib, numpy, openpyxl, docx, pptx, pypdf, pdfplumber; "
      + "print(matplotlib.__version__, numpy.__version__)",
  ],
  { encoding: "utf8", env: { ...process.env, MPLBACKEND: "Agg" } },
);
if (imports.status !== 0) fail(`staged runtime cannot import its packages: ${imports.stderr}`);

const version = spawnSync(python, ["-V"], { encoding: "utf8" });
const packages = readFileSync(requirements, "utf8")
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter((line) => line && !line.startsWith("#"));

const size = treeSize(target);
writeFileSync(
  path.join(target, "BUILD.json"),
  JSON.stringify(
    {
      python: (version.stdout || "").trim(),
      uv: spawnSync(uv, ["--version"], { encoding: "utf8" }).stdout?.trim(),
      packages,
      builtAt: new Date().toISOString(),
      sizeBytes: statSync(path.join(target, "python.exe")).size + size,
    },
    null,
    1,
  ) + "\n",
  "utf8",
);

console.log(
  `python-runtime: built ${Math.round(size / (1024 * 1024))} MB at ${target} `
    + `(${imports.stdout.trim()})`,
);