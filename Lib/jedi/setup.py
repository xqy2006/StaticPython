from __future__ import annotations

from libs import simple_library


JEDI_PARSER_CACHE_OLD = '''def get_parso_cache_node(grammar, path):
    """
    This is of course not public. But as long as I control parso, this
    shouldn't be a problem. ~ Dave

    The reason for this is mostly caching. This is obviously also a sign of a
    broken caching architecture.
    """
    return parser_cache[grammar._hashed][path]
'''


JEDI_PARSER_CACHE_NEW = '''def get_parso_cache_node(grammar, path):
    """
    This is of course not public. But as long as I control parso, this
    shouldn't be a problem. ~ Dave

    The reason for this is mostly caching. This is obviously also a sign of a
    broken caching architecture.
    """
    cache = parser_cache[grammar._hashed]
    try:
        return cache[path]
    except KeyError:
        normalized = str(path).replace("\\\\", "/")
        marker = "staticpython-resource:/"
        marker_index = normalized.rfind(marker)
        if marker_index < 0:
            raise
        identity = normalized[marker_index:]
        matches = []
        for cached_path, cache_node in cache.items():
            cached = str(cached_path).replace("\\\\", "/")
            cached_marker_index = cached.rfind(marker)
            if cached_marker_index >= 0 and cached[cached_marker_index:] == identity:
                matches.append(cache_node)
        if len(matches) == 1:
            return matches[0]
        raise
'''


LIBRARY_INTEGRATION = simple_library(
    name="jedi",
    dependencies=["parso"],
    overlay_entries=["Lib/jedi"],
    patch_rules=[
        {
            "package": ">=0.20,<0.21",
            "path": "Lib/jedi/parser_utils.py",
            "replacements": [
                {
                    "old": JEDI_PARSER_CACHE_OLD,
                    "new": JEDI_PARSER_CACHE_NEW,
                    "count": 1,
                }
            ],
        }
    ],
)
