import requests
import math
import time
import threading
from typing import Dict, List, Optional

API_URL = 'http://127.0.0.1:27772/'

# 配置参数
PHASE2_ALTITUDE = 1750.0#着陆阶段高度
SLEEP_INTERVAL = 0.01#检测间隔
MIN_THROTTLE = 0.2
STAGE_ALTITUDE = 1750.0#分级高度
WAIT_PHASE_SPEED_THRESHOLD = 200.0 #等待进入着陆阶段时减速阈值
MIN_ENGINE_SPEED = 10#安全速度

#要控制的火箭ID列表（名称）
#ROCKET_IDS = [] #None表示控制当前火箭
#ROCKET_IDS = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"]
ROCKET_IDS = ['A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8', 'A9', 'A10', 'A11', 'A12', 'A13', 'A14', 'A15', 'A16']

# 火箭状态管理
class RocketState:
    def __init__(self, rocket_name: str):
        self.rocket_name = rocket_name 
        self.staged = False
        self.landed_time = 0
        self.last_time = time.time()
        self.time_decel_done = False
        self.phase = "decel"  # decel, wait, landing, completed
        self.planet_name = None
        self.safe_speed = 5.0
        self.radius = 0
        self.gravity = 0


def get_rocket_info(rocket_id: Optional[str] = None):
    params = {}
    if rocket_id:
        params['rocketIdOrName'] = rocket_id
    resp = requests.get(API_URL + 'rocket', params=params, timeout=5)
    return resp.json()

def get_rocketsim_info(rocket_id: Optional[str] = None):
    params = {}
    if rocket_id:
        params['rocketIdOrName'] = rocket_id
    resp = requests.get(API_URL + 'rocket_sim', params=params, timeout=5)
    return resp.json()

def get_planet_info(planet_name):
    resp = requests.get(API_URL + 'planet', params={'codename': planet_name}, timeout=5)
    return resp.json()

def get_altitude(rocket_id: Optional[str] = None):
    sim = get_rocketsim_info(rocket_id)
    return sim['height']

def get_velocity(rocket_id: Optional[str] = None):
    rocket = get_rocket_info(rocket_id)
    v = rocket['location']['velocity']
    vx = v['x']
    vy = v['y']
    return vx, vy

def rotate_to_retrograde(rocket_id: Optional[str] = None):
    data = {"method": "Rotate", "args": ["Prograde", 180.0, rocket_id]}  
    requests.post(API_URL + 'control', json=data)

def rotate_to_surface(rocket_id: Optional[str] = None):
    data = {"method": "Rotate", "args": ["Surface", 0.0, rocket_id]}  
    requests.post(API_URL + 'control', json=data)

def is_rotating(rocket_id: Optional[str] = None):
    try:
        rocket_data = get_rocket_info(rocket_id)
        angular_velocity = rocket_data.get('angularVelocity', 0)
        return abs(angular_velocity) > 5  
    except:
        return False

def set_throttle(value, rocket_id: Optional[str] = None):
    data = {"method": "SetThrottle", "args": [value, rocket_id]}
    requests.post(API_URL + 'control', json=data)

def main_engine_on(on=True, rocket_id: Optional[str] = None):
    data = {"method": "SetMainEngineOn", "args": [on, rocket_id]}
    requests.post(API_URL + 'control', json=data)

def stage(rocket_id: Optional[str] = None):
    data = {"method": "Stage", "args": [rocket_id]}
    requests.post(API_URL + 'control', json=data)

def get_current_planet_name(rocket_id: Optional[str] = None):
    rocket = get_rocket_info(rocket_id)
    return rocket['location']['address']

def calc_safe_speed(gravity, radius):
    return 5.0

def get_periapsis(rocket_id: Optional[str] = None):
    sim = get_rocketsim_info(rocket_id)
    orbit = sim.get('orbit', None)
    if orbit and 'periapsis' in orbit and orbit['periapsis'] is not None:
        return orbit['periapsis']
    return None

def time_warp_plus():
    #多火箭尽量不要用这个函数
    #data = {"method": "TimewarpPlus", "args": []}
    #requests.post(API_URL + 'control', json=data, timeout=2)

def time_warp_minus():
    #多火箭尽量不要用这个函数
    #data = {"method": "TimewarpMinus", "args": []}
    #requests.post(API_URL + 'control', json=data, timeout=2)

def get_rocket_list():
    """获取所有火箭列表"""
    resp = requests.get(API_URL + 'rocket', timeout=5)
    data = resp.json()
    return data

def run_autoland_single_rocket(rocket_state: RocketState):
    #单个火箭的着陆流程
    rocket_name = rocket_state.rocket_name
    
    try:
        # 初始化火箭状态
        if rocket_state.planet_name is None:
            rocket_state.planet_name = get_current_planet_name(rocket_name)
            planet_info = get_planet_info(rocket_state.planet_name)
            rocket_state.gravity = planet_info['gravity']
            rocket_state.radius = planet_info['radius']
            rocket_state.safe_speed = calc_safe_speed(rocket_state.gravity, rocket_state.radius)
            print(f"火箭 {rocket_name}: 星球 {rocket_state.planet_name} 重力: {rocket_state.gravity} 半径: {rocket_state.radius}")
        
        #根据阶段执行不同的操作
        if rocket_state.phase == "decel":
            rocket_state.phase = run_decel_phase(rocket_state)
        elif rocket_state.phase == "wait":
            rocket_state.phase = run_wait_phase(rocket_state)
        elif rocket_state.phase == "landing":
            rocket_state.phase = run_landing_phase(rocket_state)
        elif rocket_state.phase == "completed":
            return "completed"
            
    except Exception as e:
        print(f"火箭 {rocket_name} 处理错误: {e}")
        return "error"
    
    return rocket_state.phase

def run_decel_phase(rocket_state: RocketState):
    """减速阶段"""
    rocket_name = rocket_state.rocket_name
    
    altitude = get_altitude(rocket_name)
    vx, vy = get_velocity(rocket_name)
    speed = math.sqrt(vx**2 + vy**2)
    periapsis = get_periapsis(rocket_name)
    
    # 设置角度为速度反方向
    rotate_to_retrograde(rocket_name)
    
    if periapsis is not None:
        if periapsis < rocket_state.radius:
            main_engine_on(False, rocket_name)
            return "wait"
        if speed > rocket_state.safe_speed:
            set_throttle(0.5, rocket_name)  
            main_engine_on(True, rocket_name)
        else:
            main_engine_on(False, rocket_name)
    else:
        print(f"火箭 {rocket_name}: 等待进入着陆阶段...")
        main_engine_on(False, rocket_name)
        return "wait"
    
    return "decel"

def run_wait_phase(rocket_state: RocketState):
    """等待着陆阶段"""
    rocket_name = rocket_state.rocket_name
    
    altitude = get_altitude(rocket_name)
    vx, vy = get_velocity(rocket_name)
    speed = math.sqrt(vx**2 + vy**2)
    rotate_to_retrograde(rocket_name)

    if altitude <= 10000:
        if speed > WAIT_PHASE_SPEED_THRESHOLD:
            set_throttle(0.5, rocket_name)  # 最大节流阀0.5
            main_engine_on(True, rocket_name)
        else:
            main_engine_on(False, rocket_name)
    
    if altitude <= PHASE2_ALTITUDE:
        print(f"火箭 {rocket_name}: 进入着陆阶段")
        return "landing"
    
    return "wait"

def run_landing_phase(rocket_state: RocketState):
    """着陆阶段"""
    rocket_name = rocket_state.rocket_name
    
    altitude = get_altitude(rocket_name)
    vx, vy = get_velocity(rocket_name)
    speed = math.sqrt(vx**2 + vy**2)
    
    # 着陆判定：连续5秒速度小于1m/s
    now = time.time()
    if speed < 1.0:
        rocket_state.landed_time += now - rocket_state.last_time
        if rocket_state.landed_time >= 5.0:
            print(f"火箭 {rocket_name}: 已安全着陆在{rocket_state.planet_name}表面")
            set_throttle(0, rocket_name)
            main_engine_on(False, rocket_name)
            return "completed"
    else:
        rocket_state.landed_time = 0
    rocket_state.last_time = now
    
    # 面向速度反方向
    rotate_to_retrograde(rocket_name)
    
    # 检查是否正在旋转，如果旋转则关闭发动机
    if is_rotating(rocket_name):
        set_throttle(0, rocket_name)
        main_engine_on(False, rocket_name)
    else:
        # 只有在不旋转时才点火
        ratio = min(1.0, max(0.0, speed / rocket_state.safe_speed))
        throttle = MIN_THROTTLE + (1.0 - MIN_THROTTLE) * (ratio ** 2)
        throttle = min(throttle, 0.5)
        if speed < MIN_ENGINE_SPEED:
            set_throttle(0, rocket_name)
            main_engine_on(False, rocket_name)
        else:
            set_throttle(throttle, rocket_name)
            main_engine_on(True, rocket_name)
    
    # 展开着陆架
    if altitude < STAGE_ALTITUDE and not rocket_state.staged:
        print(f"火箭 {rocket_name}: 展开着陆架")
        stage(rocket_name)
        rocket_state.staged = True
    
    return "landing"

def run_autoland():
    print("自动着陆脚本启动")
    
    # 创建火箭状态字典
    rocket_states: Dict[str, RocketState] = {}
    
    try:
        # 如果指定了火箭ID数组，为每个火箭单独请求数据
        if ROCKET_IDS:
            print(f"指定控制火箭ID: {ROCKET_IDS}")
            for rocket_id in ROCKET_IDS:
                if rocket_id is None:
                    # None表示控制当前火箭（玩家控制的火箭）
                    try:
                        current_rocket_data = get_rocket_info()  # 不传参数获取当前火箭
                        if current_rocket_data and 'rocketName' in current_rocket_data:
                            rocket_name = current_rocket_data['rocketName']
                            rocket_states[rocket_name] = RocketState(rocket_name)
                            print(f"添加当前火箭: {rocket_name}")
                        else:
                            print("警告: 未找到当前控制的火箭")
                    except Exception as e:
                        print(f"获取当前火箭失败: {e}")
                else:
                    # 指定具体的火箭ID/名称
                    rocket_id_str = str(rocket_id)
                    try:
                        # 为每个火箭单独请求数据
                        rocket_data = get_rocket_info(rocket_id_str)
                        if rocket_data and 'rocketName' in rocket_data:
                            rocket_name = rocket_data['rocketName']
                            rocket_states[rocket_name] = RocketState(rocket_name)
                            print(f"添加指定火箭: {rocket_name} (请求ID: {rocket_id_str})")
                        else:
                            print(f"警告: 未找到火箭 {rocket_id_str}")
                    except Exception as e:
                        print(f"获取火箭 {rocket_id_str} 失败: {e}")
        else:
            # 控制所有火箭 - 这里需要先获取火箭列表
            print("控制所有可用火箭")
            try:
                rockets_data = get_rocket_list()
                if isinstance(rockets_data, dict) and 'rocketName' in rockets_data:
                    # 单个火箭
                    rocket_name = rockets_data['rocketName']
                    rocket_states[rocket_name] = RocketState(rocket_name)
                    print(f"发现火箭: {rocket_name}")
                elif isinstance(rockets_data, list):
                    # 火箭列表
                    for rocket_data in rockets_data:
                        if isinstance(rocket_data, dict) and 'rocketName' in rocket_data:
                            rocket_name = rocket_data['rocketName']
                            rocket_states[rocket_name] = RocketState(rocket_name)
                            print(f"发现火箭: {rocket_name}")
            except Exception as e:
                print(f"获取火箭列表失败: {e}")
        
        if not rocket_states:
            print("没有可控制的火箭")
            return
        
        print(f"开始控制 {len(rocket_states)} 个火箭的自动着陆")
        
        # 减速阶段完成后开始时间加速*6
        print("减速阶段完成，开始时间加速6次...")
        for _ in range(6):
            time_warp_plus()
            time.sleep(0.1)
        
        # 主循环
        while True:
            active_rockets = []
            
            # 处理每个火箭
            for rocket_name, rocket_state in rocket_states.items():
                if rocket_state.phase not in ["completed", "error"]:
                    result = run_autoland_single_rocket(rocket_state)
                    if result not in ["completed", "error"]:
                        active_rockets.append(rocket_name)
            
            # 如果所有火箭都完成了，退出
            if not active_rockets:
                print("所有火箭着陆完成！")
                break
            
            time.sleep(SLEEP_INTERVAL)
            
    except Exception as e:
        print(f"多火箭控制错误: {e}")

if __name__ == "__main__":
    print("自动着陆脚本启动")
    #time.sleep(10)
    run_autoland()