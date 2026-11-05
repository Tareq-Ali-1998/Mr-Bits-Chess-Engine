# Reader documentation

Whenever you create or edit human-facing Markdown, regenerate its sibling HTML before finishing:

```powershell
python tools/docs_html.py "path/from/workspace/root/document.md"
```

Run `python tools/docs_html.py --check` to confirm reader exports are current. VS Code's Markdown PDF save hook does not run for edits made by terminal tools or assistants. Do not export agent instructions, `HANDOFF.md`, private/runtime data, or third-party documentation. Do not read or export `Claude Docs` contents. Keep source Markdown and reader HTML together in changes. See `tools/README.md` for the supported local workflow.
