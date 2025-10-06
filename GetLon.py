#获取经度脚本
from PySFS import SFSClient
sfs = SFSClient()
lon = sfs.values_api.rocket_longitude()
print(lon)