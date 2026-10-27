"""Zweisprachige Fassung (DE/EN) des Stronghold Sprite Editors erzeugen.

Die gepruefte Editordatei bleibt unveraendert. Erzeugt wird
``Stronghold_Sprite_Editor_EN.html``: dieselbe Datei plus ein kleines
Sprachskript (Woerterbuch aus en.json), das alle festen Texte, Tooltips und
Platzhalter umsetzt - auch in spaeter eingeblendeten Dialogen (DOM-Beobachter).
Oben rechts schaltet ein Knopf DE <-> EN um; die Wahl bleibt im Browser.

    python extras/sprite-editor/sprache/einbauen.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EDITOR = HERE.parent / "Stronghold_Sprite_Editor.html"
TARGET = HERE.parent / "Stronghold_Sprite_Editor_EN.html"

SCRIPT = r"""
<script>
(() => {
  'use strict';
  const EN = __TABLE__;
  const DE = Object.fromEntries(Object.entries(EN).map(([k, v]) => [v, k]));
  const KEY = 'sse-sprache';
  let lang = 'en';
  try { lang = localStorage.getItem(KEY) || 'en'; } catch (e) { /* ohne Speicher: Englisch */ }
  const ATTRS = ['title', 'placeholder', 'aria-label'];
  function swap(text, table) {
    if (!text) return text;
    const trimmed = text.trim();
    if (!trimmed || !(trimmed in table)) return text;
    return text.replace(trimmed, table[trimmed]);
  }
  function translate(root, table) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement && ['SCRIPT', 'STYLE', 'TEXTAREA'].includes(node.parentElement.tagName)) continue;
      const next = swap(node.nodeValue, table);
      if (next !== node.nodeValue) node.nodeValue = next;
    }
    const elements = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of [root, ...elements]) {
      if (!el.getAttribute) continue;
      for (const a of ATTRS) {
        const value = el.getAttribute(a);
        const next = swap(value, table);
        if (next !== value) el.setAttribute(a, next);
      }
    }
  }
  function apply() {
    translate(document.body, lang === 'en' ? EN : DE);
    const parts = document.title.split(' — ');
    const table = lang === 'en' ? EN : DE;
    if (parts[0] in table) document.title = [table[parts[0]], ...parts.slice(1)].join(' — ');
    document.documentElement.lang = lang;
    button.textContent = lang === 'en' ? 'DE' : 'EN';
    button.title = lang === 'en' ? 'Deutsch' : 'English';
  }
  const button = document.createElement('button');
  button.type = 'button';
  button.style.cssText = 'position:fixed;bottom:4px;right:90px;z-index:99999;padding:3px 9px;font:12px sans-serif;' +
    'border-radius:4px;border:1px solid #888;background:#2b2d31;color:#e8e6e3;cursor:pointer;opacity:.85';
  button.addEventListener('click', () => {
    lang = lang === 'en' ? 'de' : 'en';
    try { localStorage.setItem(KEY, lang); } catch (e) { /* egal */ }
    apply();
  });
  let busy = false;
  const observer = new MutationObserver(records => {
    if (busy || lang !== 'en') return;
    busy = true;
    try {
      for (const r of records) {
        if (r.type === 'characterData' && r.target.parentNode) translate(r.target.parentNode, EN);
        for (const n of r.addedNodes || []) {
          if (n.nodeType === 1) translate(n, EN);
          else if (n.nodeType === 3 && n.parentNode) translate(n.parentNode, EN);
        }
        if (r.type === 'attributes' && r.target.nodeType === 1) translate(r.target, EN);
      }
    } finally { busy = false; }
  });
  function start() {
    document.body.appendChild(button);
    apply();
    observer.observe(document.body, { childList: true, subtree: true, characterData: true,
                                      attributes: true, attributeFilter: ATTRS });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
</script>
"""


def build() -> Path:
    html = EDITOR.read_text(encoding="utf-8")
    table = json.loads((HERE / "en.json").read_text(encoding="utf-8"))
    payload = json.dumps(table, ensure_ascii=False).replace("</", "<\\/")
    script = SCRIPT.replace("__TABLE__", payload)
    marker = "</body>"
    if marker not in html:
        raise SystemExit("Editordatei ohne </body> - unbekanntes Format")
    head, tail = html.rsplit(marker, 1)
    TARGET.write_text(head + script + marker + tail, encoding="utf-8", newline="\n")
    return TARGET


if __name__ == "__main__":
    print(build())
