from robot_sketch_studio.robots import MockRobot


def test_mock_robot_simulates_trajectory_and_stop():
    robot = MockRobot()
    robot.connect()
    robot.calibrate()
    robot.execute_trajectory([[(1.0, 2.0), (3.0, 4.0)], [(8.0, 9.0), (10.0, 11.0)]])
    assert robot.position == (10.0, 11.0)
    assert not robot.pen_is_down
    assert any(event[0] == "move_to" for event in robot.events)
    robot.emergency_stop()
    try:
        robot.move_to(0, 0)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Emergency stop did not block movement")
