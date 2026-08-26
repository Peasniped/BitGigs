"""The log line format, and the colour on its severity.

One formatter class serves both sinks, because a log line should read the same
wherever it lands::

    2026-08-13 09:45:47  INFO      [core.apps]                -> Using Loglevel: INFO

Colour is applied to the severity only, and only on a real terminal — a file
handler and a piped stream (``docker compose logs``, journald) get the plain
text, or every line would carry escape sequences that only a terminal can read
and every grep would have to account for them.

This module is imported by the ``LOGGING`` dictConfig in
``config/settings/base.py``, which Django applies during ``django.setup()``
*before* the app registry is populated. So it must stay import-light: stdlib
only, plus one guarded Django import that is not needed for it to work.
"""
import logging
import sys

# The bracketed source is the *logger* name, which for the getLogger(__name__)
# that every module uses is the dotted path of the file itself (core.views =
# apps/core/views.py). record.filename would print "views.py", and eleven apps
# have one of those.
FORMAT = "{asctime}  {level_tag}  {source_tag} -> {message}"
DATEFMT = "%Y-%m-%d %H:%M:%S"

RESET = "\033[0m"
LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",     # cyan
    logging.INFO: "\033[32m",      # green
    logging.WARNING: "\033[33m",   # yellow
    logging.ERROR: "\033[31m",     # red
    logging.CRITICAL: "\033[1;31m",  # bold red — worse than error, and it shows
}

# Plain magenta rather than bright (95): the bright variant washes out on a light
# terminal background, and this has to stay legible on both. Only the name is
# tinted — the brackets stay in the body colour, so they read as punctuation
# holding the name rather than as part of it.
SOURCE_COLOR = "\033[35m"  # purple

LEVEL_WIDTH = 8  # len("CRITICAL"), so the level column is the same width always

# Wide enough for the longest name in play (django.utils.autoreload, 23 + the two
# brackets). Both columns are padded so the messages line up into one readable
# column down the page instead of each starting wherever its source name ended.
# A longer name than this overflows and pushes its own arrow right — it costs
# that one line's alignment, which is better than sizing for a hypothetical.
SOURCE_WIDTH = 25


def _stream_supports_color(stream) -> bool:
    """Whether ANSI escapes will render rather than be printed literally.

    Two independent questions: is this stream a terminal at all (a pipe or a
    file is not), and does *this* terminal understand the codes — which on
    Windows is not a given. Django already answers the second one, including the
    Windows Terminal / VT-registry cases, so defer to it rather than re-deriving
    it here; if it can't be imported for any reason, having established the
    stream is a tty is enough to try.
    """
    if not (hasattr(stream, "isatty") and stream.isatty()):
        return False
    try:
        from django.core.management.color import supports_color
    except Exception:  # pragma: no cover - Django is always importable here
        return True
    return supports_color()


class BitGigsFormatter(logging.Formatter):
    """The app's log format, optionally colouring the severity.

    ``color`` is a tri-state: True/False force it, and None (the default) decides
    once, on first use, from the stream the console handler writes to. It is
    resolved lazily rather than in ``__init__`` because the config is built
    during settings import, when stdio may not yet be what it will be.
    """

    def __init__(self, *args, color=None, **kwargs):
        kwargs.setdefault("fmt", FORMAT)
        kwargs.setdefault("datefmt", DATEFMT)
        kwargs.setdefault("style", "{")
        super().__init__(*args, **kwargs)
        self._color = color

    def uses_color(self) -> bool:
        if self._color is None:
            # StreamHandler's default stream, i.e. where `console` writes.
            self._color = _stream_supports_color(sys.stderr)
        return self._color

    def _level_tag(self, record) -> str:
        # Pad *before* colouring: the escape codes have no width on screen but
        # every bit as much width to str.format, so padding a coloured string
        # would leave each level indented by a different amount.
        tag = f"{record.levelname:<{LEVEL_WIDTH}}"
        if not self.uses_color():
            return tag
        color = LEVEL_COLORS.get(record.levelno)
        return f"{color}{tag}{RESET}" if color else tag

    def _source_tag(self, record) -> str:
        # Same reasoning as the level column, but it can't be done with a format
        # width here: the padding has to sit *outside* the escape codes while the
        # width is measured on the visible text alone, so it's counted by hand
        # from the name rather than from the string being padded.
        tag = (
            f"[{SOURCE_COLOR}{record.name}{RESET}]"
            if self.uses_color()
            else f"[{record.name}]"
        )
        visible = len(record.name) + 2  # the brackets
        return tag + " " * max(0, SOURCE_WIDTH - visible)

    def format(self, record):
        # Derived attributes rather than rewritten levelname/name: one record is
        # handed to every handler in turn, so mutating a real field would leak
        # this formatter's colour into the file handler's copy of the line.
        record.level_tag = self._level_tag(record)
        record.source_tag = self._source_tag(record)
        return super().format(record)
