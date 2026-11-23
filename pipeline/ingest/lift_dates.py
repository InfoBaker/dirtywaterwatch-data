"""Conservative ordering of dated lifts and episode starts/observed returns."""
from datetime import datetime
from zoneinfo import ZoneInfo


def instant(value, zone):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return t if t.tzinfo else t.replace(tzinfo=ZoneInfo(zone))


def follows(end, precision, start, start_precision, zone, seen_at):
    """A day-only lift on a return day needs an observation later than that return.

    Callers retain the lift's first observation across replays. The same predicate
    excludes predecessors when a newer episode lies between their start and lift.
    """
    if not end or not start or not seen_at:
        return False
    x, y = instant(end, zone), instant(start, zone)
    if precision == 'day' or start_precision == 'day' or len(end) == 10 or len(start) == 10:
        xd, yd = x.astimezone(ZoneInfo(zone)).date(), y.astimezone(ZoneInfo(zone)).date()
        if xd != yd:
            return xd > yd
        return start_precision == 'day' or len(start) == 10 or instant(seen_at, zone) > y
    return x > y


def remember(observations, end, precision, at):
    """Keep the first observation of each dated lift, separate from later fetches."""
    prior = next((o for o in observations if o['date'] == end and o['precision'] == precision), None)
    if prior is None:
        prior = {'date': end, 'precision': precision, 'seen_at': at}
        observations.append(prior)
    elif instant(at, 'UTC') < instant(prior['seen_at'], 'UTC'):
        prior['seen_at'] = at
    return prior['seen_at']
