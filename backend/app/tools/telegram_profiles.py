"""Read public Telegram peer pages; generic contact templates prove nothing."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class TelegramObservation:
    status: str
    peer_type: str = "unknown"
    title: str = ""
    bio: str = ""
    signals: tuple[str, ...] = ()
    reason: str = "insufficient_public_metadata"


def observe_telegram_page(soup: BeautifulSoup, username: str) -> TelegramObservation:
    title_tag = soup.select_one(".tgme_page_title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    # A random username also receives HTTP 200, a resolve link, OG tags and
    # a contact invitation. Only the dedicated named peer header distinguishes it.
    if not title or title.lower() in {"telegram", f"@{username.lower()}"} or title.lower().startswith("telegram:"):
        return TelegramObservation("inconclusive", reason="generic_contact_or_missing_peer_header")

    bound = False
    for link in soup.select("a[href]"):
        try:
            parsed = urlsplit(str(link["href"]))
            domains = parse_qs(parsed.query).get("domain", [])
            if parsed.scheme == "tg" and parsed.netloc == "resolve" and len(domains) == 1 and domains[0].lower() == username.lower():
                bound = True
                break
        except ValueError:
            continue
    if not bound:
        return TelegramObservation("inconclusive", reason="missing_matching_resolve_link")

    extras = " ".join(tag.get_text(" ", strip=True) for tag in soup.select(".tgme_page_extra"))
    visible_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    actions = " ".join(tag.get_text(" ", strip=True) for tag in soup.select(".tgme_page_action a"))
    peer_type = "unknown"
    if re.search(r"\b(?:subscribers|suscriptores)\b", extras, re.I):
        peer_type = "channel"
    elif re.search(r"\b(?:members|miembros)\b", extras, re.I):
        peer_type = "group"
    elif (re.search(r"\bmonthly users\b", extras, re.I)
          or visible_title.lower().startswith("telegram: launch @")
          or "start bot" in actions.lower()):
        peer_type = "bot"
    elif (visible_title.lower().startswith("telegram: contact @")
          and extras.lower().strip() == f"@{username.lower()}"):
        peer_type = "user"

    description = soup.select_one(".tgme_page_description")
    bio = description.get_text(" ", strip=True) if description else ""
    return TelegramObservation("verified", peer_type, title, bio,
                               ("telegram_named_peer_header", "telegram_matching_resolve_link"), "public_peer_metadata")
