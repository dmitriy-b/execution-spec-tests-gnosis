"""All Ethereum fork class definitions."""

from dataclasses import replace
from hashlib import sha256
from os.path import realpath
from pathlib import Path
from typing import List, Literal, Mapping, Optional, Sized, Tuple

from ethereum_test_base_types import (AccessList, Address, BlobSchedule, Bytes,
                                      ForkBlobSchedule)
from ethereum_test_base_types.conversions import BytesConvertible
from ethereum_test_vm import EVMCodeType, Opcodes

from ..base_fork import (BaseFork, BlobGasPriceCalculator,
                         CalldataGasCalculator, ExcessBlobGasCalculator,
                         MemoryExpansionGasCalculator,
                         TransactionDataFloorCostCalculator,
                         TransactionIntrinsicCostCalculator)
from ..gas_costs import GasCosts
from .helpers import ceiling_division, fake_exponential

CURRENT_FILE = Path(realpath(__file__))
CURRENT_FOLDER = CURRENT_FILE.parent


# All forks must be listed here !!! in the order they were introduced !!!
class Frontier(BaseFork, solc_name="homestead"):
    """Frontier fork."""

    @classmethod
    def transition_tool_name(cls, block_number: int = 0, timestamp: int = 0) -> str:
        """Return fork name as it's meant to be passed to the transition tool for execution."""
        if cls._transition_tool_name is not None:
            return cls._transition_tool_name
        return cls.name()

    @classmethod
    def solc_name(cls) -> str:
        """Return fork name as it's meant to be passed to the solc compiler."""
        if cls._solc_name is not None:
            return cls._solc_name
        return cls.name().lower()

    @classmethod
    def header_base_fee_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At genesis, header must not contain base fee."""
        return False

    @classmethod
    def header_prev_randao_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At genesis, header must not contain Prev Randao value."""
        return False

    @classmethod
    def header_zero_difficulty_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At genesis, header must not have difficulty zero."""
        return False

    @classmethod
    def header_withdrawals_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At genesis, header must not contain withdrawals."""
        return False

    @classmethod
    def header_excess_blob_gas_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At genesis, header must not contain excess blob gas."""
        return False

    @classmethod
    def header_blob_gas_used_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At genesis, header must not contain blob gas used."""
        return False

    @classmethod
    def gas_costs(cls, block_number: int = 0, timestamp: int = 0) -> GasCosts:
        """Return dataclass with the defined gas costs constants for genesis."""
        return GasCosts(
            G_JUMPDEST=1,
            G_BASE=2,
            G_VERY_LOW=3,
            G_LOW=5,
            G_MID=8,
            G_HIGH=10,
            G_WARM_ACCOUNT_ACCESS=100,
            G_COLD_ACCOUNT_ACCESS=2_600,
            G_ACCESS_LIST_ADDRESS=2_400,
            G_ACCESS_LIST_STORAGE=1_900,
            G_WARM_SLOAD=100,
            G_COLD_SLOAD=2_100,
            G_STORAGE_SET=20_000,
            G_STORAGE_RESET=2_900,
            R_STORAGE_CLEAR=4_800,
            G_SELF_DESTRUCT=5_000,
            G_CREATE=32_000,
            G_CODE_DEPOSIT_BYTE=200,
            G_INITCODE_WORD=2,
            G_CALL_VALUE=9_000,
            G_CALL_STIPEND=2_300,
            G_NEW_ACCOUNT=25_000,
            G_EXP=10,
            G_EXP_BYTE=50,
            G_MEMORY=3,
            G_TX_DATA_ZERO=4,
            G_TX_DATA_NON_ZERO=68,
            G_TX_DATA_STANDARD_TOKEN_COST=0,
            G_TX_DATA_FLOOR_TOKEN_COST=0,
            G_TRANSACTION=21_000,
            G_TRANSACTION_CREATE=32_000,
            G_LOG=375,
            G_LOG_DATA=8,
            G_LOG_TOPIC=375,
            G_KECCAK_256=30,
            G_KECCAK_256_WORD=6,
            G_COPY=3,
            G_BLOCKHASH=20,
            G_AUTHORIZATION=0,
            R_AUTHORIZATION_EXISTING_AUTHORITY=0,
        )

    @classmethod
    def memory_expansion_gas_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> MemoryExpansionGasCalculator:
        """Return callable that calculates the gas cost of memory expansion for the fork."""
        gas_costs = cls.gas_costs(block_number, timestamp)

        def fn(*, new_bytes: int, previous_bytes: int = 0) -> int:
            if new_bytes <= previous_bytes:
                return 0
            new_words = ceiling_division(new_bytes, 32)
            previous_words = ceiling_division(previous_bytes, 32)

            def c(w: int) -> int:
                return (gas_costs.G_MEMORY * w) + ((w * w) // 512)

            return c(new_words) - c(previous_words)

        return fn

    @classmethod
    def calldata_gas_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> CalldataGasCalculator:
        """
        Return callable that calculates the transaction gas cost for its calldata
        depending on its contents.
        """
        gas_costs = cls.gas_costs(block_number, timestamp)

        def fn(*, data: BytesConvertible, floor: bool = False) -> int:
            cost = 0
            for b in Bytes(data):
                if b == 0:
                    cost += gas_costs.G_TX_DATA_ZERO
                else:
                    cost += gas_costs.G_TX_DATA_NON_ZERO
            return cost

        return fn

    @classmethod
    def transaction_data_floor_cost_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> TransactionDataFloorCostCalculator:
        """At frontier, the transaction data floor cost is a constant zero."""

        def fn(*, data: BytesConvertible) -> int:
            return 0

        return fn

    @classmethod
    def transaction_intrinsic_cost_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> TransactionIntrinsicCostCalculator:
        """Return callable that calculates the intrinsic gas cost of a transaction for the fork."""
        gas_costs = cls.gas_costs(block_number, timestamp)
        calldata_gas_calculator = cls.calldata_gas_calculator(block_number, timestamp)

        def fn(
            *,
            calldata: BytesConvertible = b"",
            contract_creation: bool = False,
            access_list: List[AccessList] | None = None,
            authorization_list_or_count: Sized | int | None = None,
            return_cost_deducted_prior_execution: bool = False,
        ) -> int:
            assert access_list is None, f"Access list is not supported in {cls.name()}"
            assert authorization_list_or_count is None, (
                f"Authorizations are not supported in {cls.name()}"
            )

            intrinsic_cost: int = gas_costs.G_TRANSACTION

            if contract_creation:
                intrinsic_cost += gas_costs.G_INITCODE_WORD * ceiling_division(
                    len(Bytes(calldata)), 32
                )

            return intrinsic_cost + calldata_gas_calculator(data=calldata)

        return fn

    @classmethod
    def blob_gas_price_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> BlobGasPriceCalculator:
        """Return a callable that calculates the blob gas price at a given fork."""
        raise NotImplementedError(f"Blob gas price calculator is not supported in {cls.name()}")

    @classmethod
    def excess_blob_gas_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> ExcessBlobGasCalculator:
        """Return a callable that calculates the excess blob gas for a block at a given fork."""
        raise NotImplementedError(f"Excess blob gas calculator is not supported in {cls.name()}")

    @classmethod
    def min_base_fee_per_blob_gas(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Return the amount of blob gas used per blob at a given fork."""
        raise NotImplementedError(f"Base fee per blob gas is not supported in {cls.name()}")

    @classmethod
    def blob_base_fee_update_fraction(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Return the blob base fee update fraction at a given fork."""
        raise NotImplementedError(
            f"Blob base fee update fraction is not supported in {cls.name()}"
        )

    @classmethod
    def blob_gas_per_blob(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Return the amount of blob gas used per blob at a given fork."""
        return 0

    @classmethod
    def supports_blobs(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """Blobs are not supported at Frontier."""
        return False

    @classmethod
    def target_blobs_per_block(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Return the target number of blobs per block at a given fork."""
        raise NotImplementedError(f"Target blobs per block is not supported in {cls.name()}")

    @classmethod
    def max_blobs_per_block(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Return the max number of blobs per block at a given fork."""
        raise NotImplementedError(f"Max blobs per block is not supported in {cls.name()}")

    @classmethod
    def full_blob_tx_wrapper_version(cls, block_number: int = 0, timestamp: int = 0) -> int | None:
        """Return the version of the full blob transaction wrapper."""
        raise NotImplementedError(
            f"Full blob transaction wrapper version is not supported in {cls.name()}"
        )

    @classmethod
    def blob_schedule(cls, block_number: int = 0, timestamp: int = 0) -> BlobSchedule | None:
        """At genesis, no blob schedule is used."""
        return None

    @classmethod
    def header_requests_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At genesis, header must not contain beacon chain requests."""
        return False

    @classmethod
    def engine_new_payload_version(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> Optional[int]:
        """At genesis, payloads cannot be sent through the engine API."""
        return None

    @classmethod
    def header_beacon_root_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At genesis, header must not contain parent beacon block root."""
        return False

    @classmethod
    def engine_new_payload_blob_hashes(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At genesis, payloads do not have blob hashes."""
        return False

    @classmethod
    def engine_new_payload_beacon_root(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At genesis, payloads do not have a parent beacon block root."""
        return False

    @classmethod
    def engine_new_payload_requests(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At genesis, payloads do not have requests."""
        return False

    @classmethod
    def engine_new_payload_target_blobs_per_block(
        cls,
        block_number: int = 0,
        timestamp: int = 0,
    ) -> bool:
        """At genesis, payloads do not have target blobs per block."""
        return False

    @classmethod
    def engine_payload_attribute_target_blobs_per_block(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> bool:
        """At genesis, payload attributes do not include the target blobs per block."""
        return False

    @classmethod
    def engine_payload_attribute_max_blobs_per_block(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> bool:
        """At genesis, payload attributes do not include the max blobs per block."""
        return False

    @classmethod
    def engine_forkchoice_updated_version(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> Optional[int]:
        """At genesis, forkchoice updates cannot be sent through the engine API."""
        return cls.engine_new_payload_version(block_number, timestamp)

    @classmethod
    def engine_get_payload_version(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> Optional[int]:
        """At genesis, payloads cannot be retrieved through the engine API."""
        return cls.engine_new_payload_version(block_number, timestamp)

    @classmethod
    def engine_get_blobs_version(cls, block_number: int = 0, timestamp: int = 0) -> Optional[int]:
        """At genesis, blobs cannot be retrieved through the engine API."""
        return None

    @classmethod
    def get_reward(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """
        At Genesis the expected reward amount in wei is
        5_000_000_000_000_000_000.
        """
        return 5_000_000_000_000_000_000

    @classmethod
    def tx_types(cls, block_number: int = 0, timestamp: int = 0) -> List[int]:
        """At Genesis, only legacy transactions are allowed."""
        return [0]

    @classmethod
    def contract_creating_tx_types(cls, block_number: int = 0, timestamp: int = 0) -> List[int]:
        """At Genesis, only legacy transactions are allowed."""
        return [0]

    @classmethod
    def transaction_gas_limit_cap(cls, block_number: int = 0, timestamp: int = 0) -> int | None:
        """At Genesis, no transaction gas limit cap is imposed."""
        return None

    @classmethod
    def block_rlp_size_limit(cls, block_number: int = 0, timestamp: int = 0) -> int | None:
        """At Genesis, no RLP block size limit is imposed."""
        return None

    @classmethod
    def precompiles(cls, block_number: int = 0, timestamp: int = 0) -> List[Address]:
        """At Genesis, no pre-compiles are present."""
        return []

    @classmethod
    def system_contracts(cls, block_number: int = 0, timestamp: int = 0) -> List[Address]:
        """At Genesis, no system-contracts are present."""
        return []

    @classmethod
    def evm_code_types(cls, block_number: int = 0, timestamp: int = 0) -> List[EVMCodeType]:
        """At Genesis, only legacy EVM code is supported."""
        return [EVMCodeType.LEGACY]

    @classmethod
    def max_code_size(cls) -> int:
        """At genesis, there is no upper bound for code size (bounded by block gas limit)."""
        """However, the default is set to the limit of EIP-170 (Spurious Dragon)"""
        return 0x6000

    @classmethod
    def max_stack_height(cls) -> int:
        """At genesis, the maximum stack height is 1024."""
        return 1024

    @classmethod
    def max_initcode_size(cls) -> int:
        """At genesis, there is no upper bound for initcode size."""
        """However, the default is set to the limit of EIP-3860 (Shanghai)"""
        return 0xC000

    @classmethod
    def call_opcodes(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> List[Tuple[Opcodes, EVMCodeType]]:
        """Return list of call opcodes supported by the fork."""
        return [
            (Opcodes.CALL, EVMCodeType.LEGACY),
            (Opcodes.CALLCODE, EVMCodeType.LEGACY),
        ]

    @classmethod
    def valid_opcodes(
        cls,
    ) -> List[Opcodes]:
        """Return list of Opcodes that are valid to work on this fork."""
        return [
            Opcodes.STOP,
            Opcodes.ADD,
            Opcodes.MUL,
            Opcodes.SUB,
            Opcodes.DIV,
            Opcodes.SDIV,
            Opcodes.MOD,
            Opcodes.SMOD,
            Opcodes.ADDMOD,
            Opcodes.MULMOD,
            Opcodes.EXP,
            Opcodes.SIGNEXTEND,
            Opcodes.LT,
            Opcodes.GT,
            Opcodes.SLT,
            Opcodes.SGT,
            Opcodes.EQ,
            Opcodes.ISZERO,
            Opcodes.AND,
            Opcodes.OR,
            Opcodes.XOR,
            Opcodes.NOT,
            Opcodes.BYTE,
            Opcodes.SHA3,
            Opcodes.ADDRESS,
            Opcodes.BALANCE,
            Opcodes.ORIGIN,
            Opcodes.CALLER,
            Opcodes.CALLVALUE,
            Opcodes.CALLDATALOAD,
            Opcodes.CALLDATASIZE,
            Opcodes.CALLDATACOPY,
            Opcodes.CODESIZE,
            Opcodes.CODECOPY,
            Opcodes.GASPRICE,
            Opcodes.EXTCODESIZE,
            Opcodes.EXTCODECOPY,
            Opcodes.BLOCKHASH,
            Opcodes.COINBASE,
            Opcodes.TIMESTAMP,
            Opcodes.NUMBER,
            Opcodes.PREVRANDAO,
            Opcodes.GASLIMIT,
            Opcodes.POP,
            Opcodes.MLOAD,
            Opcodes.MSTORE,
            Opcodes.MSTORE8,
            Opcodes.SLOAD,
            Opcodes.SSTORE,
            Opcodes.PC,
            Opcodes.MSIZE,
            Opcodes.GAS,
            Opcodes.JUMP,
            Opcodes.JUMPI,
            Opcodes.JUMPDEST,
            Opcodes.PUSH1,
            Opcodes.PUSH2,
            Opcodes.PUSH3,
            Opcodes.PUSH4,
            Opcodes.PUSH5,
            Opcodes.PUSH6,
            Opcodes.PUSH7,
            Opcodes.PUSH8,
            Opcodes.PUSH9,
            Opcodes.PUSH10,
            Opcodes.PUSH11,
            Opcodes.PUSH12,
            Opcodes.PUSH13,
            Opcodes.PUSH14,
            Opcodes.PUSH15,
            Opcodes.PUSH16,
            Opcodes.PUSH17,
            Opcodes.PUSH18,
            Opcodes.PUSH19,
            Opcodes.PUSH20,
            Opcodes.PUSH21,
            Opcodes.PUSH22,
            Opcodes.PUSH23,
            Opcodes.PUSH24,
            Opcodes.PUSH25,
            Opcodes.PUSH26,
            Opcodes.PUSH27,
            Opcodes.PUSH28,
            Opcodes.PUSH29,
            Opcodes.PUSH30,
            Opcodes.PUSH31,
            Opcodes.PUSH32,
            Opcodes.DUP1,
            Opcodes.DUP2,
            Opcodes.DUP3,
            Opcodes.DUP4,
            Opcodes.DUP5,
            Opcodes.DUP6,
            Opcodes.DUP7,
            Opcodes.DUP8,
            Opcodes.DUP9,
            Opcodes.DUP10,
            Opcodes.DUP11,
            Opcodes.DUP12,
            Opcodes.DUP13,
            Opcodes.DUP14,
            Opcodes.DUP15,
            Opcodes.DUP16,
            Opcodes.SWAP1,
            Opcodes.SWAP2,
            Opcodes.SWAP3,
            Opcodes.SWAP4,
            Opcodes.SWAP5,
            Opcodes.SWAP6,
            Opcodes.SWAP7,
            Opcodes.SWAP8,
            Opcodes.SWAP9,
            Opcodes.SWAP10,
            Opcodes.SWAP11,
            Opcodes.SWAP12,
            Opcodes.SWAP13,
            Opcodes.SWAP14,
            Opcodes.SWAP15,
            Opcodes.SWAP16,
            Opcodes.LOG0,
            Opcodes.LOG1,
            Opcodes.LOG2,
            Opcodes.LOG3,
            Opcodes.LOG4,
            Opcodes.CREATE,
            Opcodes.CALL,
            Opcodes.CALLCODE,
            Opcodes.RETURN,
            Opcodes.SELFDESTRUCT,
        ]

    @classmethod
    def create_opcodes(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> List[Tuple[Opcodes, EVMCodeType]]:
        """At Genesis, only `CREATE` opcode is supported."""
        return [
            (Opcodes.CREATE, EVMCodeType.LEGACY),
        ]

    @classmethod
    def max_request_type(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """At genesis, no request type is supported, signaled by -1."""
        return -1

    @classmethod
    def pre_allocation(cls) -> Mapping:
        """
        Return whether the fork expects pre-allocation of accounts.

        Frontier does not require pre-allocated accounts
        """
        return {}

    @classmethod
    def pre_allocation_blockchain(cls) -> Mapping:
        """
        Return whether the fork expects pre-allocation of accounts.

        Frontier does not require pre-allocated accounts
        """
# contract EmptyRewarder {
#    fallback() external payable {
#        assembly {
#            let ptr := mload(0x40)
#            mstore(ptr,       0x40)
#            mstore(add(ptr,32), 0x60)
#            mstore(add(ptr,64), 0)
#            mstore(add(ptr,96), 0)
#            return(ptr, 0x80)
#        }
#    }
# }
        new_allocation = {
            # Hardcoded address of the BlockReward contract
            0x2000000000000000000000000000000000000001: {
                "nonce": 1,
                "code": "0x608060408181528152606060a0525f60c081905260e0528080f3fea264697066735822"
                "1220ad48f9b500787ea20a77467cda4f31efaf4768b15664ca9fb5e0639aea63976e64736f6c6343"
                "00081e0033"
            }
        }
        return new_allocation | super(Cancun, cls).pre_allocation_blockchain()  # type: ignore


class Homestead(Frontier):
    """Homestead fork."""

    @classmethod
    def precompiles(cls, block_number: int = 0, timestamp: int = 0) -> List[Address]:
        """
        At Homestead, EC-recover, SHA256, RIPEMD160, and Identity pre-compiles
        are introduced.
        """
        return [
            Address(1, label="ECREC"),
            Address(2, label="SHA256"),
            Address(3, label="RIPEMD160"),
            Address(4, label="ID"),
        ] + super(Homestead, cls).precompiles(block_number, timestamp)

    @classmethod
    def call_opcodes(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> List[Tuple[Opcodes, EVMCodeType]]:
        """At Homestead, DELEGATECALL opcode was introduced."""
        return [(Opcodes.DELEGATECALL, EVMCodeType.LEGACY)] + super(Homestead, cls).call_opcodes(
            block_number, timestamp
        )

    @classmethod
    def valid_opcodes(
        cls,
    ) -> List[Opcodes]:
        """Return the list of Opcodes that are valid to work on this fork."""
        return [Opcodes.DELEGATECALL] + super(Homestead, cls).valid_opcodes()

    @classmethod
    def transaction_intrinsic_cost_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> TransactionIntrinsicCostCalculator:
        """
        At Homestead, the transaction intrinsic cost needs to take contract
        creation into account.
        """
        super_fn = super(Homestead, cls).transaction_intrinsic_cost_calculator(
            block_number, timestamp
        )
        gas_costs = cls.gas_costs(block_number, timestamp)

        def fn(
            *,
            calldata: BytesConvertible = b"",
            contract_creation: bool = False,
            access_list: List[AccessList] | None = None,
            authorization_list_or_count: Sized | int | None = None,
            return_cost_deducted_prior_execution: bool = False,
        ) -> int:
            intrinsic_cost: int = super_fn(
                calldata=calldata,
                contract_creation=contract_creation,
                access_list=access_list,
                authorization_list_or_count=authorization_list_or_count,
            )
            if contract_creation:
                intrinsic_cost += gas_costs.G_TRANSACTION_CREATE
            return intrinsic_cost

        return fn


class DAOFork(Homestead, ignore=True):
    """DAO fork."""

    pass


class Tangerine(DAOFork, ignore=True):
    """Tangerine fork (EIP-150)."""

    pass


class SpuriousDragon(Tangerine, ignore=True):
    """SpuriousDragon fork (EIP-155, EIP-158)."""

    pass


class Byzantium(Homestead):
    """Byzantium fork."""

    @classmethod
    def get_reward(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """
        At Byzantium, the block reward is reduced to
        3_000_000_000_000_000_000 wei.
        """
        return 3_000_000_000_000_000_000

    @classmethod
    def precompiles(cls, block_number: int = 0, timestamp: int = 0) -> List[Address]:
        """
        At Byzantium, pre-compiles for bigint modular exponentiation, addition and scalar
        multiplication on elliptic curve alt_bn128, and optimal ate pairing check on
        elliptic curve alt_bn128 are introduced.
        """
        return [
            Address(5, label="MODEXP"),
            Address(6, label="BN256_ADD"),
            Address(7, label="BN256_MUL"),
            Address(8, label="BN256_PAIRING"),
        ] + super(Byzantium, cls).precompiles(block_number, timestamp)

    @classmethod
    def max_code_size(cls) -> int:
        # NOTE: Move this to Spurious Dragon once this fork is introduced. See EIP-170.
        """At Spurious Dragon, an upper bound was introduced for max contract code size."""
        return 0x6000

    @classmethod
    def call_opcodes(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> List[Tuple[Opcodes, EVMCodeType]]:
        """At Byzantium, STATICCALL opcode was introduced."""
        return [(Opcodes.STATICCALL, EVMCodeType.LEGACY)] + super(Byzantium, cls).call_opcodes(
            block_number, timestamp
        )

    @classmethod
    def valid_opcodes(
        cls,
    ) -> List[Opcodes]:
        """Return list of Opcodes that are valid to work on this fork."""
        return [
            Opcodes.REVERT,
            Opcodes.RETURNDATASIZE,
            Opcodes.RETURNDATACOPY,
            Opcodes.STATICCALL,
        ] + super(Byzantium, cls).valid_opcodes()


class Constantinople(Byzantium):
    """Constantinople fork."""

    @classmethod
    def get_reward(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """
        At Constantinople, the block reward is reduced to
        2_000_000_000_000_000_000 wei.
        """
        return 2_000_000_000_000_000_000

    @classmethod
    def create_opcodes(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> List[Tuple[Opcodes, EVMCodeType]]:
        """At Constantinople, `CREATE2` opcode is added."""
        return [(Opcodes.CREATE2, EVMCodeType.LEGACY)] + super(Constantinople, cls).create_opcodes(
            block_number, timestamp
        )

    @classmethod
    def valid_opcodes(
        cls,
    ) -> List[Opcodes]:
        """Return list of Opcodes that are valid to work on this fork."""
        return [
            Opcodes.SHL,
            Opcodes.SHR,
            Opcodes.SAR,
            Opcodes.EXTCODEHASH,
            Opcodes.CREATE2,
        ] + super(Constantinople, cls).valid_opcodes()


class ConstantinopleFix(Constantinople, solc_name="constantinople"):
    """Constantinople Fix fork."""

    pass


class Istanbul(ConstantinopleFix):
    """Istanbul fork."""

    @classmethod
    def precompiles(cls, block_number: int = 0, timestamp: int = 0) -> List[Address]:
        """At Istanbul, pre-compile for blake2 compression is introduced."""
        return [
            Address(9, label="BLAKE2F"),
        ] + super(Istanbul, cls).precompiles(block_number, timestamp)

    @classmethod
    def valid_opcodes(
        cls,
    ) -> List[Opcodes]:
        """Return list of Opcodes that are valid to work on this fork."""
        return [Opcodes.CHAINID, Opcodes.SELFBALANCE] + super(Istanbul, cls).valid_opcodes()

    @classmethod
    def gas_costs(cls, block_number: int = 0, timestamp: int = 0) -> GasCosts:
        """
        On Istanbul, the non-zero transaction data byte cost is reduced to 16 due to
        EIP-2028.
        """
        return replace(
            super(Istanbul, cls).gas_costs(block_number, timestamp),
            G_TX_DATA_NON_ZERO=16,  # https://eips.ethereum.org/EIPS/eip-2028
        )


# Glacier forks skipped, unless explicitly specified
class MuirGlacier(Istanbul, solc_name="istanbul", ignore=True):
    """Muir Glacier fork."""

    pass


class Berlin(Istanbul):
    """Berlin fork."""

    @classmethod
    def tx_types(cls, block_number: int = 0, timestamp: int = 0) -> List[int]:
        """At Berlin, access list transactions are introduced."""
        return [1] + super(Berlin, cls).tx_types(block_number, timestamp)

    @classmethod
    def contract_creating_tx_types(cls, block_number: int = 0, timestamp: int = 0) -> List[int]:
        """At Berlin, access list transactions are introduced."""
        return [1] + super(Berlin, cls).contract_creating_tx_types(block_number, timestamp)

    @classmethod
    def transaction_intrinsic_cost_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> TransactionIntrinsicCostCalculator:
        """At Berlin, the transaction intrinsic cost needs to take the access list into account."""
        super_fn = super(Berlin, cls).transaction_intrinsic_cost_calculator(
            block_number, timestamp
        )
        gas_costs = cls.gas_costs(block_number, timestamp)

        def fn(
            *,
            calldata: BytesConvertible = b"",
            contract_creation: bool = False,
            access_list: List[AccessList] | None = None,
            authorization_list_or_count: Sized | int | None = None,
            return_cost_deducted_prior_execution: bool = False,
        ) -> int:
            intrinsic_cost: int = super_fn(
                calldata=calldata,
                contract_creation=contract_creation,
                authorization_list_or_count=authorization_list_or_count,
            )
            if access_list is not None:
                for access in access_list:
                    intrinsic_cost += gas_costs.G_ACCESS_LIST_ADDRESS
                    for _ in access.storage_keys:
                        intrinsic_cost += gas_costs.G_ACCESS_LIST_STORAGE
            return intrinsic_cost

        return fn


class London(Berlin):
    """London fork."""

    @classmethod
    def header_base_fee_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """Header must contain the Base Fee starting from London."""
        return True

    @classmethod
    def tx_types(cls, block_number: int = 0, timestamp: int = 0) -> List[int]:
        """At London, dynamic fee transactions are introduced."""
        return [2] + super(London, cls).tx_types(block_number, timestamp)

    @classmethod
    def contract_creating_tx_types(cls, block_number: int = 0, timestamp: int = 0) -> List[int]:
        """At London, dynamic fee transactions are introduced."""
        return [2] + super(London, cls).contract_creating_tx_types(block_number, timestamp)

    @classmethod
    def valid_opcodes(
        cls,
    ) -> List[Opcodes]:
        """Return list of Opcodes that are valid to work on this fork."""
        return [Opcodes.BASEFEE] + super(London, cls).valid_opcodes()


# Glacier forks skipped, unless explicitly specified
class ArrowGlacier(London, solc_name="london", ignore=True):
    """Arrow Glacier fork."""

    pass


class GrayGlacier(ArrowGlacier, solc_name="london", ignore=True):
    """Gray Glacier fork."""

    pass


class Paris(
    London,
    transition_tool_name="Merge",
):
    """Paris (Merge) fork."""

    @classmethod
    def header_prev_randao_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """Prev Randao is required starting from Paris."""
        return True

    @classmethod
    def header_zero_difficulty_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """Zero difficulty is required starting from Paris."""
        return True

    @classmethod
    def get_reward(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Paris updates the reward to 0."""
        return 0

    @classmethod
    def engine_new_payload_version(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> Optional[int]:
        """From Paris, payloads can be sent through the engine API."""
        return 1


class Shanghai(Paris):
    """Shanghai fork."""

    @classmethod
    def header_withdrawals_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """Withdrawals are required starting from Shanghai."""
        return True

    @classmethod
    def engine_new_payload_version(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> Optional[int]:
        """From Shanghai, new payload calls must use version 2."""
        return 2

    @classmethod
    def max_initcode_size(cls) -> int:
        """From Shanghai, the initcode size is now limited. See EIP-3860."""
        return 0xC000

    @classmethod
    def valid_opcodes(
        cls,
    ) -> List[Opcodes]:
        """Return list of Opcodes that are valid to work on this fork."""
        return [Opcodes.PUSH0] + super(Shanghai, cls).valid_opcodes()


class Cancun(Shanghai):
    """Cancun fork."""

    BLOB_CONSTANTS = {  # every value is an int or a Literal
        "FIELD_ELEMENTS_PER_BLOB": 4096,
        "BYTES_PER_FIELD_ELEMENT": 32,
        "CELL_LENGTH": 2048,
        "BLS_MODULUS": 0x73EDA753299D7D483339D80809A1D80553BDA402FFFE5BFEFFFFFFFF00000001,  # EIP-2537: Main subgroup order = q, due to this BLS_MODULUS every blob byte (uint256) must be smaller than 116  # noqa: E501
        # https://github.com/ethereum/consensus-specs/blob/cc6996c22692d70e41b7a453d925172ee4b719ad/specs/deneb/polynomial-commitments.md?plain=1#L78
        "BYTES_PER_PROOF": 48,
        "BYTES_PER_COMMITMENT": 48,
        "KZG_ENDIANNESS": "big",
        "AMOUNT_CELL_PROOFS": 0,
    }

    @classmethod
    def get_blob_constant(cls, name: str) -> int | Literal["big"]:
        """Return blob constant if it exists."""
        retrieved_constant = cls.BLOB_CONSTANTS.get(name)
        assert retrieved_constant is not None, (
            f"You tried to retrieve the blob constant {name} but it does not exist!"
        )
        return retrieved_constant

    @classmethod
    def header_excess_blob_gas_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """Excess blob gas is required starting from Cancun."""
        return True

    @classmethod
    def header_blob_gas_used_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """Blob gas used is required starting from Cancun."""
        return True

    @classmethod
    def header_beacon_root_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """Parent beacon block root is required starting from Cancun."""
        return True

    @classmethod
    def blob_gas_price_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> BlobGasPriceCalculator:
        """Return a callable that calculates the blob gas price at Cancun."""
        min_base_fee_per_blob_gas = cls.min_base_fee_per_blob_gas(block_number, timestamp)
        blob_base_fee_update_fraction = cls.blob_base_fee_update_fraction(block_number, timestamp)

        def fn(*, excess_blob_gas) -> int:
            return fake_exponential(
                min_base_fee_per_blob_gas,
                excess_blob_gas,
                blob_base_fee_update_fraction,
            )

        return fn

    @classmethod
    def excess_blob_gas_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> ExcessBlobGasCalculator:
        """Return a callable that calculates the excess blob gas for a block at Cancun."""
        target_blobs_per_block = cls.target_blobs_per_block(block_number, timestamp)
        blob_gas_per_blob = cls.blob_gas_per_blob(block_number, timestamp)
        target_blob_gas_per_block = target_blobs_per_block * blob_gas_per_blob

        def fn(
            *,
            parent_excess_blob_gas: int | None = None,
            parent_excess_blobs: int | None = None,
            parent_blob_gas_used: int | None = None,
            parent_blob_count: int | None = None,
            parent_base_fee_per_gas: int,  # Required for Osaka as using this as base
        ) -> int:
            if parent_excess_blob_gas is None:
                assert parent_excess_blobs is not None, "Parent excess blobs are required"
                parent_excess_blob_gas = parent_excess_blobs * blob_gas_per_blob
            if parent_blob_gas_used is None:
                assert parent_blob_count is not None, "Parent blob count is required"
                parent_blob_gas_used = parent_blob_count * blob_gas_per_blob
            if parent_excess_blob_gas + parent_blob_gas_used < target_blob_gas_per_block:
                return 0
            else:
                return parent_excess_blob_gas + parent_blob_gas_used - target_blob_gas_per_block

        return fn

    @classmethod
    def min_base_fee_per_blob_gas(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Return the minimum base fee per blob gas for Cancun."""
        return 1

    @classmethod
    def blob_base_fee_update_fraction(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Return the blob base fee update fraction for Cancun."""
        return 3338477

    @classmethod
    def blob_gas_per_blob(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Blobs are enabled starting from Cancun."""
        return 2**17

    @classmethod
    def supports_blobs(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """At Cancun, blobs support is enabled."""
        return True

    @classmethod
    def target_blobs_per_block(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Blobs are enabled starting from Cancun, with a static target of 3 blobs."""
        return 3

    @classmethod
    def max_blobs_per_block(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Blobs are enabled starting from Cancun, with a static max of 6 blobs."""
        return 6

    @classmethod
    def full_blob_tx_wrapper_version(cls, block_number: int = 0, timestamp: int = 0) -> int | None:
        """Pre-Osaka forks don't use tx wrapper versions for full blob transactions."""
        return None

    @classmethod
    def blob_schedule(cls, block_number: int = 0, timestamp: int = 0) -> BlobSchedule | None:
        """
        At Cancun, the fork object runs this routine to get the updated blob
        schedule.
        """
        parent_fork = cls.parent()
        assert parent_fork is not None, "Parent fork must be defined"
        blob_schedule = parent_fork.blob_schedule(block_number, timestamp) or BlobSchedule()
        current_blob_schedule = ForkBlobSchedule(
            target_blobs_per_block=cls.target_blobs_per_block(block_number, timestamp),
            max_blobs_per_block=cls.max_blobs_per_block(block_number, timestamp),
            base_fee_update_fraction=cls.blob_base_fee_update_fraction(block_number, timestamp),
        )
        blob_schedule.append(fork=cls.name(), schedule=current_blob_schedule)
        return blob_schedule

    @classmethod
    def tx_types(cls, block_number: int = 0, timestamp: int = 0) -> List[int]:
        """At Cancun, blob type transactions are introduced."""
        return [3] + super(Cancun, cls).tx_types(block_number, timestamp)

    @classmethod
    def precompiles(cls, block_number: int = 0, timestamp: int = 0) -> List[Address]:
        """At Cancun, pre-compile for kzg point evaluation is introduced."""
        return [
            Address(10, label="KZG_POINT_EVALUATION"),
        ] + super(Cancun, cls).precompiles(block_number, timestamp)

    @classmethod
    def system_contracts(cls, block_number: int = 0, timestamp: int = 0) -> List[Address]:
        """Cancun introduces the system contract for EIP-4788."""
        return [Address(0x000F3DF6D732807EF1319FB7B8BB8522D0BEAC02, label="BEACON_ROOTS_ADDRESS")]

    @classmethod
    def pre_allocation_blockchain(cls) -> Mapping:
        """
        Cancun requires pre-allocation of the beacon root contract for EIP-4788 on blockchain
        type tests.
        """
        new_allocation = {
            0x000F3DF6D732807EF1319FB7B8BB8522D0BEAC02: {
                "nonce": 1,
                "code": "0x3373fffffffffffffffffffffffffffffffffffffffe14604d57602036146024575f5f"
                "fd5b5f35801560495762001fff810690815414603c575f5ffd5b62001fff01545f5260205ff35b5f"
                "5ffd5b62001fff42064281555f359062001fff015500",
            }
        }
        # return new_allocation | super(Cancun, cls).pre_allocation_blockchain()  # type: ignore
        return new_allocation

    @classmethod
    def engine_new_payload_version(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> Optional[int]:
        """From Cancun, new payload calls must use version 3."""
        return 3

    @classmethod
    def engine_get_blobs_version(cls, block_number: int = 0, timestamp: int = 0) -> Optional[int]:
        """At Cancun, the engine get blobs version is 1."""
        return 1

    @classmethod
    def engine_new_payload_blob_hashes(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """From Cancun, payloads must have blob hashes."""
        return True

    @classmethod
    def engine_new_payload_beacon_root(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """From Cancun, payloads must have a parent beacon block root."""
        return True

    @classmethod
    def valid_opcodes(
        cls,
    ) -> List[Opcodes]:
        """Return list of Opcodes that are valid to work on this fork."""
        return [
            Opcodes.BLOBHASH,
            Opcodes.BLOBBASEFEE,
            Opcodes.TLOAD,
            Opcodes.TSTORE,
            Opcodes.MCOPY,
        ] + super(Cancun, cls).valid_opcodes()


class Prague(Cancun):
    """Prague fork."""

    # update some blob constants
    BLOB_CONSTANTS = {
        **Cancun.BLOB_CONSTANTS,  # same base constants as cancun
        "MAX_BLOBS_PER_BLOCK": 9,  # but overwrite or add these
        "TARGET_BLOBS_PER_BLOCK": 6,
        "MAX_BLOB_GAS_PER_BLOCK": 1179648,
        "TARGET_BLOB_GAS_PER_BLOCK": 786432,
        "BLOB_BASE_FEE_UPDATE_FRACTION": 5007716,
    }

    @classmethod
    def is_deployed(cls) -> bool:
        """
        Flag that the fork has not been deployed to mainnet; it is under active
        development.
        """
        return False

    @classmethod
    def precompiles(cls, block_number: int = 0, timestamp: int = 0) -> List[Address]:
        """
        At Prague, pre-compile for BLS operations are added.

        BLS12_G1ADD = 0x0B
        BLS12_G1MSM = 0x0C
        BLS12_G2ADD = 0x0D
        BLS12_G2MSM = 0x0E
        BLS12_PAIRING_CHECK = 0x0F
        BLS12_MAP_FP_TO_G1 = 0x10
        BLS12_MAP_FP2_TO_G2 = 0x11
        """
        return [
            Address(11, label="BLS12_G1ADD"),
            Address(12, label="BLS12_G1MSM"),
            Address(13, label="BLS12_G2ADD"),
            Address(14, label="BLS12_G2MSM"),
            Address(15, label="BLS12_PAIRING_CHECK"),
            Address(16, label="BLS12_MAP_FP_TO_G1"),
            Address(17, label="BLS12_MAP_FP2_TO_G2"),
        ] + super(Prague, cls).precompiles(block_number, timestamp)

    @classmethod
    def tx_types(cls, block_number: int = 0, timestamp: int = 0) -> List[int]:
        """At Prague, set-code type transactions are introduced."""
        return [4] + super(Prague, cls).tx_types(block_number, timestamp)

    @classmethod
    def gas_costs(cls, block_number: int = 0, timestamp: int = 0) -> GasCosts:
        """
        On Prague, the standard token cost and the floor token costs are introduced due to
        EIP-7623.
        """
        return replace(
            super(Prague, cls).gas_costs(block_number, timestamp),
            G_TX_DATA_STANDARD_TOKEN_COST=4,  # https://eips.ethereum.org/EIPS/eip-7623
            G_TX_DATA_FLOOR_TOKEN_COST=10,
            G_AUTHORIZATION=25_000,
            R_AUTHORIZATION_EXISTING_AUTHORITY=12_500,
        )

    @classmethod
    def system_contracts(cls, block_number: int = 0, timestamp: int = 0) -> List[Address]:
        """Prague introduces the system contracts for EIP-6110, EIP-7002, EIP-7251 and EIP-2935."""
        return [
            Address(
                0x00000000219AB540356CBB839CBE05303D7705FA,
                label="DEPOSIT_CONTRACT_ADDRESS",
            ),
            Address(
                0x00000961EF480EB55E80D19AD83579A64C007002,
                label="WITHDRAWAL_REQUEST_PREDEPLOY_ADDRESS",
            ),
            Address(
                0x0000BBDDC7CE488642FB579F8B00F3A590007251,
                label="CONSOLIDATION_REQUEST_PREDEPLOY_ADDRESS",
            ),
            Address(
                0x0000F90827F1C53A10CB7A02335B175320002935,
                label="HISTORY_STORAGE_ADDRESS",
            ),
        ] + super(Prague, cls).system_contracts(block_number, timestamp)

    @classmethod
    def max_request_type(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """At Prague, three request types are introduced, hence the max request type is 2."""
        return 2

    @classmethod
    def calldata_gas_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> CalldataGasCalculator:
        """
        Return a callable that calculates the transaction gas cost for its calldata
        depending on its contents.
        """
        gas_costs = cls.gas_costs(block_number, timestamp)

        def fn(*, data: BytesConvertible, floor: bool = False) -> int:
            tokens = 0
            for b in Bytes(data):
                if b == 0:
                    tokens += 1
                else:
                    tokens += 4
            if floor:
                return tokens * gas_costs.G_TX_DATA_FLOOR_TOKEN_COST
            return tokens * gas_costs.G_TX_DATA_STANDARD_TOKEN_COST

        return fn

    @classmethod
    def transaction_data_floor_cost_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> TransactionDataFloorCostCalculator:
        """On Prague, due to EIP-7623, the transaction data floor cost is introduced."""
        calldata_gas_calculator = cls.calldata_gas_calculator(block_number, timestamp)
        gas_costs = cls.gas_costs(block_number, timestamp)

        def fn(*, data: BytesConvertible) -> int:
            return calldata_gas_calculator(data=data, floor=True) + gas_costs.G_TRANSACTION

        return fn

    @classmethod
    def transaction_intrinsic_cost_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> TransactionIntrinsicCostCalculator:
        """
        At Prague, the transaction intrinsic cost needs to take the
        authorizations into account.
        """
        super_fn = super(Prague, cls).transaction_intrinsic_cost_calculator(
            block_number, timestamp
        )
        gas_costs = cls.gas_costs(block_number, timestamp)
        transaction_data_floor_cost_calculator = cls.transaction_data_floor_cost_calculator(
            block_number, timestamp
        )

        def fn(
            *,
            calldata: BytesConvertible = b"",
            contract_creation: bool = False,
            access_list: List[AccessList] | None = None,
            authorization_list_or_count: Sized | int | None = None,
            return_cost_deducted_prior_execution: bool = False,
        ) -> int:
            intrinsic_cost: int = super_fn(
                calldata=calldata,
                contract_creation=contract_creation,
                access_list=access_list,
                return_cost_deducted_prior_execution=False,
            )
            if authorization_list_or_count is not None:
                if isinstance(authorization_list_or_count, Sized):
                    authorization_list_or_count = len(authorization_list_or_count)
                intrinsic_cost += authorization_list_or_count * gas_costs.G_AUTHORIZATION

            if return_cost_deducted_prior_execution:
                return intrinsic_cost

            transaction_floor_data_cost = transaction_data_floor_cost_calculator(data=calldata)
            return max(intrinsic_cost, transaction_floor_data_cost)

        return fn

    @classmethod
    def blob_base_fee_update_fraction(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Return the blob base fee update fraction for Prague."""
        return 5007716

    @classmethod
    def target_blobs_per_block(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Target blob count of 6 for Prague."""
        return 6

    @classmethod
    def max_blobs_per_block(cls, block_number: int = 0, timestamp: int = 0) -> int:
        """Max blob count of 9 for Prague."""
        return 9

    @classmethod
    def pre_allocation_blockchain(cls) -> Mapping:
        """
        Prague requires pre-allocation of the beacon chain deposit contract for EIP-6110,
        the exits contract for EIP-7002, and the history storage contract for EIP-2935.
        """
        new_allocation = {}

        # Add the beacon chain deposit contract
        deposit_contract_tree_depth = 32
        storage = {}
        next_hash = sha256(b"\x00" * 64).digest()
        for i in range(deposit_contract_tree_depth + 2, deposit_contract_tree_depth * 2 + 1):
            storage[i] = next_hash
            next_hash = sha256(next_hash + next_hash).digest()

        with open(CURRENT_FOLDER / "contracts" / "deposit_contract.bin", mode="rb") as f:
            new_allocation.update(
                {
                    0x00000000219AB540356CBB839CBE05303D7705FA: {
                        "nonce": 1,
                        "code": f.read(),
                        "storage": storage,
                    }
                }
            )

        # EIP-7002: Add the withdrawal request contract
        with open(CURRENT_FOLDER / "contracts" / "withdrawal_request.bin", mode="rb") as f:
            new_allocation.update(
                {
                    0x00000961EF480EB55E80D19AD83579A64C007002: {
                        "nonce": 1,
                        "code": f.read(),
                    },
                }
            )

        # EIP-7251: Add the consolidation request contract
        with open(CURRENT_FOLDER / "contracts" / "consolidation_request.bin", mode="rb") as f:
            new_allocation.update(
                {
                    0x0000BBDDC7CE488642FB579F8B00F3A590007251: {
                        "nonce": 1,
                        "code": f.read(),
                    },
                }
            )

        # EIP-2935: Add the history storage contract
        with open(CURRENT_FOLDER / "contracts" / "history_contract.bin", mode="rb") as f:
            new_allocation.update(
                {
                    0x0000F90827F1C53A10CB7A02335B175320002935: {
                        "nonce": 1,
                        "code": f.read(),
                    }
                }
            )

        return new_allocation | super(Prague, cls).pre_allocation_blockchain()  # type: ignore

    @classmethod
    def header_requests_required(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """
        Prague requires that the execution layer header contains the beacon
        chain requests hash.
        """
        return True

    @classmethod
    def engine_new_payload_requests(cls, block_number: int = 0, timestamp: int = 0) -> bool:
        """From Prague, new payloads include the requests hash as a parameter."""
        return True

    @classmethod
    def engine_new_payload_version(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> Optional[int]:
        """From Prague, new payload calls must use version 4."""
        return 4

    @classmethod
    def engine_forkchoice_updated_version(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> Optional[int]:
        """At Prague, version number of NewPayload and ForkchoiceUpdated diverge."""
        return 3


class Osaka(Prague, solc_name="cancun"):
    """Osaka fork."""

    # update some blob constants
    BLOB_CONSTANTS = {
        **Prague.BLOB_CONSTANTS,  # same base constants as prague
        "AMOUNT_CELL_PROOFS": 128,
    }

    @classmethod
    def engine_get_payload_version(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> Optional[int]:
        """From Osaka, get payload calls must use version 5."""
        return 5

    @classmethod
    def engine_get_blobs_version(cls, block_number: int = 0, timestamp: int = 0) -> Optional[int]:
        """At Osaka, the engine get blobs version is 2."""
        return 2

    @classmethod
    def full_blob_tx_wrapper_version(cls, block_number=0, timestamp=0) -> int | None:
        """At Osaka, the full blob transaction wrapper version is defined."""
        return 1

    @classmethod
    def transaction_gas_limit_cap(cls, block_number: int = 0, timestamp: int = 0) -> int | None:
        """At Osaka, transaction gas limit is capped at 30 million."""
        return 16_777_216

    @classmethod
    def block_rlp_size_limit(cls, block_number: int = 0, timestamp: int = 0) -> int | None:
        """From Osaka, block RLP size is limited as specified in EIP-7934."""
        max_block_size = 10_485_760
        safety_margin = 2_097_152
        return max_block_size - safety_margin

    @classmethod
    def is_deployed(cls) -> bool:
        """
        Flag that the fork has not been deployed to mainnet; it is under active
        development.
        """
        return False

    @classmethod
    def valid_opcodes(
        cls,
    ) -> List[Opcodes]:
        """Return list of Opcodes that are valid to work on this fork."""
        return [
            Opcodes.CLZ,
        ] + super(Prague, cls).valid_opcodes()

    @classmethod
    def precompiles(cls, block_number: int = 0, timestamp: int = 0) -> List[Address]:
        """
        At Osaka, pre-compile for p256verify operation is added.

        P256VERIFY = 0x100
        """
        return [
            Address(0x100, label="P256VERIFY"),
        ] + super(Osaka, cls).precompiles(block_number, timestamp)

    @classmethod
    def excess_blob_gas_calculator(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> ExcessBlobGasCalculator:
        """Return a callable that calculates the excess blob gas for a block."""
        target_blobs_per_block = cls.target_blobs_per_block(block_number, timestamp)
        blob_gas_per_blob = cls.blob_gas_per_blob(block_number, timestamp)
        target_blob_gas_per_block = target_blobs_per_block * blob_gas_per_blob
        max_blobs_per_block = cls.max_blobs_per_block(block_number, timestamp)
        blob_base_cost = 2**14  # EIP-7918 new parameter

        def fn(
            *,
            parent_excess_blob_gas: int | None = None,
            parent_excess_blobs: int | None = None,
            parent_blob_gas_used: int | None = None,
            parent_blob_count: int | None = None,
            parent_base_fee_per_gas: int,  # EIP-7918 additional parameter
        ) -> int:
            if parent_excess_blob_gas is None:
                assert parent_excess_blobs is not None, "Parent excess blobs are required"
                parent_excess_blob_gas = parent_excess_blobs * blob_gas_per_blob
            if parent_blob_gas_used is None:
                assert parent_blob_count is not None, "Parent blob count is required"
                parent_blob_gas_used = parent_blob_count * blob_gas_per_blob
            if parent_excess_blob_gas + parent_blob_gas_used < target_blob_gas_per_block:
                return 0

            # EIP-7918: Apply reserve price when execution costs dominate blob costs
            current_blob_base_fee = cls.blob_gas_price_calculator()(
                excess_blob_gas=parent_excess_blob_gas
            )
            reserve_price_active = (
                blob_base_cost * parent_base_fee_per_gas
                > blob_gas_per_blob * current_blob_base_fee
            )
            if reserve_price_active:
                blob_excess_adjustment = (
                    parent_blob_gas_used
                    * (max_blobs_per_block - target_blobs_per_block)
                    // max_blobs_per_block
                )
                return parent_excess_blob_gas + blob_excess_adjustment

            # Original EIP-4844 calculation
            return parent_excess_blob_gas + parent_blob_gas_used - target_blob_gas_per_block

        return fn


class EOFv1(Prague, solc_name="cancun"):
    """EOF fork."""

    @classmethod
    def evm_code_types(cls, block_number: int = 0, timestamp: int = 0) -> List[EVMCodeType]:
        """EOF V1 is supported starting from Osaka."""
        return super(EOFv1, cls).evm_code_types(
            block_number,
            timestamp,
        ) + [EVMCodeType.EOF_V1]

    @classmethod
    def call_opcodes(
        cls, block_number: int = 0, timestamp: int = 0
    ) -> List[Tuple[Opcodes, EVMCodeType]]:
        """EOF V1 introduces EXTCALL, EXTSTATICCALL, EXTDELEGATECALL."""
        return [
            (Opcodes.EXTCALL, EVMCodeType.EOF_V1),
            (Opcodes.EXTSTATICCALL, EVMCodeType.EOF_V1),
            (Opcodes.EXTDELEGATECALL, EVMCodeType.EOF_V1),
        ] + super(EOFv1, cls).call_opcodes(block_number, timestamp)

    @classmethod
    def is_deployed(cls) -> bool:
        """
        Flag that the fork has not been deployed to mainnet; it is under active
        development.
        """
        return False
