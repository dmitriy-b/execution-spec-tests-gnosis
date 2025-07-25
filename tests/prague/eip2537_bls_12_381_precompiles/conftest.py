"""Shared pytest definitions local to EIP-2537 tests."""

from typing import SupportsBytes

import pytest

from ethereum_test_forks import Fork
from ethereum_test_tools import EOA, Address, Alloc, Bytecode, Storage, Transaction, keccak256
from ethereum_test_tools import Opcodes as Op

from .helpers import BLSPointGenerator
from .spec import GAS_CALCULATION_FUNCTION_MAP


@pytest.fixture
def vector_gas_value() -> int | None:
    """
    Gas value from the test vector if any.

    If `None` it means that the test scenario did not come from a file, so no comparison is needed.

    The `vectors_from_file` function reads the gas value from the file and overwrites this fixture.
    """
    return None


@pytest.fixture
def precompile_gas(
    precompile_address: int, input_data: bytes, vector_gas_value: int | None
) -> int:
    """Gas cost for the precompile."""
    calculated_gas = GAS_CALCULATION_FUNCTION_MAP[precompile_address](len(input_data))
    if vector_gas_value is not None:
        assert calculated_gas == vector_gas_value, (
            f"Calculated gas {calculated_gas} != Vector gas {vector_gas_value}"
        )
    return calculated_gas


@pytest.fixture
def precompile_gas_modifier() -> int:
    """
    Modify the gas passed to the precompile, for testing purposes.

    By default the call is made with the exact gas amount required for the given opcode,
    but when this fixture is overridden, the gas amount can be modified to, e.g., test
    a lower amount and test if the precompile call fails.
    """
    return 0


@pytest.fixture
def call_opcode() -> Op:
    """
    Type of call used to call the precompile.

    By default it is Op.CALL, but it can be overridden in the test.
    """
    return Op.CALL


@pytest.fixture
def call_contract_post_storage() -> Storage:
    """
    Storage of the test contract after the transaction is executed.
    Note: Fixture `call_contract_code` fills the actual expected storage values.
    """
    return Storage()


@pytest.fixture
def call_succeeds(
    expected_output: bytes | SupportsBytes,
) -> bool:
    """
    By default, depending on the expected output, we can deduce if the call is expected to succeed
    or fail.
    """
    return len(bytes(expected_output)) > 0


@pytest.fixture
def call_contract_code(
    precompile_address: int,
    precompile_gas: int | None,
    precompile_gas_modifier: int,
    expected_output: bytes | SupportsBytes,
    call_succeeds: bool,
    call_opcode: Op,
    call_contract_post_storage: Storage,
) -> Bytecode:
    """
    Code of the test contract.

    Args:
        precompile_address:
            Address of the precompile to call.
        precompile_gas:
            Gas cost for the precompile, which is automatically calculated by the `precompile_gas`
            fixture, but can be overridden in the test.
        precompile_gas_modifier:
            Gas cost modifier for the precompile, which is automatically set to zero by the
            `precompile_gas_modifier` fixture, but can be overridden in the test.
        expected_output:
            Expected output of the precompile call. This value is used to determine if the call is
            expected to succeed or fail.
        call_succeeds:
            Boolean that indicates if the call is expected to succeed or fail.
        call_opcode:
            Type of call used to call the precompile (Op.CALL, Op.CALLCODE, Op.DELEGATECALL,
            Op.STATICCALL).
        call_contract_post_storage:
            Storage of the test contract after the transaction is executed.

    """
    expected_output = bytes(expected_output)

    assert call_opcode in [Op.CALL, Op.CALLCODE, Op.DELEGATECALL, Op.STATICCALL]
    value = [0] if call_opcode in [Op.CALL, Op.CALLCODE] else []

    precompile_gas_value_opcode: int | Op
    if precompile_gas is None:
        precompile_gas_value_opcode = Op.GAS
    else:
        precompile_gas_value_opcode = precompile_gas + precompile_gas_modifier

    code = (
        Op.CALLDATACOPY(0, 0, Op.CALLDATASIZE())
        + Op.SSTORE(
            call_contract_post_storage.store_next(call_succeeds),
            call_opcode(
                precompile_gas_value_opcode,
                precompile_address,
                *value,  # Optional, only used for CALL and CALLCODE.
                0,
                Op.CALLDATASIZE(),
                0,
                0,
            ),
        )
        + Op.SSTORE(
            call_contract_post_storage.store_next(len(expected_output)),
            Op.RETURNDATASIZE(),
        )
    )
    if call_succeeds:
        # Add integrity check only if the call is expected to succeed.
        code += Op.RETURNDATACOPY(0, 0, Op.RETURNDATASIZE()) + Op.SSTORE(
            call_contract_post_storage.store_next(keccak256(expected_output)),
            Op.SHA3(0, Op.RETURNDATASIZE()),
        )

    return code


@pytest.fixture
def call_contract_address(pre: Alloc, call_contract_code: Bytecode) -> Address:
    """Address where the test contract will be deployed."""
    return pre.deploy_contract(call_contract_code)


@pytest.fixture
def sender(pre: Alloc) -> EOA:
    """Sender of the transaction."""
    return pre.fund_eoa(1_000_000_000_000_000_000)


@pytest.fixture
def post(call_contract_address: Address, call_contract_post_storage: Storage):
    """Test expected post outcome."""
    return {
        call_contract_address: {
            "storage": call_contract_post_storage,
        },
    }


@pytest.fixture
def tx_gas_limit(fork: Fork, input_data: bytes, precompile_gas: int) -> int:
    """Transaction gas limit used for the test (Can be overridden in the test)."""
    intrinsic_gas_cost_calculator = fork.transaction_intrinsic_cost_calculator()
    memory_expansion_gas_calculator = fork.memory_expansion_gas_calculator()
    extra_gas = 100_000
    return (
        extra_gas
        + intrinsic_gas_cost_calculator(calldata=input_data)
        + memory_expansion_gas_calculator(new_bytes=len(input_data))
        + precompile_gas
    )


@pytest.fixture
def tx(
    input_data: bytes,
    tx_gas_limit: int,
    call_contract_address: Address,
    sender: EOA,
) -> Transaction:
    """Transaction for the test."""
    return Transaction(
        gas_limit=tx_gas_limit,
        data=input_data,
        to=call_contract_address,
        sender=sender,
    )


NUM_TEST_POINTS = 5

# Random points not in the subgroup (fast to generate)
G1_POINTS_NOT_IN_SUBGROUP = [
    BLSPointGenerator.generate_random_g1_point_not_in_subgroup(seed=i)
    for i in range(NUM_TEST_POINTS)
]
G2_POINTS_NOT_IN_SUBGROUP = [
    BLSPointGenerator.generate_random_g2_point_not_in_subgroup(seed=i)
    for i in range(NUM_TEST_POINTS)
]
# Field points that maps to the identity point using `BLS12_MAP_FP_TO_G1`
G1_FIELD_POINTS_MAP_TO_IDENTITY = BLSPointGenerator.generate_g1_map_isogeny_kernel_points()

# Random points not on the curve (fast to generate)
G1_POINTS_NOT_ON_CURVE = [
    BLSPointGenerator.generate_random_g1_point_not_on_curve(seed=i) for i in range(NUM_TEST_POINTS)
]
G2_POINTS_NOT_ON_CURVE = [
    BLSPointGenerator.generate_random_g2_point_not_on_curve(seed=i) for i in range(NUM_TEST_POINTS)
]

# Field points that maps to the identity point using `BLS12_MAP_FP_TO_G2`
G2_FIELD_POINTS_MAP_TO_IDENTITY = BLSPointGenerator.generate_g2_map_isogeny_kernel_points()
