"""Convert job log stanzas to GitHub Check markdown (e.g. collapsible <details>/<summary>)."""

import re


def collapsible_stanza_to_details(text: str) -> str:
    """
    Convert ::: Title ... ::: stanzas to <details><summary>Title</summary>...</details>.
    - Line "::: Title" starts a collapsible; content until next ":::" or end is the body.
    - Body is wrapped in a code block so it is safe and readable.
    """
    out: list[str] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^:::(\s+(.*))?$", line.strip())
        if m:
            title = (m.group(2) or "Details").strip()
            i += 1
            body_lines: list[str] = []
            while i < len(lines) and not re.match(r"^:::(\s|$)", lines[i].strip()):
                body_lines.append(lines[i])
                i += 1
            body = "\n".join(body_lines)
            out.append("<details>")
            out.append(f"<summary>{_escape_html(title)}</summary>")
            out.append("")
            out.append("```")
            out.append(body)
            out.append("```")
            out.append("")
            out.append("</details>")
            if i < len(lines) and lines[i].strip().startswith(":::"):
                i += 1  # consume closing :::
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
