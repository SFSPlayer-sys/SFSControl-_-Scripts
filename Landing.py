import sys, os, time, math
from typing import Optional
import keyboard
sys.path.append(os.path.join(os.path.dirname(__file__), 'PySFS'))
from PySFS import SFSClient

sfs = SFSClient()

#目标发射场
T_LON = 89.93566086452715
#容差（实际上脚本会尽可能的精准）
TOL = 0.0001
#单次推进时间
BURST_DURATION = 0.25
#大气高度
ATMOSPHERIC_ALT = 30000
#开伞高度
PARACHUTE_OPEN_HEIGHT = 2500
#角度差计算
def angle_diff(a: float, b: float) -> float:
    diff = abs(a - b)
    return min(diff, 360 - diff)

def get_direction(land_lon: float, target_lon: float) -> tuple[str, float]:
    diff = land_lon - target_lon
    if diff > 180:
        diff -= 360
    elif diff < -180:
        diff += 360
    
    if diff > 0:
        direction = "left"
    else:
        direction = "right"

    return direction, abs(diff)

def landing():
    while True:
        land_lon = sfs.values_api.other_landing_point_angle()
        alt = sfs.values_api.rocket_altitude()
        #检查是否去轨
        if land_lon is None:
            sfs.rotate("Prograde", 180.0)
            sfs.set_throttle(1.0)
            sfs.set_main_engine_on(True)
            time.sleep(0.1)
            continue
        land_lon = float(land_lon)

        error = angle_diff(land_lon, T_LON)

        direction, angle_diff_value = get_direction(land_lon, T_LON)
        
        sfs.rotate("Prograde", 180.0)

        if error <= 0.5:
            sfs.set_throttle(0.0)
            sfs.set_main_engine_on(False)
            # 使用RCS进行微调 - 根据火箭朝向角度选择最优RCS方向
            # 获取火箭当前朝向角度
            rocket_rotation = sfs.values_api.rocket_rotation()
            theta = (rocket_rotation-90) % 360
            
            # RCS方向表：以90°为中点，周围45°使用相同方向
            if direction == "right":
                # 需要往左推
                if 45 <= theta < 135:  # 90°±45°区域
                    rcs_direction = "left"  # left往左
                elif 135 <= theta < 225:  # 180°±45°区域
                    rcs_direction = "right"  # right往左
                elif 225 <= theta < 315:  # 270°±45°区域
                    rcs_direction = "down"  # down往左
                else:  # 0°±45°区域 (315°-45°)
                    rcs_direction = "up"  # up往左
            else:  # left
                # 需要往右推
                if 45 <= theta < 135:  # 90°±45°区域
                    rcs_direction = "right"  # right往右
                elif 135 <= theta < 225:  # 180°±45°区域
                    rcs_direction = "left"  # left往右
                elif 225 <= theta < 315:  # 270°±45°区域
                    rcs_direction = "up"  # up往右
                else:  # 0°±45°区域 (315°-45°)
                    rcs_direction = "down"  # down往右
            
            sfs.rcs_thrust(rcs_direction, 0.05)
            print(f"RCS方向: {rcs_direction} 误差: {error:.4f}°")
        else:
            max_error = 20.0 
            dynamic_throttle = max(0.0, min(1.0, error / max_error))
            
            if alt > ATMOSPHERIC_ALT:
                if direction == "left":
                    sfs.rotate("Surface", 85.0)
                else:  # right
                    sfs.rotate("Surface", 265.0)
            sfs.set_throttle(dynamic_throttle)
            sfs.set_main_engine_on(True)
            time.sleep(BURST_DURATION)
            sfs.set_throttle(0.0)
            sfs.set_main_engine_on(False)
        if alt <= ATMOSPHERIC_ALT:
            # 高度低于30000m时，进入微调
            sfs.set_rcs(False)
            break

    # 微调循环
    while True:
        alt = sfs.values_api.rocket_altitude() #火箭相对于地形的高度
        
        # 计算径向速度用于判断是否着陆
        vx = sfs.values_api.rocket_velocity_x()
        vy = sfs.values_api.rocket_velocity_y()
        lon = sfs.values_api.rocket_longitude()
        radial_velocity = vx * math.cos(math.radians(lon)) + vy * math.sin(math.radians(lon))
        
        # 基于径向速度判断是否着陆完成
        if radial_velocity >= -3:
            print("着陆完成")
            sfs.set_throttle(0.0)
            sfs.set_main_engine_on(False)
            break
        #if alt <= PARACHUTE_OPEN_HEIGHT:
        #    sfs.stage()    
        #    sfs.remove_stage(0)

        land_lon = sfs.values_api.other_landing_point_angle()
        if land_lon is None:
            continue
        land_lon = float(land_lon)
        
        error = angle_diff(land_lon, T_LON)
        direction, angle_diff_value = get_direction(land_lon, T_LON)
        
        # 计算点火高度
        m = sfs.values_api.other_mass()*1000 #kg
        F = sfs.values_api.other_max_thrust()*9806 #N
        g = sfs.values_api.other_gravity_magnitude()
        H = (radial_velocity**2 * m) / (2 * (F - m * g)) + 38
        
        if alt < H:
            sfs.set_throttle(1.0)
            sfs.set_main_engine_on(True)
            sfs.rotate("Prograde", 180.0)
            if error > 0.0005:  # 有误差时进行RCS调整
                if direction == "right":
                    sfs.rcs_thrust("left", 0.15)
                else:
                    sfs.rcs_thrust("right", 0.15)
        else:
            sfs.set_throttle(0.0)
            sfs.set_main_engine_on(False)

        # RCS微调
        if error <= 0.25 and error >= 0.0005:
            sfs.rotate("Prograde", 180.0)  
            if direction == "right":
                sfs.rcs_thrust("left", 0.25)
            else:
                sfs.rcs_thrust("right", 0.25)
        
        # 高空位置调整
        elif alt >= ATMOSPHERIC_ALT:
            max_error = 5.0
            dynamic_throttle = max(0.0, min(1.0, error / max_error))
            if direction == "left":
                sfs.rotate("Surface", 90.0) 
            else:
                sfs.rotate("Surface", 270.0)
            sfs.set_throttle(dynamic_throttle)
            sfs.set_main_engine_on(True)
        
        # 短暂延迟避免过度频繁的控制
        time.sleep(0.1)
        
if __name__ == "__main__":
    print("等待按下L键开始着陆...")
    keyboard.wait('l')
    print("开始着陆")
    landing()