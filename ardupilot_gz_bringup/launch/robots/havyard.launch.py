import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import IncludeLaunchDescription
from launch.actions import RegisterEventHandler

from launch.conditions import IfCondition

from launch.event_handlers import OnProcessStart

from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch.substitutions import PathJoinSubstitution

from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Generate a launch description for a iris quadcopter."""
    pkg_ardupilot_sitl = get_package_share_directory("ardupilot_sitl")
    pkg_ardupilot_gazebo = get_package_share_directory("ardupilot_gazebo")
    pkg_project_bringup = get_package_share_directory("ardupilot_gz_bringup")
    pkg_ardupilot_sitl_models = get_package_share_directory("ardupilot_sitl_models")

    rover_transport = LaunchConfiguration("rover_transport")
    rover_port = LaunchConfiguration("rover_port")
    rover_mavlink_port = LaunchConfiguration("rover_mavlink_port")

    # Include component launch files.
    sitl_dds = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            [
                PathJoinSubstitution(
                    [
                        FindPackageShare("ardupilot_sitl"),
                        "launch",
                        "sitl_dds_udp.launch.py",
                    ]
                ),
            ]
        ),
        launch_arguments={
            "transport": "udp4",
            "port": "2029",
            "synthetic_clock": "True",
            "wipe": "True",
            "command": "ardurover",
            "model": "json",
            "speedup": "1",
            "slave": "0",
            "instance": "1",
            "defaults": os.path.join(
                pkg_ardupilot_sitl_models,
                "config",
                "havyard.param",
            )
            + ","
            + os.path.join(
                pkg_ardupilot_sitl,
                "config",
                "default_params",
                "dds_udp_ship.parm",
            ),
            "sim_address": "127.0.0.1",
            "master": "tcp:127.0.0.1:5770",  # Different mavlink port for rover
            "sitl": "127.0.0.1:5511",  # Different SITL port for rover
        }.items(),
    )

    # Robot description.

    # Ensure `SDF_PATH` is populated as `sdformat_urdf`` uses this rather
    # than `GZ_SIM_RESOURCE_PATH` to locate resources.
    if "GZ_SIM_RESOURCE_PATH" in os.environ:
        gz_sim_resource_path = os.environ["GZ_SIM_RESOURCE_PATH"]

        if "SDF_PATH" in os.environ:
            sdf_path = os.environ["SDF_PATH"]
            os.environ["SDF_PATH"] = sdf_path + ":" + gz_sim_resource_path
        else:
            os.environ["SDF_PATH"] = gz_sim_resource_path

    # Load SDF file.
    sdf_file = os.path.join(pkg_ardupilot_gazebo, "models", "havyard", "model.sdf")
    with open(sdf_file, "r") as infp:
        robot_desc = infp.read()
        # print(robot_desc)

    # Publish /tf and /tf_static.
    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        name="rover_robot_state_publisher",
        output="both",
        parameters=[
            {"robot_description": robot_desc},
            {"frame_prefix": ""},
        ],
    )

    # Bridge.
    bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        parameters=[
            {
                "config_file": os.path.join(
                    pkg_project_bringup, "config", "havyard_bridge.yaml"
                ),
                "qos_overrides./tf_static.publisher.durability": "transient_local",
            }
        ],
        output="screen",
    )

    # Transform - use if the model includes "gz::sim::systems::PosePublisher"
    #             and a filter is required.
    # topic_tools_tf = Node(
    #     package="topic_tools",
    #     executable="transform",
    #     arguments=[
    #         "/gz/tf",
    #         "/tf",
    #         "tf2_msgs/msg/TFMessage",
    #         "tf2_msgs.msg.TFMessage(transforms=[x for x in m.transforms if x.header.frame_id == 'odom'])",
    #         "--import",
    #         "tf2_msgs",
    #         "geometry_msgs",
    #     ],
    #     output="screen",
    #     respawn=True,
    # )

    # Relay - use instead of transform when Gazebo is only publishing odom -> base_link
    topic_tools_tf = Node(
        package="topic_tools",
        executable="relay",
        arguments=[
            "/gz/tf",
            "/tf",
        ],
        output="screen",
        respawn=False,
        condition=IfCondition(LaunchConfiguration("use_gz_tf")),
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_gz_tf", default_value="true", description="Use Gazebo TF."
            ),
            DeclareLaunchArgument(
                "rover_transport", default_value="udp4", description="Rover transport"
            ),
            DeclareLaunchArgument(
                "rover_port", default_value="2029", description="Rover DDS port"
            ),
            DeclareLaunchArgument(
                "rover_mavlink_port",
                default_value="5770",
                description="Rover port for MAVLINK connection",
            ),
            sitl_dds,
            robot_state_publisher,
            bridge,
            RegisterEventHandler(
                OnProcessStart(target_action=bridge, on_start=[topic_tools_tf])
            ),
        ]
    )
