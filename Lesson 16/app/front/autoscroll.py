"""Автоскролл страницы к последнему сообщению."""

from __future__ import annotations

import streamlit.components.v1 as components


def install() -> None:
    components.html("""
    <script>
    const doc = window.parent.document;
    const scroll = () => {
      const main = doc.querySelector('[data-testid="stMain"]');
      if (main) main.scrollTop = main.scrollHeight;
    };
    setTimeout(scroll, 100);
    setTimeout(scroll, 350);
    </script>
    """, height=0)
