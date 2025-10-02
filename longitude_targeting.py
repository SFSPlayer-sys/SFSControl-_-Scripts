#经度瞄准脚本
import sys
import time
import math
from typing import Optional, Tuple
from pathlib import Path

sys.path.append(str(Path(__file__).parent / "PySFS"))
from PySFS import SFSClient


class LongitudeTargeting:
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
        """使用PySFS的impact_point API计算落点经度"""
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
    
    def target_longitude_simple(self, target_longitude: float, tolerance: float = 1.0, max_time: float = 300.0) -> bool:
        self.target_longitude = self.normalize_longitude(target_longitude)
        self.tolerance = tolerance
        
        print(f"目标经度: {self.target_longitude}")
        print(f"容差: {self.tolerance}")
        
        start_time = time.time()
        iteration = 0
        offset = 0.0
        
        # 第一阶段：速度反方向减速
        print("阶段1: 逆行减速")
        self.sfs.rotate("Prograde", 180.0)  # 顺行+180°偏移 = 逆行
        self.sfs.set_main_engine_on(True)
        self.sfs.set_throttle(1.0)
        time.sleep(0.5)
        self.sfs.set_throttle(0.0)
        self.sfs.set_main_engine_on(False)
        
        while iteration < self.max_iterations and (time.time() - start_time) < max_time:
            # 使用PySFS API获取当前状态
            current_longitude = self.sfs.values_api.rocket_longitude()
            altitude = self.sfs.values_api.rocket_altitude()
            
            if current_longitude is None:
                time.sleep(0.5)
                continue
            
            # 获取精确落点预测
            landing_longitude = self.get_landing_longitude()
            
            # 计算落点与目标的差值
            landing_diff = self.calculate_longitude_difference(landing_longitude, self.target_longitude)
            
            print(f"[{iteration:3d}] 当前: {current_longitude:.1f} 落点: {landing_longitude:.1f} 目标: {self.target_longitude:.1f} 差值: {landing_diff:+.1f}")
            
            # 检查是否达到目标
            if abs(landing_diff) < self.tolerance:
                print("成功到达目标")
                self.sfs.rotate("Default")  # 设置为默认模式
                self.sfs.set_throttle(0.0)
                self.sfs.set_main_engine_on(False)
                return True
            
            # 动态调整偏移策略 - 持续使用逆行+偏移
            if abs(landing_diff) > self.tolerance:
                if landing_diff > 0:
                    # 落点太东，需要向西偏移
                    offset = min(abs(landing_diff) * 2.0, 90.0)  # 向西偏移
                else:
                    # 落点太西，需要向东偏移
                    offset = -min(abs(landing_diff) * 2.0, 90.0)  # 向东偏移
                
                # 执行控制 - 持续使用逆行+动态偏移
                self.sfs.rotate("Prograde", 180.0 + offset)  # 逆行 + 偏移
                self.sfs.set_main_engine_on(True)
                
                # 根据差值调整推力
                if abs(landing_diff) > 20:
                    self.sfs.set_throttle(0.5)
                elif abs(landing_diff) > 5:
                    self.sfs.set_throttle(0.3)
                else:
                    self.sfs.set_throttle(0.1)
            else:
                # 如果在容差范围内，关闭发动机但保持SAS
                self.sfs.set_throttle(0.0)
                self.sfs.set_main_engine_on(False)
            
            iteration += 1
            time.sleep(1)
        
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
        controller = LongitudeTargeting()
        
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
        
        success = controller.target_longitude_simple(
            target_longitude=target_longitude,
            tolerance=tolerance,
            max_time=300.0
        )
        
        if success:
            print("任务完成")
        else:
            print("任务失败")
            
    except KeyboardInterrupt:
        print("用户中断")
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    main()