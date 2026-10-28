import json
import os
import functools

_EMOJI_MAP: dict = {}
_SORTED_EMOJIS: list = []
_LOADED = False


def _load():
    global _EMOJI_MAP, _SORTED_EMOJIS, _LOADED
    if _LOADED:
        return
    _LOADED = True
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "ftm.json",
    )
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        free_map: dict = {}
        any_map: dict = {}
        for item in data:
            alt = item.get("alt", "")
            eid = str(item.get("emoji_id", ""))
            if not alt or not eid:
                continue
            if item.get("free") and alt not in free_map:
                free_map[alt] = eid
            if alt not in any_map:
                any_map[alt] = eid
        _EMOJI_MAP = {**any_map, **free_map}
        _SORTED_EMOJIS = sorted(_EMOJI_MAP.keys(), key=len, reverse=True)
        print(f"[EMOJI] Loaded {len(_EMOJI_MAP)} animated emojis")
    except Exception as e:
        print(f"[EMOJI] Failed to load emoji map: {e}")


def ae(text: str) -> str:
    """Replace plain emojis in text with Telegram animated <tg-emoji> tags."""
    _load()
    if not _EMOJI_MAP or not text:
        return text

    result = []
    i = 0
    length = len(text)
    while i < length:
        # Skip already-wrapped emoji tags
        if text[i:i + 7] == "<emoji ":
            end = text.find("</emoji>", i)
            if end != -1:
                result.append(text[i: end + 8])
                i = end + 8
                continue

        # Try to match an emoji (longest match first)
        matched = False
        for emoji in _SORTED_EMOJIS:
            elen = len(emoji)
            if text[i: i + elen] == emoji:
                eid = _EMOJI_MAP[emoji]
                result.append(f'<emoji id="{eid}">{emoji}</emoji>')
                i += elen
                matched = True
                break

        if not matched:
            result.append(text[i])
            i += 1

    return "".join(result)


def _make_wrapper(original, text_kwarg="text", text_pos=1, pm_pos=2):
    """
    Wrap a Pyrogram send/edit method to:
    1. Replace plain emojis with animated <tg-emoji> HTML tags via ae()
    2. Force parse_mode=HTML when tg-emoji tags were added and no parse_mode was set
    3. Skip ae() entirely for MARKDOWN messages (tags won't render there)

    text_pos : positional index of the text argument (0 = self)
    pm_pos   : positional index of the parse_mode argument (0 = self)
    """
    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        from pyrogram import enums as _enums

        args = list(args)

        # Resolve current parse_mode (kwarg wins over positional)
        pm_kwarg = kwargs.get("parse_mode")
        pm_arg   = args[pm_pos] if len(args) > pm_pos else None
        current_pm = pm_kwarg if pm_kwarg is not None else pm_arg

        # Don't touch MARKDOWN messages — tg-emoji tags would render as literal text
        if current_pm in (_enums.ParseMode.MARKDOWN,):
            return original(*args, **kwargs)

        # Apply ae() to the text (positional or keyword)
        transformed = False

        if len(args) > text_pos and isinstance(args[text_pos], str):
            new_text = ae(args[text_pos])
            if new_text != args[text_pos]:
                args[text_pos] = new_text
                transformed = True

        if text_kwarg in kwargs and isinstance(kwargs[text_kwarg], str):
            new_text = ae(kwargs[text_kwarg])
            if new_text != kwargs[text_kwarg]:
                kwargs[text_kwarg] = new_text
                transformed = True

        # Inject parse_mode=HTML when tg-emoji was added and parse_mode not already set
        if transformed and current_pm is None:
            kwargs["parse_mode"] = _enums.ParseMode.HTML

        return original(*args, **kwargs)

    wrapper._ae_patched = True
    return wrapper


def patch_all():
    """
    Patch Pyrogram send/edit methods so every outgoing message text
    automatically gets animated emojis applied.
    """
    _load()

    from pyrogram import Client
    from pyrogram.types import Message, CallbackQuery

    # (class, method_name, text_pos, pm_pos)
    # All indices are 0-based including self:
    #   self=0  for all bound methods
    targets = [
        # Client methods
        # send_message(self, chat_id, text, parse_mode, ...)
        (Client,        "send_message",         2, 3),
        # edit_message_text(self, chat_id, message_id, text, parse_mode, ...)
        (Client,        "edit_message_text",     3, 4),
        # Message methods
        # reply_text(self, text, quote, parse_mode, ...)
        (Message,       "reply_text",            1, 3),
        # reply = alias for reply_text
        (Message,       "reply",                 1, 3),
        # edit_text(self, text, parse_mode, ...)
        (Message,       "edit_text",             1, 2),
        # edit = alias for edit_text
        (Message,       "edit",                  1, 2),
        # CallbackQuery methods
        # edit_message_text(self, text, parse_mode, ...)
        (CallbackQuery, "edit_message_text",     1, 2),
    ]

    patched = 0
    for cls, method_name, text_pos, pm_pos in targets:
        original = getattr(cls, method_name, None)
        if original is None:
            continue
        if getattr(original, "_ae_patched", False):
            continue
        wrapper = _make_wrapper(original,
                                text_kwarg="text",
                                text_pos=text_pos,
                                pm_pos=pm_pos)
        setattr(cls, method_name, wrapper)
        patched += 1

    print(f"[EMOJI] Patched {patched} Pyrogram methods — animated emojis active everywhere")
