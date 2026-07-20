"""Lead magnet calculators & tools. TZ section 29 (LM-2/3/4/6).

Each module is a pure, dependency-light calculator so it can be unit tested
without a database or network. The router (app/routers/lead_magnets.py) wraps
them with rate limiting, 152-FZ consent capture and lead dedup.
"""
