from uuid import UUID


def parse_uuid(value: object) -> UUID | None:
    """The UUID in ``value`` (any of the usual spellings), or None if it is not one.

    For ids from a query string or a form, where a missing or wrong value means "no filter" instead of an error.
    """
    try:
        return UUID(str(value))
    except ValueError:
        return None
