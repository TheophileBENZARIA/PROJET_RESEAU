import random
from math import cos, sin
from typing import Any, Dict

from backend.Class.Action import Action
from backend.Class.Map import Map
from backend.Class.Units.Castle import Castle
from backend.Class.Units.Elephant import Elephant
from backend.Class.Units.Monk import Monk
from backend.Class.Units.Unit import Unit


class Army:
    def __init__(self, owner=None):
        self.owner = owner
        self.gameMode = None
        self.__general = None
        self.units = []

    @property
    def general(self):
        return self.__general

    @general.setter
    def general(self, value):
        if value is not None:
            value.army = self
        self.__general = value

    def add_unit(self, unit: Unit):
        unit.army = self
        self.units.append(unit)

    def remove_unit(self, unit):
        for i in range(len(self.units)):
            if self.units[i] == unit:
                del self.units[i]
                break

    def isEmpty(self):
        return len(self.living_units()) <= 0

    def living_units_id(self):
        return [u.id for u in self.units if u.is_alive()]

    def get_unit_by_id(self, id):
        for u in self.units:
            if u.id == id:
                return u
        return None

    def living_units(self):
        return [u for u in self.units if u.is_alive()]

    def moving_units(self):
        return [u for u in self.living_units() if u.speed > 0]

    def dead_units(self):
        return [u for u in self.units if not u.is_alive()]

    def testTargets(self, targets, map: Map, otherArmy):
        actions = []
        if isinstance(targets, list):
            targets = {u: t for u, t in targets}

        for unit, target in targets.items():
            if unit.is_alive() and target.is_alive():
                ux, uy = unit.position
                tx, ty = target.position

                dx = tx - ux
                dy = ty - uy
                dist2 = dx * dx + dy * dy

                range_ = unit.range
                if isinstance(unit, Monk) and (isinstance(target, Elephant) or isinstance(target, Castle)):
                    range_ = unit.convert_range

                if dist2 <= (range_ + unit.size / 2 + target.size / 2) ** 2:
                    if isinstance(unit, Monk):
                        if target in otherArmy.living_units():
                            if unit.cooldown <= 0:
                                actions.append(Action(unit, "conversion", target))
                        elif target in self.living_units() and target != unit:
                            actions.append(Action(unit, "heal", target))
                    elif target in otherArmy.living_units():
                        if unit.cooldown <= 0:
                            actions.append(Action(unit, "attack", target))
                else:
                    actions.append(Action(unit, "move", (dx, dy, dist2, ux, uy, map)))
        return actions

    def execOrder(self, orders: Action, otherArmy: "Army"):
        from backend.Utils.network_ownership import get_ownership_manager, OwnershipStatus

        for unit in self.units:
            if unit.cooldown > 0:
                unit.cooldown -= 1

        ownership = None
        try:
            ownership = get_ownership_manager()
        except RuntimeError:
            pass

        for action in orders:
            unit: Unit = action.unit

            if ownership and self.gameMode and hasattr(self.gameMode, "current_sender_id"):
                status = ownership.validate_action(
                    {"unit_id": unit.id},
                    self.gameMode.current_sender_id
                )
                if status != OwnershipStatus.AUTHORIZED:
                    if getattr(self.gameMode, "verbose", False):
                        print(
                            f"[Ownership] Action REJECTED for Unit {unit.id}: "
                            f"Peer {self.gameMode.current_sender_id} is not the owner."
                        )
                    continue

            target: Unit = action.target
            if action.kind == "attack":
                bonus = 0
                for classe in target.classes:
                    bonus += unit.bonuses.get(classe, 0)

                try:
                    from backend.Class.Units.Crossbowman import Crossbowman
                    is_crossbow = isinstance(unit, Crossbowman)
                except Exception:
                    is_crossbow = False

                if is_crossbow:
                    base_miss = 0.08
                    speed_factor = 0.015 * max(0, target.speed - 1)
                    dodge_chance = min(0.20, base_miss + speed_factor)
                    if random.random() < dodge_chance:
                        unit.cooldown = unit.reload_time
                        continue

                damage = max(0, (unit.attack + bonus) - target.armor)
                target.hp -= damage
                if target.hp < 0:
                    target.hp = 0

                unit.last_attacked_id = target.id
                target.last_attacker_id = unit.id
                unit.cooldown = unit.reload_time

            elif action.kind == "move":
                dx, dy, dist2, ux, uy, map = action.target
                vector = (dx / (dist2 ** 0.5) * unit.speed, dy / (dist2 ** 0.5) * unit.speed)
                collision, vector = self.test_vector(unit, map, vector, otherArmy, 4)
                if not collision:
                    new_pos = vector[0] + ux, vector[1] + uy
                    if unit.army and unit.army.gameMode and unit.army.gameMode.map:
                        game_map = unit.army.gameMode.map
                        if hasattr(game_map, "width") and hasattr(game_map, "height"):
                            new_x = max(0, min(new_pos[0], game_map.width - 1))
                            new_y = max(0, min(new_pos[1], game_map.height - 1))
                            unit.position = (new_x, new_y)
                        else:
                            unit.position = new_pos
                    else:
                        unit.position = new_pos

            elif action.kind == "heal":
                target.hp = min(target.max_hp, target.hp + unit.attack)
                unit.last_attacked_id = "heal"

            elif action.kind == "conversion":
                if target in otherArmy.living_units():
                    if hasattr(self.gameMode, "request_unit_ownership"):
                        self.gameMode.request_unit_ownership(target.id)

                    if ownership and hasattr(self.gameMode, "my_id"):
                        ownership.assign_ownership(target.id, self.gameMode.my_id)

                    otherArmy.remove_unit(target)
                    self.add_unit(target)
                    unit.cooldown = unit.reload_time
                    target.last_attacker_id = None
                    target.last_attacked_id = None
                    unit.last_attacked_id = "conversion"

            if isinstance(unit, Elephant):
                for enemy in otherArmy.living_units():
                    if (unit.position[0] - enemy.position[0]) ** 2 + (
                        unit.position[1] - enemy.position[1]
                    ) ** 2 <= 0.25 ** 2:
                        enemy.hp -= unit.attack

    def test_vector(self, unit, map, vector, otherArmy, profondeur):
        assert profondeur >= 0
        collision, find_vector = True, vector
        if profondeur > 0:
            collision, find_vector = self.test_vector(unit, map, vector, otherArmy, profondeur - 1)
        if not collision:
            return collision, find_vector
        find_vector = (
            vector[0] * cos(profondeur * 0.5) - vector[1] * sin(profondeur * 0.5),
            vector[0] * sin(profondeur * 0.5) + vector[1] * cos(profondeur * 0.5),
        )
        collision = self.try_collision(unit, map, find_vector, otherArmy)
        if not collision:
            return collision, find_vector
        find_vector = (
            vector[0] * cos(-1 * profondeur * 0.5) - vector[1] * sin(-1 * profondeur * 0.5),
            vector[0] * sin(-1 * profondeur * 0.5) + vector[1] * cos(-1 * profondeur * 0.5),
        )
        return self.try_collision(unit, map, find_vector, otherArmy), find_vector

    def try_collision(self, unit, map, vector, otherArmy, divide=4):
        collisionE, collisionA, collisionO = False, False, False
        for allie in self.living_units():
            if allie != unit:
                collisionA = self.test_collision(vector, unit, allie, divide)
                if collisionA:
                    break
        if not isinstance(unit, Elephant):
            for enemie in otherArmy.living_units():
                collisionE = self.test_collision(vector, unit, enemie, divide)
                if collisionE:
                    break
        for obstacle in map.obstacles:
            collisionO = self.test_collision(vector, unit, obstacle, divide)
            if collisionO:
                break
        return collisionE or collisionA or collisionO

    def fight(self, map: Map, otherArmy):
        targets = self.general.getTargets(map, otherArmy)
        orders = self.testTargets(targets, map, otherArmy)
        self.execOrder(orders, otherArmy)

    def test_collision(self, vector, unit, object, divide=4):
        x1, y1 = unit.position[0] + vector[0], unit.position[1] + vector[1]
        x1 -= unit.size / divide
        y1 -= unit.size / divide
        w1, h1 = unit.size / divide * 2, unit.size / divide * 2
        x2, y2 = object.position
        x2 -= unit.size / divide
        y2 -= unit.size / divide
        w2, h2 = object.size / divide * 2, object.size / divide * 2

        return not (
            x1 + w1 <= x2
            or x1 >= x2 + w2
            or y1 + h1 <= y2
            or y1 >= y2 + h2
        )

    def deepcopy_unit(self):
        new_army = Army(self.owner)
        new_army.gameMode = self.gameMode
        new_army.general = self.general
        new_army.units = [u.copy() for u in self.units]
        return new_army

    @classmethod
    def from_dict(cls, data: Dict[str, Any], units_by_id: Dict[str, object]) -> "Army":
        army = cls(data.get("owner"))
        for uid in data.get("unit_ids", []):
            unit = units_by_id.get(uid)
            if unit:
                army.add_unit(unit)
        return army

    def to_dict(self) -> Dict[str, Any]:
        return {
            "owner": self.owner,
            "unit_ids": [u.id for u in self.units],
        }
