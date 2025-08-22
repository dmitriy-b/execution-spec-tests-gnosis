import argparse
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from ethereum_test_fixtures.blockchain import FixtureHeader


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute Ethereum block header hash (and optionally RLP) from a JSON file using FixtureHeader."
    )
    parser.add_argument(
        "json_path",
        type=Path,
        help="Path to JSON file containing header fields",
    )
    parser.add_argument(
        "--rlp-out",
        type=Path,
        default=None,
        help="Optional path to write the header RLP (hex string)",
    )
    args = parser.parse_args(argv)

    data = load_json(args.json_path)

    # Build header using existing model; this leverages all field conversions and aliases
    header = FixtureHeader(**data)

    # Compute RLP and block hash using the same logic as in the fixture code,
    # but suppress internal debug prints so we only output the hash.
    with io.StringIO() as _buf, redirect_stdout(_buf):
        _ = header.rlp  # ensure RLP is computed
        block_hash_hex = str(header.block_hash)

    # Optionally write RLP out
    if args.rlp_out is not None:
        args.rlp_out.parent.mkdir(parents=True, exist_ok=True)
        args.rlp_out.write_text(str(header.rlp), encoding="utf-8")

    # Print only the block hash to stdout for easy scripting
    print(block_hash_hex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
