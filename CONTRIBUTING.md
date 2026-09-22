# Contributing

Thank you for improving Robot Sketch Studio.

1. Create a focused branch and keep model weights, output files, tokens, and personal data out of Git.
2. Install `.[dev]`, then run `ruff format .`, `ruff check .`, and `pytest`.
3. Add CPU-only tests for algorithm changes. Tests must not require a GPU, network access, or model downloads.
4. Document new third-party code/models with their real author, source, and license.
5. Never add a physical robot adapter that can move by default; require explicit connection, calibration, workspace limits, and an emergency stop.

By contributing, you agree that your contribution is provided under the MIT License. Developed by maggogerka.

