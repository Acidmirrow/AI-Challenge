"""Включает отправку формы чата по Enter в textarea Streamlit."""

from __future__ import annotations

import streamlit.components.v1 as components

_JS = """
<script>
(() => {
  const parent = window.parent;
  if (parent.__hermesEnterSubmitInstalled) return;
  parent.__hermesEnterSubmitInstalled = true;
  const doc = parent.document;

  const bind = () => {
    doc.querySelectorAll('form, [data-testid="stForm"]').forEach((form) => {
      const send = [...form.querySelectorAll("button")].find(
        (button) => button.innerText.trim() === "Отправить"
      );
      if (!send) return;
      form.querySelectorAll("textarea").forEach((area) => {
        if (area.dataset.hermesEnterBound) return;
        area.dataset.hermesEnterBound = "1";
        area.addEventListener("keydown", (event) => {
          if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
          if (!area.value.trim()) return;
          event.preventDefault();
          send.click();
        });
      });
    });
  };

  bind();
  new parent.MutationObserver(bind).observe(doc.body, {
    childList: true,
    subtree: true,
  });
})();
</script>
"""


def install() -> None:
    """Подключить Enter-отправку для textarea-форм с кнопкой «Отправить»."""
    components.html(_JS, height=0)
