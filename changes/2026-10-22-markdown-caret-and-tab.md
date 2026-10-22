- Fix: The caret shows on a sub-task or bullet line with nothing written yet
  On a new "- [ ] " line, or arriving at a sub-task's first word with Up or Down, the caret was drawn on the box's edge and could not be seen.
  It now stands where the words start, at its full height.
- Feature: Tab indents in a description or document, and Shift+Tab steps out of it
  Tab no longer jumps away across the page: it indents the line under the one above, a blank line too, and code in a fenced block as deep as it needs.
  Shift+Tab steps an indented line back out, and from a line at the left moves out of the editor.
