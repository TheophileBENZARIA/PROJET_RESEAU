import copy

from backend.Class.Army import Army



class Test_coherence:

    def __init__(self):
        self.MY_ARMY=Army()
        self.OTHER_ARMY ={}




    def test_coherence(self,gamemode):
        report=[]
        if self.MY_ARMY and gamemode.my_army :
            report.extend(self.compare_army(self.MY_ARMY, gamemode.my_army,gamemode.map, gamemode.flat()))
        for k in gamemode.othersArmy.keys():
            if self.OTHER_ARMY and self.OTHER_ARMY.get(k,None) and gamemode.othersArmy.get(k,None) :
                other_list = gamemode.othersArmy.copy()
                del other_list[k]
                other_list["0"] = gamemode.my_army

                otherArmy = Army()
                all_units = []
                for army_id in other_list:
                    all_units.extend(other_list[army_id].units)
                otherArmy.units = all_units

                report.extend(self.compare_army(self.OTHER_ARMY[k], gamemode.othersArmy[k],gamemode.map, otherArmy))

        return report

    def set_armies(self,my_army, othersArmy :dict):

        self.MY_ARMY.units = copy.deepcopy(my_army.units)
        for k in othersArmy.keys():
            self.OTHER_ARMY[k].units = copy.deepcopy(othersArmy[k].units)


    @staticmethod
    def compare_army(old_army, new_army,map, otherArmy):
        report =[]
        for unit in new_army.units:
            #collision
            if new_army.try_collision(unit,map,(0,0), otherArmy,8) :
                report.append({"type": "collision", "unit": unit})

            old_unit = old_army.get_unit_by_id(unit.id)
            if old_unit :
                # death
                if not old_unit.is_alive() and unit.is_alive():
                    report.append({"type": "zombie", "unit": unit})
                # degat
                if unit.hp > old_unit.hp:
                    report.append({"type":"hp", "unit" : unit})
                # cooldown
                if old_unit.cooldown != 0 and unit.cooldown > old_unit.cooldown:
                    report.append({"type":"cooldown", "unit" : unit})

        return report

    def print_report(self,report):
        for element in report:
            print("Suspicious "+ element["type"] +" from ", element["unit"])
