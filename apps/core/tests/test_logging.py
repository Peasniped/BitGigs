"""The logging configuration and the log lines that carry operational weight.

Django only ever configures a handler for its own ``django`` logger, so before
``LOGGING`` existed an app module's ``logger.info()`` went nowhere at all. These
tests pin the wiring that fixes that — app loggers reach a handler, third-party
noise does not — plus the sign-in trail, which is the one thing a self-hosted
install on the open internet really wants recorded.
"""
import logging
import os
import re
import sys
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from core.crypto import decrypt_secret
from core.utils import client_ip


class LoggingConfigTests(TestCase):
    """The dictConfig in bitgigs/settings/base.py, as actually applied."""

    def test_app_loggers_reach_a_handler(self):
        """Every app in LOCAL_APPS gets a logger that propagates to root's
        handler. This is what makes logger.info() in e.g. calendar_sync/invites.py
        visible at all — the bug the config exists to fix."""
        from django.conf import settings

        root = logging.getLogger()
        self.assertTrue(root.handlers, "root logger has no handler")
        for entry in settings.LOCAL_APPS:
            name = entry.split(".")[0]
            with self.subTest(app=name):
                logger = logging.getLogger(name)
                self.assertTrue(logger.propagate)
                self.assertEqual(
                    logger.getEffectiveLevel(), getattr(logging, settings.LOG_LEVEL),
                )

    def test_module_logger_inherits_its_app_level(self):
        """Modules use getLogger(__name__), which under apps/ is a dotted name
        below the app label — so the app's level has to reach it."""
        from django.conf import settings

        logger = logging.getLogger("calendar_sync.invites")
        self.assertEqual(
            logger.getEffectiveLevel(), getattr(logging, settings.LOG_LEVEL),
        )

    def test_third_party_loggers_stay_at_warning(self):
        """Libraries inherit root, not the app level — routine INFO chatter from
        a dependency must not drown out BitGigs' own lines."""
        self.assertEqual(
            logging.getLogger("some.third.party.library").getEffectiveLevel(),
            logging.WARNING,
        )

    def test_console_handler_is_not_debug_filtered(self):
        """Django's own `console` handler carries require_debug_true, which is
        exactly why nothing was ever visible in production. Redefining the name
        must not inherit that filter."""
        from django.conf import settings

        console = settings.LOGGING["handlers"]["console"]
        self.assertNotIn("filters", console)

    def test_django_logger_does_not_double_log(self):
        """`django` has its own handler, so it must not also propagate to root —
        that would print every framework message twice."""
        self.assertFalse(logging.getLogger("django").propagate)

    def test_django_logger_follows_the_configured_level(self):
        """django.server and django.utils.autoreload are *the* lines a dev sees
        at startup. While `django` was pinned at INFO, turning LOG_LEVEL down
        changed nothing visible and the variable looked broken."""
        from django.conf import settings

        for name in ("django", "django.server", "django.utils.autoreload"):
            with self.subTest(logger=name):
                self.assertEqual(
                    logging.getLogger(name).getEffectiveLevel(),
                    getattr(logging, settings.LOG_LEVEL),
                )

    def test_sql_logging_is_not_swept_up_by_debug(self):
        """django.db.backends logs every query at DEBUG. That firehose would bury
        the app lines LOG_LEVEL=DEBUG was set to read, so it stays at INFO
        whatever the variable says."""
        self.assertEqual(
            logging.getLogger("django.db.backends").getEffectiveLevel(), logging.INFO
        )

    def test_log_level_announcement_is_emitted_at_that_level(self):
        """The startup line has to survive whatever level is configured — logging
        it at a fixed INFO would hide it exactly when someone set WARNING to check
        the setting took."""
        from django.conf import settings

        from core.apps import _announce_log_level

        with self.assertLogs("core.apps", level=settings.LOG_LEVEL) as captured:
            _announce_log_level()
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].levelname, settings.LOG_LEVEL)
        self.assertIn(f"Using Loglevel: {settings.LOG_LEVEL}", captured.output[0])

    def test_the_announcement_says_where_the_level_came_from(self):
        """A real environment variable beats .env by design, and that outcome is
        otherwise invisible — a `$env:LOG_LEVEL` typed once into a PowerShell
        session silently outranks the file for the life of that console. Naming
        the source is what makes "I set it and nothing happened" answer itself."""
        from django.conf import settings

        from core.apps import _announce_log_level

        with self.assertLogs("core.apps", level=settings.LOG_LEVEL) as captured:
            _announce_log_level()
        self.assertIn(settings.LOG_LEVEL_SOURCE, captured.output[0])

    def test_the_announcement_names_its_process(self):
        """Every process announces from core/apps.py, so the source column reads
        [core.apps] for all of them and dev.py's two lines were indistinguishable."""
        from django.conf import settings

        from core.apps import _announce_log_level

        with mock.patch.object(sys, "argv", ["manage.py", "run_scheduler"]):
            with self.assertLogs("core.apps", level=settings.LOG_LEVEL) as captured:
                _announce_log_level()
        self.assertIn("run_scheduler", captured.output[0])

    def test_process_label_picks_the_command(self):
        from core.apps import _process_label

        cases = {
            ("manage.py", "runserver"): "runserver",
            ("manage.py", "run_scheduler", "--no-reload"): "run_scheduler",
            ("manage.py", "--settings=x", "migrate"): "migrate",
            ("gunicorn", "bitgigs.wsgi:application"): "bitgigs.wsgi:application",
        }
        for argv, expected in cases.items():
            with self.subTest(argv=argv):
                with mock.patch.object(sys, "argv", list(argv)):
                    self.assertEqual(_process_label(), expected)

    def test_process_label_survives_having_nothing_to_read(self):
        """A bare interpreter has no subcommand and an argv[0] of '-c'; the label
        is cosmetic, so it must degrade rather than raise into startup."""
        from core.apps import _process_label

        for argv in ([], ["-c"], [""], ["manage.py"]):
            with self.subTest(argv=argv):
                with mock.patch.object(sys, "argv", argv):
                    self.assertTrue(_process_label())


class ReloaderParentTests(TestCase):
    """`_is_reloader_parent` — which processes stay quiet at startup.

    dev.py runs two commands, each under the autoreloader, so one startup line
    appeared four times. Suppressing the watcher parents halves that; the risk
    to guard against is over-suppressing until a line appears nowhere at all.
    """

    def _ask(self, argv, run_main=None, debug=True):
        from core.apps import _is_reloader_parent

        env = {"RUN_MAIN": run_main} if run_main else {}
        with mock.patch.object(sys, "argv", ["manage.py", *argv]), \
                mock.patch.dict(os.environ, env, clear=False), \
                override_settings(DEBUG=debug):
            if run_main is None:
                os.environ.pop("RUN_MAIN", None)
            return _is_reloader_parent()

    def test_the_watcher_parent_is_the_only_quiet_one(self):
        self.assertTrue(self._ask(["runserver"]))
        self.assertTrue(self._ask(["run_scheduler"]))

    def test_the_worker_child_speaks(self):
        """It is the process that actually serves; RUN_MAIN marks it."""
        self.assertFalse(self._ask(["runserver"], run_main="true"))
        self.assertFalse(self._ask(["run_scheduler"], run_main="true"))

    def test_a_run_that_never_reloads_speaks(self):
        """The bug this caught: --once returns before the reloader branch, so it
        is the only process there will be — suppressing it printed nothing."""
        self.assertFalse(self._ask(["run_scheduler", "--once"]))
        self.assertFalse(self._ask(["run_scheduler", "--no-reload"]))
        self.assertFalse(self._ask(["runserver", "--noreload"]))

    def test_production_speaks(self):
        """DEBUG off means no reloader, so there is no second process coming."""
        self.assertFalse(self._ask(["runserver"], debug=False))

    def test_an_ordinary_command_speaks(self):
        for argv in (["check"], ["migrate"], ["shell"], []):
            with self.subTest(argv=argv):
                self.assertFalse(self._ask(argv))


class ConfigSourceTests(TestCase):
    """`_config_source` in bitgigs/settings/base.py — which of .env, the real
    environment, or the built-in default supplied a value."""

    def _patched(self, env_file_keys=(), shadowed=(), environ=None):
        from bitgigs.settings import base

        return (
            mock.patch.object(base, "_ENV_FILE_KEYS", set(env_file_keys)),
            mock.patch.object(base, "_ENV_FILE_SHADOWED", set(shadowed)),
            mock.patch.dict(os.environ, environ or {}, clear=False),
        )

    def test_each_origin_is_named(self):
        from bitgigs.settings import base

        patches = self._patched(
            env_file_keys={"FROM_FILE"},
            shadowed={"SHADOWED"},
            environ={"SHADOWED": "x", "PLAIN": "y"},
        )
        with patches[0], patches[1], patches[2]:
            self.assertEqual(base._config_source("FROM_FILE"), "from .env")
            self.assertEqual(
                base._config_source("SHADOWED"),
                "from the environment, shadowing .env",
            )
            self.assertEqual(base._config_source("PLAIN"), "from the environment")
            self.assertEqual(
                base._config_source("NOT_SET_ANYWHERE_AT_ALL"), "the built-in default"
            )

    def test_precedence_order_decides_which_name_answers(self):
        """A renamed variable passes both names, so the source reported has to be
        the one that actually won — not whichever is set at all."""
        from bitgigs.settings import base

        patches = self._patched(
            env_file_keys={"OLD_NAME"}, environ={"NEW_NAME": "x"}
        )
        with patches[0], patches[1], patches[2]:
            self.assertEqual(
                base._config_source("NEW_NAME", "OLD_NAME"), "from the environment"
            )
            self.assertEqual(
                base._config_source("OLD_NAME", "NEW_NAME"), "from .env"
            )

    def test_env_file_never_overwrites_a_real_variable(self):
        """The precedence itself, which is what makes Docker/systemd able to
        override the file without editing it."""
        from django.conf import settings

        self.assertIn(
            settings.LOG_LEVEL_SOURCE,
            {
                "from .env",
                "from the environment",
                "from the environment, shadowing .env",
                "the built-in default",
            },
        )


class LogFormatTests(TestCase):
    """core/logformat.py — the line layout and the colour on its severity."""

    def _record(self, level=logging.INFO, msg="hello"):
        return logging.LogRecord("core.demo", level, "demo.py", 7, msg, (), None)

    def test_layout(self):
        from core.logformat import BitGigsFormatter

        line = BitGigsFormatter(color=False).format(self._record())
        # <time> <severity> [<source>] -> <message>
        self.assertRegex(
            line, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\s+INFO\s+\[core\.demo\]\s+-> hello$"
        )

    def test_columns_align_across_records(self):
        """The whole point of padding both columns: the messages form one column
        down the page rather than each starting wherever its source name ended."""
        from core.logformat import BitGigsFormatter

        fmt = BitGigsFormatter(color=False)
        lines = [
            fmt.format(logging.LogRecord(name, logging.INFO, "d.py", 1, "hello", (), None))
            for name in ("core.apps", "django.utils.autoreload", "scheduler")
        ]
        starts = {line.index("-> hello") for line in lines}
        self.assertEqual(len(starts), 1, f"messages start at differing columns: {lines}")

    def test_an_overlong_source_name_still_renders(self):
        """Longer than SOURCE_WIDTH costs that line its alignment, but must never
        truncate the name or crash on a negative pad."""
        from core.logformat import BitGigsFormatter

        name = "a.very.long.logger.name.that.exceeds.the.column"
        record = logging.LogRecord(name, logging.INFO, "d.py", 1, "hello", (), None)
        line = BitGigsFormatter(color=False).format(record)
        self.assertIn(f"[{name}] -> hello", line)

    def test_each_severity_gets_its_own_colour(self):
        from core.logformat import LEVEL_COLORS, RESET, BitGigsFormatter

        fmt = BitGigsFormatter(color=True)
        expected = {
            logging.DEBUG: "36",      # cyan
            logging.INFO: "32",       # green
            logging.WARNING: "33",    # yellow
            logging.ERROR: "31",      # red
            logging.CRITICAL: "1;31",  # bold red
        }
        for level, code in expected.items():
            with self.subTest(level=logging.getLevelName(level)):
                self.assertEqual(LEVEL_COLORS[level], f"\033[{code}m")
                line = fmt.format(self._record(level))
                self.assertIn(f"\033[{code}m", line)
                self.assertIn(RESET, line)

    def test_severity_column_stays_aligned_when_coloured(self):
        """The escape codes have no width on screen but full width to
        str.format, so padding a *coloured* string indents each level
        differently. Padding happens first; stripping the codes must therefore
        give back exactly the uncoloured line."""
        from core.logformat import BitGigsFormatter

        plain = BitGigsFormatter(color=False)
        coloured = BitGigsFormatter(color=True)
        for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
            with self.subTest(level=logging.getLevelName(level)):
                record = self._record(level)
                stripped = re.sub(r"\033\[[0-9;]*m", "", coloured.format(record))
                self.assertEqual(stripped, plain.format(record))

    def test_source_name_is_purple_but_its_brackets_are_not(self):
        """The brackets are punctuation holding the name, not part of it."""
        from core.logformat import SOURCE_COLOR, RESET, BitGigsFormatter

        line = BitGigsFormatter(color=True).format(self._record())
        self.assertEqual(SOURCE_COLOR, "\033[35m")
        self.assertIn(f"[{SOURCE_COLOR}core.demo{RESET}]", line)

    def test_colour_never_leaks_into_a_second_handler(self):
        """One record is handed to every handler in turn. The colour lives on
        derived attributes rather than on levelname/name, or the file sink would
        inherit whatever the console formatter just wrote."""
        from core.logformat import BitGigsFormatter

        record = self._record(logging.WARNING)
        BitGigsFormatter(color=True).format(record)
        self.assertEqual(record.levelname, "WARNING")
        self.assertEqual(record.name, "core.demo")
        self.assertNotIn("\033", BitGigsFormatter(color=False).format(record))

    def test_non_tty_streams_get_no_escape_codes(self):
        """A pipe into `docker compose logs` or journald, and the file handler,
        must never receive escape sequences — every later grep would have to
        account for them."""
        import io

        from core.logformat import BitGigsFormatter

        fmt = BitGigsFormatter()  # auto-detect
        fmt._color = None
        with mock.patch("core.logformat.sys.stderr", io.StringIO()):
            self.assertFalse(fmt.uses_color())

    def test_file_handler_is_configured_without_colour(self):
        from django.conf import settings

        self.assertIs(settings.LOGGING["formatters"]["bitgigs"]["color"], False)


class RenamedLogVariableTests(TestCase):
    """LOG_LEVEL/LOG_FILE were DJANGO_-prefixed. Both old names stay honoured:
    an upgrade must not silently drop a deployment to INFO, nor stop writing a
    log file someone is collecting."""

    def _resolve(self, env):
        """Re-run the settings module's own resolution against a given env."""
        with mock.patch.dict(os.environ, env, clear=True):
            level = (
                os.environ.get("LOG_LEVEL") or os.environ.get("DJANGO_LOG_LEVEL") or "INFO"
            ).upper()
            file = os.environ.get("LOG_FILE") or os.environ.get("DJANGO_LOG_FILE") or ""
        return level, file

    def test_new_names_win_over_old(self):
        level, file = self._resolve(
            {
                "LOG_LEVEL": "DEBUG", "DJANGO_LOG_LEVEL": "ERROR",
                "LOG_FILE": "new.log", "DJANGO_LOG_FILE": "old.log",
            }
        )
        self.assertEqual((level, file), ("DEBUG", "new.log"))

    def test_old_names_still_work_alone(self):
        level, file = self._resolve(
            {"DJANGO_LOG_LEVEL": "WARNING", "DJANGO_LOG_FILE": "old.log"}
        )
        self.assertEqual((level, file), ("WARNING", "old.log"))

    def test_settings_expose_both_resolved_values(self):
        from django.conf import settings

        self.assertIn(settings.LOG_LEVEL, ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"))
        self.assertIsInstance(settings.LOG_FILE, str)


class SignInLoggingTests(TestCase):
    """BitGigsLoginView's auth trail."""

    def setUp(self):
        self.user = User.objects.create_user("owner@example.com", password="pw")

    def test_failed_sign_in_is_logged_as_a_warning(self):
        with self.assertLogs("core.views", level="WARNING") as captured:
            self.client.post(reverse("login"), {
                "username": "owner@example.com", "password": "wrong",
            })
        self.assertIn("Sign-in failed", captured.output[0])
        self.assertIn("owner@example.com", captured.output[0])

    def test_failed_sign_in_never_logs_the_password(self):
        with self.assertLogs("core.views", level="WARNING") as captured:
            self.client.post(reverse("login"), {
                "username": "owner@example.com", "password": "hunter2-secret",
            })
        self.assertNotIn("hunter2-secret", "\n".join(captured.output))

    def test_successful_sign_in_is_logged_as_info(self):
        with self.assertLogs("core.views", level="INFO") as captured:
            self.client.post(reverse("login"), {
                "username": "owner@example.com", "password": "pw",
            })
        self.assertTrue(
            any("Sign-in succeeded" in line for line in captured.output),
            captured.output,
        )


class ClientIpTests(TestCase):
    """The shared helper behind both the reset rate limiter and the auth log."""

    def _request(self, **meta):
        from django.test import RequestFactory
        return RequestFactory().get("/", **meta)

    def test_uses_remote_addr_by_default(self):
        request = self._request(REMOTE_ADDR="10.0.0.9",
                                HTTP_X_FORWARDED_FOR="1.2.3.4")
        self.assertEqual(client_ip(request), "10.0.0.9")

    @override_settings(TRUST_PROXY_IP=True)
    def test_honours_forwarded_for_only_when_a_proxy_is_declared(self):
        request = self._request(REMOTE_ADDR="10.0.0.9",
                                HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.1")
        self.assertEqual(client_ip(request), "1.2.3.4")

    @override_settings(TRUST_PROXY_IP=True)
    def test_falls_back_when_the_proxy_sent_no_header(self):
        request = self._request(REMOTE_ADDR="10.0.0.9")
        self.assertEqual(client_ip(request), "10.0.0.9")

    def test_missing_address_is_named_not_blank(self):
        request = self._request()
        request.META.pop("REMOTE_ADDR")  # RequestFactory supplies 127.0.0.1
        self.assertEqual(client_ip(request), "unknown")


class SecretDecryptionLoggingTests(TestCase):
    """A rotated SECRET_KEY silently unreads every stored secret. The settings
    page asks the owner to re-enter it, but only whoever opens that page sees it
    — the log is what explains a mail server that stopped authenticating."""

    def test_unreadable_secret_warns_without_leaking_the_token(self):
        token = "gAAAAAB-not-a-valid-fernet-token"
        with self.assertLogs("core.crypto", level="WARNING") as captured:
            self.assertIsNone(decrypt_secret(token))
        joined = "\n".join(captured.output)
        self.assertIn("DJANGO_SECRET_KEY", joined)
        self.assertNotIn(token, joined)
