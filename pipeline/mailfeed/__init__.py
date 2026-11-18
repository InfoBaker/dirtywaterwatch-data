"""The e-mail feed's private half (not a feed of the refresh): run by the private site repository's mail-feed job only.

It reads the site's D1 database and its archive of raw mail, which this repository's own token cannot reach and its
hourly refresh never reads (tests/test_mail_feed_split.py fails if a module the refresh runs does). See read.py.
"""
