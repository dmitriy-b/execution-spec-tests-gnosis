"""Gnosis chain fork configuration."""

from typing import Dict, List, Mapping, Type

from ethereum_test_forks import Cancun, Fork
from ethereum_test_forks.base_fork import BaseFork
from ethereum_test_forks.helpers import get_forks
from pytest_plugins.gnosis.gnosis_block_types import GNOSIS_GENESIS_HASH

# Default Gnosis chain parameters
DEFAULT_GNOSIS_BLOB_BASE_FEE_UPDATE_FRACTION = 2504285  # Custom value for Gnosis (between Cancun 3.3M and Prague 5M)
DEFAULT_GNOSIS_TARGET_BLOBS_PER_BLOCK = 1  # Custom value for Gnosis (between Cancun 3 and Prague 6)
DEFAULT_GNOSIS_MAX_BLOBS_PER_BLOCK = 2     # Custom value for Gnosis (between Cancun 6 and Prague 9)

# Global variables to store customized values (set by plugin)
_gnosis_blob_base_fee_update_fraction = DEFAULT_GNOSIS_BLOB_BASE_FEE_UPDATE_FRACTION
_gnosis_target_blobs_per_block = DEFAULT_GNOSIS_TARGET_BLOBS_PER_BLOCK
_gnosis_max_blobs_per_block = DEFAULT_GNOSIS_MAX_BLOBS_PER_BLOCK

# Gnosis chain system contracts and pre-allocated accounts
GNOSIS_SYSTEM_CONTRACTS = {
    # BLS12-381 precompile test contract
    "0x0000000000000000000000000000000000001000": {
        "nonce": "0x01",
        "balance": "0x00",
        "code": "0x366000600037600060003660006000600b610177f16000553d6001553d600060003e3d600020600255",
        "storage": {}
    },
}

GNOSIS_PRE_ALLOCATED_ACCOUNTS = {
    # Standard test account with funding
    "0xa94f5374fce5edbc8e2a8697c15331677e6ebf0b": {
        "nonce": "0x00",
        "balance": "0x0de0b6b3a7640000",  # 1 ETH
        "code": "0x",
        "storage": {}
    },
}

# Additional Gnosis-specific accounts
GNOSIS_CHAIN_ACCOUNTS = {
    "0x0000000000000000000000000000000000000000": {
        "balance": "0x3",
        "nonce": "0x2",
        "code": "0x",
        "storage": {}
    },
    "0x1234567890123456789012345678901234567890": {
        "balance": "0x56bc75e2d630eb20",  # 6.25 ETH
        "nonce": "0x0",
        "code": "0x",
        "storage": {}
    }
}


def set_gnosis_fork_parameters(
    blob_base_fee_update_fraction: int = DEFAULT_GNOSIS_BLOB_BASE_FEE_UPDATE_FRACTION,
    target_blobs_per_block: int = DEFAULT_GNOSIS_TARGET_BLOBS_PER_BLOCK,
    max_blobs_per_block: int = DEFAULT_GNOSIS_MAX_BLOBS_PER_BLOCK,
):
    """Set global Gnosis fork parameters."""
    global _gnosis_blob_base_fee_update_fraction, _gnosis_target_blobs_per_block, _gnosis_max_blobs_per_block
    _gnosis_blob_base_fee_update_fraction = blob_base_fee_update_fraction
    _gnosis_target_blobs_per_block = target_blobs_per_block
    _gnosis_max_blobs_per_block = max_blobs_per_block


class Gnosis(Cancun):
    """Gnosis chain fork class.
    
    Currently based on Cancun fork with Gnosis-specific parameters.
    Supports blobs with custom configuration.
    """
    
    @classmethod
    def name(cls) -> str:
        """Return the name of the fork."""
        return "Gnosis"
    
    # @classmethod
    # def blockchain_test_network_name(cls) -> str:
    #     """Return the network name for blockchain tests."""
    #     if cls._blockchain_test_network_name is not None:
    #         return cls._blockchain_test_network_name
    #     return "gnosis"
    
    @classmethod
    def is_deployed(cls) -> bool:
        """Indicate that this fork is deployed (not in development)."""
        return True
    
    @classmethod
    def blob_base_fee_update_fraction(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Return the blob base fee update fraction for Gnosis."""
        return _gnosis_blob_base_fee_update_fraction
    
    @classmethod
    def target_blobs_per_block(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Return the target blobs per block for Gnosis."""
        return _gnosis_target_blobs_per_block
    
    @classmethod
    def max_blobs_per_block(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Return the max blobs per block for Gnosis."""
        return _gnosis_max_blobs_per_block
    
    @classmethod
    def pre_allocation_blockchain(cls) -> Mapping:
        """Return the pre-allocation mapping for the Gnosis chain."""
        # Combine all Gnosis-specific allocations
        gnosis_allocation = {}
        gnosis_allocation.update(GNOSIS_CHAIN_ACCOUNTS)
        gnosis_allocation.update(GNOSIS_SYSTEM_CONTRACTS)
        gnosis_allocation.update(GNOSIS_PRE_ALLOCATED_ACCOUNTS)
        
        # Include parent allocations from Cancun
        parent_allocation = dict(super(Gnosis, cls).pre_allocation_blockchain())
        return gnosis_allocation | parent_allocation

