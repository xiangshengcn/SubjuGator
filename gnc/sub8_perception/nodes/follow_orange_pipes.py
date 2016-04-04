#!/usr/bin/env python
import cv2
import numpy as np
from tf import transformations
import sys
import rospy
from sensor_msgs.msg import Image
from sub8_msgs.srv import VisionRequestResponse, VisionRequest
from sub8_msgs.srv import VisionRequest2DResponse, VisionRequest2D
import sub8_ros_tools
from geometry_msgs.msg import Pose, PoseStamped, Point, Quaternion, Pose2D
from cv_bridge import CvBridge, CvBridgeError

# define threshold for orange color detection
# ORANGE_MIN = np.array([1, 90, 180], np.float32)
# ORANGE_MAX = np.array([23, 255, 255], np.float32)
RANGE = np.array([
    [0., 9.9524],
    [0., 148.7415],
    [187.7055, 255.]
])


class PipeFinder:
    def __init__(self):
        self.pose_pub = rospy.Publisher("orange_pipe_vision", Pose, queue_size=1)
        self.pose_service = rospy.Service("vision/channel_marker/2D", VisionRequest2D, self.request_pipe)
        self.image_sub = sub8_ros_tools.Image_Subscriber('/down/left/image_raw', self.image_cb)
        self.image_pub = sub8_ros_tools.Image_Publisher("down/left/target_info")
        # rospy.Timer(rospy.Duration(0.03), self.publish_target_info)
        self.last_image = None

    def image_cb(self, image):
        self.last_image = image
        self.find_pipe(np.copy(image))

    def find_pipe(self, img):
        rows, cols = img.shape[:2]

        blur = cv2.GaussianBlur(img, (5, 5), 1000)

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # mask = cv2.inRange(hsv, ORANGE_MIN, ORANGE_MAX)
        mask = cv2.inRange(hsv, RANGE[:, 0], RANGE[:, 1])
        contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        blank_img = np.zeros((rows, cols), np.uint8)
        self.draw_image = np.copy(img)

        if contours:

            # sort contours by area (greatest --> least)
            contours = sorted(contours, key=cv2.contourArea, reverse=True)[:1]
            cnt = contours[0]  # contour with greatest area
            if cv2.contourArea(cnt) > 300:  # this value will change based on our depth/the depth of the pool

                rect = cv2.minAreaRect(cnt)   # find bounding rectangle of min area (including rotation)
                box = cv2.cv.BoxPoints(rect)  # get corner coordinates of that rectangle
                box = np.int0(box)            # convert coordinates to ints

                # draw minAreaRect around pipe
                cv2.drawContours(blank_img, [box], 0, (255, 255, 255), -1)
                cv2.drawContours(self.draw_image, [box], 0, (255, 255, 255), -1)

                # get all coordinates (y,x) of pipe
                why, whx = np.where(blank_img)
                # align coordinates --> (x,y)
                wh = np.array([whx, why])

                # estimate covariance matrix and get corresponding eigenvectors
                cov = np.cov(wh)
                eig_vals, eig_vects = np.linalg.eig(cov)

                # use index of max eigenvalue to find max eigenvector
                i = np.argmax(eig_vals)
                max_eigv = eig_vects[:, i] * np.sqrt(eig_vals[i])

                # flip indices to find min eigenvector
                min_eigv = eig_vects[:, 1 - i] * np.sqrt(eig_vals[1 - i])

                # define center of pipe
                center = np.average(wh, axis=1)

                # define vertical vector (sub's current direction)
                # vert_vect = np.array([0, -1 * np.int0(center[1])])
                vert_vect = np.array([0.0, -1.0])

                if max_eigv[1] > 0:
                    max_eigv = -max_eigv
                    min_eigv = -min_eigv

                num = np.cross(max_eigv, vert_vect)
                denom = np.linalg.norm(max_eigv) * np.linalg.norm(vert_vect)
                angle_rad = np.arcsin(num / denom)

                if angle_rad >= np.pi / 2:
                    angle_rad -= np.pi / 2

                cv2.line(self.draw_image, tuple(np.int0(center)), tuple(np.int0(center + (2 * max_eigv))), (0, 255, 30), 2)
                cv2.line(self.draw_image, tuple(np.int0(center)), tuple(np.int0(center + (2 * min_eigv))), (0, 30, 255), 2)

                # quaternion = transformations.quaternion_from_euler(0.0, 0.0, angle_rad)

                # cv2.imshow("lll", self.draw_image)
                # cv2.waitKey(10)
                self.image_pub.publish(self.draw_image)
                return center, angle_rad

        # print 'nct'
        # print self.draw_image.shape
        # cv2.imshow("lll", self.draw_image)
        # cv2.waitKey(15)

    def request_pipe(self, data):
        if self.last_image is None:
            return False  # Fail if we have no images cached

        pose = self.find_pipe(self.last_image)

        found = (pose is not None)
        if not found:
            resp = VisionRequest2DResponse(
                header=sub8_ros_tools.make_header(frame='/down_camera'),
                found=found
            )
        else:
            position, orientation = pose
            resp = VisionRequest2DResponse(
                pose=Pose2D(
                    x=position[0],
                    y=position[1],
                    theta=orientation
                ),
                max_x=self.last_image.shape[0],
                max_y=self.last_image.shape[1],
                header=sub8_ros_tools.make_header(frame='/down_camera'),
                found=found
            )
        return resp


def main(args):
    pf = PipeFinder()
    try:
        rospy.spin()
    except KeyboardInterrupt:
        print("Shutting down")
    cv2.destroyAllWindows()


if __name__ == '__main__':
    rospy.init_node('orange_pipe_vision')
    main(sys.argv)
