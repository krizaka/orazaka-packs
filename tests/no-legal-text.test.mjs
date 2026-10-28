// Guard: a Québec article's text is never committed to this public repository (CTO rule, 2026-10-26).
// `document-validation/derivation/law/` holds the REFERENCE of an article (instrument, ref, official address, in-force
// date, content hash); the engine reads the text from the official source or a private store. The history still holds
// the three texts removed here — rewriting it is the CTO's call, not this guard's.
//
// What fails:
//   - a `text` field in a `law/` file, unless the article is fictional (instrument TEST-…) and short;
//   - a `quote` longer than QUOTE_MAX characters (a quote is a passage, never the article);
//   - any string of the repository's JSON/YAML/Markdown/Python/test files that hashes (as `ContentHash` defines it) to a
//     held article: the whole article pasted somewhere else.
import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
/** Longest quote of a rule or a test: the longest one shipped today is 124 characters. */
export const QUOTE_MAX = 200;
/** Longest `text` of a fictional article held under `law/`. */
export const FICTIONAL_TEXT_MAX = 400;
const TEXT_FILES = /\.(json|ya?ml|md|txt|py|mjs|java)$/;

/** SHA-256 of a text once normalised: NFC, every run of whitespace one space, trimmed (citations.content_hash). */
export const contentHash = (text) =>
  createHash("sha256").update(text.normalize("NFC").replace(/[\s ]+/g, " ").trim(), "utf8").digest("hex");

function trackedFiles() {
  try {
    const out = execFileSync("git", ["ls-files", "-z"], { cwd: root, encoding: "utf8" });
    return out.split("\0").filter(Boolean);
  } catch {
    const walk = (dir) =>
      readdirSync(dir).flatMap((n) => {
        if (n === "node_modules" || n === ".git") return [];
        const p = join(dir, n);
        return statSync(p).isDirectory() ? walk(p) : [relative(root, p).split(sep).join("/")];
      });
    return walk(root);
  }
}

function* strings(value, path = "") {
  if (typeof value === "string") yield [path, value];
  else if (Array.isArray(value)) for (const [i, v] of value.entries()) yield* strings(v, `${path}[${i}]`);
  else if (value && typeof value === "object") for (const [k, v] of Object.entries(value)) yield* strings(v, `${path}.${k}`);
}

/** Hashes of the articles held by reference under any `law/` directory. */
function heldHashes(files, read) {
  return new Set(
    files
      .filter((f) => /(^|\/)law\/[^/]+\.json$/.test(f))
      .map((f) => JSON.parse(read(f)).contentHash)
      .filter(Boolean),
  );
}

/** The violations of a set of files (path -> content), as sentences. */
export function violations(files, read, hashes = heldHashes(files, read)) {
  const found = [];
  for (const f of files) {
    if (!TEXT_FILES.test(f)) continue;
    const content = read(f);
    if (f.endsWith(".json")) {
      let json;
      try {
        json = JSON.parse(content);
      } catch {
        continue;
      }
      if (/(^|\/)law\/[^/]+\.json$/.test(f) && typeof json.text === "string") {
        const fictional = /^TEST-/.test(json.instrument ?? "");
        if (!fictional || json.text.length > FICTIONAL_TEXT_MAX) {
          found.push(`${f}: a law file carries a "text" (${json.text.length} characters): keep the reference only`);
        }
      }
      for (const [path, value] of strings(json)) {
        if (/\.quote$/.test(path) && value.length > QUOTE_MAX) {
          found.push(`${f}${path}: a quote of ${value.length} characters (max ${QUOTE_MAX}) is a passage, not the article`);
        }
      }
    }
    // The whole article pasted anywhere: a JSON/YAML string, a line, or a paragraph of any text file.
    const candidates = f.endsWith(".json") ? [...strings(safeParse(content))].map(([, v]) => v) : content.split(/\n{2,}|\n/);
    for (const c of candidates) {
      if (c.length >= 40 && hashes.has(contentHash(c)) && !/(^|\/)law\/[^/]+\.json$/.test(f)) {
        found.push(`${f}: holds the complete text of a held article`);
      }
    }
  }
  return found;
}

const safeParse = (s) => {
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
};

test("no file of the repository holds a Québec article's text or a long verbatim legal passage", () => {
  const files = trackedFiles();
  const read = (f) => readFileSync(join(root, f), "utf8");
  const found = violations(files, read);
  assert.deepEqual(found, []);
});

test("the guard fails on a law file with a text, a long quote and a pasted article", () => {
  const article = "Le locateur est tenu de donner un préavis. ".repeat(6).trim();
  const files = {
    "x/law/CCQ-1-1-fr-2000-01-01.json": JSON.stringify({ instrument: "CCQ-1991", ref: "1", contentHash: contentHash(article), text: "court" }),
    "x/rules.json": JSON.stringify({ law: [{ quote: "a".repeat(QUOTE_MAX + 1) }], note: article }),
    "x/README.md": `intro\n\n${article}\n`,
    "x/law/TEST-1-9-fr-2020-01-01.json": JSON.stringify({ instrument: "TEST-1", ref: "9", text: "Article fictif." }),
  };
  const read = (f) => files[f];
  const found = violations(Object.keys(files), read);
  assert.equal(found.length, 4, found.join("\n"));
  assert.ok(found.some((m) => m.includes("law file carries")));
  assert.ok(found.some((m) => m.includes("quote of")));
  assert.equal(found.filter((m) => m.includes("complete text")).length, 2);
});

test("every article held under law/ is a reference: instrument, ref, official address, in-force date, hash", () => {
  const files = trackedFiles().filter((f) => /(^|\/)law\/[^/]+\.json$/.test(f));
  assert.ok(files.length >= 3);
  for (const f of files) {
    const a = JSON.parse(readFileSync(join(root, f), "utf8"));
    for (const k of ["instrument", "ref", "language", "inForceFrom", "contentHash", "officialUrl"]) assert.ok(a[k], `${f}: ${k}`);
    assert.match(a.contentHash, /^[0-9a-f]{64}$/, f);
  }
});
