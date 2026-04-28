import json
from backend.Class.Army import Army
from backend.Class.Map import Map
from backend.Utils.class_by_name import GENERAL_REGISTRY
from backend.Class.Units.Knight import Knight
from backend.Class.Units.Pikeman import Pikeman
from backend.Class.Units.Crossbowman import Crossbowman
from backend.Class.Units.Castle import Castle
from backend.Class.Units.Elephant import Elephant
from backend.Class.Units.Monk import Monk
from backend.Class.Obstacles.Rocher import Rocher

def unit_to_dict(unit):
    return {
        "t": unit.__class__.__name__[0:2], # Tiny type
        "h": int(unit.hp),
        "p": [round(unit.position[0], 1), round(unit.position[1], 1)] if unit.position else None,
        "i": unit.id[0:8] # Tiny ID
    }

def army_to_dict(army):
    if army is None: return None
    return {
        "g": army.general.__class__.__name__ if army.general else None,
        "u": [unit_to_dict(u) for u in army.living_units()],
    }

def json_to_army(data):
    if data is None: return None
    army_data = json.loads(data) if isinstance(data, str) else data
    army = Army()
    
    # Map tiny types back to full names
    type_map = {"Kn": "Knight", "Pi": "Pikeman", "Cr": "Crossbowman", "Ca": "Castle", "El": "Elephant", "Mo": "Monk"}
    
    gen_name = army_data.get("g") or army_data.get("general")
    if gen_name:
        army.general = GENERAL_REGISTRY.get(gen_name.lower(), GENERAL_REGISTRY["majordaft"])()
    
    units_list = army_data.get("u") or army_data.get("units", [])
    for d in units_list:
        u_type = d.get("t") or d.get("type")
        if u_type in type_map: u_type = type_map[u_type]
        
        cls = globals().get(u_type)
        if not cls: continue
        
        pos = d.get("p") or d.get("position")
        unit = cls(position=tuple(pos) if pos else None)
        unit.hp = d.get("h") or d.get("hp", unit.hp)
        u_id = d.get("i") or d.get("id")
        if u_id: unit._Unit__id = u_id
        army.units.append(unit)
    return army

# Keep original functions for backward compatibility with saves if needed
def army_to_json(army): return json.dumps(army_to_dict(army))
def obstacle_to_dict(obs): return {"t": obs.__class__.__name__, "s": obs.size, "p": obs.position}
def map_to_dict(m): return {"w": m.width, "h": m.height, "o": [obstacle_to_dict(o) for o in m.obstacles]}
def map_to_json(m): return json.dumps(map_to_dict(m))
