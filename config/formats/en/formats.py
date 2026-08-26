"""Danish number formatting for the (English) active locale — the "en-DK" setup.

Only the number-separator keys are overridden here; every other format key
(dates, times, …) falls through to Django's bundled ``en`` locale. This module
wins over Django's built-ins because FORMAT_MODULE_PATH is consulted first.
"""
DECIMAL_SEPARATOR = ","
THOUSAND_SEPARATOR = "."
NUMBER_GROUPING = 3
