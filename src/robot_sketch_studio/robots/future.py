"""Extension points for future hardware adapters.

SerialRobot, GCodeRobot, ROSRobot, and VendorSdkRobot deliberately remain
unimplemented in v0.2.0 so this release cannot move real hardware accidentally.
"""

from robot_sketch_studio.robots.base import RobotAdapter


class UnsupportedHardwareAdapter(RobotAdapter):
    def _unsupported(self) -> None:
        raise NotImplementedError("Physical robot control is not available in v0.2.0")

    connect = disconnect = home = calibrate = pen_up = pen_down = emergency_stop = _unsupported

    def move_to(self, x: float, y: float) -> None:
        self._unsupported()

    def execute_trajectory(self, strokes) -> None:
        self._unsupported()


class SerialRobot(UnsupportedHardwareAdapter):
    pass


class GCodeRobot(UnsupportedHardwareAdapter):
    pass


class ROSRobot(UnsupportedHardwareAdapter):
    pass


class VendorSdkRobot(UnsupportedHardwareAdapter):
    pass
