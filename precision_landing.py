#定点着陆脚本
import sys
import time
import math
from typing import Optional, Tuple, Dict, Any
from pathlib import Path

sys.path.append(str(Path(__file__).parent / "PySFS"))
from PySFS import SFSClient


class PrecisionLanding:
    def __init__(self, host: str = "127.0.0.1", port: int = 27772):
        self.sfs = SFSClient(host=host, port=port)
        
        # 经度瞄准参数
        self.target_longitude = 0.0#默认目标经度
        self.longitude_tolerance = 1.0#默认经度容差
        
        # 着陆参数
        self.landing_altitude = 5000.0# 着陆高度
        self.stage_altitude = 1750.0# 展开着陆架高度
        self.min_throttle = 0.2# 最小节流阀
        self.safe_speed = 10.0# 安全速度 #没用
        self.min_engine_speed = 10.0# 最小发动机速度
        self.final_approach_altitude = 500.0  # 最终进近高度
        
        # 状态管理
        self.phase = "longitude_targeting"  # longitude_targeting, landing, completed
        self.staged = False
        self.landed_time = 0.0
        self.last_time = time.time()
        
    def normalize_longitude(self, longitude: float) -> float:
        """标准化经度到 [0, 360) 范围"""
        return longitude % 360.0
    
    def calculate_longitude_difference(self, current: float, target: float) -> float:
        """计算经度差，考虑最短路径"""
        current = self.normalize_longitude(current)
        target = self.normalize_longitude(target)
        diff = target - current
        if diff > 180:
            diff -= 360
        elif diff < -180:
            diff += 360
        return diff
    
    def get_rocket_status(self) -> Dict[str, Any]:
        """获取火箭完整状态信息"""
        try:
            longitude = self.sfs.values_api.rocket_longitude()
            altitude = self.sfs.values_api.rocket_altitude()
            velocity_info = self.sfs.calc_api.rocket_velocity_info()
            orbit_info = self.sfs.values_api.rocket_orbit()
            
            return {
                "longitude": longitude,
                "altitude": altitude,
                "velocity_magnitude": velocity_info.get("magnitude") if velocity_info else 0,
                "velocity_x": velocity_info.get("vx") if velocity_info else 0,
                "velocity_y": velocity_info.get("vy") if velocity_info else 0,
                "orbit": orbit_info,
                "angular_velocity": self.sfs.values_api.rocket_angular_velocity() or 0
            }
        except Exception as e:
            print(f"获取火箭状态失败: {e}")
            return {}
    
    def get_landing_longitude(self) -> Optional[float]:
        """使用PySFS的impact_point API计算落点经度"""
        try:
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
            if planet_data and isinstance(planet_data, dict):
                planet_radius = float(planet_data["radius"])
                planet_gravity = float(planet_data["gravity"])
            else:
                return None
            
            # 计算落点
            impact = self.sfs.calc_api.impact_point(
                rocket_x=x, rocket_y=y,
                vel_x=vx, vel_y=vy,
                planet_radius=planet_radius,
                gravity=planet_gravity
            )
            
            if impact:
                impact_x = impact["x"]
                impact_y = impact["y"]
                # 计算落点经度
                impact_angle = math.degrees(math.atan2(impact_y, impact_x))
                return self.normalize_longitude(impact_angle)
            else:
                # 如果没有落点（逃逸轨道），返回当前经度
                return self.sfs.values_api.rocket_longitude()
                
        except Exception as e:
            print(f"落点计算失败: {e}")
            return self.sfs.values_api.rocket_longitude()
    
    def longitude_targeting_phase(self, status: Dict[str, Any]) -> str:
        """经度瞄准阶段"""
        current_longitude = status.get("longitude")
        altitude = status.get("altitude", 0)
        angular_velocity = status.get("angular_velocity", 0)
        
        if current_longitude is None:
            return "longitude_targeting"
        
        # 获取预测落点
        landing_longitude = self.get_landing_longitude()
        if landing_longitude is None:
            landing_longitude = current_longitude
        
        # 计算落点与目标的差值
        landing_diff = self.calculate_longitude_difference(landing_longitude, self.target_longitude)
        
        
        # 检查是否达到目标精度且高度足够低
        if abs(landing_diff) < self.longitude_tolerance:
            if altitude <= self.landing_altitude:
                print("经度瞄准完成且到达着陆高度，进入着陆阶段")
                return "landing"
            else:
                # 关闭发动机，等待下降
                self.sfs.set_main_engine_on(False)
                self.sfs.set_throttle(0.0)
                return "longitude_targeting"

        # 根据落点差值选择控制方向
        #if landing_diff > 0:
            # 差值为正，逆行
            #self.sfs.rotate("Prograde", 0.0)
        #else:
            # 差值为负，顺行
        self.sfs.rotate("Prograde", 180.0)
        
        # 检查角速度，只有稳定时才开发动机
        if abs(angular_velocity) > 3:
            self.sfs.set_main_engine_on(False)
            self.sfs.set_throttle(0.0)
        else:
            self.sfs.set_main_engine_on(True)
            # 越接近目标，节流阀越低
            abs_diff = abs(landing_diff)
            if abs_diff > 20:
                throttle = 0.5
            elif abs_diff > 10:
                throttle = 0.3
            elif abs_diff > 5:
                throttle = 0.2
            elif abs_diff > 2:
                throttle = 0.1
            else:
                throttle = 0.05
            
            self.sfs.set_throttle(throttle)
        
        return "longitude_targeting"
    
    
    def landing_phase(self, status: Dict[str, Any]) -> str:
        """精确着陆阶段 - 分阶段减速"""
        altitude = status.get("altitude", 0)
        velocity_mag = status.get("velocity_magnitude", 0)
        angular_velocity = status.get("angular_velocity", 0)
        
        # 高度小于5m时取消SAS控制
        if altitude < 5:
            self.sfs.rotate("Default")
        else:
            # 面向逆行方向
            self.sfs.rotate("Prograde", 180.0)
        
        # 着陆判定：连续3次速度为0
        now = time.time()
        if velocity_mag == 0.0:
            self.landed_time += 1
            if self.landed_time >= 3:
                print("精确着陆成功！")
                self.sfs.set_throttle(0.0)
                self.sfs.set_main_engine_on(False)
                self.sfs.rotate("Default")
                return "completed"
        else:
            self.landed_time = 0
        self.last_time = now
        
        # 展开着陆架
        if altitude < self.stage_altitude and not self.staged:
            print("展开着陆架")
            self.sfs.stage()
            self.staged = True
        
        # 检查是否正在旋转，如果旋转则关闭发动机
        if abs(angular_velocity) > 5:
            self.sfs.set_throttle(0.0)
            self.sfs.set_main_engine_on(False)
            return "landing"
        
        # 分阶段减速控制
        if altitude > self.final_approach_altitude:
            # 第一阶段：高空减速到最小发动机速度
            if velocity_mag > self.min_engine_speed:
                ratio = min(1.0, max(0.0, (velocity_mag - self.min_engine_speed) / 50.0))
                throttle = self.min_throttle + (0.8 - self.min_throttle) * ratio
                self.sfs.set_throttle(throttle)
                self.sfs.set_main_engine_on(True)
            else:
                self.sfs.set_throttle(0.0)
                self.sfs.set_main_engine_on(False)
        else:
            # 第二阶段：低空最终减速到最小发动机速度
            if velocity_mag > self.min_engine_speed:
                ratio = min(1.0, max(0.0, (velocity_mag - self.min_engine_speed) / 20.0))
                throttle = self.min_throttle + (0.6 - self.min_throttle) * ratio
                self.sfs.set_throttle(throttle)
                self.sfs.set_main_engine_on(True)
            else:
                if velocity_mag < self.safe_speed:  # 极低速度时完全关闭
                    self.sfs.set_throttle(0.0)
                    self.sfs.set_main_engine_on(False)
                else:
                    # 保持极小推力防止坠落
                    self.sfs.set_throttle(0.0)
                    self.sfs.set_main_engine_on(True)
        
        return "landing"
    
    def precision_land(self, target_longitude: float, longitude_tolerance: float = 2.0, max_time: float = 600.0) -> bool:
        """执行精确定点着陆"""
        self.target_longitude = self.normalize_longitude(target_longitude)
        self.longitude_tolerance = longitude_tolerance
        
        print(f"开始精确定点着陆 - 目标: {self.target_longitude:.1f}° 容差: {self.longitude_tolerance:.1f}°")
        
        start_time = time.time()
        iteration = 0
        
        while iteration < 10000 and (time.time() - start_time) < max_time:
            # 获取火箭状态
            status = self.get_rocket_status()
            if not status:
                time.sleep(0.5)
                continue
            
            # 根据当前阶段执行相应操作
            if self.phase == "longitude_targeting":
                self.phase = self.longitude_targeting_phase(status)
            elif self.phase == "landing":
                self.phase = self.landing_phase(status)
            elif self.phase == "completed":
                return True
            
            iteration += 1
            time.sleep(0.5)
        
        # 超时处理
        print("任务超时")
        self.sfs.rotate("Default")
        self.sfs.set_throttle(0.0)
        self.sfs.set_main_engine_on(False)
        return False


def main():
    """主函数"""
    try:
        controller = PrecisionLanding()
        
        # 获取当前状态
        current_longitude = controller.sfs.values_api.rocket_longitude()
        altitude = controller.sfs.values_api.rocket_altitude()
        
        print(f"当前经度: {current_longitude:.1f}°")
        print(f"当前高度: {altitude/1000 if altitude else 0:.1f}km")
        
        # 输入目标参数
        target_longitude = float(input("目标经度 (0-360): "))
        longitude_tolerance = float(input("经度容差 (默认2.0): ") or "2.0")
        
        # 开始精确着陆
        success = controller.precision_land(
            target_longitude=target_longitude,
            longitude_tolerance=longitude_tolerance,
            max_time=600.0
        )
        
        if success:
            print("精确定点着陆成功！")
        else:
            print("精确定点着陆失败")
            
    except KeyboardInterrupt:
        print("用户中断")
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    main()