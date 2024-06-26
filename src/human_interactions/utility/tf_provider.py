#!/usr/bin/env python

import math

import rospy
import tf
from geometry_msgs.msg import Pose, Transform, Quaternion
from tf.transformations import quaternion_multiply, quaternion_from_euler


class TFProvider:
    """
    Provides methods for common tasks regarding transformations using the TF
    ROS library.

    Attributes:
        _tf_listener (tf.TransformListener): A listener for TF transformations.
    """

    def __init__(self):
        """
        Initialize the TFProvider.
        """
        self._tf_listener = tf.TransformListener()

    def get_tf(self, target_frame, source_frame, inverse=True):
        """
        Get the transformation from the target_frame to the source_frame.

        Args:
            target_frame (str): The target frame for the transformation.
            source_frame (str): The source frame for the transformation.
            inverse (bool, optional): If True, get the inverse transformation (True by default).

        Returns:
            Transform (optional): The requested transformation. None if the transformation lookup fails.
        """
        if inverse:
            target_frame, source_frame = source_frame, target_frame

        try:
            self._tf_listener.waitForTransform(
                target_frame, source_frame, rospy.Time(0), rospy.Duration(5.0)
            )
            (translation, rotation) = self._tf_listener.lookupTransform(
                target_frame, source_frame, rospy.Time(0)
            )

            # Convert to Transform message format.
            transform = Transform()
            (
                transform.translation.x,
                transform.translation.y,
                transform.translation.z,
            ) = translation
            (
                transform.rotation.x,
                transform.rotation.y,
                transform.rotation.z,
                transform.rotation.w,
            ) = rotation
            return transform
        except (
            tf.LookupException,
            tf.ConnectivityException,
            tf.ExtrapolationException,
        ):
            rospy.logerr("Failed to lookup transform.")
            return None

    def get_map_tf(self, target_frame, inverse=True):
        """
        Get the transformation from the map frame to the specified target_frame.

        Args:
            target_frame (str): The target frame for the transformation.
            source_frame (str): The source frame for the transformation.
            inverse (bool, optional): If True, get the inverse transformation (True by default).

        Returns:
            Transform (optional): The requested transformation. None if the transformation lookup fails.
        """
        MAP_TF = "map"
        return self.get_tf(target_frame, MAP_TF, inverse)

    @staticmethod
    def get_transform_as_pose(transform):
        """
        Get a corresponding Pose message from Transform message

        Args:
            transform (Transform): A Transform message.

        Returns:
            Pose: A Pose message representing the transformation.
        """
        pose = Pose()

        pose.position.x = transform.translation.x
        pose.position.y = transform.translation.y
        pose.position.z = 1.5  # Change to assumed human face height.
        pose.orientation = transform.rotation

        return pose

    @staticmethod
    def get_quaternion_as_list(quaternion):
        """
        Get a list representing the Quaternion message.

        Args:
            quaternion (Quaternion): A Quaternion message.

        Returns:
            list[float]: A list representing the quaternion.
        """
        return [quaternion.x, quaternion.y, quaternion.z, quaternion.w]

    @staticmethod
    def get_opposite_orientation(orientation):
        """
        Return an orientation facing the opposite direction in the x-y plane by
        applying the corresponding rotation.

        Args:
            orientation (Quaternion): The original orientation.

        Returns:
            Quaternion: Orientation facing the opposite direction.
        """
        rotation_quaternion = quaternion_from_euler(0, 0, math.pi)
        return Quaternion(
            *quaternion_multiply(
                TFProvider.get_quaternion_as_list(orientation), rotation_quaternion
            )
        )
