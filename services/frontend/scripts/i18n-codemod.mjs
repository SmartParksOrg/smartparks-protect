/** One-off codemod for decision D93: wraps hard-coded UI text in t(). Run with
 *  `node scripts/i18n-codemod.mjs [files...]` (default: every src/**\/*.tsx except tests).
 *
 *  - JSX text with letters becomes {t("text")} (whitespace and punctuation-only text stays).
 *  - String attributes named in ATTRIBUTES become {t("...")}.
 *  - Inside a function component or hook, `const { t } = useTranslation();` is inserted and
 *    react-i18next imported; elsewhere `i18n.t(...)` is used with the i18n instance imported.
 *  - Leftovers (template literals, strings in expressions) are for the lint rule and a person.
 */
import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";

const ATTRIBUTES = new Set(["title", "label", "placeholder", "description", "hint", "aria-label", "alt", "header", "emptyMessage", "success", "confirmLabel", "cancelLabel"]);
const SKIP_TAGS = new Set(["code", "pre", "kbd", "Trans"]);
const WORD = /[A-Za-z]{2,}/;

function listFiles(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...listFiles(p));
    else if (p.endsWith(".tsx") && !p.endsWith(".test.tsx") && !p.includes("/components/ui/") && !p.includes("/test/")) out.push(p);
  }
  return out;
}

function enclosingFunction(node) {
  let n = node.parent;
  while (n) {
    if (ts.isFunctionDeclaration(n) || ts.isFunctionExpression(n) || ts.isArrowFunction(n) || ts.isMethodDeclaration(n)) return n;
    n = n.parent;
  }
  return null;
}

function functionName(fn) {
  if (fn.name) return fn.name.text;
  const p = fn.parent;
  if (p && ts.isVariableDeclaration(p) && ts.isIdentifier(p.name)) return p.name.text;
  return null;
}

/** The component or hook that owns this node: the outermost function whose name is a
 *  component (Uppercase) or a hook (useX); null when the node is at module level or inside a
 *  plain helper. */
function ownerComponent(node) {
  let fn = enclosingFunction(node);
  let owner = null;
  while (fn) {
    const name = functionName(fn);
    if (name && (/^[A-Z]/.test(name) || /^use[A-Z]/.test(name))) owner = fn;
    fn = enclosingFunction(fn);
  }
  return owner;
}

function normalize(text) {
  return text.replace(/\s+/g, " ").trim();
}

function transform(file) {
  const source = readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const edits = []; // {start, end, text}
  const owners = new Set();
  let usesModuleT = false;

  function key(text) {
    return JSON.stringify(text);
  }

  function visit(node) {
    if (ts.isJsxText(node)) {
      const raw = node.getText(sf);
      const text = normalize(raw);
      const parentTag = node.parent && ts.isJsxElement(node.parent) ? node.parent.openingElement.tagName.getText(sf) : "";
      if (text && WORD.test(text) && !SKIP_TAGS.has(parentTag)) {
        const leading = raw.match(/^\s*/)[0];
        const trailing = raw.match(/\s*$/)[0];
        const hasNl = /\n/.test(leading) || /\n/.test(trailing);
        const owner = ownerComponent(node);
        const call = owner ? `t(${key(text)})` : `i18n.t(${key(text)})`;
        if (owner) owners.add(owner); else usesModuleT = true;
        const pre = hasNl ? leading : (leading ? " " : "");
        const post = hasNl ? trailing : (trailing ? " " : "");
        edits.push({ start: node.getStart(sf), end: node.getEnd(), text: `${pre}{${call}}${post}` });
      }
      return;
    }
    if (ts.isJsxAttribute(node) && node.initializer && ts.isStringLiteral(node.initializer)) {
      const name = node.name.getText(sf);
      const text = node.initializer.text;
      if (ATTRIBUTES.has(name) && WORD.test(text)) {
        const owner = ownerComponent(node);
        const call = owner ? `t(${key(text)})` : `i18n.t(${key(text)})`;
        if (owner) owners.add(owner); else usesModuleT = true;
        edits.push({ start: node.initializer.getStart(sf), end: node.initializer.getEnd(), text: `{${call}}` });
      }
      return;
    }
    // Object property strings for table columns and toasts: header: "...", success: "..."
    if (ts.isPropertyAssignment(node) && ts.isStringLiteral(node.initializer)) {
      const name = node.name.getText(sf);
      const text = node.initializer.text;
      if (ATTRIBUTES.has(name) && WORD.test(text)) {
        const owner = ownerComponent(node);
        const call = owner ? `t(${key(text)})` : `i18n.t(${key(text)})`;
        if (owner) owners.add(owner); else usesModuleT = true;
        edits.push({ start: node.initializer.getStart(sf), end: node.initializer.getEnd(), text: call });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sf);
  if (!edits.length) return false;

  // Insert `const { t } = useTranslation();` at the top of each owner body.
  for (const owner of owners) {
    const body = owner.body;
    if (!body || !ts.isBlock(body)) continue;
    const already = /useTranslation\(\)/.test(body.getText(sf));
    if (already) continue;
    const first = body.statements[0];
    const at = first ? first.getStart(sf) : body.getStart(sf) + 1;
    const indent = first ? source.slice(source.lastIndexOf("\n", at) + 1, at) : "  ";
    edits.push({ start: at, end: at, text: `const { t } = useTranslation();\n${indent}` });
  }
  edits.sort((a, b) => b.start - a.start);
  let out = source;
  for (const e of edits) out = out.slice(0, e.start) + e.text + out.slice(e.end);
  // Imports
  const importLines = [];
  if (owners.size && !/from "react-i18next"/.test(out)) importLines.push('import { useTranslation } from "react-i18next";');
  if (usesModuleT && !/from "@\/i18n"/.test(out)) importLines.push('import i18n from "@/i18n";');
  if (importLines.length) {
    const firstImport = out.search(/^import /m);
    out = out.slice(0, firstImport) + importLines.join("\n") + "\n" + out.slice(firstImport);
  }
  writeFileSync(file, out);
  return true;
}

const files = process.argv.length > 2 ? process.argv.slice(2) : listFiles("src");
let changed = 0;
for (const f of files) if (transform(f)) { changed++; console.log("rewrote", relative(process.cwd(), f)); }
console.log(`${changed} file(s) rewritten`);
