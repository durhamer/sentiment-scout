# Lazy import via PEP 562 — prevents RuntimeWarning when running
# `python -m src.collectors.reddit` (which would otherwise load reddit.py
# twice: once via this __init__ and once as __main__).

__all__ = ["RedditCollector"]


def __getattr__(name: str):
    if name == "RedditCollector":
        from .reddit import RedditCollector
        return RedditCollector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
