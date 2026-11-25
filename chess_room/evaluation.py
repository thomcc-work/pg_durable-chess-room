"""Prompt and scoring rules, independent of PostgreSQL and the provider."""

import json
import re

HINT = {"A": "", "B": "Before choosing, check that the opponent has no legal reply. "}


def prompt(variant: str, fen: str) -> str:
    return (f"Find mate in one for the side to move. {HINT[variant]}"
            "Return exactly one move in lowercase UCI coordinate notation, "
            f"with a promotion suffix if needed. No other text.\nFEN: {fen}")


def canned_reply(status: int, text: str) -> dict:
    body = ({"choices": [{"message": {"content": text}}]} if status == 200
            else {"error": {"message": text}})
    return {"status": status, "body": json.dumps(body, ensure_ascii=False)}


def grade(status: int, encoding: str | None, body: str | None, mates: list[str]) -> tuple[str, str | None]:
    if not 200 <= status < 300:
        return "provider_error", None
    if encoding != "text" or body is None:
        return "response_error", None
    try:
        content = json.loads(body)["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        return "response_error", None
    if not isinstance(content, str) or re.search(r"[\x00\ud800-\udfff]", content):
        return "response_error", None
    move = content.strip(" \t\r\n")
    if not re.fullmatch("[a-h][1-8][a-h][1-8][qrbn]?", move) or move[:2] == move[2:4]:
        return "malformed", move
    return ("mate" if move in mates else "miss"), move


def comparison(a: str, b: str) -> str:
    if a in ("pending", "recorded") or b in ("pending", "recorded"):
        return "unfinished"
    if a not in ("mate", "miss") or b not in ("mate", "miss"):
        return "needs attention"
    if a == b:
        return "same"
    return "B gain" if b == "mate" else "B regression"
