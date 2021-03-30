from dynamic_graph import plug
import numpy as np
from dynamic_graph.sot.core.operator import Selec_of_vector, Substract_of_vector, Component_of_vector, Stack_of_vector
from dynamic_graph.sot.torque_control.talos.create_entities_utils_talos import create_trajectory_switch, connect_synchronous_trajectories
from dynamic_graph.sot.torque_control.talos.create_entities_utils_talos import NJ, create_rospublish, create_topic, get_default_conf, get_sim_conf, create_encoders_velocity
from dynamic_graph.sot.torque_control.talos.create_entities_utils_talos import create_waist_traj_gen, create_trajectory_generator, create_com_traj_gen, create_encoders
from dynamic_graph.sot.torque_control.talos.create_entities_utils_talos import create_simple_inverse_dyn_controller#create_ctrl_manager, connect_ctrl_manager
from dynamic_graph.sot_talos_balance.create_entities_utils import fill_parameter_server, create_ctrl_manager
from dynamic_graph.sot.torque_control.talos.create_entities_utils_talos import addTrace, dump_tracer
from dynamic_graph.sot.torque_control.talos.sot_utils_talos import go_to_position
from dynamic_graph.sot_talos_balance.create_entities_utils import create_device_filters, create_imu_filters, create_base_estimator
from dynamic_graph.tracer_real_time import TracerRealTime
import dynamic_graph.sot_talos_balance.talos.control_manager_conf as cm_conf

# --- EXPERIMENTAL SET UP ------------------------------------------------------
#conf = get_sim_conf()
conf = get_default_conf()
dt = robot.timeStep
robot.device.setControlInputType('noInteg') # No integration for torque control
# cm_conf.CTRL_MAX = 1e6 # temporary hack

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
fill_parameter_server(robot.param_server, conf.control_manager, dt)
# robot.ctrl_manager = create_ctrl_manager(conf.control_manager, conf.motor_params, dt)
robot.encoders = create_encoders(robot)
robot.encoders_velocity = create_encoders_velocity(robot)

# --- Posture trajectory
robot.traj_gen = create_trajectory_generator(robot, dt)
robot.traj_gen.q.recompute(0)
# --- CoM trajectory
robot.com_traj_gen = create_com_traj_gen(robot, dt)
robot.com_traj_gen.x.recompute(0)
# --- Base orientation (SE3 on the waist) trajectory
robot.waist_traj_gen = create_waist_traj_gen("tg_waist_ref", robot, dt)
robot.waist_traj_gen.x.recompute(0)

# --- Switch which synchronizes trajectories
robot.traj_sync = create_trajectory_switch()
trajs = [robot.com_traj_gen, robot.waist_traj_gen]
connect_synchronous_trajectories(robot.traj_sync, trajs)

# --- Base Estimator
robot.device_filters = create_device_filters(robot, dt)
robot.imu_filters = create_imu_filters(robot, dt)
robot.base_estimator = create_base_estimator(robot, dt, conf.base_estimator)
plug(robot.device_filters.vel_filter.x_filtered, robot.base_estimator.joint_velocities)

robot.base_estimator.q.recompute(0)
robot.base_estimator.v.recompute(0)

# --- Simple inverse dynamic controller
robot.inv_dyn = create_simple_inverse_dyn_controller(robot, conf.balance_ctrl, dt)
robot.inv_dyn.setControlOutputType("torque")
robot.inv_dyn.kd_com.value = np.array([20, 20, 20])
robot.inv_dyn.active_joints.value = np.ones(32)

# --- Reference position of the feet for base estimator
robot.inv_dyn.left_foot_pos.recompute(0)
robot.inv_dyn.right_foot_pos.recompute(0)
robot.base_estimator.lf_ref_xyzquat.value = robot.inv_dyn.left_foot_pos.value
robot.base_estimator.rf_ref_xyzquat.value = robot.inv_dyn.right_foot_pos.value

# --- High gains position controller
# from dynamic_graph.sot.torque_control.position_controller import PositionController
# posCtrl = PositionController('pos_ctrl')
# posCtrl.Kp.value = np.array(conf.pos_ctrl_gains.kp_pos[round(dt,3)]);
# posCtrl.Kd.value = np.array(conf.pos_ctrl_gains.kd_pos[round(dt,3)]);
# posCtrl.Ki.value = np.array(conf.pos_ctrl_gains.ki_pos[round(dt,3)]);
# plug(robot.device.robotState, posCtrl.base6d_encoders);
# plug(robot.device_filters.vel_filter.x_filtered, posCtrl.jointsVelocities);
# plug(robot.traj_gen.q, posCtrl.qRef);
# plug(robot.traj_gen.dq, posCtrl.dqRef);
# posCtrl.init(dt, "robot");
# robot.pos_ctrl = posCtrl

# --- Connect control manager
robot.ctrl_manager = create_ctrl_manager(cm_conf, dt, robot_name='robot')
effortLimit = 0.9 * robot.dynamic.model.effortLimit[6:]
robot.ctrl_manager.u_max.value = np.concatenate((100*np.ones(6), effortLimit))
# robot.ctrl_manager.u_max.value = np.array(38 * (conf.control_manager.CTRL_MAX, ))
# plug(robot.device.currents, robot.ctrl_manager.i_measured)
# plug(robot.device.ptorque, robot.ctrl_manager.tau)

robot.ff_torque = Stack_of_vector('ff_torque')
robot.ff_torque.sin1.value = np.zeros(6)
plug(robot.inv_dyn.tau_des, robot.ff_torque.sin2)
robot.ff_torque.selec1(0, 6)
robot.ff_torque.selec2(0, 32) 

robot.ctrl_manager.addCtrlMode("torque")
# plug(robot.inv_dyn.u, robot.ctrl_manager.ctrl_torque)
robot.ctrl_manager.setCtrlMode("lh-rh-hp-hy-lhy-lhr-lhp-lk-lap-lar-rhy-rhr-rhp-rk-rap-rar-ty-tp-lsy-lsr-lay-le-lwy-lwp-lwr-rsy-rsr-ray-re-rwy-rwp-rwr", "torque")
plug(robot.ff_torque.sout, robot.ctrl_manager.signal('ctrl_torque'))

# robot.ff_pos = Stack_of_vector('ff_pos')
# robot.ff_pos.sin1.value = np.zeros(6)
# plug(robot.pos_ctrl.pwmDes, robot.ff_pos.sin2)
# robot.ff_pos.selec1(0, 6)
# robot.ff_pos.selec2(0, 32)

# robot.ctrl_manager.addCtrlMode("pos")
# robot.ctrl_manager.setCtrlMode("lh-rh-hp-hy", "pos")
# plug(robot.ff_pos.sout, robot.ctrl_manager.signal('ctrl_pos'))

robot.ctrl_manager.addCtrlMode("base")
robot.ctrl_manager.setCtrlMode("freeflyer", "base")
plug(robot.inv_dyn.q_des, robot.ctrl_manager.signal('ctrl_base'))

plug(robot.ctrl_manager.signal('u_safe'), robot.device.control)

# --- Error on the CoM task
# robot.errorComTSID = Substract_of_vector('error_com')
# plug(robot.inv_dyn.com_ref_pos, robot.errorComTSID.sin2)
# plug(robot.dynamic.com, robot.errorComTSID.sin1)

# # --- Error on the Posture task
# robot.errorPoseTSID = Substract_of_vector('error_pose')
# plug(robot.inv_dyn.posture_ref_pos, robot.errorPoseTSID.sin2)
# plug(robot.encoders.sout, robot.errorPoseTSID.sin1)


# # # --- ROS PUBLISHER ----------------------------------------------------------

robot.publisher = create_rospublish(robot, 'robot_publisher')
# create_topic(robot.publisher, robot.errorPoseTSID, 'sout', 'errorPoseTSID', robot=robot, data_type='vector')  
# create_topic(robot.publisher, robot.errorComTSID, 'sout', 'errorComTSID', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'com', 'com', robot=robot, data_type='vector') 
create_topic(robot.publisher, robot.com_traj_gen, 'x', 'com_traj_gen', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'q_des', 'q_des', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'tau_des', 'tau_des', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'u', 'u', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.base_estimator, 'q', 'base_q', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.base_estimator, 'v', 'base_v', robot=robot, data_type='vector')

create_topic(robot.publisher, robot.inv_dyn, 'left_foot_pos', 'LF_pos_inv_dyn', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.inv_dyn, 'right_foot_pos', 'RF_pos_inv_dyn', robot=robot, data_type='vector')

create_topic(robot.publisher, robot.device, 'motorcontrol', 'motorcontrol', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.device, 'robotVelocity', 'device_rV', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.device, 'robotState', 'device_rq', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.device, 'state', 'device_q', robot=robot, data_type='vector')
create_topic(robot.publisher, robot.device, 'velocity', 'device_v', robot=robot, data_type='vector') 
create_topic(robot.publisher, robot.device_filters.vel_filter, 'x_filtered', 'v_filt', robot=robot, data_type='vector')

# # --- TRACER
# robot.tracer = TracerRealTime("tau_tracer")
# robot.tracer.setBufferSize(80*(2**20))
# robot.tracer.open('/tmp','dg_','.dat')
# robot.device.after.addSignal('{0}.triger'.format(robot.tracer.name))

# addTrace(robot.tracer, robot.inv_dyn, 'tau_des')
# addTrace(robot.tracer, robot.inv_dyn, 'q_des')
# addTrace(robot.tracer, robot.inv_dyn, 'v_des')
# addTrace(robot.tracer, robot.inv_dyn, 'dv_des')
# addTrace(robot.tracer, robot.errorPoseTSID, 'sout')
# addTrace(robot.tracer, robot.errorComTSID, 'sout')
# addTrace(robot.tracer, robot.device, 'robotState')
# addTrace(robot.tracer, robot.device, 'motorcontrol')

# robot.tracer.start()