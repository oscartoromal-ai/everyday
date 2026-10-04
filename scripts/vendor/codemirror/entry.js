// What the app's editors (app/static/notepad.js, doc-editor.js and the
// Markdown engine, markdown-live.js) take from CodeMirror 6 and its
// Markdown parser.
import { LanguageDescription, LanguageSupport, StreamLanguage } from "@codemirror/language";
import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { python } from "@codemirror/lang-python";
import { diff } from "@codemirror/legacy-modes/mode/diff";
import { powerShell } from "@codemirror/legacy-modes/mode/powershell";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { standardSQL } from "@codemirror/legacy-modes/mode/sql";
import { toml } from "@codemirror/legacy-modes/mode/toml";
import { yaml } from "@codemirror/legacy-modes/mode/yaml";

export {
  Annotation, EditorSelection, EditorState, MapMode, Prec, RangeSetBuilder, StateEffect, StateField,
  Transaction,
} from "@codemirror/state";
export {
  Decoration, EditorView, GutterMarker, ViewPlugin, WidgetType, drawSelection, gutterLineClass,
  keymap, lineNumberWidgetMarker, lineNumbers, placeholder,
} from "@codemirror/view";
export { defaultKeymap, history, historyKeymap, invertedEffects, isolateHistory } from "@codemirror/commands";
export { autocompletion, completionStatus, startCompletion } from "@codemirror/autocomplete";
export { syntaxHighlighting, syntaxTree } from "@codemirror/language";
export { tagHighlighter, tags } from "@lezer/highlight";
export { GFM } from "@lezer/markdown";
export { commonmarkLanguage, markdown, markdownKeymap } from "@codemirror/lang-markdown";

// The languages a fenced code block is highlighted in, by its info string's
// first word (```python, ```ps1); any other is drawn as plain code.
const describe = (name, alias, support) => LanguageDescription.of({ name, alias, support });
const stream = (mode) => new LanguageSupport(StreamLanguage.define(mode));
export const codeLanguages = [
  describe("Python", ["py"], python()),
  describe("JavaScript", ["js", "jsx", "mjs"], javascript({ jsx: true })),
  describe("TypeScript", ["ts", "tsx"], javascript({ jsx: true, typescript: true })),
  describe("JSON", ["jsonc"], json()),
  describe("HTML", ["htm", "xml", "svg"], html()),
  describe("CSS", [], css()),
  describe("Shell", ["sh", "bash", "zsh", "console"], stream(shell)),
  describe("PowerShell", ["ps1", "pwsh"], stream(powerShell)),
  describe("YAML", ["yml"], stream(yaml)),
  describe("TOML", [], stream(toml)),
  describe("SQL", ["sqlite"], stream(standardSQL)),
  describe("Diff", ["patch"], stream(diff)),
];
