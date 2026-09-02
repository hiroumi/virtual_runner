"""Entry point.

Default (no args) launches the Phase 1 calibrator. `--stereo-test`
launches the Phase 2 static depth/disparity confirmation scene.
`--race` launches the actual racing game.
"""
from __future__ import annotations

import argparse

import calibration
import game
import phase2_test_scene


def main() -> None:
    parser = argparse.ArgumentParser(description="Virtual Boy stereo racing prototype")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--stereo-test",
        action="store_true",
        help="Launch the Phase 2 static stereo depth confirmation scene instead of the calibrator.",
    )
    mode.add_argument(
        "--race",
        action="store_true",
        help="Launch the racing game.",
    )
    parser.add_argument(
        "--test-frames",
        type=int,
        default=None,
        help="Render N frames and exit automatically (smoke test / CI, no input needed).",
    )
    args = parser.parse_args()
    if args.race:
        game.run(test_frames=args.test_frames)
    elif args.stereo_test:
        phase2_test_scene.run(test_frames=args.test_frames)
    else:
        calibration.run(test_frames=args.test_frames)


if __name__ == "__main__":
    main()
