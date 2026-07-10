"""CLI ``breezy`` — диагностика и управление без UI.

Команды scan/pair/state/set/monitor появляются в Фазе 1 вместе с BLE-слоем.
"""

from __future__ import annotations

import argparse

from easy_breezy import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="breezy",
        description="Easy Breezy — управление бризерами Tion",
    )
    parser.add_argument("--version", action="version", version=f"breezy {__version__}")
    parser.parse_args()
    parser.print_help()


if __name__ == "__main__":
    main()
