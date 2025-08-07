"""Simple test for Gnosis blockchain without pre-allocated accounts.

This test demonstrates a minimal blockchain test that should work
without complex pre-allocated account configurations.

1. Start hive with test container
./hive --dev --client go-ethereum-gnosis --dev.addr=127.0.0.1:3000 --sim.loglevel=3 --docker.output --docker.pull

2. Fill tests with fixtures
uv run fill ./tests/gnosis/test_gnosis_blockchain.py --fork Prague --clean -c pytest-gnosis.ini --gnosis
3. Run the test
export HIVE_SIMULATOR=http://127.0.0.1:3000 && uv run consume engine -v --input fixtures/blockchain_tests_engine/gnosis/gnosis_blockchain            


"""

from ethereum_test_specs.blockchain import Block
from ethereum_test_tools import (Account, Alloc, BlockchainTestFiller,
                                 Environment, TestAddress, TestPrivateKey,
                                 Transaction)


def test_gnosis_simple(blockchain_test: BlockchainTestFiller):
    """Simple test to verify basic Gnosis blockchain functionality.
    
    This test creates a minimal blockchain test with just a basic transaction
    to verify that the basic blockchain mechanism works.
    """

    # Minimal environment (will use Gnosis defaults from plugin)
    env = Environment()

    # Minimal pre-state - just the test account
    pre = Alloc({
        TestAddress: Account(balance=1_000_000_000_000_000_000),  # 1 ETH
    })

    post: dict = {}

    # Create the blockchain test with one transaction
    blockchain_test(
        env=env,
        pre=pre,
        post=post,
        blocks=[Block(txs=[])],
    )


def test_gnosis_with_transaction(blockchain_test: BlockchainTestFiller):
    """Simple test to verify basic Gnosis blockchain functionality.

    This test creates a minimal blockchain test with just a basic transaction
    to verify that the basic blockchain mechanism works.
    """

    # Minimal environment (will use Gnosis defaults from plugin)
    env = Environment()

    # Minimal pre-state - just the test account
    pre = Alloc(
        {
            TestAddress: Account(balance=1_000_000_000_000_000_000),  # 1 ETH
            0x00000000219AB540356CBB839CBE05303D7705FA: Account(balance=0),
        }
    )

    # Simple transaction that transfers some ETH to null address
    tx = Transaction(
        to=0x00000000219AB540356CBB839CBE05303D7705FA,
        value=1000,
        gas_limit=21000,
        nonce=0,  # TestAddress now starts with nonce 0 in both mainnet and gnosis
        sender=TestAddress,
        secret_key=TestPrivateKey,
    )

    # Expected post-state
    post = {
        0x00000000219AB540356CBB839CBE05303D7705FA: Account(
            balance=1000,  # Received the transfer
        ),
    }
    post: dict = {}

    # Create the blockchain test with one transaction
    blockchain_test(
        env=env,
        pre=pre,
        post=post,
        blocks=[Block(txs=[tx])],
    )


if __name__ == "__main__":
    """
    To run this test:
    uv run fill ./test_gnosis_blockchain.py --fork Prague --gnosis -c pytest-gnosis.ini --clean
    """
    pass
