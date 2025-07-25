"""
Top-level pytest configuration file providing:
- Command-line options,
- Test-fixtures that can be used by all test cases,
and that modifies pytest hooks in order to fill test specs for all tests and
writes the generated fixtures to file.
"""

import configparser
import datetime
import os
import warnings
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Generator, List, Type

import pytest
import xdist
from _pytest.compat import NotSetType
from _pytest.terminal import TerminalReporter
from cli.gen_index import generate_fixtures_index
from ethereum_clis import TransitionTool
from ethereum_clis.clis.geth import FixtureConsumerTool
from ethereum_test_base_types import Account, Address, Alloc, ReferenceSpec
from ethereum_test_fixtures import (BaseFixture, BlockchainEngineXFixture,
                                    FixtureCollector, FixtureConsumer,
                                    LabeledFixtureFormat, PreAllocGroup,
                                    PreAllocGroups, TestInfo)
from ethereum_test_forks import (Fork, get_transition_fork_predecessor,
                                 get_transition_forks)
from ethereum_test_specs import BaseTest
from ethereum_test_tools.utility.versioning import (
    generate_github_url, get_current_commit_hash_or_tag)
from ethereum_test_types import EnvironmentDefaults, TransactionDefaults
from pytest_metadata.plugin import metadata_key  # type: ignore
from pytest_plugins.spec_version_checker.spec_version_checker import \
    EIPSpecTestItem

from ..shared.helpers import (get_spec_format_for_item,
                              is_help_or_collectonly_mode,
                              labeled_format_parameter_set)
from ..spec_version_checker.spec_version_checker import \
    get_ref_spec_from_module
from .fixture_output import FixtureOutput


def calculate_post_state_diff(post_state: Alloc, genesis_state: Alloc) -> Alloc:
    """
    Calculate the state difference between post_state and genesis_state.

    This function enables significant space savings in Engine X fixtures by storing
    only the accounts that changed during test execution, rather than the full
    post-state which may contain thousands of unchanged accounts.

    Returns an Alloc containing only the accounts that:
    - Changed between genesis and post state (balance, nonce, storage, code)
    - Were created during test execution (new accounts)
    - Were deleted during test execution (represented as None)

    Args:
        post_state: Final state after test execution
        genesis_state: Genesis pre-allocation state

    Returns:
        Alloc containing only the state differences for efficient storage

    """
    diff: Dict[Address, Account | None] = {}

    # Find all addresses that exist in either state
    all_addresses = set(post_state.root.keys()) | set(genesis_state.root.keys())

    for address in all_addresses:
        genesis_account = genesis_state.root.get(address)
        post_account = post_state.root.get(address)

        # Account was deleted (exists in genesis but not in post)
        if genesis_account is not None and post_account is None:
            diff[address] = None

        # Account was created (doesn't exist in genesis but exists in post)
        elif genesis_account is None and post_account is not None:
            diff[address] = post_account

        # Account was modified (exists in both but different)
        elif genesis_account != post_account:
            diff[address] = post_account

        # Account unchanged - don't include in diff

    return Alloc(diff)


def default_output_directory() -> str:
    """
    Directory (default) to store the generated test fixtures. Defined as a
    function to allow for easier testing.
    """
    return "./fixtures"


def default_html_report_file_path() -> str:
    """
    File path (default) to store the generated HTML test report. Defined as a
    function to allow for easier testing.
    """
    return ".meta/report_fill.html"


def pytest_addoption(parser: pytest.Parser):
    """Add command-line options to pytest."""
    evm_group = parser.getgroup("evm", "Arguments defining evm executable behavior")
    evm_group.addoption(
        "--evm-bin",
        action="store",
        dest="evm_bin",
        type=Path,
        default=None,
        help=(
            "Path to an evm executable (or name of an executable in the PATH) that provides `t8n`."
            " Default: `ethereum-spec-evm-resolver`."
        ),
    )
    evm_group.addoption(
        "--t8n-server-url",
        action="store",
        dest="t8n_server_url",
        type=str,
        default=None,
        help=(
            "[INTERNAL USE ONLY] URL of the t8n server to use. Used by framework tests/ci; not "
            "intended for regular CLI use."
        ),
    )
    evm_group.addoption(
        "--traces",
        action="store_true",
        dest="evm_collect_traces",
        default=None,
        help="Collect traces of the execution information from the transition tool.",
    )
    evm_group.addoption(
        "--verify-fixtures",
        action="store_true",
        dest="verify_fixtures",
        default=False,
        help=(
            "Verify generated fixture JSON files using geth's evm blocktest command. "
            "By default, the same evm binary as for the t8n tool is used. A different (geth) evm "
            "binary may be specified via --verify-fixtures-bin, this must be specified if filling "
            "with a non-geth t8n tool that does not support blocktest."
        ),
    )
    evm_group.addoption(
        "--verify-fixtures-bin",
        action="store",
        dest="verify_fixtures_bin",
        type=Path,
        default=None,
        help=(
            "Path to an evm executable that provides the `blocktest` command. "
            "Default: The first (geth) 'evm' entry in PATH."
        ),
    )

    test_group = parser.getgroup("tests", "Arguments defining filler location and output")
    test_group.addoption(
        "--filler-path",
        action="store",
        dest="filler_path",
        default="./tests/",
        type=Path,
        help="Path to filler directives",
    )
    test_group.addoption(
        "--output",
        action="store",
        dest="output",
        type=Path,
        default=Path(default_output_directory()),
        help=(
            "Directory path to store the generated test fixtures. Must be empty if it exists. "
            "If the specified path ends in '.tar.gz', then the specified tarball is additionally "
            "created (the fixtures are still written to the specified path without the '.tar.gz' "
            f"suffix). Tarball output automatically enables --generate-all-formats. "
            f"Can be deleted. Default: '{default_output_directory()}'."
        ),
    )
    test_group.addoption(
        "--clean",
        action="store_true",
        dest="clean",
        default=False,
        help="Clean (remove) the output directory before filling fixtures.",
    )
    test_group.addoption(
        "--flat-output",
        action="store_true",
        dest="flat_output",
        default=False,
        help="Output each test case in the directory without the folder structure.",
    )
    test_group.addoption(
        "--single-fixture-per-file",
        action="store_true",
        dest="single_fixture_per_file",
        default=False,
        help=(
            "Don't group fixtures in JSON files by test function; write each fixture to its own "
            "file. This can be used to increase the granularity of --verify-fixtures."
        ),
    )
    test_group.addoption(
        "--no-html",
        action="store_true",
        dest="disable_html",
        default=False,
        help=(
            "Don't generate an HTML test report (in the output directory). "
            "The --html flag can be used to specify a different path."
        ),
    )
    test_group.addoption(
        "--build-name",
        action="store",
        dest="build_name",
        default=None,
        type=str,
        help="Specify a build name for the fixtures.ini file, e.g., 'stable'.",
    )
    test_group.addoption(
        "--skip-index",
        action="store_false",
        dest="generate_index",
        default=True,
        help="Skip generating an index file for all produced fixtures.",
    )
    test_group.addoption(
        "--block-gas-limit",
        action="store",
        dest="block_gas_limit",
        default=EnvironmentDefaults.gas_limit,
        type=int,
        help=(
            "Default gas limit used ceiling used for blocks and tests that attempt to "
            f"consume an entire block's gas. (Default: {EnvironmentDefaults.gas_limit})"
        ),
    )
    test_group.addoption(
        "--generate-pre-alloc-groups",
        action="store_true",
        dest="generate_pre_alloc_groups",
        default=False,
        help="Generate pre-allocation groups (phase 1 only).",
    )
    test_group.addoption(
        "--use-pre-alloc-groups",
        action="store_true",
        dest="use_pre_alloc_groups",
        default=False,
        help="Fill tests using existing pre-allocation groups (phase 2 only).",
    )
    test_group.addoption(
        "--generate-all-formats",
        action="store_true",
        dest="generate_all_formats",
        default=False,
        help=(
            "Generate all fixture formats including BlockchainEngineXFixture. "
            "This enables two-phase execution: Phase 1 generates pre-allocation groups, "
            "phase 2 generates all supported fixture formats."
        ),
    )

    debug_group = parser.getgroup("debug", "Arguments defining debug behavior")
    debug_group.addoption(
        "--evm-dump-dir",
        "--t8n-dump-dir",
        action="store",
        dest="base_dump_dir",
        default=None,
        help=(
            "Path to dump the transition tool debug output. "
            "Only creates debug output when explicitly specified."
        ),
    )

    debug_group.addoption(
        "--skip-evm-dump",
        "--skip-t8n-dump",
        action="store_true",
        dest="skip_dump_dir",
        default=False,
        help=("Skip dumping the the transition tool debug output."),
    )

def pytest_sessionstart(session: pytest.Session):
    """
    Initialize session-level state.

    Either initialize an empty pre-allocation groups container for phase 1 or
    load the pre-allocation groups for phase 2 execution.
    """
    # Initialize empty pre-allocation groups container for phase 1
    if session.config.getoption("generate_pre_alloc_groups"):
        session.config.pre_alloc_groups = PreAllocGroups(root={})  # type: ignore[attr-defined]

    # Load the pre-allocation groups for phase 2
    if session.config.getoption("use_pre_alloc_groups"):
        pre_alloc_groups_folder = session.config.fixture_output.pre_alloc_groups_folder_path  # type: ignore[attr-defined]
        if pre_alloc_groups_folder.exists():
            session.config.pre_alloc_groups = PreAllocGroups.from_folder(  # type: ignore[attr-defined]
                pre_alloc_groups_folder
            )
        else:
            pytest.exit(
                f"Pre-allocation groups folder not found: {pre_alloc_groups_folder}. "
                "Run phase 1 with --generate-pre-alloc-groups first.",
                returncode=pytest.ExitCode.USAGE_ERROR,
            )

@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """
    Pytest hook called after command line options have been parsed and before
    test collection begins.

    Couple of notes:
    1. Register the plugin's custom markers and process command-line options.

        Custom marker registration:
        https://docs.pytest.org/en/7.1.x/how-to/writing_plugins.html#registering-custom-markers

    2. `@pytest.hookimpl(tryfirst=True)` is applied to ensure that this hook is
        called before the pytest-html plugin's pytest_configure to ensure that
        it uses the modified `htmlpath` option.
    """
    # Modify the block gas limit if specified.
    if config.getoption("block_gas_limit"):
        EnvironmentDefaults.gas_limit = config.getoption("block_gas_limit")

    # Initialize fixture output configuration
    config.fixture_output = FixtureOutput.from_config(config)

    if is_help_or_collectonly_mode(config):
        return

    try:
        # Check whether the directory exists and is not empty; if --clean is set, it will delete it
        config.fixture_output.create_directories(is_master=not hasattr(config, "workerinput"))
    except ValueError as e:
        pytest.exit(str(e), returncode=pytest.ExitCode.USAGE_ERROR)

    if (
        not config.getoption("disable_html")
        and config.getoption("htmlpath") is None
        and not config.getoption("generate_pre_alloc_groups")
    ):
        config.option.htmlpath = config.fixture_output.directory / default_html_report_file_path()

    # Instantiate the transition tool here to check that the binary path/trace option is valid.
    # This ensures we only raise an error once, if appropriate, instead of for every test.
    evm_bin = config.getoption("evm_bin")
    if evm_bin is None:
        assert TransitionTool.default_tool is not None, "No default transition tool found"
        t8n = TransitionTool.default_tool(trace=config.getoption("evm_collect_traces"))
    else:
        t8n = TransitionTool.from_binary_path(
            binary_path=evm_bin, trace=config.getoption("evm_collect_traces")
        )
        if (
            isinstance(config.getoption("numprocesses"), int)
            and config.getoption("numprocesses") > 0
            and "Besu" in str(t8n.detect_binary_pattern)
        ):
            pytest.exit(
                "The Besu t8n tool does not work well with the xdist plugin; use -n=0.",
                returncode=pytest.ExitCode.USAGE_ERROR,
            )

    if "Tools" not in config.stash[metadata_key]:
        config.stash[metadata_key]["Tools"] = {
            "t8n": t8n.version(),
        }
    else:
        config.stash[metadata_key]["Tools"]["t8n"] = t8n.version()

    args = ["fill"] + [str(arg) for arg in config.invocation_params.args]
    for i in range(len(args)):
        if " " in args[i]:
            args[i] = f'"{args[i]}"'
    command_line_args = " ".join(args)
    config.stash[metadata_key]["Command-line args"] = f"<code>{command_line_args}</code>"


@pytest.hookimpl(trylast=True)
def pytest_report_header(config: pytest.Config):
    """Add lines to pytest's console output header."""
    if is_help_or_collectonly_mode(config):
        return
    t8n_version = config.stash[metadata_key]["Tools"]["t8n"]
    return [(f"{t8n_version}")]


@pytest.hookimpl(tryfirst=True)
def pytest_report_teststatus(report, config: pytest.Config):
    """
    Modify test results in pytest's terminal output.

    We use this:

    1. To disable test session progress report if we're writing the JSON
        fixtures to stdout to be read by a consume command on stdin. I.e.,
        don't write this type of output to the console:
    ```text
    ...x...
    ```
    """
    if config.fixture_output.is_stdout:  # type: ignore[attr-defined]
        return report.outcome, "", report.outcome.upper()


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_terminal_summary(
    terminalreporter: TerminalReporter, exitstatus: int, config: pytest.Config
):
    """
    Modify pytest's terminal summary to emphasize that no tests were ran.

    Emphasize that fixtures have only been filled; they must now be executed to
    actually run the tests.
    """
    yield
    if config.fixture_output.is_stdout or hasattr(config, "workerinput"):  # type: ignore[attr-defined]
        return
    stats = terminalreporter.stats
    if "passed" in stats and stats["passed"]:
        # Custom message for Phase 1 (pre-allocation group generation)
        if config.getoption("generate_pre_alloc_groups"):
            # Generate summary stats
            pre_alloc_groups: PreAllocGroups
            if config.pluginmanager.hasplugin("xdist"):
                # Load pre-allocation groups from disk
                pre_alloc_groups = PreAllocGroups.from_folder(
                    config.fixture_output.pre_alloc_groups_folder_path  # type: ignore[attr-defined]
                )
            else:
                assert hasattr(config, "pre_alloc_groups")
                pre_alloc_groups = config.pre_alloc_groups  # type: ignore[attr-defined]

            total_groups = len(pre_alloc_groups.root)
            total_accounts = sum(
                group.pre_account_count for group in pre_alloc_groups.root.values()
            )

            terminalreporter.write_sep(
                "=",
                f" Phase 1 Complete: Generated {total_groups} pre-allocation groups "
                f"({total_accounts} total accounts) ",
                bold=True,
                green=True,
            )

        else:
            # Normal message for fixture generation
            # append / to indicate this is a directory
            output_dir = str(config.fixture_output.directory) + "/"  # type: ignore[attr-defined]
            terminalreporter.write_sep(
                "=",
                (
                    f' No tests executed - the test fixtures in "{output_dir}" may now be '
                    "executed against a client "
                ),
                bold=True,
                yellow=True,
            )


def pytest_metadata(metadata):
    """Add or remove metadata to/from the pytest report."""
    metadata.pop("JAVA_HOME", None)


def pytest_html_results_table_header(cells):
    """Customize the table headers of the HTML report table."""
    cells.insert(3, '<th class="sortable" data-column-type="fixturePath">JSON Fixture File</th>')
    cells.insert(4, '<th class="sortable" data-column-type="evmDumpDir">EVM Dump Dir</th>')
    del cells[-1]  # Remove the "Links" column


def pytest_html_results_table_row(report, cells):
    """Customize the table rows of the HTML report table."""
    if hasattr(report, "user_properties"):
        user_props = dict(report.user_properties)
        if (
            report.passed
            and "fixture_path_absolute" in user_props
            and "fixture_path_relative" in user_props
        ):
            fixture_path_absolute = user_props["fixture_path_absolute"]
            fixture_path_relative = user_props["fixture_path_relative"]
            fixture_path_link = (
                f'<a href="{fixture_path_absolute}" target="_blank">{fixture_path_relative}</a>'
            )
            cells.insert(3, f"<td>{fixture_path_link}</td>")
        elif report.failed:
            cells.insert(3, "<td>Fixture unavailable</td>")
        if "evm_dump_dir" in user_props:
            if user_props["evm_dump_dir"] is None:
                cells.insert(
                    4, "<td>For t8n debug info use <code>--evm-dump-dir=path --traces</code></td>"
                )
            else:
                evm_dump_dir = user_props.get("evm_dump_dir")
                if evm_dump_dir == "N/A":
                    evm_dump_entry = "N/A"
                else:
                    evm_dump_entry = f'<a href="{evm_dump_dir}" target="_blank">{evm_dump_dir}</a>'
                cells.insert(4, f"<td>{evm_dump_entry}</td>")
    del cells[-1]  # Remove the "Links" column


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Make each test's fixture json path available to the test report via
    user_properties.

    This hook is called when each test is run and a report is being made.
    """
    outcome = yield
    report = outcome.get_result()

    if call.when == "call":
        if hasattr(item.config, "fixture_path_absolute") and hasattr(
            item.config, "fixture_path_relative"
        ):
            report.user_properties.append(
                ("fixture_path_absolute", item.config.fixture_path_absolute)
            )
            report.user_properties.append(
                ("fixture_path_relative", item.config.fixture_path_relative)
            )
        if hasattr(item.config, "evm_dump_dir") and hasattr(item.config, "fixture_format"):
            if item.config.fixture_format in [
                "state_test",
                "blockchain_test",
                "blockchain_test_engine",
            ]:
                report.user_properties.append(("evm_dump_dir", item.config.evm_dump_dir))
            else:
                report.user_properties.append(("evm_dump_dir", "N/A"))  # not yet for EOF


def pytest_html_report_title(report):
    """Set the HTML report title (pytest-html plugin)."""
    report.title = "Fill Test Report"


@pytest.fixture(autouse=True, scope="session")
def evm_bin(request: pytest.FixtureRequest) -> Path | None:
    """Return configured evm tool binary path used to run t8n."""
    return request.config.getoption("evm_bin")


@pytest.fixture(autouse=True, scope="session")
def verify_fixtures_bin(request: pytest.FixtureRequest) -> Path | None:
    """
    Return configured evm tool binary path used to run statetest or
    blocktest.
    """
    return request.config.getoption("verify_fixtures_bin")


@pytest.fixture(autouse=True, scope="session")
def t8n_server_url(request: pytest.FixtureRequest) -> str | None:
    """Return configured t8n server url."""
    return request.config.getoption("t8n_server_url")


@pytest.fixture(autouse=True, scope="session")
def t8n(
    request: pytest.FixtureRequest, evm_bin: Path | None, t8n_server_url: str | None
) -> Generator[TransitionTool, None, None]:
    """Return configured transition tool."""

    kwargs = {
        "trace": request.config.getoption("evm_collect_traces"),
    }
    if t8n_server_url is not None:
        kwargs["server_url"] = t8n_server_url
    if evm_bin is None:
        assert TransitionTool.default_tool is not None, "No default transition tool found"
        t8n = TransitionTool.default_tool(**kwargs)
    else:
        t8n = TransitionTool.from_binary_path(binary_path=evm_bin, **kwargs)
    if not t8n.exception_mapper.reliable:
        warnings.warn(
            f"The t8n tool that is currently being used to fill tests ({t8n.__class__.__name__}) "
            "does not provide reliable exception messages. This may lead to false positives when "
            "writing tests and extra care should be taken when writing tests that produce "
            "exceptions.",
            stacklevel=2,
        )
    yield t8n
    t8n.shutdown()


@pytest.fixture(scope="session")
def do_fixture_verification(
    request: pytest.FixtureRequest, verify_fixtures_bin: Path | None
) -> bool:
    """
    Return True if evm statetest or evm blocktest should be ran on the
    generated fixture JSON files.
    """
    do_fixture_verification = False
    if verify_fixtures_bin:
        do_fixture_verification = True
    if request.config.getoption("verify_fixtures"):
        do_fixture_verification = True
    return do_fixture_verification


@pytest.fixture(autouse=True, scope="session")
def evm_fixture_verification(
    request: pytest.FixtureRequest,
    do_fixture_verification: bool,
    evm_bin: Path | None,
    verify_fixtures_bin: Path | None,
) -> Generator[FixtureConsumer | None, None, None]:
    """
    Return configured evm binary for executing statetest and blocktest
    commands used to verify generated JSON fixtures.
    """
    if not do_fixture_verification:
        yield None
        return
    reused_evm_bin = False
    if not verify_fixtures_bin and evm_bin:
        verify_fixtures_bin = evm_bin
        reused_evm_bin = True
    if not verify_fixtures_bin:
        return
    try:
        evm_fixture_verification = FixtureConsumerTool.from_binary_path(
            binary_path=Path(verify_fixtures_bin),
            trace=request.config.getoption("evm_collect_traces"),
        )
    except Exception:
        if reused_evm_bin:
            pytest.exit(
                "The binary specified in --evm-bin could not be recognized as a known "
                "FixtureConsumerTool. Either remove --verify-fixtures or set "
                "--verify-fixtures-bin to a known fixture consumer binary.",
                returncode=pytest.ExitCode.USAGE_ERROR,
            )
        else:
            pytest.exit(
                "Specified binary in --verify-fixtures-bin could not be recognized as a known "
                "FixtureConsumerTool. Please see `GethFixtureConsumer` for an example "
                "of how a new fixture consumer can be defined.",
                returncode=pytest.ExitCode.USAGE_ERROR,
            )
    yield evm_fixture_verification


@pytest.fixture(scope="session")
def base_dump_dir(request: pytest.FixtureRequest) -> Path | None:
    """Path to base directory to dump the evm debug output."""
    base_dump_dir_str = request.config.getoption("base_dump_dir")
    if base_dump_dir_str:
        return Path(base_dump_dir_str)
    return None


@pytest.fixture(scope="session")
def fixture_output(request: pytest.FixtureRequest) -> FixtureOutput:
    """Return the fixture output configuration."""
    return request.config.fixture_output  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def is_output_tarball(fixture_output: FixtureOutput) -> bool:
    """Return True if the output directory is a tarball."""
    return fixture_output.is_tarball


@pytest.fixture(scope="session")
def output_dir(fixture_output: FixtureOutput) -> Path:
    """Return directory to store the generated test fixtures."""
    return fixture_output.directory


@pytest.fixture(scope="session", autouse=True)
def create_properties_file(request: pytest.FixtureRequest, fixture_output: FixtureOutput) -> None:
    """
    Create ini file with fixture build properties in the fixture output
    directory.
    """
    if fixture_output.is_stdout:
        return

    fixture_properties = {
        "timestamp": datetime.datetime.now().isoformat(),
    }
    if build_name := request.config.getoption("build_name"):
        fixture_properties["build"] = build_name
    if github_ref := os.getenv("GITHUB_REF"):
        fixture_properties["ref"] = github_ref
    if github_sha := os.getenv("GITHUB_SHA"):
        fixture_properties["commit"] = github_sha
    command_line_args = request.config.stash[metadata_key]["Command-line args"]
    command_line_args = command_line_args.replace("<code>", "").replace("</code>", "")
    fixture_properties["command_line_args"] = command_line_args

    config = configparser.ConfigParser(interpolation=None)
    config["fixtures"] = fixture_properties
    environment_properties = {}
    for key, val in request.config.stash[metadata_key].items():
        if key.lower() == "command-line args":
            continue
        if key.lower() in ["ci", "python", "platform"]:
            environment_properties[key] = val
        elif isinstance(val, dict):
            config[key.lower()] = val
        else:
            warnings.warn(
                f"Fixtures ini file: Skipping metadata key {key} with value {val}.", stacklevel=2
            )
    config["environment"] = environment_properties

    ini_filename = fixture_output.metadata_dir / "fixtures.ini"
    with open(ini_filename, "w") as f:
        f.write("; This file describes fixture build properties\n\n")
        config.write(f)


@pytest.fixture(scope="function")
def dump_dir_parameter_level(
    request: pytest.FixtureRequest, base_dump_dir: Path | None, filler_path: Path
) -> Path | None:
    """
    Directory to dump evm transition tool debug output on a test parameter
    level.

    Example with --evm-dump-dir=/tmp/evm:
    -> /tmp/evm/shanghai__eip3855_push0__test_push0__test_push0_key_sstore/fork_shanghai/
    """
    evm_dump_dir = node_to_test_info(request.node).get_dump_dir_path(
        base_dump_dir,
        filler_path,
        level="test_parameter",
    )
    # NOTE: Use str for compatibility with pytest-dist
    if evm_dump_dir:
        request.node.config.evm_dump_dir = str(evm_dump_dir)
    else:
        request.node.config.evm_dump_dir = None
    return evm_dump_dir


def get_fixture_collection_scope(fixture_name, config):
    """
    Return the appropriate scope to write fixture JSON files.

    See: https://docs.pytest.org/en/stable/how-to/fixtures.html#dynamic-scope
    """
    if config.fixture_output.is_stdout:
        return "session"
    if config.fixture_output.single_fixture_per_file:
        return "function"
    return "module"


@pytest.fixture(autouse=True, scope="module")
def reference_spec(request) -> None | ReferenceSpec:
    """
    Pytest fixture that returns the reference spec defined in a module.

    See `get_ref_spec_from_module`.
    """
    if hasattr(request, "module"):
        return get_ref_spec_from_module(request.module)
    return None


@pytest.fixture(scope=get_fixture_collection_scope)
def fixture_collector(
    request: pytest.FixtureRequest,
    do_fixture_verification: bool,
    evm_fixture_verification: FixtureConsumer,
    filler_path: Path,
    base_dump_dir: Path | None,
    fixture_output: FixtureOutput,
) -> Generator[FixtureCollector, None, None]:
    """
    Return configured fixture collector instance used for all tests
    in one test module.
    """
    # Dynamically load the 'static_filler' and 'solc' plugins if needed
    if request.config.getoption("fill_static_tests_enabled"):
        request.config.pluginmanager.import_plugin("pytest_plugins.filler.static_filler")
        request.config.pluginmanager.import_plugin("pytest_plugins.solc.solc")

    fixture_collector = FixtureCollector(
        output_dir=fixture_output.directory,
        flat_output=fixture_output.flat_output,
        fill_static_tests=request.config.getoption("fill_static_tests_enabled"),
        single_fixture_per_file=fixture_output.single_fixture_per_file,
        filler_path=filler_path,
        base_dump_dir=base_dump_dir,
    )
    yield fixture_collector
    fixture_collector.dump_fixtures()
    if do_fixture_verification:
        fixture_collector.verify_fixture_files(evm_fixture_verification)


@pytest.fixture(autouse=True, scope="session")
def filler_path(request: pytest.FixtureRequest) -> Path:
    """Return directory containing the tests to execute."""
    return request.config.getoption("filler_path")


def node_to_test_info(node: pytest.Item) -> TestInfo:
    """Return test info of the current node item."""
    return TestInfo(
        name=node.name,
        id=node.nodeid,
        original_name=node.originalname,  # type: ignore
        module_path=Path(node.path),
    )


@pytest.fixture(scope="session")
def commit_hash_or_tag() -> str:
    """Cache the git commit hash or tag for the entire test session."""
    return get_current_commit_hash_or_tag()


@pytest.fixture(scope="function")
def fixture_source_url(
    request: pytest.FixtureRequest,
    commit_hash_or_tag: str,
) -> str:
    """Return URL to the fixture source."""
    if hasattr(request.node, "github_url"):
        return request.node.github_url
    function_line_number = request.function.__code__.co_firstlineno
    module_relative_path = os.path.relpath(request.function.__code__.co_filename)

    github_url = generate_github_url(
        module_relative_path,
        branch_or_commit_or_tag=commit_hash_or_tag,
        line_number=function_line_number,
    )
    test_module_relative_path = os.path.relpath(request.module.__file__)
    if module_relative_path != test_module_relative_path:
        # This can be the case when the test function's body only contains pass and the entire
        # test logic is implemented as a test generator from the framework.
        test_module_github_url = generate_github_url(
            test_module_relative_path,
            branch_or_commit_or_tag=commit_hash_or_tag,
        )
        github_url += f" called via `{request.node.originalname}()` in {test_module_github_url}"
    return github_url


def base_test_parametrizer(cls: Type[BaseTest]):
    """
    Generate pytest.fixture for a given BaseTest subclass.

    Implementation detail: All spec fixtures must be scoped on test function level to avoid
    leakage between tests.
    """

    @pytest.fixture(
        scope="function",
        name=cls.pytest_parameter_name(),
    )
    def base_test_parametrizer_func(
        request: pytest.FixtureRequest,
        t8n: TransitionTool,
        fork: Fork,
        reference_spec: ReferenceSpec,
        pre: Alloc,
        output_dir: Path,
        dump_dir_parameter_level: Path | None,
        fixture_collector: FixtureCollector,
        test_case_description: str,
        fixture_source_url: str,
    ):
        """
        Fixture used to instantiate an auto-fillable BaseTest object from within
        a test function.

        Every test that defines a test filler must explicitly specify its parameter name
        (see `pytest_parameter_name` in each implementation of BaseTest) in its function
        arguments.

        When parametrize, indirect must be used along with the fixture format as value.
        """
        if hasattr(request.node, "fixture_format"):
            fixture_format = request.node.fixture_format
        else:
            fixture_format = request.param
        assert issubclass(fixture_format, BaseFixture)
        if fork is None:
            assert hasattr(request.node, "fork")
            fork = request.node.fork

        class BaseTestWrapper(cls):  # type: ignore
            def __init__(self, *args, **kwargs):
                kwargs["t8n_dump_dir"] = dump_dir_parameter_level
                if "pre" not in kwargs:
                    kwargs["pre"] = pre
                super(BaseTestWrapper, self).__init__(*args, **kwargs)
                self._request = request

                # Phase 1: Generate pre-allocation groups
                if fixture_format is BlockchainEngineXFixture and request.config.getoption(
                    "generate_pre_alloc_groups"
                ):
                    self.update_pre_alloc_groups(
                        request.config.pre_alloc_groups, fork, request.node.nodeid
                    )
                    return  # Skip fixture generation in phase 1

                # Phase 2: Use pre-allocation groups (only for BlockchainEngineXFixture)
                pre_alloc_hash = None
                if fixture_format is BlockchainEngineXFixture and request.config.getoption(
                    "use_pre_alloc_groups"
                ):
                    pre_alloc_hash = self.compute_pre_alloc_group_hash(fork=fork)
                    if pre_alloc_hash not in request.config.pre_alloc_groups:
                        pre_alloc_path = (
                            request.config.fixture_output.pre_alloc_groups_folder_path
                            / pre_alloc_hash
                        )
                        raise ValueError(
                            f"Pre-allocation hash {pre_alloc_hash} not found in "
                            f"pre-allocation groups. "
                            f"Please check the pre-allocation groups file at: {pre_alloc_path}. "
                            "Make sure phase 1 (--generate-pre-alloc-groups) was run "
                            "before phase 2."
                        )
                    group: PreAllocGroup = request.config.pre_alloc_groups[pre_alloc_hash]  # type: ignore[annotation-unchecked]
                    self.pre = group.pre

                fixture = self.generate(
                    t8n=t8n,
                    fork=fork,
                    fixture_format=fixture_format,
                )

                # Post-process for Engine X format (add pre_hash and state diff)
                if (
                    fixture_format is BlockchainEngineXFixture
                    and request.config.getoption("use_pre_alloc_groups")
                    and pre_alloc_hash is not None
                ):
                    fixture.pre_hash = pre_alloc_hash

                    # Calculate state diff for efficiency
                    if hasattr(fixture, "post_state") and fixture.post_state is not None:
                        group = request.config.pre_alloc_groups[pre_alloc_hash]
                        fixture.post_state_diff = calculate_post_state_diff(
                            fixture.post_state, group.pre
                        )

                fixture.fill_info(
                    t8n.version(),
                    test_case_description,
                    fixture_source_url=fixture_source_url,
                    ref_spec=reference_spec,
                    _info_metadata=t8n._info_metadata,
                )

                fixture_path = fixture_collector.add_fixture(
                    node_to_test_info(request.node),
                    fixture,
                )

                # NOTE: Use str for compatibility with pytest-dist
                request.node.config.fixture_path_absolute = str(fixture_path.absolute())
                request.node.config.fixture_path_relative = str(
                    fixture_path.relative_to(output_dir)
                )
                request.node.config.fixture_format = fixture_format.format_name

        return BaseTestWrapper

    return base_test_parametrizer_func


# Dynamically generate a pytest fixture for each test spec type.
for cls in BaseTest.spec_types.values():
    # Fixture needs to be defined in the global scope so pytest can detect it.
    globals()[cls.pytest_parameter_name()] = base_test_parametrizer(cls)


class ExecutionPhase(Enum):
    """Execution phase for fixture generation."""

    NORMAL = "normal"
    PHASE_1_PREALLOC = "phase_1_prealloc"
    PHASE_2_ENGINE_X_ONLY = "phase_2_engine_x_only"
    PHASE_2_ALL_FORMATS = "phase_2_all_formats"


def _determine_execution_phase(
    generate_pre_alloc_groups: bool,
    use_pre_alloc_groups: bool,
    generate_all_formats: bool,
) -> ExecutionPhase:
    """Determine which execution phase we're in based on the flags."""
    if generate_all_formats and use_pre_alloc_groups:
        return ExecutionPhase.PHASE_2_ALL_FORMATS
    elif use_pre_alloc_groups:
        return ExecutionPhase.PHASE_2_ENGINE_X_ONLY
    elif generate_pre_alloc_groups or generate_all_formats:
        return ExecutionPhase.PHASE_1_PREALLOC
    else:
        return ExecutionPhase.NORMAL


def _is_blockchain_engine_x_fixture(format_item) -> bool:
    """Check if a fixture format is BlockchainEngineXFixture."""
    return format_item is BlockchainEngineXFixture or (
        isinstance(format_item, LabeledFixtureFormat)
        and format_item.format is BlockchainEngineXFixture
    )


def _determine_fixture_formats(test_type, execution_phase: ExecutionPhase) -> List:
    """Determine which fixture formats to generate based on execution phase."""
    all_formats = test_type.supported_fixture_formats

    if execution_phase == ExecutionPhase.PHASE_2_ALL_FORMATS:
        # Phase 2 with --generate-all-formats: Generate ALL fixture formats
        return all_formats
    elif execution_phase in (
        ExecutionPhase.PHASE_1_PREALLOC,
        ExecutionPhase.PHASE_2_ENGINE_X_ONLY,
    ):
        # Phase 1 or Phase 2 without --generate-all-formats: only BlockchainEngineXFixture
        return [
            format_item
            for format_item in all_formats
            if _is_blockchain_engine_x_fixture(format_item)
        ]
    else:
        # Normal execution: Filter out BlockchainEngineXFixture
        return [
            format_item
            for format_item in all_formats
            if not _is_blockchain_engine_x_fixture(format_item)
        ]


def pytest_generate_tests(metafunc: pytest.Metafunc):
    """
    Pytest hook used to dynamically generate test cases for each fixture format a given
    test spec supports.
    """
    for test_type in BaseTest.spec_types.values():
        if test_type.pytest_parameter_name() in metafunc.fixturenames:
            generate_pre_alloc_groups = metafunc.config.getoption(
                "generate_pre_alloc_groups", False
            )
            use_pre_alloc_groups = metafunc.config.getoption("use_pre_alloc_groups", False)
            generate_all_formats = metafunc.config.getoption("generate_all_formats", False)

            execution_phase = _determine_execution_phase(
                generate_pre_alloc_groups, use_pre_alloc_groups, generate_all_formats
            )
            supported_formats = _determine_fixture_formats(test_type, execution_phase)

            parameters = []
            for i, format_with_or_without_label in enumerate(supported_formats):
                parameter = labeled_format_parameter_set(format_with_or_without_label)
                if i > 0:
                    parameter.marks.append(pytest.mark.derived_test)  # type: ignore
                parameters.append(parameter)
            metafunc.parametrize(
                [test_type.pytest_parameter_name()],
                parameters,
                scope="function",
                indirect=True,
            )


def pytest_collection_modifyitems(
    config: pytest.Config, items: List[pytest.Item | pytest.Function]
):
    """
    Remove pre-Paris tests parametrized to generate hive type fixtures; these
    can't be used in the Hive Pyspec Simulator.

    Replaces the test ID for state tests that use a transition fork with the base fork.

    These can't be handled in this plugins pytest_generate_tests() as the fork
    parametrization occurs in the forks plugin.
    """
    for item in items[:]:  # use a copy of the list, as we'll be modifying it
        params: Dict[str, Any] | None = None
        if isinstance(item, pytest.Function):
            params = item.callspec.params
        elif hasattr(item, "params"):
            params = item.params
        if not params or "fork" not in params or params["fork"] is None:
            items.remove(item)
            continue
        fork: Fork = params["fork"]
        spec_type, fixture_format = get_spec_format_for_item(params)
        if isinstance(fixture_format, NotSetType):
            items.remove(item)
            continue
        assert issubclass(fixture_format, BaseFixture)
        if not fixture_format.supports_fork(fork):
            items.remove(item)
            continue
        markers = list(item.iter_markers())
        if spec_type.discard_fixture_format_by_marks(fixture_format, fork, markers):
            items.remove(item)
            continue
        for marker in markers:
            if marker.name == "fill":
                for mark in marker.args:
                    item.add_marker(mark)
        if "yul" in item.fixturenames:  # type: ignore
            item.add_marker(pytest.mark.yul_test)

        # Update test ID for state tests that use a transition fork
        if fork in get_transition_forks():
            has_state_test = any(marker.name == "state_test" for marker in markers)
            has_valid_transition = any(
                marker.name == "valid_at_transition_to" for marker in markers
            )
            if has_state_test and has_valid_transition:
                base_fork = get_transition_fork_predecessor(fork)
                item._nodeid = item._nodeid.replace(
                    f"fork_{fork.name()}",
                    f"fork_{base_fork.name()}",
                )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int):
    """
    Perform session finish tasks.

    - Save pre-allocation groups (phase 1)
    - Remove any lock files that may have been created.
    - Generate index file for all produced fixtures.
    - Create tarball of the output directory if the output is a tarball.
    """
    # Save pre-allocation groups after phase 1
    fixture_output = session.config.fixture_output  # type: ignore[attr-defined]
    if session.config.getoption("generate_pre_alloc_groups") and hasattr(
        session.config, "pre_alloc_groups"
    ):
        pre_alloc_groups_folder = fixture_output.pre_alloc_groups_folder_path
        pre_alloc_groups_folder.mkdir(parents=True, exist_ok=True)
        session.config.pre_alloc_groups.to_folder(pre_alloc_groups_folder)
        return

    if xdist.is_xdist_worker(session):
        return

    if fixture_output.is_stdout or is_help_or_collectonly_mode(session.config):
        return

    # Remove any lock files that may have been created.
    for file in fixture_output.directory.rglob("*.lock"):
        file.unlink()

    # Generate index file for all produced fixtures.
    if session.config.getoption("generate_index") and not session.config.getoption(
        "generate_pre_alloc_groups"
    ):
        generate_fixtures_index(
            fixture_output.directory, quiet_mode=True, force_flag=False, disable_infer_format=False
        )

    # Create tarball of the output directory if the output is a tarball.
    fixture_output.create_tarball()