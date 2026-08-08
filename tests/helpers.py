"""Shared bits the test modules need. Not a conftest: these are called from
inside helper functions, not injected as fixtures."""
import uuid

# managers.telegram_id and managers.max_user_id are UNIQUE, and the test database
# is not dropped between runs. Fixtures drew from ranges 10 000 wide
# ("1000 + uuid % 10000") -- fine on an empty database, hopeless once a few
# hundred runs have piled up. At 823 accumulated managers a collision was likely
# on any given run, and the insert failed inside whichever test happened to draw
# the duplicate, so the suite looked flaky rather than wrong.
#
# The column is a bigint; there is no reason to be thrifty with it.


def unique_telegram_id() -> int:
    """A telegram_id no row in the test database already holds."""
    return 10 ** 12 + int(uuid.uuid4().int % 10 ** 12)


def unique_max_user_id() -> int:
    """Same, for the MAX platform id."""
    return 2 * 10 ** 12 + int(uuid.uuid4().int % 10 ** 12)
