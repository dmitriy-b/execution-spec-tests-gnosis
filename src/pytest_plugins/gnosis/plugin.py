"""Pytest plugin for Gnosis chain support."""

import pytest
from _pytest.config import Config

from .gnosis import Gnosis, set_gnosis_fork_parameters
from .gnosis_block_types import patch_environment_defaults_and_class
from .gnosis_fork_monkey_patch import (patch_fork_parameters,
                                       set_custom_fork_parameters)


def patch_transaction_defaults_for_gnosis():
    """Monkey patch TransactionDefaults to work with Gnosis's higher base fee."""
    try:
        from ethereum_test_types.transaction_types import TransactionDefaults

        from .gnosis_block_types import GNOSIS_DEFAULT_BASE_FEE

        # Store original values for potential restoration
        if not hasattr(TransactionDefaults, "_original_gas_price"):
            TransactionDefaults._original_gas_price = TransactionDefaults.gas_price
            TransactionDefaults._original_max_fee_per_gas = TransactionDefaults.max_fee_per_gas

        # Set gas_price to 2 Gwei (higher than Gnosis base fee of 1 Gwei)
        TransactionDefaults.gas_price = 2_000_000_000  # 2 Gwei
        # Set max_fee_per_gas to 2 Gwei for EIP-1559 transactions
        TransactionDefaults.max_fee_per_gas = 2_000_000_000  # 2 Gwei

        print("🔧 Patched TransactionDefaults for Gnosis:")
        print(f"  - gas_price: {TransactionDefaults.gas_price:,} wei (2 Gwei)")
        print(f"  - max_fee_per_gas: {TransactionDefaults.max_fee_per_gas:,} wei (2 Gwei)")

    except ImportError as e:
        print(f"⚠️  Could not patch TransactionDefaults: {e}")


class GnosisPlugin:
    """Plugin for Gnosis chain support in the test framework."""

    def __init__(self, config: pytest.Config):
        """Initialize the plugin."""
        self.config = config
        self.use_gnosis = config.getoption("--gnosis")

        if self.use_gnosis:
            # Import the correct Gnosis defaults
            from .gnosis_block_types import GNOSIS_DEFAULT_BASE_FEE, GNOSIS_DEFAULT_BLOCK_GAS_LIMIT

            # Collect all gnosis environment options with proper defaults
            gnosis_options = {
                "gas_limit": config.getoption("--gnosis-gas-limit")
                or GNOSIS_DEFAULT_BLOCK_GAS_LIMIT,
                "number": config.getoption("--gnosis-number") or 1,
                "timestamp": config.getoption("--gnosis-timestamp") or 1000,
                "base_fee_per_gas": config.getoption("--gnosis-base-fee")
                or GNOSIS_DEFAULT_BASE_FEE,
                "difficulty": config.getoption("--gnosis-difficulty") or 0x20000,
                "excess_blob_gas": config.getoption("--gnosis-excess-blob-gas") or 0,
                "patch_genesis_hash": config.getoption(
                    "--gnosis-patch-genesis-hash"
                ),  # Only patch when explicitly requested
                "fee_recipient": "0x2adc25665018aa1fe0e6bc666dac8fc2697ff9ba",
                # updates in env.json but not in genesisBlockHeader
                # TODO: add more gnosis properties here
            }

            print("🔧 Gnosis Environment Defaults:")
            print(f"  - gas_limit: {gnosis_options['gas_limit']:,} ({hex(gnosis_options['gas_limit'])})")
            print(f"  - base_fee_per_gas: {gnosis_options['base_fee_per_gas']:,} ({hex(gnosis_options['base_fee_per_gas'])})")
            print(f"  - number: {gnosis_options['number']}")
            print(f"  - timestamp: {gnosis_options['timestamp']}")
            print(f"  - difficulty: {hex(gnosis_options['difficulty'])}")
            print(f"  - excess_blob_gas: {gnosis_options['excess_blob_gas']}")
            print(f"  - fee_recipient: {gnosis_options['fee_recipient']}")

            # Apply environment defaults patching with Gnosis values
            patch_environment_defaults_and_class(**gnosis_options)

            # Apply transaction defaults patch for Gnosis
            patch_transaction_defaults_for_gnosis()

        # Gnosis fork is now auto-registered by a session fixture in gnosis.py
        # No need to call register_gnosis_fork() here anymore.


def pytest_addoption(parser):
    """Add command-line options for Gnosis support."""
    gnosis_group = parser.getgroup("Gnosis", "Gnosis chain specific options")
    gnosis_group.addoption(
        "--gnosis",
        action="store_true",
        dest="gnosis",
        default=False,
        help="Use Gnosis chain for tests",
    )
    gnosis_group.addoption(
        "--gnosis-rpc",
        action="store",
        dest="gnosis_rpc",
        default="https://rpc.gnosis.gateway.fm",
        help="Gnosis RPC endpoint to use for tests",
    )
    gnosis_group.addoption(
        "--gnosis-gas-limit",
        action="store",
        dest="gnosis_gas_limit",
        type=int,
        default=None,
        help="Custom gas limit for Gnosis chain tests (default: 10,000,000 / 0x989680)",
    )
    gnosis_group.addoption(
        "--gnosis-number",
        action="store",
        dest="gnosis_number",
        type=int,
        default=None,
        help="Default block number for Environment (default: 0)",
    )
    gnosis_group.addoption(
        "--gnosis-timestamp",
        action="store",
        dest="gnosis_timestamp",
        type=int,
        default=None,
        help="Default timestamp for Environment (default: 0)",
    )
    gnosis_group.addoption(
        "--gnosis-base-fee",
        action="store",
        dest="gnosis_base_fee",
        type=int,
        default=None,
        help="Default base fee per gas for Environment (default: 1,000,000,000 wei / 0x3b9aca00 / 1 Gwei)",
    )
    gnosis_group.addoption(
        "--gnosis-difficulty",
        action="store",
        dest="gnosis_difficulty",
        type=int,
        default=None,
        help="Default difficulty for Environment (default: 0x20000)",
    )
    gnosis_group.addoption(
        "--gnosis-excess-blob-gas",
        action="store",
        dest="gnosis_excess_blob_gas",
        type=int,
        default=None,
        help="Default excess blob gas for Environment (default: 0)",
    )
    gnosis_group.addoption(
        "--gnosis-blob-base-fee-update-fraction",
        type=int,
        help="Set custom blob base fee update fraction for Gnosis fork"
    )
    gnosis_group.addoption(
        "--gnosis-target-blobs-per-block",
        type=int,
        help="Set custom target blobs per block for Gnosis fork"
    )
    gnosis_group.addoption(
        "--gnosis-max-blobs-per-block",
        type=int,
        help="Set custom max blobs per block for Gnosis fork"
    )
    gnosis_group.addoption(
        "--gnosis-patch-genesis-hash",
        action="store_true",
        dest="gnosis_patch_genesis_hash",
        default=False,
        help="Patch genesis hash for Gnosis fork"
    )


@pytest.hookimpl(trylast=True)
def pytest_configure(config: Config):
    """Configure Gnosis plugin on pytest startup."""
    # Register the plugin
    config.pluginmanager.register(GnosisPlugin(config), "gnosis_plugin")

    # Check if Gnosis mode is enabled
    use_gnosis = config.getoption("--gnosis")

    # Configure fork parameters if Gnosis is enabled or any are specified
    blob_base_fee_update_fraction = config.getoption("--gnosis-blob-base-fee-update-fraction")
    target_blobs_per_block = config.getoption("--gnosis-target-blobs-per-block")
    max_blobs_per_block = config.getoption("--gnosis-max-blobs-per-block")

    fork_options = [blob_base_fee_update_fraction, target_blobs_per_block, max_blobs_per_block]

    # Apply fork parameters if:
    # 1. Any specific blob parameters are provided, OR
    # 2. Gnosis mode is enabled (use defaults)
    if any(fork_options) or use_gnosis:
        print("\n=== Gnosis Fork Configuration ===")

        # Import defaults for display and fallback
        from .gnosis import (
            DEFAULT_GNOSIS_BLOB_BASE_FEE_UPDATE_FRACTION,
            DEFAULT_GNOSIS_MAX_BLOBS_PER_BLOCK,
            DEFAULT_GNOSIS_TARGET_BLOBS_PER_BLOCK,
        )

        # Use provided values or fall back to Gnosis defaults if in Gnosis mode
        final_blob_base_fee_update_fraction = blob_base_fee_update_fraction
        final_target_blobs_per_block = target_blobs_per_block
        final_max_blobs_per_block = max_blobs_per_block

        if use_gnosis:
            # Apply Gnosis defaults for any unspecified parameters
            if final_blob_base_fee_update_fraction is None:
                final_blob_base_fee_update_fraction = DEFAULT_GNOSIS_BLOB_BASE_FEE_UPDATE_FRACTION
            if final_target_blobs_per_block is None:
                final_target_blobs_per_block = DEFAULT_GNOSIS_TARGET_BLOBS_PER_BLOCK
            if final_max_blobs_per_block is None:
                final_max_blobs_per_block = DEFAULT_GNOSIS_MAX_BLOBS_PER_BLOCK

        # Set custom parameters for Gnosis fork (legacy)
        fork_params = {}
        if final_blob_base_fee_update_fraction is not None:
            fork_params["blob_base_fee_update_fraction"] = final_blob_base_fee_update_fraction
        if final_target_blobs_per_block is not None:
            fork_params["target_blobs_per_block"] = final_target_blobs_per_block
        if final_max_blobs_per_block is not None:
            fork_params["max_blobs_per_block"] = final_max_blobs_per_block

        set_gnosis_fork_parameters(**fork_params)

        # Also set custom parameters for ALL forks
        # Include pre_allocation patching when --gnosis is used
        # TODO: change this when create a brand new gnosis fork
        set_custom_fork_parameters(
            blob_base_fee_update_fraction=final_blob_base_fee_update_fraction,
            target_blobs_per_block=final_target_blobs_per_block,
            max_blobs_per_block=final_max_blobs_per_block,
            patch_pre_allocation=use_gnosis,  # Patch pre-allocation when --gnosis is used
        )

        # Apply the patches
        patch_fork_parameters()

        print(f"Blob Base Fee Update Fraction: {final_blob_base_fee_update_fraction}")
        print(f"Target Blobs Per Block: {final_target_blobs_per_block}")
        print(f"Max Blobs Per Block: {final_max_blobs_per_block}")
        if use_gnosis:
            print("Pre-allocation: Patched with Gnosis accounts")
        print("=== End Gnosis Configuration ===\n")


@pytest.hookimpl(tryfirst=True)
def pytest_unconfigure(config: Config):
    """Clean up when pytest shuts down."""
    # Restore original environment defaults if they were patched?


@pytest.fixture
def gnosis_network(request):
    """Provide Gnosis network configuration as a fixture."""
    return {
        "name": "gnosis",
        "fork": Gnosis,
        "chain_id": 100,
        "rpc_url": request.config.getoption("--gnosis-rpc"),
    }


@pytest.fixture
def is_gnosis_network(request):
    """Check if tests are running against Gnosis network."""
    return request.config.getoption("--gnosis")
