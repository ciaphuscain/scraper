"""Choose which caption track to use, following the documented priority:

1. creator-provided (manual) captions in a preferred language
2. automatic captions in a preferred language, *original audio only*
3. manual captions in the video's original language
4. automatic captions in the original language
5. any manual captions

Auto-translated tracks are never used: they are not the spoken content.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FORMAT_PREFERENCE = ["vtt", "srt", "json3"]


@dataclass
class TrackChoice:
    method: str  # manual_captions | auto_captions
    language: str
    ext: str
    url: str
    name: str | None = None


def _lang_matches(key: str, lang: str) -> bool:
    key_l, lang_l = key.lower(), lang.lower()
    return key_l == lang_l or key_l.split("-")[0] == lang_l.split("-")[0]


def _pick_format(formats: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_ext = {f.get("ext"): f for f in formats if f.get("url")}
    for ext in FORMAT_PREFERENCE:
        if ext in by_ext:
            return by_ext[ext]
    return None


def _original_auto_keys(autos: dict[str, Any], orig_lang: str | None) -> list[str]:
    keys = [k for k in autos if k.endswith("-orig")]
    if orig_lang:
        keys += [k for k in autos if k == orig_lang]
    return keys


def choose_track(info: dict[str, Any], preferred: list[str], allow_auto: bool = True) -> TrackChoice | None:
    subs = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat" and v}
    autos = {k: v for k, v in (info.get("automatic_captions") or {}).items() if v}
    orig = info.get("language")
    orig_auto_keys = _original_auto_keys(autos, orig)

    def make(method: str, key: str, formats: list[dict[str, Any]]) -> TrackChoice | None:
        f = _pick_format(formats)
        if not f:
            return None
        lang = key.removesuffix("-orig")
        return TrackChoice(method, lang, f.get("ext", "vtt"), f["url"], f.get("name"))

    for lang in preferred:
        for key, formats in subs.items():
            if _lang_matches(key, lang) and (c := make("manual_captions", key, formats)):
                return c
    if allow_auto:
        for lang in preferred:
            for key in orig_auto_keys:
                if _lang_matches(key.removesuffix("-orig"), lang) and (c := make("auto_captions", key, autos[key])):
                    return c
            # If YouTube doesn't mark the original track, accept a preferred-language auto
            # track only when it matches the declared original language.
            if orig and _lang_matches(orig, lang):
                for key, formats in autos.items():
                    if _lang_matches(key, lang) and (c := make("auto_captions", key, formats)):
                        return c
    if orig:
        for key, formats in subs.items():
            if _lang_matches(key, orig) and (c := make("manual_captions", key, formats)):
                return c
        if allow_auto:
            for key in orig_auto_keys:
                if c := make("auto_captions", key, autos[key]):
                    return c
    for key, formats in subs.items():
        if c := make("manual_captions", key, formats):
            return c
    return None
