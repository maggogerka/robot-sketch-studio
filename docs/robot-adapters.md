# Robot adapters

`RobotAdapter` defines `connect`, `disconnect`, `home`, `calibrate`, `pen_up`, `pen_down`, `move_to`, `execute_trajectory`, and `emergency_stop`.

Only `MockRobot` is implemented in v0.1.0. It records deterministic events in memory and powers the browser's visual trajectory simulation. It cannot access serial ports, ROS, G-code devices, or vendor SDKs.

Placeholders identify possible future `SerialRobot`, `GCodeRobot`, `ROSRobot`, and `VendorSdkRobot` implementations. A hardware implementation must add explicit opt-in, coordinate/workspace validation, velocity limits, connection timeouts, a tested emergency stop, and a physical risk warning. It must never auto-connect or execute an uploaded trajectory.

Developed by maggogerka.

