"""Test harness: run the arbitrage scanner and write its output to ./debug (published to the debug branch)."""
import os

os.environ["PROP_OUT"] = "debug"

from . import arb  # noqa: E402

if __name__ == "__main__":
    arb.main()
