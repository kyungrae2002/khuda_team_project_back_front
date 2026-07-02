"""Parses Google Places API (New) regularOpeningHours JSON into a simple
(open_time, close_time) pair for a given calendar date."""

from datetime import date, time

from app.models.place import Place


def get_opening_period(place: Place, day_date: date) -> tuple[time, time] | None:
    if not place.opening_hours:
        return None
    periods = place.opening_hours.get("periods")
    if not periods:
        return None

    # Google's Places API day field is 0=Sunday..6=Saturday. Python's
    # date.weekday() is 0=Monday..6=Sunday, so shift by one and wrap.
    google_weekday = (day_date.weekday() + 1) % 7

    for period in periods:
        open_info = period.get("open")
        if not open_info or open_info.get("day") != google_weekday:
            continue

        open_time = time(open_info.get("hour", 0), open_info.get("minute", 0))
        close_info = period.get("close")
        if close_info and close_info.get("day") == google_weekday:
            close_time = time(close_info.get("hour", 23), close_info.get("minute", 59))
        else:
            # Overnight hours (closes the next day) or missing close info —
            # treat as open until end of day rather than modeling the rollover.
            close_time = time(23, 59)
        return open_time, close_time

    return None
