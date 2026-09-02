"""Entry point.

The racing game itself has not been implemented yet -- see README.md.
Default (no args) launches the Phase 1 calibrator. `--stereo-test`
launches the Phase 2 static depth/disparity confirmation scene instead.
"""
from __future__ import annotations

import argparse

import calibration
import phase2_test_scene


def main() -> None:
    parser = argparse.ArgumentParser(description="Virtual Boy stereo racing prototype")
    parser.add_argument(
        "--stereo-test",
        action="store_true",
        help="Launch the Phase 2 static stereo depth confirmation scene instead of the calibrator.",
    )
    parser.add_argument(
        "--test-frames",
        type=int,
        default=None,
        help="Render N frames and exit automatically (smoke test / CI, no input needed).",
    )
    args = parser.parse_args()
    if args.stereo_test:
        phase2_test_scene.run(test_frames=args.test_frames)
    else:
        calibration.run(test_frames=args.test_frames)


if __name__ == "__main__":
    main()
