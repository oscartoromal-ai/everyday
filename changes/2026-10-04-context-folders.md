- Feature: File a project's context documents in folders and subfolders, on a tree that folds
  A folder's row adds a document or a folder in it, renames or deletes it (with everything in it, after asking); rows are dragged into folders or out to the top, and a document moves from its own page too.
  A new document named as a path ("decisions/adr/0001.md") makes its folders; F2 renames, Delete deletes, and the arrow keys walk the tree.
  Claude reads each document's path, and every folder, in get_project_context.
