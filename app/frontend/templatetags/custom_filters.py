from datetime import datetime, timedelta

from django import template

register = template.Library()

@register.filter
def duration(start: datetime, end: datetime) -> str:
    """
    Calculate the duration between two datetime objects and return a string of format H:MM
    :param start: datetime
    :param end: datetime
    :return: timedelta
    """

    d = end - start
    hours, remainder = divmod(d.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    return f"{hours}:{minutes:02d}"

@register.filter
def format_timedelta(d: timedelta) -> str:
    """
    Format a timedelta object as H:MM
    :param d: timedelta
    :return: str
    """

    try:
      total_seconds = int(d.total_seconds())
      hours, remainder = divmod(total_seconds, 3600)
      minutes, _ = divmod(remainder, 60)
      return f"{hours}:{minutes:02d}"
    except AttributeError:
      return d

@register.filter
def get_item(dictionary: dict, key: str) -> any:
    """
    Get an item from a dictionary
    :param dictionary: dict
    :param key: str
    :return: any
    """
    return dictionary.get(key)
