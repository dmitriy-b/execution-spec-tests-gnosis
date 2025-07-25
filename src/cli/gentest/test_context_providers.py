"""
Various providers which generate contexts required to create test scripts.

Classes:
- Provider: An provider generates required context for creating a test.
- BlockchainTestProvider: The BlockchainTestProvider takes a transaction hash and creates
  required context to create a test.

Example:
    provider = BlockchainTestContextProvider(transaction=transaction)
    context = provider.get_context()

"""

from abc import ABC, abstractmethod
from sys import stderr
from typing import Any, Dict, Optional

from pydantic import BaseModel

from ethereum_test_base_types import Account, Hash
from ethereum_test_rpc.types import TransactionByHashResponse
from ethereum_test_tools import Environment, Transaction

from .request_manager import RPCRequest


class Provider(ABC, BaseModel):
    """An provider generates required context for creating a test."""

    @abstractmethod
    def get_context(self) -> Dict:
        """Get the context for generating a test."""

    pass


class StateTestProvider(Provider):
    """Provides context required to generate a `state_test` using pytest."""

    transaction_hash: Hash
    block: Optional[Environment] = None
    transaction_response: Optional[TransactionByHashResponse] = None
    state: Optional[Dict[str, Dict]] = None

    def _make_rpc_calls(self):
        request = RPCRequest()
        print(
            f"Perform tx request: eth_get_transaction_by_hash({self.transaction_hash})",
            file=stderr,
        )
        self.transaction_response = request.eth_get_transaction_by_hash(self.transaction_hash)

        print("Perform debug_trace_call", file=stderr)
        self.state = request.debug_trace_call(self.transaction_response)

        print("Perform eth_get_block_by_number", file=stderr)
        self.block = request.eth_get_block_by_number(self.transaction_response.block_number)

        print("Generate py test", file=stderr)

    def _get_environment(self) -> Environment:
        assert self.block is not None
        return self.block

    def _get_pre_state(self) -> Dict[str, Account]:
        assert self.state is not None
        assert self.transaction_response is not None

        pre_state: Dict[str, Account] = {}
        for address, account_data in self.state.items():
            # TODO: Check if this is required. Ideally,
            # the pre-state tracer should have the correct
            # values without requiring any additional modifications.
            if address == self.transaction_response.sender:
                account_data["nonce"] = self.transaction_response.nonce

            pre_state[address] = Account(**account_data)
        return pre_state

    def _get_transaction(self) -> Transaction:
        assert self.transaction_response is not None
        # Validate the RPC TransactionHashResponse and convert it to a Transaction instance.
        return Transaction.model_validate(self.transaction_response.model_dump())

    def get_context(self) -> Dict[str, Any]:
        """
        Get the context for generating a blockchain test.

        Returns:
            Dict[str, Any]: A dictionary containing environment,
            pre-state, a transaction and its hash.

        """
        self._make_rpc_calls()
        return {
            "environment": self._get_environment(),
            "pre_state": self._get_pre_state(),
            "transaction": self._get_transaction(),
            "tx_hash": self.transaction_hash,
        }
