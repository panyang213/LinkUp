"""Who is online (registered users). In-memory; use Redis for multi-process deployments."""
from collections import Counter

_conns = Counter()


def add(uid):
    _conns[uid] += 1
    return _conns[uid] == 1      # True if this is their first connection


def remove(uid):
    _conns[uid] -= 1
    if _conns[uid] <= 0:
        _conns.pop(uid, None)
        return True               # that was their last connection
    return False


def is_online(uid):
    return _conns.get(uid, 0) > 0


def count():
    return len(_conns)
