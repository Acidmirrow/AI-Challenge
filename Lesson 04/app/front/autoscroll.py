"""Автоскролл чатов к последнему сообщению для всех страниц AI Challenge."""

from __future__ import annotations

import streamlit.components.v1 as components

_JS = """
<script>
(() => {
  const parent = window.parent;
  if (!parent) return;
  const doc = parent.document;

  const scrollChats = () => {
    const messages = [...doc.querySelectorAll('[data-testid="stChatMessage"]')];
    const containers = new Set();
    for (const message of messages) {
      let node = message.parentElement;
      while (node && node !== doc.body) {
        const style = parent.getComputedStyle(node);
        const scrollable = style.overflowY === 'auto' || style.overflowY === 'scroll';
        if (scrollable && node.scrollHeight > node.clientHeight + 8) {
          containers.add(node);
          break;
        }
        node = node.parentElement;
      }
    }
    containers.forEach((node) => {
      node.scrollTop = node.scrollHeight;
    });
  };

  let scheduled = false;
  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    parent.requestAnimationFrame(() => {
      scheduled = false;
      scrollChats();
    });
  };

  if (!parent.__hermesChatAutoscroll) {
    parent.__hermesChatAutoscroll = () => scrollChats();
    new parent.MutationObserver(schedule).observe(doc.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }
  [40, 160, 400, 800, 1400].forEach((delay) => parent.setTimeout(scrollChats, delay));
})();
</script>
"""


def install() -> None:
    """Подключить автоскролл к последнему сообщению во всех чатах."""
    components.html(_JS, height=0)
