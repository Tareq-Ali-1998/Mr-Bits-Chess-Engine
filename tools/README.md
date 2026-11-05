# Keep the reading documents in sync

**Your Markdown source and its sibling HTML should travel together.** Read either one; edit the `.md` file.

Markdown PDF is already configured to export **HTML on save** when this project is open in VS Code. Run **Developer: Reload Window** once if VS Code was open when these settings were added. The project settings work whether you open `Mr_Bits` or `lichess-bot-master`. They preserve the guides' inline colors and print styles. They do not change your settings in other projects.

Changes made by an assistant, Git, or a terminal do not trigger the extension's editor-save event. For those changes, run this from `Mr_Bits`:

```powershell
python tools/docs_html.py
```

That updates missing or stale HTML beside the project-owned reader documents. To export a particular document immediately:

```powershell
python tools/docs_html.py "lichess-bot-master/engines/Kernels/v3.0/HOW_V3_0_WORKS.md"
```

`--check` reports stale/missing exports without writing. `--force` refreshes every selected export. `--watch` watches for external edits until you press Ctrl+C; no hidden service is installed. The command-line renderer uses Markdown-it with syntax highlighting, tables, headings, preserved inline HTML/CSS, and Mermaid diagrams. It follows the same Markdown conventions as the extension; exact typography can differ. Mermaid diagrams need an internet connection when the HTML is opened; text diagrams work offline. Local links to reader Markdown open the corresponding HTML.

The dependencies are already available on this PC. On another machine:

```powershell
python -m pip install -r tools/docs-requirements.in
```

`HANDOFF.md`, `AGENTS.md`, and other named assistant instruction files are excluded. The command-line scan also skips Claude Docs, datasets, training runs, diagnostics, logs, virtual environments, and bundled third-party documentation. The extension excludes assistant filenames; it exports only a Markdown document you explicitly save in the editor.
