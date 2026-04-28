import ast
import json
import os
import uuid
import time
import random
from pathlib import Path

from backend.Class.Army import Army
from backend.GameModes.GameMode import GameMode
from backend.Utils.class_by_name import general_from_name
from backend.Class.Units.Knight import Knight
from backend.Class.Units.Pikeman import Pikeman
from backend.Class.Units.Crossbowman import Crossbowman
from backend.Utils.convert_json import json_to_army, army_to_dict
from network.network_api import NetworkBridge

class Online(GameMode):
    def __init__(self, py_port=5000, lan_port=6000, remote_port=6000, is_first=True):
        super().__init__()
        self.tick = 0
        self.tick_delay = 0.5 # SLOWER: 0.5s per tick instead of 0.05s
        self.frame_delay = 0.05
        self.my_army = None
        self.othersArmy = {} 
        self.peer_last_seen = {} 
        self.army_colors = {}    
        self.network_bridge = NetworkBridge(port=py_port)
        self.know_ip = set() 
        self.my_id = str(uuid.uuid4())[:8]
        self.lan_port = lan_port
        self.remote_port = remote_port
        self.is_first = is_first 
        self.has_started = False
        self.timeout_duration = 5.0 
        self.notifications = []

    def flat(self):
        new = Army()
        for army in self.othersArmy.values(): new.units.extend(army.units)
        return new

    def continue_condition(self): return True

    def end(self):
        if hasattr(self.affichage, "shutdown"): self.affichage.shutdown()
        if hasattr(self, "network_bridge"): self.network_bridge.disconnect()

    def save(self): pass

    def add_notification(self, text):
        self.notifications.append((text, time.time()))
        if len(self.notifications) > 6: self.notifications.pop(0)

    def message_receive(self):
        messages = self.network_bridge.get_updates()
        for msg in messages:
            sender_ip = msg.get("_sender_ip")
            sender_port = msg.get("_sender_port") # From tagged proxy header
            payload = msg.get("payload", {})
            if not isinstance(payload, dict): continue
            
            # Discovery using REAL sender port
            if sender_ip and sender_port:
                peer = (sender_ip, int(sender_port))
                if peer not in self.know_ip and not (sender_ip == "127.0.0.1" and int(sender_port) == self.lan_port):
                    self.add_notification(f"Nouveau pair connecte: {sender_port}")
                    self.know_ip.add(peer)

            # Peer exchange
            for p_info in payload.get("_ki", []):
                p_tuple = (p_info[0], int(p_info[1]))
                if p_tuple not in self.know_ip and not (p_tuple[0] == "127.0.0.1" and p_tuple[1] == self.lan_port):
                    self.know_ip.add(p_tuple)

            # Sync armies
            for aid, army_data in payload.items():
                if aid.startswith("_") or aid == self.my_id: continue
                self.peer_last_seen[aid] = time.time()
                new_army = json_to_army(army_data)
                if aid not in self.othersArmy:
                    self.add_notification(f"Joueur {aid} a rejoint !")
                    self.othersArmy[aid] = new_army
                    self.army_colors[aid] = (random.randint(50,255), random.randint(50,255), random.randint(50,255))
                else:
                    self.othersArmy[aid].units = new_army.units
                    self.othersArmy[aid].general = new_army.general
        return len(messages) > 0

    def run(self):
        self.message_receive()
        now = time.time()
        to_remove = [aid for aid, last in self.peer_last_seen.items() if now - last > self.timeout_duration]
        for aid in to_remove:
            self.add_notification(f"Joueur {aid} a quitte")
            if aid in self.othersArmy: del self.othersArmy[aid]
            del self.peer_last_seen[aid]

        if not self.my_army.isEmpty():
            all_enemies = self.flat()
            if not all_enemies.isEmpty():
                # 1. Authoritative MOVE
                targets = self.my_army.general.getTargets(self.map, all_enemies)
                orders = self.my_army.testTargets(targets, self.map, all_enemies)
                self.my_army.execOrder([o for o in orders if o.kind == "move"], all_enemies)
                # 2. Authoritative HP (Decide damage to OURSELVES)
                for enemy in self.othersArmy.values():
                    if not enemy.general: continue
                    e_targets = enemy.general.getTargets(self.map, self.my_army)
                    e_orders = enemy.testTargets(e_targets, self.map, self.my_army)
                    enemy.execOrder([o for o in e_orders if o.kind != "move"], self.my_army)

        self.tick += 1
        self._broadcast_state()

    def _broadcast_state(self):
        p = self.create_payload()
        for ip, port in self.know_ip:
            self.network_bridge.send_message("SYNC_UPDATE", ip, p, dest_port=port)

    def create_payload(self):
        return {
            self.my_id: army_to_dict(self.my_army),
            "_ki": [list(p) for p in self.know_ip],
            "_lp": self.lan_port
        }

    @property
    def army1(self): return self.my_army
    @property
    def army2(self): return self.flat()

    def launch(self):
        if not self.is_first and self.my_army:
            for u in self.my_army.units:
                if u.position: u.position = ((self.map.width - 1) - u.position[0], u.position[1])
        self.affichage.initialiser()
        initial_ip = list(self.know_ip)[0][0] if self.know_ip else None
        print(f"[Online] Start. Initial Peer: {initial_ip}:{self.remote_port}")
        self.network_bridge.connect(remote_ip=initial_ip, lan_port=self.lan_port, remote_port=self.remote_port)

    @army1.setter
    def army1(self, value):
        value.gameMode = self
        self.my_army = value
    @army2.setter
    def army2(self, value):
        value.gameMode = self

    def to_dict(self): return {"tick": self.tick, "my_id": self.my_id}
