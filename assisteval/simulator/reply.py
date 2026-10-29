"""Asistan cevabını (metin + buton + kart içeren JSON) sade bir yapıya çevirir.

Gerçek cevap formatının örneği henüz elimizde olmadığı için ayrıştırma sezgisel:
JSON ağacı gezilir, metin alanları, kartlar ve butonlar (başlık + aksiyon) toplanır.
Ham cevap her zaman `raw` içinde saklanır, transcript'e de o yazılır.
"""

from dataclasses import dataclass, field
from typing import Any

TEXT_KEYS = ("text", "message", "content")
BUTTON_LIST_KEYS = ("buttons", "quick_replies", "quickreplies", "actions", "options")
BUTTON_TITLE_KEYS = ("title", "text", "label", "name", "caption")
BUTTON_ACTION_KEYS = ("payload", "action", "value", "postback", "url", "intent")


@dataclass
class Button:
    title: str
    payload: str | None = None

    def to_dict(self) -> dict:
        return {"title": self.title, "payload": self.payload}


@dataclass
class Reply:
    texts: list[str] = field(default_factory=list)
    buttons: list[Button] = field(default_factory=list)
    raw: Any = None

    @property
    def text(self) -> str:
        return "\n".join(self.texts)

    def find_button(self, wanted: str) -> Button | None:
        """Başlığa (veya aksiyona) göre buton bulur; önce birebir, sonra içerir eşleşmesi."""
        wanted_n = _norm(wanted)
        for b in self.buttons:
            if _norm(b.title) == wanted_n or (b.payload and _norm(b.payload) == wanted_n):
                return b
        for b in self.buttons:
            if wanted_n and wanted_n in _norm(b.title):
                return b
        return None

    def render(self) -> str:
        """Simülatör LLM'ine ve konsola gösterilecek okunur hali."""
        lines = list(self.texts) or ["(metin yok)"]
        if self.buttons:
            lines.append("Butonlar:")
            lines += [f"  [{b.title}] → {b.payload}" for b in self.buttons]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"texts": self.texts, "buttons": [b.to_dict() for b in self.buttons]}


def parse_reply(raw: Any) -> Reply:
    reply = Reply(raw=raw)
    _walk(raw, reply)
    return reply


def _walk(node: Any, reply: Reply) -> None:
    if isinstance(node, str):
        if node.strip():
            reply.texts.append(node.strip())
        return
    if isinstance(node, list):
        for item in node:
            _walk(item, reply)
        return
    if not isinstance(node, dict):
        return

    lower = {k.lower(): k for k in node}
    handled = set()

    card_title = None
    if _looks_like_card(lower):
        card_title = _first_str(node, lower, ("title",))
        subtitle = _first_str(node, lower, ("subtitle", "description"))
        reply.texts.append("[Kart] " + " - ".join(p for p in (card_title, subtitle) if p))
        handled |= {lower[k] for k in ("title", "subtitle", "description") if k in lower}

    for key in BUTTON_LIST_KEYS:
        if key in lower and isinstance(node[lower[key]], list):
            handled.add(lower[key])
            for item in node[lower[key]]:
                button = _as_button(item)
                if button:
                    # Kart butonları ("Detay" gibi) hangi karta ait olduklarını kaybetmesin
                    if card_title:
                        button.title = f"{card_title} › {button.title}"
                    reply.buttons.append(button)

    for key in TEXT_KEYS:
        if key in lower and isinstance(node[lower[key]], str):
            handled.add(lower[key])
            if node[lower[key]].strip():
                reply.texts.append(node[lower[key]].strip())

    for key, value in node.items():
        if key not in handled and isinstance(value, (dict, list)):
            _walk(value, reply)


def _as_button(item: Any) -> Button | None:
    if isinstance(item, str):
        return Button(title=item, payload=item)
    if not isinstance(item, dict):
        return None
    lower = {k.lower(): k for k in item}
    title = _first_str(item, lower, BUTTON_TITLE_KEYS)
    payload = _first_str(item, lower, BUTTON_ACTION_KEYS)
    if not title and not payload:
        return None
    return Button(title=title or payload, payload=payload)


def _looks_like_card(lower: dict) -> bool:
    return "title" in lower and any(k in lower for k in ("subtitle", "description", "image_url", "image", *BUTTON_LIST_KEYS))


def _first_str(node: dict, lower: dict, keys) -> str | None:
    for key in keys:
        if key in lower and isinstance(node[lower[key]], (str, int, float)) and str(node[lower[key]]).strip():
            return str(node[lower[key]]).strip()
    return None


def _norm(s: str) -> str:
    return " ".join(s.casefold().split())
