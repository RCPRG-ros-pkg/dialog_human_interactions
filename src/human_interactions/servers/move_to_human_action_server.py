#!/usr/bin/env python

import math
import time

import actionlib
import rospy
from tf.transformations import quaternion_from_euler

# Msgs
from geometry_msgs.msg import Point, Pose, Quaternion
from human_interactions.msg import (
    MoveToHumanAction,
    MoveToHumanFeedback,
    MoveToHumanResult,
)
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from nav_msgs.msg import Odometry
from nav_msgs.srv import GetPlan, GetPlanRequest
from std_msgs.msg import String

# Local scripts
from human_interactions.utility.logger import ActionServerLogger, Action, LogLevel
from human_interactions.utility.tf_provider import TFProvider
from human_interactions.utility.head_controller import HeadController
from human_interactions.utility.utils import wait_until_server_ready


class MoveToHumanActionServer:
    """
    Server for the 'MoveToHuman' action.

    This class handles requests to move the robot to stand a safe distance away
    from the person's position and face them.

    Attributes:
        _initialized (bool): Flag to indicate if the server has been initialized.
        _logger (ActionServerLogger): An instance of the ActionServerLogger.
        _action_name (str): The name of the action server.
        _action_server (actionlib.SimpleActionServer): The action server instance.
        _current_odom (Odometry): The current odometry of the robot.
        _odom_subscriber (rospy.Subscriber): Subscriber for robot's Odometry messages.
        _tf_provider (TFProvider): An instance of the TFProvider for providing transforms.
        _head_controller (HeadController): An instance of the HeadController for controlling the robot's head movement.
        _move_base_client (actionlib.SimpleActionClient): The MoveBase action client.
        _plan_service (rospy.ServiceProxy): The service for getting a navigation plan.
        _human_pose_topic (str): The topic to use for getting the pose of human.
        _distance_from_human (float): The desired distance from the human.
    """

    def __init__(self):
        """
        Initialize the MoveToHumanActionServer.
        """
        self._initialized = False

        self._logger = ActionServerLogger(Action.MOVE_TO_HUMAN)
        self._action_name = rospy.get_param("move_to_human_action_name")

        # Init the action server
        self._logger.log("Initializing %s server." % self._action_name)
        self._action_server = actionlib.SimpleActionServer(
            self._action_name,
            MoveToHumanAction,
            self.execute_callback,
            auto_start=False,
        )
        self._action_server.start()

        # Current state variables
        self._current_odom = Odometry()

        # Subscribers
        self._odom_subscriber = rospy.Subscriber(
            rospy.get_param("odometry_topic"), Odometry, self.robot_odometry_callback
        )

        # Transform provider
        self._tf_provider = TFProvider()

        # Head controller
        self._head_controller = HeadController()

        # Action servers
        self._move_base_client = actionlib.SimpleActionClient(
            rospy.get_param("move_base_action_name"), MoveBaseAction
        )

        # Init odom plan service
        self._plan_service = rospy.ServiceProxy(
            rospy.get_param("move_base_plan_service_name"), GetPlan
        )

        wait_until_server_ready(
            self._move_base_client,
            rospy.get_param("move_base_action_name"),
            self._logger,
        )

        # Initalize goal variables with defaults.
        self._human_pose_topic = rospy.get_param("human_tf")
        self._distance_from_human = rospy.get_param("default_distance_from_human")

        self._logger.log("%s server initialization complete." % self._action_name)
        self._initialized = True

    def robot_odometry_callback(self, message):
        """
        Callback for receiving robot's current odometry.

        Args:
            message (Odometry): odometry message.
        """
        self._current_odom = message

    def publish_feedback(self):
        """
        Publish feedback for the client.
        """
        feedback = MoveToHumanFeedback()
        feedback.robot_pose = self._current_odom.pose.pose
        self._action_server.publish_feedback(feedback)

    def publish_result(self, status):
        """
        Publish the result of the action for the client.

        Args:
            status (str): The finished action's status.
        """
        result = MoveToHumanResult()
        result.status = String(status)
        result.robot_pose = self._current_odom.pose.pose
        self._action_server.set_succeeded(result)
        self._logger.log("Action ended with status: '%s'" % status)

    def get_pose(self, point, origin):
        """
        Get a pose from a point relative to the requested origin.

        Args:
            point: The point to transform into a pose.
            origin: The origin frame for the transformation.

        Returns:
            Pose: The resulting pose.
        """
        transform = self._tf_provider.get_tf(point, origin)
        return TFProvider.get_transform_as_pose(transform)

    def get_plan(self, goal, tolerance=0.5):
        """
        Request a navigation plan from the MoveBase plan service to the given
        destination.

        Args:
            goal (Pose): The goal in robot's tf.
            tolerance (float): The x/y goal tolerance when planning.

        Returns:
            Optional[Path]: The navigation plan. If the location is not
                reacheable return None.
        """
        start_pose = self.get_pose(rospy.get_param("robot_base_tf"), "map")
        if not start_pose:
            self._logger.log("Can't determine start pose, aborting.", LogLevel.ERROR)
            return

        request = GetPlanRequest()
        request.start.header.frame_id = "map"
        request.start.pose = start_pose
        request.goal.header.frame_id = "map"
        request.goal.pose = goal
        request.tolerance = tolerance

        try:
            response = self._plan_service.call(request)

            plan = response.plan
            plan.header.frame_id = "map"
            return plan
        except rospy.ServiceException:
            return None

    @staticmethod
    def get_points_around(center, radius, num_points):
        """
        Generate a list of evenly distributed points around a provided center point.

        Args:
            center (Point): The center point.
            radius (float): Required distance from the center.
            num_points (int): Number of points to generate.

        Returns:
            list[Point]: The list of generated points.
        """
        points = []
        for i in range(num_points):
            theta = (2 * math.pi * i) / num_points
            x = center.x + radius * math.cos(theta)
            y = center.y + radius * math.sin(theta)
            z = 0
            points.append(Point(x=x, y=y, z=z))
        return points

    @staticmethod
    def get_route_length(plan):
        """
        Calculate the length of a planned route.

        Args:
            plan: A plan with a sequence of poses to follow.

        Returns:
            Optional[float]: Calculated length of the route when following the
                plan. Infinity if the plan is None or empty.
        """

        if plan is None or len(plan.poses) == 0:
            return float("inf")

        route_length = 0
        poses = plan.poses
        for i in range(1, len(poses)):
            previous_position = poses[i - 1].pose.position
            current_position = poses[i].pose.position
            route_length += math.sqrt(
                (current_position.x - previous_position.x) ** 2
                + (current_position.y - previous_position.y) ** 2
            )
        return route_length

    def get_destination(self, num_candidates=16):
        """
        Determine the robot's most optimal destination to move to. Candidate
        points are generated and the one that is reacheable with the shortest
        route is selected.

        Args:
            num_candidates (int): How many candidate destination should be checked.
                A high number could allow for better result, but could also take
                too long to calculate.

        Returns:
            Optional[Pose]: The destination pose for the robot,
                or None if it can't be determined.
        """

        human_pose = self.get_pose(self._human_pose_topic, "map")
        if not human_pose:
            self._logger.log("Can't determine human pose, aborting.", LogLevel.ERROR)
            return

        start_time = time.time()

        self._logger.log(
            "Choosing a destination %.3f from the human." % self._distance_from_human
        )
        # Generate points with the requested distance around the human
        # position to choose from.
        human_position = human_pose.position
        candidates = self.get_points_around(
            human_position, self._distance_from_human, num_candidates
        )
        # Function to calculate the final orientation the robot should have
        # to end up facing the human based on their relative position.
        get_orientation_to_face_human = lambda robot_position: Quaternion(
            *quaternion_from_euler(
                0,
                0,
                math.atan2(
                    human_position.y - robot_position.y,
                    human_position.x - robot_position.x,
                ),
            )
        )
        # Get plans for all the candidates.
        plans = [
            self.get_plan(
                Pose(
                    position=candidate,
                    orientation=get_orientation_to_face_human(candidate),
                )
            )
            for candidate in candidates
        ]
        # Abort if a route can't be planned to any destination.
        if all(plan is None for plan in plans):
            self._logger.log(
                "Could not find a plan to any of the possible points around the human."
            )
            return None
        # Calculate the length of each planned route.
        route_lengths = [self.get_route_length(plan) for plan in plans]
        # Choose best plan (the one with the shortests route).
        best_plan_index = route_lengths.index(min(route_lengths))

        chosen_destination = candidates[best_plan_index]
        self._logger.log(
            "Chosen goal {x: %f, y: %f, z: %f} with route length of %.2f meters."
            % (
                chosen_destination.x,
                chosen_destination.y,
                chosen_destination.z,
                route_lengths[best_plan_index],
            )
        )
        self._logger.log(
            "Choosing destination took %.3f seconds." % (time.time() - start_time)
        )

        return plans[best_plan_index].poses[-1]

    def move_head(self):
        """
        Move the robot's head to face the human.
        """
        self._logger.log("Moving head.")
        pose = self.get_pose(self._human_pose_topic, rospy.get_param("robot_base_tf"))
        if not pose:
            self._logger.log("Can't determine pose, aborting.", LogLevel.ERROR)
            return

        self._head_controller.point_at(pose.position)
        self._head_controller.wait_till_idle()

    def execute_callback(self, goal):
        """
        Callback for handling action requests.

        Moves the robot to the vicinity of the human and orients it towards them.

        Args:
            goal (MoveToHumanActionGoal): The goal message.
        """
        self._logger.log("New request received.")

        if not self._initialized:
            self._logger.log("Server not ready, ignoring request.", LogLevel.WARNING)
            self.publish_result("failure")
            return

        # If provided override the defaults with the values from goal.
        human_pose_topic = goal.human_pose_topic.data
        if len(human_pose_topic) > 0:
            self._human_pose_topic = human_pose_topic
        distance = goal.distance.data
        if distance > 0.0:
            self._distance_from_human = distance
        self._logger.log(
            "Received goal: {human pose topic: '%s', distance: %f}"
            % (human_pose_topic, distance)
        )
        self._logger.log(
            "Used values: {human pose topic: '%s', distance: %f}"
            % (self._human_pose_topic, self._distance_from_human)
        )

        self._head_controller.reset()

        destination = self.get_destination()
        if destination is not None:
            navigation_goal = MoveBaseGoal()
            navigation_goal.target_pose = destination

            self._move_base_client.send_goal(navigation_goal)
            while not self._move_base_client.wait_for_result(rospy.Duration(0.5)):
                self.publish_feedback()

            self.move_head()
            self.publish_result("success")
        else:
            self._logger.log("Failed to plan movement.")
            self.publish_result("failure")

        self._logger.log("%s execution finished." % self._action_name)


def run_server():
    rospy.init_node("move_to_human_action_server")
    MoveToHumanActionServer()
    rospy.spin()


if __name__ == "__main__":
    run_server()