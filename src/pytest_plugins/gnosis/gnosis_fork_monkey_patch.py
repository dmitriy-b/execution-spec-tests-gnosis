"""Fork parameter monkey patching for Gnosis customizations."""

from typing import Any, Dict, Mapping, Optional, Type

from ethereum_test_forks.base_fork import BaseFork

# Import Gnosis defaults to keep values in sync
from .gnosis import (DEFAULT_GNOSIS_BLOB_BASE_FEE_UPDATE_FRACTION,
                     DEFAULT_GNOSIS_MAX_BLOBS_PER_BLOCK,
                     DEFAULT_GNOSIS_TARGET_BLOBS_PER_BLOCK,
                     GNOSIS_CHAIN_ACCOUNTS, GNOSIS_PRE_ALLOCATED_ACCOUNTS,
                     GNOSIS_SYSTEM_CONTRACTS)

# Store original fork methods for restoration
_original_fork_methods: Dict[Type[BaseFork], Dict[str, Any]] = {}

# Store custom parameters to apply
_custom_fork_params: Dict[str, Any] = {}

# Flag to control whether to patch pre-allocation
_patch_pre_allocation: bool = False


def set_custom_fork_parameters(
    blob_base_fee_update_fraction: Optional[int] = None,
    target_blobs_per_block: Optional[int] = None,
    max_blobs_per_block: Optional[int] = None,
    patch_pre_allocation: bool = False,
) -> None:
    """Set custom fork parameters that will be applied to any fork.
    
    If None is provided for a parameter, the corresponding Gnosis default will be used.
    Default values:
    - blob_base_fee_update_fraction: DEFAULT_GNOSIS_BLOB_BASE_FEE_UPDATE_FRACTION ({DEFAULT_GNOSIS_BLOB_BASE_FEE_UPDATE_FRACTION})
    - target_blobs_per_block: DEFAULT_GNOSIS_TARGET_BLOBS_PER_BLOCK ({DEFAULT_GNOSIS_TARGET_BLOBS_PER_BLOCK})
    - max_blobs_per_block: DEFAULT_GNOSIS_MAX_BLOBS_PER_BLOCK ({DEFAULT_GNOSIS_MAX_BLOBS_PER_BLOCK})
    - patch_pre_allocation: Whether to patch pre_allocation_blockchain method to include Gnosis accounts
    """
    global _custom_fork_params, _patch_pre_allocation
    
    _custom_fork_params = {}
    _patch_pre_allocation = patch_pre_allocation
    
    if blob_base_fee_update_fraction is not None:
        _custom_fork_params['blob_base_fee_update_fraction'] = blob_base_fee_update_fraction
    if target_blobs_per_block is not None:
        _custom_fork_params['target_blobs_per_block'] = target_blobs_per_block
    if max_blobs_per_block is not None:
        _custom_fork_params['max_blobs_per_block'] = max_blobs_per_block


def apply_gnosis_defaults_to_all_forks(patch_pre_allocation: bool = True) -> None:
    """Apply Gnosis default fork parameters to all blob-supporting forks.
    
    This is useful when you want to make all forks use Gnosis-like defaults
    without specifying custom values.
    
    Args:
        patch_pre_allocation: Whether to also patch pre-allocation to include Gnosis accounts
    """
    set_custom_fork_parameters(
        blob_base_fee_update_fraction=DEFAULT_GNOSIS_BLOB_BASE_FEE_UPDATE_FRACTION,
        target_blobs_per_block=DEFAULT_GNOSIS_TARGET_BLOBS_PER_BLOCK,
        max_blobs_per_block=DEFAULT_GNOSIS_MAX_BLOBS_PER_BLOCK,
        patch_pre_allocation=patch_pre_allocation,
    )
    patch_fork_parameters()


def patch_fork_parameters() -> None:
    """Monkey patch all fork classes to use custom parameters when available."""
    # Import here to avoid circular imports
    from ethereum_test_forks import get_forks
    
    if not _custom_fork_params and not _patch_pre_allocation:
        return  # No custom parameters to apply
    
    print(f"🔧 Patching fork parameters: {_custom_fork_params}, pre_allocation: {_patch_pre_allocation}")
    
    # Get all available forks
    forks = get_forks()
    
    for fork_class in forks:
        # Store original methods if not already stored
        if fork_class not in _original_fork_methods:
            _original_fork_methods[fork_class] = {}
            
            # Store original methods
            if hasattr(fork_class, 'blob_base_fee_update_fraction'):
                _original_fork_methods[fork_class]['blob_base_fee_update_fraction'] = fork_class.blob_base_fee_update_fraction
            if hasattr(fork_class, 'target_blobs_per_block'):
                _original_fork_methods[fork_class]['target_blobs_per_block'] = fork_class.target_blobs_per_block
            if hasattr(fork_class, 'max_blobs_per_block'):
                _original_fork_methods[fork_class]['max_blobs_per_block'] = fork_class.max_blobs_per_block
            if hasattr(fork_class, 'pre_allocation_blockchain'):
                _original_fork_methods[fork_class]['pre_allocation_blockchain'] = fork_class.pre_allocation_blockchain
        
        # Skip blob parameter patching if this fork doesn't support blobs
        patch_blob_params = _custom_fork_params and hasattr(fork_class, 'supports_blobs')
        if patch_blob_params:
            try:
                # Check if fork supports blobs at all
                if not fork_class.supports_blobs():
                    patch_blob_params = False
            except (NotImplementedError, AttributeError):
                patch_blob_params = False
        
        # Patch blob_base_fee_update_fraction if specified
        if patch_blob_params and 'blob_base_fee_update_fraction' in _custom_fork_params:
            custom_value = _custom_fork_params['blob_base_fee_update_fraction']
            setattr(fork_class, 'blob_base_fee_update_fraction', 
                   classmethod(lambda cls, block_number=0, timestamp=0, value=custom_value: value))
        
        # Patch target_blobs_per_block if specified
        if patch_blob_params and 'target_blobs_per_block' in _custom_fork_params:
            custom_value = _custom_fork_params['target_blobs_per_block']
            setattr(fork_class, 'target_blobs_per_block',
                   classmethod(lambda cls, block_number=0, timestamp=0, value=custom_value: value))
        
        # Patch max_blobs_per_block if specified
        if patch_blob_params and 'max_blobs_per_block' in _custom_fork_params:
            custom_value = _custom_fork_params['max_blobs_per_block']
            setattr(fork_class, 'max_blobs_per_block',
                   classmethod(lambda cls, block_number=0, timestamp=0, value=custom_value: value))
        
        # Patch pre_allocation_blockchain if requested
        if _patch_pre_allocation and hasattr(fork_class, 'pre_allocation_blockchain'):
            original_method = _original_fork_methods[fork_class]['pre_allocation_blockchain']
            
            def create_patched_pre_allocation(original_pre_allocation):
                def patched_pre_allocation(cls) -> Mapping:
                    """Return pre-allocation with Gnosis accounts added."""
                    # Get original allocation
                    original_allocation = dict(original_pre_allocation())
                    
                    # Add Gnosis allocations
                    gnosis_allocation = {}
                    gnosis_allocation.update(GNOSIS_CHAIN_ACCOUNTS)
                    gnosis_allocation.update(GNOSIS_SYSTEM_CONTRACTS)
                    gnosis_allocation.update(GNOSIS_PRE_ALLOCATED_ACCOUNTS)
                    
                    # Merge allocations (Gnosis accounts override original ones)
                    # return original_allocation | gnosis_allocation
                    return gnosis_allocation
                # Return the patched pre-allocation method
                return classmethod(patched_pre_allocation)
            
            setattr(fork_class, 'pre_allocation_blockchain', create_patched_pre_allocation(original_method))
        
        print(f"  ✓ Patched {fork_class.__name__}")

