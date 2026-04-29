import uuid
from math import sin
from math import cos

from backend.Class.Map import Map
from backend.Class.Action import Action
import random  # NEW: for ranged dodge rolls

from backend.Class.Units.Castle import Castle
from backend.Class.Units.Elephant import Elephant
from backend.Class.Units.Monk import Monk
from backend.Class.Units.Unit import Unit


class Army:
    def __init__(self):
        self.gameMode = None
        self.__general = None
        self.units = []  # list of Unit objects

    @property
    def general(self):
        return self.__general

    @general.setter
    def general(self, value):
        value.army = self
        self.__general = value


    def add_unit(self, unit: Unit):
        unit.army = self
        self.units.append(unit)

    def remove_unit(self, unit):
        for i in range(len(self.units)):
            if self.units[i] == unit :
                del self.units[i]
                break

    def isEmpty(self):
        return len(self.living_units()) <= 0

    def living_units_id(self):
        return [u.id for u in self.units if u.is_alive()]

    def get_unit_by_id(self, id):
        for u in self.units:
            if u.id == id: return u
        return None

    def living_units(self):
        return [u for u in self.units if u.is_alive()]

    def moving_units(self):
        return [u for u in self.living_units() if u.speed > 0]

    def dead_units(self):
        return [u for u in self.units if not u.is_alive()]

    def testTargets(self, targets, map: Map, otherArmy):
        # Le générale donne juste des cibles, il associe une unité à une unité adverse
        # L'objectif de cette fonction est de transformer cette association en action
        # Si l'unité cible est trop loin il faut que l'unité se déplace et si elle est dans le champ d'action elle l'attaque
        # Il faut aussi verifier que l'unité peut avancer (elle n'est pas face a un mur ou une autre unité)
        # Il faut vérifier que le cooldown est a zero si on veut attaqué et si le cooldown n'est pas à 0 il faut le diminuer
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

                # print(unit, target, dist2, unit.range,dist2 <= unit.range **2)
                range_ = unit.range
                if isinstance(unit, Monk) and (isinstance(target, Elephant) or isinstance(target, Castle)) :
                    range_ = unit.convert_range


                # ATTAQUE
                if dist2 <= (range_+ unit.size/2 + target.size/2) ** 2:
                    if isinstance(unit, Monk):
                        if target in otherArmy.living_units() :
                            if unit.cooldown <= 0:
                                actions.append(Action(unit, "conversion", target))
                        elif target in self.living_units() and target != unit:
                            actions.append(Action(unit, "heal", target))
                    elif target in otherArmy.living_units():
                        if unit.cooldown <= 0:
                            actions.append(Action(unit, "attack", target))
                else:
                    vector = (dx / (dist2 ** 0.5) * unit.speed,dy / (dist2 ** 0.5) * unit.speed)
                    #print(vector)
                    """
                    if self.try_collision(unit,map,vector,otherArmy):
                        vector1 = vector[0] * cos(1) - vector[1] * sin(1), vector[0] * sin(1) + vector[1] * cos(1)
                        #print(vector1)
                        if self.try_collision(unit,map,vector1,otherArmy) :
                            vector2 = vector[0] * cos(-1) - vector[1] * sin(-1), vector[0] * sin(-1) + vector[1] * cos(-1)
                            #print(vector2)
                            if self.try_collision(unit,map, vector2,otherArmy):
                                vector = None
                            else :
                                vector = vector2
                        else :
                            vector = vector1
                    """
                    collision, vector = self.test_vector(unit, map, vector, otherArmy, 4)
                    if not collision :
                        vector = vector[0] +ux, vector[1]+uy
                        actions.append(
                            Action(unit, "move", vector)
                        )
        return actions

    def test_vector(self,unit,map,vector, otherArmy, profondeur):
        assert profondeur >=0
        collision, find_vector = True, vector
        if profondeur > 0:
            collision, find_vector = self.test_vector(unit,map,vector, otherArmy, profondeur-1)
        if not collision : return collision, find_vector
        find_vector = vector[0] * cos(profondeur*0.5) - vector[1] * sin(profondeur*0.5), vector[0] * sin(profondeur*0.5) + vector[1] * cos(profondeur*0.5)
        collision = self.try_collision(unit,map,find_vector,otherArmy)
        if not collision: return collision, find_vector
        find_vector = vector[0] * cos(-1*profondeur*0.5) - vector[1] * sin(-1*profondeur*0.5), vector[0] * sin(-1*profondeur*0.5) + vector[1] * cos(-1*profondeur*0.5)
        return self.try_collision(unit,map,find_vector,otherArmy), find_vector

    def try_collision(self, unit, map, vector, otherArmy, divide=4):
        collisionE, collisionA, collisionO = False, False, False
        for allie in self.living_units():
            if allie != unit:
                collisionA = self.test_collision(vector, unit, allie, divide)
                if collisionA:
                    break
        if not isinstance(unit, Elephant) :
            for enemie in otherArmy.living_units():
                collisionE = self.test_collision(vector, unit, enemie, divide)
                if collisionE:
                    break
        for obstacle in map.obstacles:
            collisionO = self.test_collision(vector, unit, obstacle, divide)
            if collisionO: break
        collision = collisionE or collisionA or collisionO

        return collision





    def execOrder(self, orders: Action, otherArmy: "Army"):
        from backend.Utils.network_ownership import get_ownership_manager, OwnershipStatus

        for unit in self.units:
            if unit.cooldown > 0: unit.cooldown -= 1
        # Cette fonction applique les dégâts avec les bonus sur l'armée adverse et
        # déplace des unités alliées à la bonne vitesse selon les ordres.
        """
        Applique les actions décidées par testTargets :
        - attaque : dégâts + cooldown
        - déplacement : mise à jour de la position
        """

        ownership = None
        try:
            ownership = get_ownership_manager()
        except RuntimeError:
            # Ownership not initialized (likely single player/Battle mode), skip check
            pass

        for action in orders:
            unit : Unit = action.unit
            
            # VALIDATION CHECK
            if ownership and self.gameMode and hasattr(self.gameMode, "current_sender_id"):
                status = ownership.validate_action(
                    {"unit_id": unit.id}, 
                    self.gameMode.current_sender_id
                )
                if status != OwnershipStatus.AUTHORIZED:
                    if getattr(self.gameMode, "verbose", False):
                        print(f"[Ownership] Action REJECTED for Unit {unit.id}: Peer {self.gameMode.current_sender_id} is not the owner.")
                    continue

            target: Unit = action.target
            # ATTAQUE
            if action.kind == "attack":


                bonus = 0
                for classe in target.classes:
                    bonus += unit.bonuses.get(classe, 0)

                # Crossbow-specific dodge mechanic (rare miss, scales with target speed)
                try:
                    from backend.Class.Units.Crossbowman import Crossbowman
                    is_crossbow = isinstance(unit, Crossbowman)
                except Exception:
                    is_crossbow = False

                if is_crossbow:
                    base_miss = 0.08  # 8% base dodge chance
                    speed_factor = 0.015 * max(0, target.speed - 1)  # +1.5% per extra speed
                    dodge_chance = min(0.20, base_miss + speed_factor)  # cap at 20%
                    if random.random() < dodge_chance:
                        # miss / dodge: only consume reload time
                        unit.cooldown = unit.reload_time
                        continue

                # Compute applied damage (never heal)
                damage = max(0, (unit.attack + bonus) - target.armor)
                target.hp -= damage
                if target.hp < 0:
                    target.hp = 0

                unit.last_attacked_id = target.id
                target.last_attacker_id = unit.id
                unit.cooldown = unit.reload_time

            # DÉPLACEMENT
            elif action.kind == "move":
                new_pos = action.target
                # Clamp position to map bounds if map has dimensions
                if unit.army and unit.army.gameMode and unit.army.gameMode.map:
                    game_map = unit.army.gameMode.map
                    if hasattr(game_map, 'width') and hasattr(game_map, 'height'):
                        new_x = max(0, min(new_pos[0], game_map.width - 1))
                        new_y = max(0, min(new_pos[1], game_map.height - 1))
                        unit.position = (new_x, new_y)
                    else:
                        unit.position = new_pos
                else:
                    unit.position = new_pos
            #Monk healing
            elif action.kind == "heal" :
                target.hp = min(target.max_hp, target.hp+unit.attack)
                unit.last_attacked_id = "heal"
            #Monk convert
            elif action.kind == "conversion":
                if target in otherArmy.living_units() :
                    # Request network ownership transfer before we take it locally
                    if hasattr(self.gameMode, "request_unit_ownership"):
                        self.gameMode.request_unit_ownership(target.id)
                    
                    # Locally assign ownership immediately to avoid REJECTED errors
                    if ownership and hasattr(self.gameMode, "my_id"):
                        ownership.assign_ownership(target.id, self.gameMode.my_id)
                        
                    otherArmy.remove_unit(target)
                    self.add_unit(target)
                    unit.cooldown = unit.reload_time
                    target.last_attacker_id = None
                    target.last_attacked_id = None
                    unit.last_attacked_id = "conversion"

            if isinstance(unit, Elephant) :
                for enemy in otherArmy.living_units():
                    if (unit.position[0]-enemy.position[0])**2 + (unit.position[1]-enemy.position[1])**2 <= 0.25**2 :
                        enemy.hp-=unit.attack

    def fight(self, map: Map, otherArmy):

        targets = self.general.getTargets(map, otherArmy)

        orders = self.testTargets(targets, map, otherArmy)

        self.execOrder(orders, otherArmy)



    def test_collision(self, vector, unit, object, divide=4):
        """
        rect = (x, y, largeur, hauteur)
        """

        x1, y1 = unit.position[0] + vector[0], unit.position[1] + vector[1]
        x1 -= unit.size / divide
        y1 -= unit.size / divide
        w1, h1 = unit.size / divide * 2, unit.size / divide * 2
        x2, y2 = object.position
        x2 -= unit.size / divide
        y2 -= unit.size / divide
        w2, h2 = object.size / divide * 2, object.size / divide * 2

        return not (
                x1 + w1 <= x2 or  # rect1 à gauche de rect2
                x1 >= x2 + w2 or  # rect1 à droite de rect2
                y1 + h1 <= y2 or  # rect1 au-dessus de rect2
                y1 >= y2 + h2  # rect1 en dessous de rect2
        )
