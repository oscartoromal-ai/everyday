// What the app's editors (app/static/notepad.js, doc-editor.js and
// markdown-editor.js) take from CodeMirror 6 and its Markdown parser.
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
export { Language, LanguageSupport, defineLanguageFacet, syntaxTree } from "@codemirror/language";
export { GFM, parser as markdownParser } from "@lezer/markdown";
