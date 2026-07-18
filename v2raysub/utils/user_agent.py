# -*- coding: utf-8 -*-
"""User-Agent client classification."""


def parse_user_agent(ua_string):
    """Classify a User-Agent string into a known client name (see CLIENTS).

    Order matters: some clients embed other clients' names in their own UA
    string (e.g. HiddifyNext's UA contains both "ClashMeta" and "sing-box"
    since it bundles those cores), so the more specific/composite strings
    must be checked before the generic ones they'd otherwise be caught by.
    """
    if not ua_string:
        return 'Other'
    ua = ua_string.lower()

    if 'hiddify' in ua:
        return 'Hiddify'
    if 'flclash' in ua:
        return 'FlClash'
    if 'karing' in ua:
        return 'Karing'
    if 'streisand' in ua:
        return 'Streisand'
    if 'napsternet' in ua:
        return 'NapsternetV'
    if 'v2rayng' in ua:
        return 'v2rayNG'
    if 'v2rayn' in ua:
        # v2rayN (Windows desktop) — checked after v2rayNG, whose UA also
        # contains this substring, so v2rayNG is never misclassified here.
        return 'v2rayN'
    if 'nekobox' in ua or 'nekoray' in ua or 'husi' in ua:
        return 'Nekobox'
    if 'shadowrocket' in ua:
        return 'Shadowrocket'
    if 'clash' in ua or 'mihomo' in ua:
        return 'Clash'
    if 'sing-box' in ua:
        return 'Sing-box'
    if 'bot' in ua or 'mozilla' in ua:
        # Link-preview bots (Telegram, generic crawlers) and plain browser
        # visits aren't subscription clients at all. Keep them out of
        # 'Other' so that bucket stays a useful signal for "a real client we
        # don't recognize yet" instead of being swamped by non-client traffic.
        return 'Browser/Bot'
    return 'Other'