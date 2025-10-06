#经度瞄准脚本
import sys
import time
import math
from typing import Optional, Tuple
from pathlib import Path

sys.path.append(str(Path(__file__).parent / "PySFS"))
from PySFS import SFSClient


class PrecisionLanding:
    def __init__(self, host: str = "127.0.0.1", port: int = 27772):
        self.sfs = SFSClient(host=host, port=port)
        self.target_longitude = 0.0
        self.tolerance = 1.0
        self.max_iterations = 1000
        
    def normalize_longitude(self, longitude: float) -> float:
        return longitude % 360.0
    
    def calculate_longitude_difference(self, current: float, target: float) -> float:
        current = self.normalize_longitude(current)
        target = self.normalize_longitude(target)
        diff = target - current
        if diff > 180:
            diff -= 360
        elif diff < -180:
            diff += 360
        return diff
    
    def get_landing_longitude(self) -> float:
        # 获取火箭当前状态
        rocket_save = self.sfs.info_api.rocket_save()
        location = rocket_save["location"]
        position = location["position"]
        velocity = location["velocity"]
        
        # 获取位置和速度
        x = float(position["x"])
        y = float(position["y"])
        vx = float(velocity["x"])
        vy = float(velocity["y"])
        
        # 获取当前星球信息
        planet_data = self.sfs.info_api.planet()
        
        # 从当前星球数据获取正确的参数
        if planet_data and isinstance(planet_data, dict):
            planet_radius = float(planet_data["radius"])
            planet_gravity = float(planet_data["gravity"])
        else:
            raise Exception("无法获取当前星球信息")
        
        # 计算落点
        impact = self.sfs.calc_api.impact_point(
            rocket_x=x,
            rocket_y=y,
            vel_x=vx,
            vel_y=vy,
            planet_radius=planet_radius,
            gravity=planet_gravity
        )
        
        if impact:
            impact_x = impact["x"]
            impact_y = impact["y"]
            # 计算落点经度
            impact_angle = math.degrees(math.atan2(impact_y, impact_x))
            landing_longitude = self.normalize_longitude(impact_angle)
            return landing_longitude
        else:
            # 如果没有落点（逃逸轨道），返回当前经度
            current_longitude = self.sfs.values_api.rocket_longitude()
            return current_longitude
    
    def precision_landing(self, target_longitude: float, tolerance: float = 1.0, max_time: float = 300.0) -> bool:
        self.target_longitude = self.normalize_longitude(target_longitude)
        self.tolerance = tolerance
        
        print(f"目标经度: {self.target_longitude}")
        print(f"容差: {self.tolerance}")
        
        start_time = time.time()
        iteration = 0
        
        while iteration < self.max_iterations and (time.time() - start_time) < max_time:
            # 使用PySFS API获取当前状态
            current_longitude = self.sfs.values_api.rocket_longitude()
            altitude = self.sfs.values_api.rocket_altitude()
            angular_velocity = self.sfs.values_api.rocket_angular_velocity() or 0.0
            
            if current_longitude is None:
                time.sleep(0.05)
                continue
            
            # 获取精确落点预测
            landing_longitude = self.get_landing_longitude()
            
            # 计算落点与目标的差值
            landing_diff = self.calculate_longitude_difference(landing_longitude, self.target_longitude)
            
            print(f"[{iteration:3d}] 当前: {current_longitude:.1f} 落点: {landing_longitude:.1f} 目标: {self.target_longitude:.1f} 差值: {landing_diff:+.1f}")
            
            # 检查是否达到目标精度
            if abs(landing_diff) < self.tolerance:
                print("定点着陆目标达成")
                self.sfs.rotate("Default")
                self.sfs.set_throttle(0.0)
                self.sfs.set_main_engine_on(False)
                return True
            
            # 定点着陆逻辑：只进行逆行减速和微调
            # 只有在角速度稳定时才执行机动
            if abs(angular_velocity) < 3.0:
                # 定点着陆只使用逆行减速，通过调整偏移角度来微调落点
                base_angle = 180.0  # 基础逆行角度
                
                # 根据落点偏差计算微调偏移
                if abs(landing_diff) > self.tolerance:
                    # 计算偏移角度：落点偏差越大，偏移越大
                    offset_angle = landing_diff * 0.5  # 偏移系数可调整
                    offset_angle = max(-30.0, min(30.0, offset_angle))  # 限制偏移范围
                    
                    final_angle = base_angle + offset_angle
                    self.sfs.rotate("Prograde", final_angle)
                    
                    # 根据距离目标的远近调整推力（越近推力越小）
                    throttle = min(0.5, abs(landing_diff) / 20.0)
                    throttle = max(0.1, throttle)  # 最小推力0.1
                    
                    self.sfs.set_throttle(throttle)
                    self.sfs.set_main_engine_on(True)
                else:
                    # 在容差范围内，停止推进
                    self.sfs.set_throttle(0.0)
                    self.sfs.set_main_engine_on(False)
            else:
                # 角速度过大时暂停推进，等待稳定
                self.sfs.set_throttle(0.0)
                self.sfs.set_main_engine_on(False)
                print(f"等待稳定... 角速度: {angular_velocity:.1f}")
            
            iteration += 1
            time.sleep(0.5)
        
        # 超时处理
        final_longitude = self.sfs.values_api.rocket_longitude()
        if final_longitude:
            final_diff = self.calculate_longitude_difference(final_longitude, self.target_longitude)
            print(f"超时 最终偏差: {final_diff:+.1f}")
        
        # 清理：关闭所有控制
        print("超时")
        self.sfs.rotate("Default")  # 设置为默认模式
        self.sfs.set_throttle(0.0)
        self.sfs.set_main_engine_on(False)
        return False


def main():
    try:
        controller = PrecisionLanding()
        
        # 使用PySFS API获取当前状态
        current_longitude = controller.sfs.values_api.rocket_longitude()
        altitude = controller.sfs.values_api.rocket_altitude()
        
        if current_longitude is None:
            print("无法连接游戏")
            return
        
        print(f"当前经度: {current_longitude:.1f}")
        print(f"当前高度: {altitude/1000 if altitude else 0:.1f}km")
        
        target_longitude = float(input("目标经度 (0-360): "))
        tolerance = float(input("容差 (默认1.0): ") or "1.0")
        
        success = controller.precision_landing(
            target_longitude=target_longitude,
            tolerance=tolerance,
            max_time=300.0
        )
        
        if success:
            print("定点着陆完成")
        else:
            print("定点着陆失败")
            
    except KeyboardInterrupt:
        print("用户中断")
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    main()