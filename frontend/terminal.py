from __future__ import annotations

import html
from datetime import datetime

import streamlit as st


TONES = {"dim":"#68727d","info":"#8ab4f8","ok":"#7ee787","warn":"#e3b341","accent":"#bc8cff","code":"#79c0ff","crash":"#e0952f","cause":"#37c9b9"}
CHANNEL_TONE = {"GREPTILE LIVE":"ok","GREPTILE FAILURE":"crash","GREPTILE REVIEW":"accent","CALLGRAPH":"code","FUSION":"cause","PATCH":"cause","CITE":"crash","FIXTURE":"accent"}


def script_rows(events: list[tuple[float, str, str, str]], cursor: int) -> list[tuple[str, str, str, str]]:
    now = datetime.now().strftime("%H:%M:%S")
    return [(now, channel, text, tone) for _delay, channel, text, tone in events[:cursor]]


def to_html(rows: list[tuple[str, str, str, str]]) -> str:
    if not rows:
        body = '<div class="idle"><i>idle — press Diagnose</i></div>'
    else:
        rendered = []
        for stamp, channel, text, tone in rows:
            color = TONES.get(tone, TONES["dim"])
            content = html.escape(text) or "&nbsp;"
            rendered.append(f'<div><span class="ts">{html.escape(stamp)}</span> <span style="color:{color}">[{html.escape(channel)}]</span> {content}</div>')
        body = "".join(rendered)
    return f'<div class="terminal">{body}</div>'


def render(rows: list[tuple[str, str, str, str]]) -> None:
    document = f"""
    <style>
    html,body{{margin:0;background:transparent}}
    .terminal{{box-sizing:border-box;height:520px;overflow-y:auto;display:flex;flex-direction:column;
    background:linear-gradient(180deg,#0b111a,#070a10);color:#c9d1d9;border:1px solid #25344a;
    border-radius:14px;padding:16px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
    white-space:pre;font-size:.82rem;line-height:1.55}}
    .ts{{color:#687b93}}.idle{{color:#687b93}}
    </style>
    {to_html(rows)}
    <script>
    const terminal = document.querySelector('.terminal');
    terminal.scrollTop = terminal.scrollHeight;
    requestAnimationFrame(() => {{ terminal.scrollTop = terminal.scrollHeight; }});
    </script>
    """
    st.iframe(document, height=522, width="stretch")
