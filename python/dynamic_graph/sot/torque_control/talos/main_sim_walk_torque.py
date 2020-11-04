from dynamic_graph import plug
import numpy as np
from dynamic_graph.sot.torque_control.se3_trajectory_generator import SE3TrajectoryGenerator
from sot_talos_balance.nd_trajectory_generator import NdTrajectoryGenerator
from dynamic_graph.sot.torque_control.talos.create_entities_utils_talos import create_trajectory_switch, connect_synchronous_trajectories, create_force_traj_gen
from dynamic_graph.sot.torque_control.talos.create_entities_utils_talos import NJ, create_rospublish, create_topic, get_sim_conf 
from dynamic_graph.sot.torque_control.talos.create_entities_utils_talos import create_waist_traj_gen, create_trajectory_generator, create_com_traj_gen
from dynamic_graph.sot.torque_control.talos.create_entities_utils_talos import create_filters, create_encoders, create_am_traj_gen
from dynamic_graph.sot.torque_control.talos.create_entities_utils_talos import create_balance_controller, create_simple_inverse_dyn_controller, create_ctrl_manager
from dynamic_graph.sot.torque_control.talos.create_entities_utils_talos import addTrace, dump_tracer, create_encoders_velocity
from sot_talos_balance.create_entities_utils import create_device_filters, create_imu_filters, create_base_estimator
from dynamic_graph.sot.torque_control.talos.sot_utils_talos import go_to_position
from dynamic_graph.tracer_real_time import TracerRealTime
from dynamic_graph.sot.core.operator import Substract_of_vector, Component_of_vector
from sot_talos_balance.round_double_to_int import RoundDoubleToInt
from sot_talos_balance.delay import DelayVector
from dynamic_graph.sot.core.math_small_entities import Derivator_of_Vector

# --- EXPERIMENTAL SET UP ------------------------------------------------------
conf = get_sim_conf()
dt = robot.timeStep
robot.device.setControlInputType('noInteg') # No integration for torque control

# --- SET INITIAL CONFIGURATION ------------------------------------------------
# TMP: overwrite halfSitting configuration to use SoT joint order
q = [0., 0., 1.018213, 0., 0., 0.] # Free flyer
q += [0.0, 0.0, -0.411354, 0.859395, -0.448041, -0.001708] # legs
q += [0.0, 0.0, -0.411354, 0.859395, -0.448041, -0.001708] # legs
q += [0.0, 0.006761] # Chest
q += [0.25847, 0.173046, -0.0002, -0.525366, 0.0, -0.0, 0.1, -0.005] # arms
q += [-0.25847, -0.173046, 0.0002, -0.525366, 0.0, 0.0, 0.1, -0.005] # arms
q += [0., 0.] # Head

robot.halfSitting = q

# --- CREATE ENTITIES ----------------------------------------------------------

robot.ctrl_manager = create_ctrl_manager(conf.control_manager, conf.motor_params, dt)
robot.encoders = create_encoders(robot)
robot.encoders_velocity = create_encoders_velocity(robot)

# --- Posture trajectory
robot.traj_gen = create_trajectory_generator(robot, dt)
robot.traj_gen.q.recompute(0)

# --- CoM trajectory
init_value_com = np.loadtxt(folder + walk_type + "/com.dat", usecols=(0,1,2))[0]
robot.com_traj_gen = create_com_traj_gen(robot, dt, init_value_com)
robot.com_traj_gen.x.recompute(0)

# --- Base orientation (SE3 on the waist) trajectory
robot.waist_traj_gen = create_waist_traj_gen("tg_waist_ref", robot, dt)
robot.waist_traj_gen.x.recompute(0)

# --- Angular momentum trajectory
init_value_am = np.loadtxt(folder + walk_type + "/am.dat", usecols=(0,1,2))[0]
robot.am_traj_gen = create_am_traj_gen(robot, dt, init_value_am)
robot.am_traj_gen.x.recompute(0)

# --- Contact phases trajectories
robot.phases_traj_gen = NdTrajectoryGenerator("tg_phases")
robot.phases_traj_gen.initial_value.value = [0]
robot.phases_traj_gen.init(dt, 1)
# Set phase to int
robot.phaseScalar = Component_of_vector("phase_scalar")
robot.phaseScalar.setIndex(0)
plug(robot.phases_traj_gen.x, robot.phaseScalar.sin)
robot.phaseInt = RoundDoubleToInt("phase_int")
plug(robot.phaseScalar.sout, robot.phaseInt.sin)

# --- Feet trajectories
init_value_rf = np.loadtxt(folder + walk_type + "/rightFoot.dat")[0]
init_value_lf = np.loadtxt(folder + walk_type + "/leftFoot.dat")[0]
robot.rf_traj_gen = NdTrajectoryGenerator("tg_rf")
robot.rf_traj_gen.initial_value.value = init_value_rf
robot.lf_traj_gen = NdTrajectoryGenerator("tg_lf")
robot.lf_traj_gen.initial_value.value = init_value_lf
robot.rf_traj_gen.init(dt, 12)
robot.lf_traj_gen.init(dt, 12)

# --- Hands trajectories
robot.rh_traj_gen = SE3TrajectoryGenerator("tg_rh")
robot.lh_traj_gen = SE3TrajectoryGenerator("tg_lh")
robot.rh_traj_gen.init(dt)
robot.lh_traj_gen.init(dt)

# --- Switch which synchronizes trajectories
robot.traj_sync = create_trajectory_switch()
trajs = [robot.com_traj_gen, robot.waist_traj_gen, robot.am_traj_gen, robot.phases_traj_gen]
trajs += [robot.rf_traj_gen, robot.lf_traj_gen, robot.rh_traj_gen, robot.lh_traj_gen]
connect_synchronous_trajectories(robot.traj_sync, trajs)

# --- Base Estimator
robot.device_filters = create_device_filters(robot, dt)
robot.imu_filters = create_imu_filters(robot, dt)
robot.base_estimator = create_base_estimator(robot, dt, conf.base_estimator)
plug(robot.device_filters.vel_filter.x_filtered, robot.base_estimator.joint_velocities)

robot.base_estimator.q.recompute(0)
robot.base_estimator.v.recompute(0)

# --- Inverse dynamic controller
robot.inv_dyn = create_balance_controller(robot, conf.balance_ctrl,conf.motor_params, dt, controlType="torque")
robot.inv_dyn.active_joints.value = 32*(1.0,)

# --- Reference position of the feet for base estimator
robot.inv_dyn.left_foot_pos_quat.recompute(0)
robot.inv_dyn.right_foot_pos_quat.recompute(0)
plug(robot.inv_dyn.left_foot_pos_quat, robot.base_estimator.lf_ref_xyzquat)
plug(robot.inv_dyn.right_foot_pos_quat, robot.base_estimator.rf_ref_xyzquat)

# --- High gains position controller
from dynamic_graph.sot.torque_control.position_controller import PositionController
posCtrl = PositionController('pos_ctrl')
posCtrl.Kp.value = tuple(conf.pos_ctrl_gains.kp_pos[round(dt,3)]);
posCtrl.Kd.value = tuple(conf.pos_ctrl_gains.kd_pos[round(dt,3)]);
posCtrl.Ki.value = tuple(conf.pos_ctrl_gains.ki_pos[round(dt,3)]);
plug(robot.device.robotState, posCtrl.base6d_encoders);
plug(robot.device_filters.vel_filter.x_filtered, posCtrl.jointsVelocities);
plug(robot.traj_gen.q, posCtrl.qRef);
plug(robot.traj_gen.dq, posCtrl.dqRef);
posCtrl.init(dt, "robot");
robot.pos_ctrl = posCtrl

# --- Connect control manager
plug(robot.device.currents, robot.ctrl_manager.i_measured)
plug(robot.device.ptorque, robot.ctrl_manager.tau)

robot.ctrl_manager.addCtrlMode("torque")
plug(robot.inv_dyn.tau_des, robot.ctrl_manager.ctrl_torque)
robot.ctrl_manager.setCtrlMode("lhy-lhr-lhp-lk-lap-lar-rhy-rhr-rhp-rk-rap-rar-ty-tp-lsy-lsr-lay-le-lwy-lwp-lwr-rsy-rsr-ray-re-rwy-rwp-rwr", "torque")

robot.ctrl_manager.addCtrlMode("pos")
plug(robot.pos_ctrl.pwmDes, robot.ctrl_manager.ctrl_pos)
robot.ctrl_manager.setCtrlMode("lh-rh-hp-hy", "pos")
plug(robot.ctrl_manager.u_safe, robot.device.control)

# --- Delay position q
robot.delay_pos = DelayVector("delay_pos")
robot.delay_pos.setMemory(robot.base_estimator.q.value)
robot.device.before.addSignal(robot.delay_pos.name + '.current')
plug(robot.inv_dyn.q_des, robot.delay_pos.sin)

# --- Delay velocity dq
robotDim = len(robot.base_estimator.v.value)
robot.delay_vel = DelayVector("delay_vel")
robot.delay_vel.setMemory(robotDim * [0.])
robot.device.before.addSignal(robot.delay_vel.name + '.current')
plug(robot.inv_dyn.v_des, robot.delay_vel.sin)

# --- Fix robot.dynamic inputs
plug(robot.delay_pos.previous, robot.dynamic.position)
plug(robot.delay_vel.previous, robot.dynamic.velocity)
# plug(robot.delay_vel.previous, robot.vselec.sin)
robot.dvdt = Derivator_of_Vector("dv_dt")
robot.dvdt.dt.value = dt
plug(robot.delay_vel.previous, robot.dvdt.sin)
plug(robot.dvdt.sout, robot.dynamic.acceleration)


# --- ROS PUBLISHER ----------------------------------------------------------

robot.publisher = create_rospublish(robot, 'robot_publisher')
create_topic(robot.publisher, robot.inv_dyn, 'com', 'inv_dyn_com', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'am_L', 'inv_dyn_am', robot=robot, data_type='vector') 
create_topic(robot.publisher, robot.inv_dyn, 'am_dL', 'inv_dyn_dam', robot=robot, data_type='vector') 
create_topic(robot.publisher, robot.inv_dyn, 'q_des', 'q_des', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'v_des', 'v_des', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'dv_des', 'dv_des', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'tau_des', 'tau_des', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'tau_pd_des', 'tau_pd_des', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'left_foot_pos', 'left_foot_pos', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'right_foot_pos', 'right_foot_pos', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.base_estimator, 'q', 'base_q', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.base_estimator, 'v', 'base_v', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.phaseInt, 'sout', 'contactphase', robot=robot, data_type='int')
create_topic(robot.publisher, robot.com_traj_gen, 'x', 'com_traj_gen', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.lf_traj_gen, 'x', 'lf_traj_gen', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.rf_traj_gen, 'x', 'rf_traj_gen', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.am_traj_gen, 'x', 'am_traj_gen', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.am_traj_gen, 'dx', 'dam_traj_gen', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.device, 'motorcontrol', 'motorcontrol', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.device, 'robotState', 'robotState', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'zmp', 'zmp_estim', robot=robot, data_type='vector')  # estimated ZMP
create_topic(robot.publisher, robot.inv_dyn, 'dcm', 'dcm_estim', robot=robot, data_type='vector')  # estimated DCM
create_topic(robot.publisher, robot.device, 'forceLLEG', 'forceLLEG', robot = robot, data_type='vector') # measured left wrench
create_topic(robot.publisher, robot.device, 'forceRLEG', 'forceRLEG', robot = robot, data_type='vector')
create_topic(robot.publisher, robot.device, 'ptorque', 'tau_meas', robot = robot, data_type='vector')

# --- TRACER ----------------------------------------------------------
robot.tracer = TracerRealTime("inv_dyn_tracer")
robot.tracer.setBufferSize(80*(2**20))
robot.tracer.open('/tmp','dg_','.dat')
robot.device.after.addSignal('{0}.triger'.format(robot.tracer.name))

addTrace(robot.tracer, robot.inv_dyn, 'tau_des')
addTrace(robot.tracer, robot.inv_dyn, 'tau_pd_des')
addTrace(robot.tracer, robot.inv_dyn, 'q_des')
addTrace(robot.tracer, robot.inv_dyn, 'v_des')
addTrace(robot.tracer, robot.inv_dyn, 'dv_des')
addTrace(robot.tracer, robot.device, 'robotState')
addTrace(robot.tracer, robot.device, 'motorcontrol')

robot.tracer.start()
