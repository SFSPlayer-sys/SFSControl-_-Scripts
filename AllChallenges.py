#完成所有挑战脚本 - 此脚本不依赖PySFS
import requests

planets = requests.get("http://127.0.0.1:27772/planets").json()

EXCLUDE = {"Sun", "Venus", "Mercury"}  

special_ids = [
    "Liftoff_0",
    "Reach_10km",
    "Reach_30km",
    "Reach_Downrange",
    "Reach_Orbit",
    "Orbit_High",
    "Moon_Orbit",
    "Moon_Tour",
    "Asteroid_Crash",
    "Mars_Tour",
    "Venus_One_Way",
    "Venus_Landing",
    "Mercury_One_Way",
    "Mercury_Landing"
]

land_ids = []

for p in planets:
    name = p.get("name") or p.get("codeName") or p.get("codename")
    
    if name and name not in EXCLUDE:
        land_ids.append(f"Land_{name}")

all_ids = special_ids + land_ids

for i in all_ids:
    requests.post(
        "http://127.0.0.1:27772/control",
        json={"method": "CompleteChallenge", "args": [i]}
    )
    print(f"Success: {i}")