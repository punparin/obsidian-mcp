# Frontmatter & Templates

## Frontmatter convention

For best results, standardize your notes with YAML frontmatter:

```yaml
---
title: Meeting Notes
type: meeting-note    # note, project, meeting-note, reference, journal, moc
tags: [work, planning]
date: 2026-04-08
status: active        # draft, active, archived
---
```

The `type` field helps the agent understand what kind of note it's
looking at without reading the full content.

## Templates

Place templates in a `templates/` folder in your vault. Use
`{{variables}}` for expansion:

```markdown
---
title: {{title}}
date: {{date}}
---

## {{title}}

Created on {{date}} at {{time}}.
```

Built-in variables: `{{title}}`, `{{date}}`, `{{time}}`, `{{datetime}}`.

Use the `create_note_from_template` MCP tool to instantiate one.
