"""Coverage plugin for pytest."""

import argparse
import os
import re
import warnings
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from . import CovDisabledWarning
from . import CovReportWarning
from . import PytestCovWarning

if TYPE_CHECKING:
    from .engine import CovController


COVERAGE_SQLITE_WARNING_RE = re.compile(
    r"unclosed database in sqlite3.Connection object at",
    re.I,
)


def validate_report(arg):
    file_choices = {"annotate", "html", "xml", "json", "markdown", "markdown-append", "lcov"}
    term_choices = {"term", "term-missing"}
    term_modifier_choices = {"skip-covered"}
    all_choices = term_choices | file_choices

    values = arg.split(":", 1)
    report_type = values[0]

    if report_type not in all_choices:
        msg = f"invalid choice: {arg!r} (choose from {all_choices!r})"
        raise argparse.ArgumentTypeError(msg)

    if len(values) == 1:
        return (report_type, None)

    report_modifier = values[1]
    if report_type in term_choices and report_modifier in term_modifier_choices:
        return (report_type, report_modifier)

    if report_type not in file_choices:
        msg = f"output specifier not supported for: {arg!r} (choose from {file_choices!r})"
        raise argparse.ArgumentTypeError(msg)

    return values


def validate_fail_under(num_str):
    try:
        value = int(num_str)
    except ValueError:
        try:
            value = float(num_str)
        except ValueError:
            raise argparse.ArgumentTypeError(
                "An integer or float value is required."
            ) from None
    if value > 100:
        raise argparse.ArgumentTypeError(
            "Your desire for over-achievement is admirable but misplaced. "
            "The maximum value is 100. Perhaps write more integration tests?"
        )
    return value


def validate_context_arg(arg):
    if arg != "test":
        raise argparse.ArgumentTypeError("The only supported value is 'test'.")
    return arg


class StoreReport(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        report_type, file = values
        if report_type not in namespace.cov_report:
            namespace.cov_report[report_type] = file
        if report_type in {"markdown", "markdown-append"} and file is None:
            namespace.cov_report[report_type] = "coverage.md"
        if all(x in namespace.cov_report for x in {"markdown", "markdown-append"}):
            self.validate_markdown_dest_files(namespace.cov_report, parser)

    def validate_markdown_dest_files(self, cov_report_options, parser):
        markdown_file = cov_report_options.get("markdown")
        markdown_append_file = cov_report_options.get("markdown-append")
        if markdown_file == markdown_append_file:
            error_message = (
                f"markdown and markdown-append options cannot point to the "
                f"same file ({markdown_file}). "
                f"Please redirect one of them using :DEST, "
                f"e.g. --cov-report=markdown:dest_file.md"
            )
            parser.error(error_message)


def pytest_addoption(parser):
    """Add options to control coverage."""
    group = parser.getgroup("cov", "coverage reporting with distributed testing support")

    group.addoption(
        "--cov",
        action="append",
        default=[],
        metavar="SOURCE",
        nargs="?",
        const=True,
        dest="cov_source",
        help="Path or package name to measure during execution (multi-allowed). "
             "Use --cov to not do any source filtering and record everything.",
    )

    group.addoption(
        "--cov-reset",
        action="store_const",
        const=[],
        dest="cov_source",
        help="Reset cov sources accumulated in options so far. ",
    )

    group.addoption(
        "--cov-report",
        action=StoreReport,
        default={},
        metavar="TYPE",
        type=validate_report,
        help="Type of report to generate: term, term-missing, annotate, html, xml, json, "
             "markdown, markdown-append, lcov (multi-allowed). "
             "term, term-missing may be followed by :skip-covered. "
             "annotate, html, xml, json, markdown, markdown-append and lcov may be followed by "
             ":DEST where DEST specifies the output location. "
             "Use --cov-report= to not generate any output.",
    )

    group.addoption(
        "--cov-config",
        action="store",
        default=".coveragerc",
        metavar="PATH",
        help="Config file for coverage. Default: .coveragerc",
    )

    group.addoption(
        "--no-cov-on-fail",
        action="store_true",
        default=False,
        help="Do not report coverage if test run fails. Default: False",
    )

    group.addoption(
        "--no-cov",
        action="store_true",
        default=False,
        help="Disable coverage report completely (useful for debuggers). Default: False",
    )

    group.addoption(
        "--cov-fail-under",
        action="store",
        metavar="MIN",
        type=validate_fail_under,
        help="Fail if the total coverage is less than MIN.",
    )

    group.addoption(
        "--cov-append",
        action="store_true",
        default=False,
        help="Do not delete coverage but append to current. Default: False",
    )

    group.addoption(
        "--cov-branch",
        action="store_true",
        default=None,
        help="Enable branch coverage.",
    )

    group.addoption(
        "--cov-precision",
        type=int,
        default=None,
        help="Override the reporting precision.",
    )

    group.addoption(
        "--cov-context",
        action="store",
        metavar="CONTEXT",
        type=validate_context_arg,
        help="Dynamic contexts to use. 'test' for now.",
    )


def pytest_load_initial_conftests(early_config, parser, args):
    """Prepare covsource so that --cov --cov=foobar is equivalent to --cov --cov=foobar."""
    options = early_config.known_args_namespace
    no_cov = options.no_cov
    should_warn = False

    for arg in args:
        arg = str(arg)
        if arg == "--no-cov":
            no_cov = True
        elif arg.startswith("--cov") and no_cov:
            should_warn = True
            break

    if early_config.known_args_namespace.cov_source:
        plugin = CovPlugin(options, early_config.pluginmanager)
        early_config.pluginmanager.register(plugin, "cov")


class CovPlugin:
    """Use coverage package to produce code coverage reports.

    Delegates all work to a particular implementation based on whether
    this test process is centralised, a distributed master or a distributed worker.
    """

    def __init__(self, options: argparse.Namespace, pluginmanager, start=True, no_cov_should_warn=False):
        """Creates a coverage pytest plugin."""
        self.pid = None
        self.cov_controller = None
        self.cov_report = StringIO()
        self.cov_total = None
        self.failed = False
        self.started = False
        self.start_path = None
        self.disabled = False
        self.options = options
        self.wrote_heading = False

        is_dist = (
            getattr(options, "numprocesses", False)
            or getattr(options, "dist_load", False)
            or getattr(options, "dist", "no") != "no"
        )

        if getattr(options, "no_cov", False):
            self.disabled = True
            return

        if not self.options.cov_report:
            self.options.cov_report = {"term": None}
        elif len(self.options.cov_report) == 1 and "" in self.options.cov_report:
            self.options.cov_report = {}

        self.options.cov_source = self._prepare_cov_source(self.options.cov_source)

        from . import engine

        if is_dist and start:
            self._start(engine.DistMaster)
        elif start:
            self._start(engine.Central)

    def _start(self, controller_cls, config=None, nodeid=None):
        """Start the coverage controller."""
        if config is None:
            class Config:
                option = self.options

            config = Config()

        self.cov_controller = controller_cls(self.options, config, nodeid)
        self.cov_controller.start()
        self.started = True
        self.start_path = Path.cwd()

        cov_config = self.cov_controller.cov.config
        if self.options.cov_fail_under is None and hasattr(cov_config, "fail_under"):
            self.options.cov_fail_under = cov_config.fail_under
        if self.options.cov_precision is None:
            self.options.cov_precision = getattr(cov_config, "precision", 0)
              def _is_worker(self, session):
        return getattr(session.config, 'workerinput', None) is not None

    def pytest_sessionstart(self, session):
        """At session start determine our implementation and delegate to it."""
        if self.options.no_cov:
            # Coverage can be disabled because it does not cooperate with debuggers well.
            self._disabled = True
            return

        # import engine lazily here to avoid importing
        # it for unit tests that don't need it
        from . import engine

        self.pid = os.getpid()

        if self._is_worker(session):
            nodeid = session.config.workerinput.get('workerid', session.nodeid)
            self.start(engine.DistWorker, session.config, nodeid)
        elif not self._started:
            self.start(engine.Central)

        if self.options.cov_context == 'test':
            session.config.pluginmanager.register(TestContextPlugin(self.cov_controller), '_cov_contexts')

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node):
        """Delegate to our implementation.

        Mark this hook as optional in case xdist is not installed.
        """
        if not self._disabled:
            self.cov_controller.configure_node(node)

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node, error):
        """Delegate to our implementation.

        Mark this hook as optional in case xdist is not installed.
        """
        if not self._disabled:
            self.cov_controller.testnodedown(node, error)

    def _should_report(self):
        needed = self.options.cov_report or self.options.cov_fail_under
        return needed and not (self.failed and self.options.no_cov_on_fail)

    # we need to wrap pytest_runtestloop. by the time pytest_sessionfinish
    # runs, it's too late to set testsfailed
    @pytest.hookimpl(wrapper=True)
    def pytest_runtestloop(self, session):
        if self._disabled:
            return (yield)

        # we add default warning configuration to prevent certain warnings to bubble up as errors due to rigid filterwarnings configuration
        for _, message, category, _, _ in warnings.filters:
            if category is ResourceWarning and message in (COVERAGE_SQLITE_WARNING_RE, COVERAGE_SQLITE_WARNING_RE2):
                break
        else:
            warnings.filterwarnings('default', 'unclosed database in ')

        yield

        self.failed = session.testsfailed
    def pytest_sessionfinish(self, session):
        self.cov_controller.finish()

        if not self._should_report():
            return
        if self.failed:
            if not self.options.no_cov_on_fail:
                self.cov_report.write('\ncoverage: runtests failed\n')
            return

        if self.cov_controller.cov is None:
            # There was a problem collecting coverage data. For example
            # xdist workers fail before the coverage run can start.
            self.cov_controller.cov = coverage.Coverage()
        else:
            # On certain error conditions (like ctrl-C), the
            # coverage data might not be written to disk
            # despite having been collected. Force a save.
            self.cov_controller.cov.save()

        if 'term' in self.options.cov_report or 'term-missing' in self.options.cov_report:
            self.cov_report.write('\n')
            self.cov_controller.summary(self.cov_report)

        for type_, file_path in self.options.cov_report.items():
            if type_ in ('annotate', 'html', 'xml', 'json', 'markdown', 'markdown-append', 'lcov'):
                self.cov_controller.report(type_, file_path)
            elif type_ == 'term-missing':
                self.cov_report.write('\n')
                self.cov_controller.term_missing(self.cov_report)
            elif type_ == 'term':
                self.cov_report.write('\n')
                self.cov_controller.report('term', self.cov_report)

        report = self.cov_report.getvalue()
        if report:
            self.write_heading(self.cov_report)
            terminalreporter = session.config.pluginmanager.getplugin('terminalreporter')
            if terminalreporter:
                terminalreporter.write(report)

        if self.options.cov_fail_under is not None:
            self.write_heading(session)
            failed = self.cov_total < self.options.cov_fail_under
            markup = {'red': True, 'bold': True} if failed else {'green': True}
            message = '{fail}Required test coverage of {required}% {reached}. Total coverage: {actual:.2f}%\n'.format(
                required=self.options.cov_fail_under,
                actual=self.cov_total,
                fail='FAIL ' if failed else '',
                reached='not reached' if failed else 'reached',
            )
            terminalreporter.write(message, **markup)
    def write_heading(self, stream):
        if not self._wrote_heading:
            stream.write('\n---------- coverage: platform {}, python {} ----------\n'.format(
                sys.platform, sys.version.split('\n')[0],
            ))
            self._wrote_heading = True

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_call(self, item):
        if item.get_closest_marker('no_cover') or 'no_cover' in getattr(item, 'fixturenames', ()):
            self.cov_controller.pause()
            yield
            self.cov_controller.resume()
        else:
            yield


class TestContextPlugin:
    cov_controller: 'CovController'

    def __init__(self, cov_controller):
        self.cov_controller = cov_controller

    def pytest_runtest_setup(self, item):
        self.switch_context(item, 'setup')

    def pytest_runtest_teardown(self, item):
        self.switch_context(item, 'teardown')

    def pytest_runtest_call(self, item):
        self.switch_context(item, 'run')

    def switch_context(self, item, when):
        if self.cov_controller.started:
            self.cov_controller.cov.switch_context(f'{item.nodeid}|{when}')


@pytest.fixture
def no_cover():
    """A pytest fixture to disable coverage."""


@pytest.fixture
def cov(request):
    """A pytest fixture to provide access to the underlying coverage object."""
    # Check with hasplugin to avoid getplugin exception in older pytest.
    if request.config.pluginmanager.hasplugin('_cov'):
        plugin = request.config.pluginmanager.getplugin('_cov')
        if plugin.cov_controller:
            return plugin.cov_controller.cov
    return None


def pytest_configure(config):
    config.addinivalue_line('markers', 'no_cover: disable coverage for this test.')


    def is_worker(self, session):
        return getattr(session.config, "workerinput", None) is not None
