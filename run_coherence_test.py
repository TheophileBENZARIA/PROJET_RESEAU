import sys
import os
import time

# Add root to sys.path
sys.path.append(os.getcwd())

from backend.Class.Army import Army
from backend.Class.Units.Knight import Knight
from backend.Class.Units.Pikeman import Pikeman
from backend.Class.Map import Map
from backend.GameModes.Battle import Battle
from backend.Utils.Test_coherence import Test_coherence
from backend.Class.Generals.CaptainBraindead import CaptainBraindead

def run_test():
    print("--- Running Coherence Test ---")
    
    # 1. Setup a simple battle
    map_obj = Map(50, 50)
    army1 = Army("Player1")
    army1.general = CaptainBraindead()
    army1.add_unit(Knight(position=(5, 5)))
    army1.add_unit(Pikeman(position=(6, 6)))
    
    army2 = Army("Player2")
    army2.general = CaptainBraindead()
    army2.add_unit(Knight(position=(40, 40)))
    
    battle = Battle()
    battle.map = map_obj
    battle.army1 = army1
    battle.army2 = army2
    
    tester = Test_coherence()
    
    # Snapshot state
    tester.set_armies(battle.army1, {"peer2": battle.army2})
    
    # 2. Simulate a normal tick
    print("Simulating normal tick...")
    battle.run()
    
    # Mock some expected attributes for coherence test if it expects a specific gamemode structure
    battle.my_army = battle.army1
    battle.othersArmy = {"peer2": battle.army2}
    def mock_flat():
        from backend.Class.Army import Army
        return battle.army2
    battle.flat = mock_flat
    
    report = tester.test_coherence(battle)
    if not report:
        print("[Pass] Normal tick is coherent")
    else:
        print("[Fail] Normal tick has issues:")
        tester.print_report(report)
        
    # 3. Simulate suspicious behavior: HP increase
    print("\nSimulating suspicious HP increase...")
    tester.set_armies(battle.army1, {"peer2": battle.army2})
    unit = battle.army1.units[0]
    unit.hp -= 10
    tester.set_armies(battle.army1, {"peer2": battle.army2}) # Snapshot after damage
    unit.hp += 5 # Suspicious heal
    
    report = tester.test_coherence(battle)
    found_hp = any(r["type"] == "hp" for r in report)
    if found_hp:
        print("[Pass] Suspicious HP increase detected")
    else:
        print("[Fail] Suspicious HP increase NOT detected")
        
    # 4. Simulate collision
    print("\nSimulating collision...")
    u1 = battle.army1.units[0]
    u2 = battle.army1.units[1]
    u1.position = (10, 10)
    u2.position = (10, 10) # Overlap
    
    report = tester.test_coherence(battle)
    found_collision = any(r["type"] == "collision" for r in report)
    if found_collision:
        print("[Pass] Collision detected")
    else:
        print("[Fail] Collision NOT detected")

if __name__ == "__main__":
    run_test()
