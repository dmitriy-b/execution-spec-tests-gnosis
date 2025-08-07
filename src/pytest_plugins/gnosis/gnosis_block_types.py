"""Modified block types for Gnosis chain support."""

from dataclasses import dataclass
from typing import Any, Optional

# Gnosis chain specific defaults - MUST match what the jq mapper produces
# From hive/mapper_new.jq:
# - "gasLimit": "0x989680" (line 241)
# - "baseFeePerGas": "0x3b9aca00" (line 243)
GNOSIS_DEFAULT_BASE_FEE = 0x3b9aca00  # 1 Gwei (1,000,000,000 wei)
GNOSIS_CURRENT_BLOCK_GAS_LIMIT = 0x989680  # 10,000,000
GNOSIS_DEFAULT_BLOCK_GAS_LIMIT = GNOSIS_CURRENT_BLOCK_GAS_LIMIT

# The genesis hash that the Gnosis client actually computes
# Observed from client logs: "Genesis hash : 0x92f2bad26c57198059f54c809a588e2acdd8ed140dd92683d570d1d5f83aa9a0"
# TODO: find a way to override it for genesis block
GNOSIS_GENESIS_HASH = "0x92f2bad26c57198059f54c809a588e2acdd8ed140dd92683d570d1d5f83aa9a0"


@dataclass
class GnosisEnvironmentDefaults:
    """Comprehensive Gnosis-specific environment defaults."""

    # Gas and block limits
    gas_limit: int = GNOSIS_DEFAULT_BLOCK_GAS_LIMIT

    # Block identifiers
    number: int = 1
    timestamp: int = 0

    # Value here is not important, it's just a placeholder
    base_fee_per_gas: int = GNOSIS_DEFAULT_BASE_FEE

    # Consensus
    difficulty: int = 0x20000
    prev_randao: Optional[int] = None

    # Blob gas (EIP-4844)
    excess_blob_gas: int = 0
    blob_gas_used: int = 0

    # Other defaults
    fee_recipient: str = "0x0000000000000000000000000000000000000000"


# Store original classes globally
_original_defaults: Optional[Any] = None
_original_environment_class: Optional[Any] = None
_original_set_fork_requirements: Optional[Any] = None


def _patch_set_fork_requirements() -> None:
    """Monkey patch Environment.set_fork_requirements to preserve block_hashes."""
    from ethereum_test_types import block_types

    global _original_set_fork_requirements

    # Store the original method
    if _original_set_fork_requirements is None:
        _original_set_fork_requirements = block_types.Environment.set_fork_requirements

    def patched_set_fork_requirements(self, fork):
        """Patched set_fork_requirements that ensures Gnosis genesis hash is always present."""
        # Call the original method
        result = _original_set_fork_requirements(self, fork)

        # Ensure block_hashes includes Gnosis genesis hash
        from ethereum_test_base_types import Hash, Number

        # Start with existing block_hashes from self or result
        block_hashes = {}
        if hasattr(self, 'block_hashes') and self.block_hashes:
            block_hashes.update(self.block_hashes)
        elif hasattr(result, 'block_hashes') and result.block_hashes:
            block_hashes.update(result.block_hashes)

        # Always ensure Gnosis genesis hash is present
        genesis_number = Number(0)
        genesis_hash = Hash(GNOSIS_GENESIS_HASH)
        block_hashes[genesis_number] = genesis_hash

        # Return result with updated block_hashes
        return result.copy(block_hashes=block_hashes)

        # Replace the method
        setattr(block_types.Environment, "set_fork_requirements", patched_set_fork_requirements)


def patch_environment_defaults_and_class(
    gas_limit: Optional[int] = None,
    number: Optional[int] = None,
    timestamp: Optional[int] = None,
    base_fee_per_gas: Optional[int] = None,
    fee_recipient: Optional[str] = None,
    patch_genesis_hash: bool = False,
    **kwargs: Any,
) -> None:
    """
    Monkey patch EnvironmentDefaults and modify the Environment constructor defaults.

    Args:
        gas_limit: Custom gas limit
        number: Custom block number default
        timestamp: Custom timestamp default
        base_fee_per_gas: Custom base fee default
        patch_genesis_hash: Whether to patch set_fork_requirements for genesis hash handling
        **kwargs: Other environment defaults
    """

    from ethereum_test_types import block_types

    global _original_defaults, _original_environment_class

    # Store originals for potential restoration
    if _original_defaults is None:
        _original_defaults = block_types.EnvironmentDefaults
    if _original_environment_class is None:
        _original_environment_class = block_types.Environment

    # Create custom defaults
    custom_defaults = GnosisEnvironmentDefaults()

    # Apply custom values
    if gas_limit is not None:
        custom_defaults.gas_limit = gas_limit
    if number is not None:
        custom_defaults.number = number
    if timestamp is not None:
        custom_defaults.timestamp = timestamp
    # Important
    if base_fee_per_gas is not None:
        custom_defaults.base_fee_per_gas = base_fee_per_gas
    if fee_recipient is not None:
        from ethereum_test_base_types import Address

        custom_defaults.fee_recipient = Address(fee_recipient)  # type: ignore

    # Apply any additional kwargs
    for key, value in kwargs.items():
        if hasattr(custom_defaults, key):
            setattr(custom_defaults, key, value)

    # Create patched EnvironmentDefaults
    @dataclass
    class PatchedEnvironmentDefaults:
        """Patched environment defaults for Gnosis chain."""

        gas_limit: int = custom_defaults.gas_limit

    # Replace EnvironmentDefaults
    setattr(block_types, "EnvironmentDefaults", PatchedEnvironmentDefaults)

    # Patch the Field defaults by modifying the class attributes directly
    try:
        # Try to access model fields (pydantic v2 style)
        model_fields = block_types.Environment.model_fields

        if "number" in model_fields:
            # Update the default value in the field info
            model_fields["number"].default = custom_defaults.number

        if "timestamp" in model_fields:
            model_fields["timestamp"].default = custom_defaults.timestamp

        if "fee_recipient" in model_fields:
            from ethereum_test_base_types import Address

            model_fields["fee_recipient"].default = Address(custom_defaults.fee_recipient)

        # Conditionally patch block_hashes to have Gnosis genesis hash by default
        if "block_hashes" in model_fields and patch_genesis_hash:
            from ethereum_test_base_types import Hash, Number

            def gnosis_block_hashes_factory():
                """Return block_hashes dict with Gnosis genesis hash."""
                return {Number(0): Hash(GNOSIS_GENESIS_HASH)}

            # Update the default_factory for block_hashes
            model_fields["block_hashes"].default_factory = gnosis_block_hashes_factory

        # Force rebuild of the model to pick up new defaults
        try:
            block_types.Environment.model_rebuild()
        except AttributeError:
            pass

    except AttributeError:
        # Fallback: patch by creating new class attributes
        print("INFO: Using fallback method for patching Environment defaults")
        pass

    # Monkey patch the Environment class's __init__ method to use our custom defaults
    original_init = _original_environment_class.__init__

    # This uses for environment tests and do not patch
    def patched_init(self, **kwargs_init):
        # Force our custom defaults - always override if not explicitly provided
        original_kwargs = dict(kwargs_init)  # Keep a copy for debugging
        print(f"INFO: kwargs_init: {kwargs_init}")
        if "number" not in kwargs_init:
            kwargs_init["number"] = custom_defaults.number
        if "timestamp" not in kwargs_init:
            kwargs_init["timestamp"] = custom_defaults.timestamp
        # Important?
        if "base_fee_per_gas" not in kwargs_init:
            kwargs_init["base_fee_per_gas"] = custom_defaults.base_fee_per_gas
        if "difficulty" not in kwargs_init:
            kwargs_init["difficulty"] = custom_defaults.difficulty
        if "prev_randao" not in kwargs_init and custom_defaults.prev_randao is not None:
            kwargs_init["prev_randao"] = custom_defaults.prev_randao
        if "excess_blob_gas" not in kwargs_init:
            kwargs_init["excess_blob_gas"] = custom_defaults.excess_blob_gas
        if "blob_gas_used" not in kwargs_init:
            kwargs_init["blob_gas_used"] = custom_defaults.blob_gas_used
        if "fee_recipient" not in kwargs_init:
            from ethereum_test_base_types import Address

            print(f"INFO: Setting fee_recipient to {custom_defaults.fee_recipient}")
            kwargs_init["fee_recipient"] = Address(custom_defaults.fee_recipient)

        # Call the original init
        original_init(self, **kwargs_init)

        # Force set the values after init in case pydantic field defaults took precedence
        # This ensures our custom values are applied even if field defaults override them
        if hasattr(self, "number") and "number" not in original_kwargs:
            self.number = custom_defaults.number
        if hasattr(self, "timestamp") and "timestamp" not in original_kwargs:
            self.timestamp = custom_defaults.timestamp
        if hasattr(self, "fee_recipient") and "fee_recipient" not in original_kwargs:
            from ethereum_test_base_types import Address

            self.fee_recipient = Address(custom_defaults.fee_recipient)

        # Conditionally ensure block_hashes includes Gnosis genesis hash if not explicitly provided
        if (
            patch_genesis_hash
            and hasattr(self, "block_hashes")
            and "block_hashes" not in original_kwargs
        ):
            from ethereum_test_base_types import Hash, Number

            genesis_number = Number(0)
            genesis_hash = Hash(GNOSIS_GENESIS_HASH)

            # If block_hashes is empty or doesn't have genesis, set it properly
            if not self.block_hashes or genesis_number not in self.block_hashes:
                if self.block_hashes is None:
                    self.block_hashes = {}
                self.block_hashes[genesis_number] = genesis_hash

    # Replace the Environment class's __init__ method
    setattr(block_types.Environment, "__init__", patched_init)

    # Don't patch Block.set_environment - any modification breaks the internal structure
    # Blockchain tests are designed to test state transitions to the "next block"
    # The currentNumber=1 and currentTimestamp=12 represent the block being tested

    # Conditionally monkey patch set_fork_requirements to preserve block_hashes
    if patch_genesis_hash:
        _patch_set_fork_requirements()

    print("INFO: Patched Environment class with custom defaults:")
    print(f"  - gas_limit: {custom_defaults.gas_limit:,} ({hex(custom_defaults.gas_limit)})")
    print(f"  - number: {custom_defaults.number}")
    print(f"  - timestamp: {custom_defaults.timestamp}")
    print(f"  - base_fee_per_gas: {custom_defaults.base_fee_per_gas}")
    print(f"  - difficulty: {hex(custom_defaults.difficulty)}")
    print(f"  - excess_blob_gas: {custom_defaults.excess_blob_gas}")
    print(f"  - fee_recipient: {custom_defaults.fee_recipient}")
    if patch_genesis_hash:
        print(f"  - block_hashes: Default includes Gnosis genesis hash ({GNOSIS_GENESIS_HASH})")
        print("  - set_fork_requirements: Patched to preserve genesis hash")
    else:
        print("  - block_hashes: Default factory (no genesis hash patching)")
        print("  - set_fork_requirements: Not patched (use --gnosis for genesis hash handling)")

