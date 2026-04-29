import json

from backend.Class.Army import Army
from backend.Class.Map import Map
from backend.Utils.class_by_name import GENERAL_REGISTRY
from backend.Utils.file_loader import load_mirrored_army_from_file, load_map_from_file

from backend.Class.Units.Castle import Castle
from backend.Class.Units.Crossbowman import Crossbowman
from backend.Class.Units.Elephant import Elephant
from backend.Class.Units.Knight import Knight
from backend.Class.Units.Monk import Monk
from backend.Class.Units.Pikeman import Pikeman

from backend.Class.Obstacles.Rocher import Rocher

#Tous les imports sont nécessaires !

# ====================================================================
#   ConvertJson — Données Python ↔ Chaine de caractères (format json)
#
#   Fonctionnalités clés :
#   - unit_to_dict(unit) -> dict():
#   - army_to_dict(army) -> dict():
#   - obstacle_to_dict(obstacle) -> dict():
#   - map_to_dict(map_obj) -> dict():
#   Transforme les données (unit, army, obstacle, map) en dictionnaires
#   lisible pour la conversion en json
#
#   - army_to_json(army) -> str():
#   - map_to_json(map_obj) -> str():
#   Converti les dictionnaires (army, map) en chaine de caractères json
#
#   - json_to_army(data_army) -> Army:
#   - json_to_map(data_map) -> Map:
#   Converti les chaines de caractères json en armée et map
# =====================================================================

# ==============================================
# Transformation des données en dictionnaire   =
# ==============================================

def unit_to_dict(unit):
    return {
        "id": unit.id,
        "type": unit.__class__.__name__,
        "hp": unit.hp,
        "position": unit.position,
        "cooldown": unit.cooldown,
        "last_attacker": unit.last_attacker_id,
        "last_attacked": unit.last_attacked_id,
    }

def army_to_dict(army):
    if army is None:
        return None
    return {
        "owner": army.owner if hasattr(army, "owner") else None,
        "general" : army.general.__class__.__name__ if army.general else None,
        "units": [unit_to_dict(u) for u in army.units],
    }

def obstacle_to_dict(obstacle):
    return {
        "type": obstacle.__class__.__name__,
        "size": obstacle.size,
        "position": obstacle.position,
    }

def map_to_dict(map_obj):
    return {
        "width": map_obj.width,
        "height": map_obj.height,
        "obstacles": [obstacle_to_dict(o) for o in map_obj.obstacles],
    }


# ========================
# Conversion de l'armée  =
# ========================

def army_to_json(army):
    data = json.dumps(army_to_dict(army))
    return data

def json_to_army(data_army):
    if data_army is None:
        return None
    if isinstance(data_army, str):
        army_data = json.loads(data_army)
    else:
        army_data = data_army
    
    owner = army_data.get("owner")
    army = Army()
    if hasattr(army, "owner"):
        army.owner = owner

    if army_data.get("general"):
        army.general = GENERAL_REGISTRY[army_data["general"].lower()]()
    
    for d in army_data["units"]:
        cls = globals().get(d["type"])
        if cls is None:
            continue
        unit = cls(
            position=tuple(d["position"]) if d["position"] else None,
        )
        # Restore the ID from network data
        if "id" in d:
            unit._Unit__id = d["id"]
            
        unit.hp = d["hp"]
        unit.cooldown = d["cooldown"]
        unit.last_attacker = d["last_attacker"]
        unit.last_attacked = d["last_attacked"]
        army.units.append(unit)
    return army


# ========================
# Conversion de la map   =
# ========================

def map_to_json(map_obj):
    data = json.dumps(map_to_dict(map_obj))
    return data


def json_to_map(data_map):
    if isinstance(data_map, str):
        map_data = json.loads(data_map)
    else:
        map_data = data_map
    map_obj = Map(
        width=map_data["width"],
        height=map_data["height"],
    )
    for o in map_data["obstacles"]:
        cls = globals().get(o["type"])
        if cls is None:
            continue
        obs = cls(
            position=tuple(o["position"] if o["position"] else None),
            size=o["size"] if o["size"] else None,
        )
        map_obj.obstacles.add(obs)
    return map_obj


"""def main():
    army1, army2 = load_mirrored_army_from_file("../../army/classique.army")
    map_obj = load_map_from_file("../../map/superflat.map")
    print(army1.units)
    print(map_obj.obstacles)

    #Conversion en string de type json
    data_army1 = army_to_json(army1)
    data_army2 = army_to_json(army2)
    print(data_army1)
    data_json_map = map_to_json(map_obj)

    #conversion en structure python
    army_end1 = json_to_army(data_army1)
    army_end2 = json_to_army(data_army2)
    map_end = json_to_map(data_json_map)

    #Vérifications
    print(army_end1.units)
    print(map_end.obstacles)
    
main()
"""