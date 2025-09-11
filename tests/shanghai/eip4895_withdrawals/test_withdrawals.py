"""
abstract: Tests [EIP-4895: Beacon chain withdrawals](https://eips.ethereum.org/EIPS/eip-4895)
    Test cases for [EIP-4895: Beacon chain push withdrawals as
    operations](https://eips.ethereum.org/EIPS/eip-4895).
"""

import pytest

from ethereum_test_tools import (
    Account,
    Address,
    Alloc,
    Block,
    BlockchainTestFiller,
    Withdrawal,
)
from ethereum_test_tools.vm.opcode import Opcodes as Op

from .spec import ref_spec_4895

REFERENCE_SPEC_GIT_PATH = ref_spec_4895.git_path
REFERENCE_SPEC_VERSION = ref_spec_4895.version

pytestmark = pytest.mark.valid_from("Shanghai")


def test_store_withdrawal_values_in_contract(
    blockchain_test: BlockchainTestFiller,
    pre: Alloc,
):
    """Test that system transaction calldata is correctly formed."""
    contract_address = pre.deploy_contract(
        code=Op.SSTORE(0, Op.CALLDATASIZE) + sum(Op.SSTORE(i + 1, Op.CALLDATALOAD(i * 32)) for i in range(10))
    )

    withdrawal_1 = Withdrawal(
        index=0,
        validator_index=0,
        address=Address(0x0a),
        amount=0x0c,
    )
    withdrawal_2 = Withdrawal(
        index=0,
        validator_index=0,
        address=Address(0x0b),
        amount=0x0d,
    )

    blocks = [
        Block(
            withdrawals=[withdrawal_1, withdrawal_2],
        ),
    ]
# Function signature
#
#    function executeSystemWithdrawals(
#        uint256 maxFailedWithdrawalsToProcess,
#        uint64[] amounts,
#        address[] addresses
#    )
#
# Encoded words:
# ── selector
# ── maxFailedWithdrawalsToProcess = 0
# ── offset to amounts[]  (96 bytes)
# ── offset to addresses[] (192 bytes)
# ── amounts.length = 2
# ── amounts[0]
# ── amounts[1]
# ── addresses.length = 2
# ── addresses[0]
# ── addresses[1]
    post = {
        contract_address: Account(
            storage={
                0x00: 0x99face17000000000000000000000000000000000000000000000000000000
                0x01: 0000000000000000000000000000000000000000000000000000000000000000
                0x02: 0000000060000000000000000000000000000000000000000000000000000000
                0x03: 00000000c0000000000000000000000000000000000000000000000000000000
                0x04: 0000000002000000000000000000000000000000000000000000000000000000
                0x05: 000000000c000000000000000000000000000000000000000000000000000000
                0x06: 000000000d000000000000000000000000000000000000000000000000000000
                0x07: 0000000002000000000000000000000000000000000000000000000000000000
                0x08: 000000000a000000000000000000000000000000000000000000000000000000
                0x09: 000000000b000000000000000000000000000000000000000000000000000000
            }
        ),
    }

    blockchain_test(pre=pre, post=post, blocks=blocks)

def test_withdrawal_system_call_reverts(
    blockchain_test: BlockchainTestFiller,
    pre: Alloc,
):
    """Test the system contract call reverting."""
    contract_address = pre.deploy_contract(
        code=Op.REVERT(0, 0)
    )

    withdrawal = Withdrawal(
        index=0,
        validator_index=0,
        address=Address(0x01),
        amount=1,
    )

    blocks = [
        Block(
            withdrawals=[withdrawal],
        ),
    ]
    post = {}

    blockchain_test(pre=pre, post=post, blocks=blocks)

def test_withdrawal_system_call_runs_out_of_gas(
    blockchain_test: BlockchainTestFiller,
    pre: Alloc,
):
    """Test the system contract call reverting."""
    contract_address = pre.deploy_contract(
        code=Op.INVALID
    )

    withdrawal = Withdrawal(
        index=0,
        validator_index=0,
        address=Address(0x01),
        amount=1,
    )

    blocks = [
        Block(
            withdrawals=[withdrawal],
        ),
    ]
    post = {}

    blockchain_test(pre=pre, post=post, blocks=blocks)


def test_empty_withdrawals_list(
    blockchain_test: BlockchainTestFiller,
    pre: Alloc,
):
    """Test that the system contract call is done even if the withdrawal list is empty."""
    contract_address = pre.deploy_contract(
        code=Op.SSTORE(0, 1)
    )

    blocks = [
        Block(
            withdrawals=[],
        ),
    ]
    post = {
        contract_address: Account(
            storage={
                0x0: 0x1,
            }
        ),
    }

    blockchain_test(pre=pre, post=post, blocks=blocks)

# TODO: Test with contract not deployed
