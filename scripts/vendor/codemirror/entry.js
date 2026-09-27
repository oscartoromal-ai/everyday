// What the notepad (app/static/notepad.js) takes from CodeMirror 6.
export {
  Annotation, EditorSelection, EditorState, MapMode, Prec, RangeSetBuilder, StateEffect, StateField,
  Transaction,
} from "@codemirror/state";
export {
  Decoration, EditorView, GutterMarker, ViewPlugin, WidgetType, drawSelection, gutterLineClass,
  keymap, lineNumberWidgetMarker, lineNumbers, placeholder,
} from "@codemirror/view";
export { defaultKeymap, history, historyKeymap, invertedEffects, isolateHistory } from "@codemirror/commands";
