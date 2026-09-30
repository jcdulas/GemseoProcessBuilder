"""An external code computing the noise of the aircraft at take-off.

It reads the fuel burnt from an input file and writes the noise level to an
output file: any program reading and writing text files can be wrapped the
same way (noise.gpbwrap.json describes how).

Usage: python noise_solver.py input.txt output.txt
"""

import math
import sys


def main(input_path: str, output_path: str) -> None:
    """Read the fuel burnt, compute the noise level, write it."""
    values = {}
    with open(input_path, encoding="utf-8") as lines:
        for line in lines:
            name, _, value = line.partition("=")
            values[name.strip()] = float(value)
    noise_db = 70.0 + 10.0 * math.log10(max(values["fuel_burn"], 1.0))
    with open(output_path, "w", encoding="utf-8") as output:
        output.write(f"noise_db = {noise_db:.12e}\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
