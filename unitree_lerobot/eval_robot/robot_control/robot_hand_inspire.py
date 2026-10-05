from unitree_sdk2py.core.channel import ChannelPublisher, ChannelSubscriber, ChannelFactoryInitialize  # dds
try:
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import MotorCmds_, MotorStates_  # idl
except ImportError:
    MotorCmds_, MotorStates_ = None, None
from unitree_sdk2py.idl.default import unitree_go_msg_dds__MotorCmd_

import numpy as np
from enum import IntEnum
import threading
import time
from multiprocessing import Process, Array

import logging_mp

logger_mp = logging_mp.getLogger(__name__)
logger_mp.setLevel(logging_mp.INFO)

Inspire_Num_Motors = 6
kTopicInspireCommand = "rt/inspire/cmd"
kTopicInspireState = "rt/inspire/state"


class Inspire_Controller:
    def __init__(
        self,
        left_hand_array,
        right_hand_array,
        dual_hand_data_lock=None,
        dual_hand_state_array=None,
        dual_hand_action_array=None,
        fps=100.0,
        Unit_Test=False,
        simulation_mode=False,
    ):
        logger_mp.info("Initialize Inspire_Controller...")
        self.fps = fps
        self.Unit_Test = Unit_Test
        self.simulation_mode = simulation_mode

        if self.simulation_mode:
            ChannelFactoryInitialize(1)
        else:
            ChannelFactoryInitialize(0)

        # initialize handcmd publisher and handstate subscriber
        self.HandCmb_publisher = ChannelPublisher(kTopicInspireCommand, MotorCmds_)
        self.HandCmb_publisher.Init()

        self.HandState_subscriber = ChannelSubscriber(kTopicInspireState, MotorStates_)
        self.HandState_subscriber.Init()

        # Shared Arrays for hand states
        self.left_hand_state_array = Array("d", Inspire_Num_Motors, lock=True)
        self.right_hand_state_array = Array("d", Inspire_Num_Motors, lock=True)

        # initialize subscribe thread
        self.subscribe_state_thread = threading.Thread(target=self._subscribe_hand_state)
        self.subscribe_state_thread.daemon = True
        self.subscribe_state_thread.start()

        while True:
            if any(self.right_hand_state_array):  # any(self.left_hand_state_array) and
                break
            time.sleep(0.01)
            logger_mp.warning("[Inspire_Controller] Waiting to subscribe dds...")
        logger_mp.info("[Inspire_Controller] Subscribe dds ok.")

        hand_control_process = Process(
            target=self.control_process,
            args=(
                left_hand_array,
                right_hand_array,
                self.left_hand_state_array,
                self.right_hand_state_array,
                dual_hand_data_lock,
                dual_hand_state_array,
                dual_hand_action_array,
            ),
        )
        hand_control_process.daemon = True
        hand_control_process.start()

        logger_mp.info("Initialize Inspire_Controller OK!\n")

    def _subscribe_hand_state(self):
        while True:
            hand_msg = self.HandState_subscriber.Read()
            if hand_msg is not None:
                for idx, id in enumerate(Inspire_Left_Hand_JointIndex):
                    self.left_hand_state_array[idx] = hand_msg.states[id].q
                for idx, id in enumerate(Inspire_Right_Hand_JointIndex):
                    self.right_hand_state_array[idx] = hand_msg.states[id].q
            time.sleep(0.002)

    def ctrl_dual_hand(self, left_q_target, right_q_target):
        """
        Set current left, right hand motor state target q
        """
        for idx, id in enumerate(Inspire_Left_Hand_JointIndex):
            self.hand_msg.cmds[id].q = left_q_target[idx]
        for idx, id in enumerate(Inspire_Right_Hand_JointIndex):
            self.hand_msg.cmds[id].q = right_q_target[idx]

        self.HandCmb_publisher.Write(self.hand_msg)
        # logger_mp.debug("hand ctrl publish ok.")

    def control_process(
        self,
        left_hand_array,
        right_hand_array,
        left_hand_state_array,
        right_hand_state_array,
        dual_hand_data_lock=None,
        dual_hand_state_array=None,
        dual_hand_action_array=None,
    ):
        self.running = True

        left_q_target = np.full(Inspire_Num_Motors, 1.0)
        right_q_target = np.full(Inspire_Num_Motors, 1.0)

        # initialize inspire hand's cmd msg
        self.hand_msg = MotorCmds_()
        self.hand_msg.cmds = [
            unitree_go_msg_dds__MotorCmd_()
            for _ in range(len(Inspire_Right_Hand_JointIndex) + len(Inspire_Left_Hand_JointIndex))
        ]

        for idx, id in enumerate(Inspire_Left_Hand_JointIndex):
            self.hand_msg.cmds[id].q = 1.0
        for idx, id in enumerate(Inspire_Right_Hand_JointIndex):
            self.hand_msg.cmds[id].q = 1.0

        try:
            while self.running:
                start_time = time.time()

                # get dual hand state
                with left_hand_array.get_lock():
                    left_hand_mat = np.array(left_hand_array[:]).copy()
                with right_hand_array.get_lock():
                    right_hand_mat = np.array(right_hand_array[:]).copy()

                # Read left and right q_state from shared arrays
                state_data = np.concatenate((np.array(left_hand_state_array[:]), np.array(right_hand_state_array[:])))

                action_data = np.concatenate((left_hand_mat, right_hand_mat))
                if dual_hand_data_lock is not None:
                    with dual_hand_data_lock:
                        dual_hand_state_array[:] = state_data
                        dual_hand_action_array[:] = action_data

                if dual_hand_state_array and dual_hand_action_array:
                    with dual_hand_data_lock:
                        left_q_target = left_hand_mat
                        right_q_target = right_hand_mat

                self.ctrl_dual_hand(left_q_target, right_q_target)
                current_time = time.time()
                time_elapsed = current_time - start_time
                sleep_time = max(0, (1 / self.fps) - time_elapsed)
                time.sleep(sleep_time)
        finally:
            logger_mp.info("Inspire_Controller has been closed.")



kTopicInspireFTPLeftCommand = "rt/inspire_hand/ctrl/l"
kTopicInspireFTPRightCommand = "rt/inspire_hand/ctrl/r"
kTopicInspireFTPLeftState = "rt/inspire_hand/state/l"
kTopicInspireFTPRightState = "rt/inspire_hand/state/r"


class Inspire_FTP_Controller:
    """Inspire_Controller for the FTP dexterous hands (--ee inspire_ftp).

    Same constructor signature and shared-memory contract as Inspire_Controller,
    so make_robot.setup_robot_interface builds both the same way. The only
    difference is the wire protocol: the FTP hands listen on
    rt/inspire_hand/ctrl/l|r with inspire_dds.inspire_hand_ctrl, served by the
    inspire_hand_ftp_driver.py Modbus bridge. Inspire_Controller publishes to
    rt/inspire/cmd (the DFX hand), which this hardware ignores -- the hand then
    simply never moves, with no error on either side.

    Unlike teleop's Inspire_Controller_FTP, left_hand_array/right_hand_array
    here carry a 6-dof target already normalized to [0,1], written straight from
    the policy action by the eval loop -- not 25x3 XR hand keypoints. So there
    is no HandRetargeting step; the values only get scaled to the hardware's
    0-1000 range.

    Prerequisite: the FTP bridge must be running for BOTH hands, otherwise
    commands go nowhere and the state arrays stay at zero.
    """

    def __init__(
        self,
        left_hand_array,
        right_hand_array,
        dual_hand_data_lock=None,
        dual_hand_state_array=None,
        dual_hand_action_array=None,
        fps=100.0,
        Unit_Test=False,
        simulation_mode=False,
    ):
        logger_mp.info("Initialize Inspire_FTP_Controller...")
        from inspire_sdkpy import inspire_dds  # lazy: external SDK, only needed for the FTP hands
        import inspire_sdkpy.inspire_hand_defaut as inspire_hand_default

        self._inspire_hand_default = inspire_hand_default
        self.fps = fps
        self.Unit_Test = Unit_Test
        self.simulation_mode = simulation_mode

        # ChannelFactory.Init is a class-level singleton: if the arm controller
        # (or an eno1 wrapper) already pinned the interface, this is a no-op.
        if self.simulation_mode:
            ChannelFactoryInitialize(1)
        else:
            ChannelFactoryInitialize(0)

        self.LeftHandCmd_publisher = ChannelPublisher(kTopicInspireFTPLeftCommand, inspire_dds.inspire_hand_ctrl)
        self.LeftHandCmd_publisher.Init()
        self.RightHandCmd_publisher = ChannelPublisher(kTopicInspireFTPRightCommand, inspire_dds.inspire_hand_ctrl)
        self.RightHandCmd_publisher.Init()

        self.LeftHandState_subscriber = ChannelSubscriber(kTopicInspireFTPLeftState, inspire_dds.inspire_hand_state)
        self.LeftHandState_subscriber.Init()
        self.RightHandState_subscriber = ChannelSubscriber(kTopicInspireFTPRightState, inspire_dds.inspire_hand_state)
        self.RightHandState_subscriber.Init()

        # Shared arrays for hand states, normalized back to [0,1]
        self.left_hand_state_array = Array("d", Inspire_Num_Motors, lock=True)
        self.right_hand_state_array = Array("d", Inspire_Num_Motors, lock=True)

        # Explicit "a real state message has arrived" flags. Do NOT infer this from
        # any(state_array): a hand legitimately closed to angle 0 on all six joints
        # reads as all-zeros, which is indistinguishable from "no data yet".
        self.left_state_seen = threading.Event()
        self.right_state_seen = threading.Event()

        self.subscribe_state_thread = threading.Thread(target=self._subscribe_hand_state)
        self.subscribe_state_thread.daemon = True
        self.subscribe_state_thread.start()

        # Wait for BOTH hands, not either. This condition used to be `or` (and tested
        # any(state_array) rather than an arrival flag), so it returned as soon as the
        # FIRST hand reported -- measured at 0.04s on this rig -- while the other hand's
        # state array was still all zeros. The seed below then copied those zeros into
        # that hand's target and control_process() drove the REAL hand to angle 0 at
        # ~100Hz, regardless of --send_real_robot. Measured 2026-09-20 during a
        # --send_real_robot=false dry run: the right hand went [2,1,1,4,244,149] ->
        # [2,0,1,2,2,0] with motor current up to 744 for ~28s, while the left hand
        # (seeded correctly) never moved. See Checklist.md.
        wait_count = 0
        deadline = time.time() + 5.0
        while not (self.left_state_seen.is_set() and self.right_state_seen.is_set()):
            if wait_count % 100 == 0:
                logger_mp.info("[Inspire_FTP_Controller] Waiting to subscribe dds...")
            if time.time() > deadline:
                missing = [
                    name for name, ev in (("left", self.left_state_seen), ("right", self.right_state_seen))
                    if not ev.is_set()
                ]
                # Deliberately fatal, not a warning. Proceeding would start
                # control_process() with an all-zero target for the unseeded hand,
                # which is real actuation on real hardware. A silently frozen state
                # branch on the FTP bridge (a known failure mode of this rig) looks
                # exactly like this, so refuse rather than move the hand.
                raise RuntimeError(
                    f"[Inspire_FTP_Controller] No hand state received for: {', '.join(missing)} "
                    f"(topics {kTopicInspireFTPLeftState} / {kTopicInspireFTPRightState}) within 5s. "
                    "Refusing to start -- the actuation process would drive the unseeded hand to "
                    "angle 0. Check that inspire_hand_ftp_driver.py is running for BOTH hands and "
                    "that its state branch has not silently frozen (count distinct angle_act values)."
                )
            time.sleep(0.01)
            wait_count += 1
        logger_mp.info("[Inspire_FTP_Controller] Subscribe dds ok (both hands reporting).")

        # Seed the shared "target" arrays (left_hand_array/right_hand_array, i.e.
        # ee_shared_mem["left"/"right"]) with the hand's own current reported position
        # instead of leaving them at their zero default. control_process() below reads
        # its actuation target straight from these arrays every cycle regardless of
        # --send_real_robot -- a caller that legitimately never writes to them (e.g.
        # eval_g1.py's dry run, which intentionally skips writing real policy actions
        # when send_real_robot=False) was therefore driving the real hand toward
        # angle=0 on every one of these ~100Hz cycles. Verified empirically
        # 2026-09-20: this pulled a real hand from ~[999,997,1000,999,1000,990] to
        # ~[1,0,3,3,340,0] with real motor current, entirely independent of
        # --send_real_robot -- see Checklist.md. Seeding here makes an unwritten
        # target a true no-op (hold current position) instead of a snap to zero.
        with left_hand_array.get_lock():
            left_hand_array[:] = self.left_hand_state_array[:]
        with right_hand_array.get_lock():
            right_hand_array[:] = self.right_hand_state_array[:]

        hand_control_process = Process(
            target=self.control_process,
            args=(
                left_hand_array,
                right_hand_array,
                self.left_hand_state_array,
                self.right_hand_state_array,
                dual_hand_data_lock,
                dual_hand_state_array,
                dual_hand_action_array,
            ),
        )
        hand_control_process.daemon = True
        hand_control_process.start()

        logger_mp.info("Initialize Inspire_FTP_Controller OK!\n")

    def _subscribe_hand_state(self):
        while True:
            left_state_msg = self.LeftHandState_subscriber.Read()
            if left_state_msg is not None and len(left_state_msg.angle_act) == Inspire_Num_Motors:
                with self.left_hand_state_array.get_lock():
                    for i in range(Inspire_Num_Motors):
                        self.left_hand_state_array[i] = left_state_msg.angle_act[i] / 1000.0
                self.left_state_seen.set()
            right_state_msg = self.RightHandState_subscriber.Read()
            if right_state_msg is not None and len(right_state_msg.angle_act) == Inspire_Num_Motors:
                with self.right_hand_state_array.get_lock():
                    for i in range(Inspire_Num_Motors):
                        self.right_hand_state_array[i] = right_state_msg.angle_act[i] / 1000.0
                self.right_state_seen.set()
            time.sleep(0.002)

    def ctrl_dual_hand(self, left_q_target, right_q_target):
        """
        Set current left, right hand motor state target q (normalized [0,1]).
        """
        left_msg = self._inspire_hand_default.get_inspire_hand_ctrl()
        left_msg.angle_set = [int(np.clip(val * 1000, 0, 1000)) for val in left_q_target]
        left_msg.mode = 0b0001  # angle control
        self.LeftHandCmd_publisher.Write(left_msg)

        right_msg = self._inspire_hand_default.get_inspire_hand_ctrl()
        right_msg.angle_set = [int(np.clip(val * 1000, 0, 1000)) for val in right_q_target]
        right_msg.mode = 0b0001
        self.RightHandCmd_publisher.Write(right_msg)

    def control_process(
        self,
        left_hand_array,
        right_hand_array,
        left_hand_state_array,
        right_hand_state_array,
        dual_hand_data_lock=None,
        dual_hand_state_array=None,
        dual_hand_action_array=None,
    ):
        self.running = True

        left_q_target = np.full(Inspire_Num_Motors, 1.0)
        right_q_target = np.full(Inspire_Num_Motors, 1.0)

        try:
            while self.running:
                start_time = time.time()

                with left_hand_array.get_lock():
                    left_hand_mat = np.array(left_hand_array[:]).copy()
                with right_hand_array.get_lock():
                    right_hand_mat = np.array(right_hand_array[:]).copy()

                state_data = np.concatenate((np.array(left_hand_state_array[:]), np.array(right_hand_state_array[:])))
                action_data = np.concatenate((left_hand_mat, right_hand_mat))

                if dual_hand_data_lock is not None:
                    with dual_hand_data_lock:
                        dual_hand_state_array[:] = state_data
                        dual_hand_action_array[:] = action_data

                if dual_hand_state_array and dual_hand_action_array:
                    with dual_hand_data_lock:
                        left_q_target = left_hand_mat
                        right_q_target = right_hand_mat

                self.ctrl_dual_hand(left_q_target, right_q_target)
                current_time = time.time()
                time_elapsed = current_time - start_time
                sleep_time = max(0, (1 / self.fps) - time_elapsed)
                time.sleep(sleep_time)
        finally:
            logger_mp.info("Inspire_FTP_Controller has been closed.")


# Update hand state, according to the official documentation, https://support.unitree.com/home/en/G1_developer/inspire_dfx_dexterous_hand
# the state sequence is as shown in the table below
# ┌──────┬───────┬──────┬────────┬────────┬────────────┬────────────────┬───────┬──────┬────────┬────────┬────────────┬────────────────┐
# │ Id   │   0   │  1   │   2    │   3    │     4      │       5        │   6   │  7   │   8    │   9    │    10      │       11       │
# ├──────┼───────┼──────┼────────┼────────┼────────────┼────────────────┼───────┼──────┼────────┼────────┼────────────┼────────────────┤
# │      │                    Right Hand                                │                   Left Hand                                  │
# │Joint │ pinky │ ring │ middle │ index  │ thumb-bend │ thumb-rotation │ pinky │ ring │ middle │ index  │ thumb-bend │ thumb-rotation │
# └──────┴───────┴──────┴────────┴────────┴────────────┴────────────────┴───────┴──────┴────────┴────────┴────────────┴────────────────┘
class Inspire_Right_Hand_JointIndex(IntEnum):
    kRightHandPinky = 0
    kRightHandRing = 1
    kRightHandMiddle = 2
    kRightHandIndex = 3
    kRightHandThumbBend = 4
    kRightHandThumbRotation = 5


class Inspire_Left_Hand_JointIndex(IntEnum):
    kLeftHandPinky = 6
    kLeftHandRing = 7
    kLeftHandMiddle = 8
    kLeftHandIndex = 9
    kLeftHandThumbBend = 10
    kLeftHandThumbRotation = 11
