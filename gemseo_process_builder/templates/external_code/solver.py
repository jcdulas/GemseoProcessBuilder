"""A tiny external code for the executable wrapper example.

It reads x and y from an input file, computes

    f = (x - 1)**2 + (y - 2)**2 + 1
    g = x + y - 2.5

and writes them to an output file. It only uses the standard library, like
any program the wrapper would run.

Usage: python solver.py input.txt output.txt
"""

import sys


def main(input_path: str, output_path: str) -> None:
    """Read the inputs, compute f and g, write them."""
    values = {}
    with open(input_path, encoding="utf-8") as lines:
        for line in lines:
            name, _, value = line.partition("=")
            values[name.strip()] = float(value)
    x, y = values["x"], values["y"]
    f = (x - 1) ** 2 + (y - 2) ** 2 + 1
    g = x + y - 2.5
    with open(output_path, "w", encoding="utf-8") as output:
        output.write("RESULTS\n")
        output.write(f"f = {f:.12e}\n")
        output.write(f"g = {g:.12e}\n")
    print("Converged.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
