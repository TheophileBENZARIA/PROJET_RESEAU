import ast
import uuid
import time
import socket

from backend.Class.Army import Army
from backend.GameModes.GameMode import GameMode
from backend.Utils.Test_coherence import Test_coherence
from backend.Utils.class_by_name import general_from_name
from backend.Class.Units.Knight import Knight
from backend.Class.Units.Pikeman import Pikeman
from backend.Class.Units.Crossbowman import Crossbowman
from backend.Utils.network_ownership import initialize_ownership, get_ownership_manager
from backend.Utils.convert_json import json_to_army, army_to_dict, map_to_dict, json_to_map
from network.network_api import NetworkBridge


# client1 envoie les ordres de sont général -> client2 execute les ordres et envoie l'état du monde -> client1


class Online(GameMode):

    def __init__(self, py_port=5000, lan_port=6000, remote_port=6000, is_first=True, spawn_slot=None):
        super().__init__()
        self.max_tick = None
        self.tick = 0
        self.tick_delay = 0.5
        self.frame_delay = 0.05
        self.verbose = True
        self.my_army = None
        self.othersArmy = {} 
        self.network_bridge = NetworkBridge(port=py_port)
        self.know_ip= set()
        self.pending_handshakes = {}
        # Stable UID based on machine and port to allow persistent identification and coloring
        # while still supporting multiple instances on the same machine.
        seed = f"medievail-{socket.gethostname()}-{uuid.getnode()}-{py_port}"
        self.my_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, seed))
        self.network_bridge.my_id = self.my_id

        self.lan_port = lan_port
        self.remote_port = remote_port
        self.is_first = is_first # Host is Blue (P1), Joiner is Red (P2)
        if spawn_slot is None:
            # Joiners start with -1 to avoid colliding on "Player B" (slot 1)
            # until the host assigns a definitive slot.
            spawn_slot = 0 if is_first else -1
        self.spawn_slot = spawn_slot
        self.has_started = False
        self.current_sender_id = None
        
        # Map to display the IP and port of each player in the UI
        # Format: {peer_id: (ip, lan_port)}
        self.peer_ips = {self.my_id: (self.network_bridge._my_ip, self.lan_port)}
        self.peer_slots = {self.my_id: self.spawn_slot}
        self.slot_authority_id = self.my_id if self.is_first else None
        self.last_recv_time = {}
        
        # Initialize ownership system
        initialize_ownership(self.my_id)
        
        self._army_base_positions = {}
        self._army_mirrored_for_width = None
        self._last_known_remote_armies = 0
        self._last_logged_map_signature = None
        # Damage dealt to remote units this tick (unit_id -> hp after attack)
        self._enemy_damage = {}
        self._army_versions = {self.my_id: 0}

        self.Test_coherence = Test_coherence()

    def _next_free_slot(self):
        used_slots = set()
        for slot in self.peer_slots.values():
            try:
                used_slots.add(int(slot))
            except (TypeError, ValueError):
                pass

        slot = 0
        while slot in used_slots:
            slot += 1
        return slot

    def _ensure_peer_slot(self, peer_id):
        if not peer_id or peer_id == "unknown":
            return
        if peer_id not in self.peer_slots:
            self.peer_slots[peer_id] = self._next_free_slot()

    def _apply_peer_slots(self, peer_slots_payload):
        if not isinstance(peer_slots_payload, dict):
            return

        authority_id = None
        for peer_id, slot in peer_slots_payload.items():
            try:
                if int(slot) == 0:
                    authority_id = peer_id
                    break
            except (TypeError, ValueError):
                continue

        if self.is_first:
            for peer_id in peer_slots_payload.keys():
                if peer_id != self.my_id:
                    self._ensure_peer_slot(peer_id)
            return

        if authority_id:
            self.slot_authority_id = authority_id

        if self.slot_authority_id and authority_id == self.slot_authority_id:
            for peer_id, slot in peer_slots_payload.items():
                try:
                    self.peer_slots[peer_id] = int(slot)
                except (TypeError, ValueError):
                    pass
            new_slot = self.peer_slots.get(self.my_id)
            if new_slot is not None and int(new_slot) != self.spawn_slot:
                self.spawn_slot = int(new_slot)
                self._army_mirrored_for_width = None
                self._deploy_my_army_for_current_map()
            return

        for peer_id, slot in peer_slots_payload.items():
            if peer_id not in self.peer_slots:
                try:
                    self.peer_slots[peer_id] = int(slot)
                except (TypeError, ValueError):
                    pass

    def _slot_zero_peer_id(self):
        for peer_id, slot in self.peer_slots.items():
            try:
                if int(slot) == 0:
                    return peer_id
            except (TypeError, ValueError):
                pass
        return self.slot_authority_id

    def _can_accept_army_snapshot(self, army_id, sender_id):
        if army_id == self.my_id:
            return False
        if sender_id == army_id:
            return True
        host_id = self._slot_zero_peer_id()
        if host_id and sender_id == host_id:
            return True
        return False

    def _incoming_army_version(self, army_id, army_versions_payload, msg):
        version = None
        if isinstance(army_versions_payload, dict):
            version = army_versions_payload.get(army_id)
        if version is None:
            version = msg.get("seq", 0)
        try:
            return int(version)
        except (TypeError, ValueError):
            return 0

    def _is_stale_army_snapshot(self, army_id, incoming_version):
        return incoming_version < self._army_versions.get(army_id, -1)

    def _remember_army_version(self, army_id, incoming_version):
        self._army_versions[army_id] = max(
            incoming_version,
            self._army_versions.get(army_id, -1)
        )

    def _bump_army_version(self, army_id):
        if not army_id:
            return
        self._army_versions[army_id] = max(
            self._army_versions.get(army_id, -1) + 1,
            self.tick
        )

    def _apply_hp_report_to_army(self, army, unit_id, reported_hp):
        if army is None:
            return False
        unit = army.get_unit_by_id(unit_id)
        if unit is None:
            return False
        changed = False
        if reported_hp < unit.hp:
            unit.hp = reported_hp
            changed = True
        if unit.hp < 0:
            unit.hp = 0
            changed = True
        return changed

    def _apply_hp_reductions_from_army_data(self, army_data):
        if not self.my_army or not isinstance(army_data, dict):
            return False
        changed = False
        local_units = {u.id: u for u in self.my_army.units}
        for unit_data in army_data.get("units", []):
            unit_id = unit_data.get("id")
            if unit_id in local_units:
                reported_hp = unit_data.get("hp", local_units[unit_id].hp)
                if reported_hp < local_units[unit_id].hp:
                    local_units[unit_id].hp = reported_hp
                    changed = True
                if local_units[unit_id].hp < 0:
                    local_units[unit_id].hp = 0
                    changed = True
        return changed

    def _map_signature(self):
        if self.map is None:
            return "none"
        width = getattr(self.map, "width", "?")
        height = getattr(self.map, "height", "?")
        obstacles = len(getattr(self.map, "obstacles", []))
        return f"{width}x{height}, obstacles={obstacles}"

    def _log_map_if_changed(self):
        signature = self._map_signature()
        if signature != self._last_logged_map_signature:
            print(f"[Online] Map courante : {signature}")
            self._last_logged_map_signature = signature

    def _mark_army_owner(self, army, army_id):
        if army is None:
            return
        army.owner = army_id
        for unit in army.units:
            unit.army = army
            unit.network_owner_id = army_id

    def _remember_base_positions(self):
        if self.my_army is None:
            return
        self._army_base_positions = {
            unit.id: unit.position
            for unit in self.my_army.units
            if unit.position is not None
        }

    def _deploy_my_army_for_current_map(self):
        if self.my_army is None or self.map is None:
            return
        width = getattr(self.map, "width", None)
        height = getattr(self.map, "height", None)
        if width is None or height is None or self._army_mirrored_for_width == width:
            return
        print(f"[Online] Deploying army slot {self.spawn_slot} on map {width}x{height}...")
        
        # Determine y_offset: slot 0 is at 0, slot 1 at 20, slot 2 at 40...
        # If pending (-1), we use a temporary offset far from the host
        y_offset = 0
        if self.spawn_slot > 0:
            y_offset = self.spawn_slot * 20
        elif self.spawn_slot < 0:
            y_offset = 40 # Temporary offset for joining players
            
        for unit in self.my_army.units:
            base_pos = self._army_base_positions.get(unit.id, unit.position)
            if base_pos:
                x, y = base_pos
                if self.spawn_slot != 0:
                    x = (width - 1) - x
                y = max(0, min(height - 1, y + y_offset))
                unit.position = (x, y)
        self._army_mirrored_for_width = width

    def flat(self):
        new = Army()
        all_units = []
        for army_id in self.othersArmy:
            all_units.extend(self.othersArmy[army_id].units)
        new.units = all_units
        return new

    def continue_condition(self):
        return self.max_tick is None or self.tick < self.max_tick

    def end(self):
        # Arrêt du thread de communication
        if hasattr(self, "_network_thread_running"):
            self._network_thread_running = False

        # Fermeture de l'affichage
        if hasattr(self.affichage, "shutdown"):
            self.affichage.shutdown()
        
        # Fermeture de la connexion réseau et du Proxy C
        if hasattr(self, "network_bridge"):
            print("[Online] Fermeture de la connexion réseau...")
            self.network_bridge.disconnect()

    def request_unit_ownership(self, unit_id: str):
        """Sends an OWNERSHIP_REQUEST to the current owner."""
        ownership = get_ownership_manager()
        current_owner = ownership.get_owner(unit_id)
        if current_owner and current_owner != self.my_id:
            ownership.request_ownership(unit_id, self.my_id)
            peer_info = self.peer_ips.get(current_owner)
            if peer_info:
                ip, port = peer_info
                self.network_bridge.send_message("OWNERSHIP_REQUEST", ip, {
                    "unit_id": unit_id,
                    "requester_id": self.my_id
                }, peer_id=current_owner)
            else:
                # Broadcast unencrypted as fallback
                for fallback_ip in self.know_ip:
                    self.network_bridge.send_message("OWNERSHIP_REQUEST", fallback_ip, {
                        "unit_id": unit_id,
                        "requester_id": self.my_id
                    })


    def message_receive(self):
        """
        Recuperer les messages reseau, synchroniser la map envoyee par le host,
        puis mettre a jour les armees des autres joueurs.
        """
        messages = self.network_bridge.get_updates()
        updated = False
        ownership = get_ownership_manager()
        security = self.network_bridge.security_manager

        for msg in messages:
            sender_ip = msg.get("_sender_ip")
            msg_type = msg.get("type", "SYNC_UPDATE")
            payload = msg.get("payload", {})
            
            if sender_ip and sender_ip not in self.know_ip:
                self.know_ip.add(sender_ip)
                
            sender_id = msg.get("sender_id")
            if sender_id and sender_id != self.my_id and sender_id != "unknown":
                # Discovery of peer port from outer message header
                remote_port = msg.get("sender_port") or payload.get("my_port")
                if sender_ip:
                    if sender_id not in self.peer_ips or (remote_port and self.peer_ips[sender_id][1] != remote_port):
                        port = remote_port or self.remote_port
                        self.peer_ips[sender_id] = (sender_ip, port)
                        # Tell proxy to add this peer for direct broadcasting
                        self.network_bridge.add_peer(sender_ip, port)
                        print(f"[Online] Discovering new peer connection: {sender_id} at {sender_ip}:{port}")
                
                if self.is_first:
                    self._ensure_peer_slot(sender_id)
                
                # Handshake initiation
                if security and sender_id not in security.peer_session_keys:
                    last_hello = self.pending_handshakes.get(sender_id, 0)
                    if time.time() - last_hello > 2.0:
                        print(f"[Online] Nouveau pair decouvert ou attente de clé (ID) : {sender_id}")
                        self.pending_handshakes[sender_id] = time.time()
                        # Initiate handshake
                        self.network_bridge.send_message("SECURE_HELLO", sender_ip, {
                            "public_key": security.get_my_public_key_pem(),
                            "peer_id": self.my_id
                        })
            
            # If payload is still a string (ciphertext), skip further processing in this loop
            if not isinstance(payload, dict):
                continue

            raw_peer_ips = payload.get("peer_ips", {})
            peer_ips_payload = raw_peer_ips if isinstance(raw_peer_ips, dict) else {}
            for p_id, p_info in peer_ips_payload.items():
                if p_id != self.my_id and p_info:
                    # p_info should now be [ip, port] or (ip, port)
                    if isinstance(p_info, (list, tuple)) and len(p_info) == 2:
                        p_ip, p_port = p_info
                        if p_id not in self.peer_ips or self.peer_ips[p_id] != (p_ip, p_port):
                            self.peer_ips[p_id] = (p_ip, p_port)
                            self.network_bridge.add_peer(p_ip, p_port)
                            #print(f"[Online] Peer {p_id} discovered via gossip: {p_ip}:{p_port}")
                    else:
                        # Fallback for old clients (only IP)
                        if p_id not in self.peer_ips:
                            self.peer_ips[p_id] = (p_info, self.remote_port)
                            self.network_bridge.add_peer(p_info, self.remote_port)

            raw_peer_slots = payload.get("peer_slots", {})
            peer_slots_payload = raw_peer_slots if isinstance(raw_peer_slots, dict) else {}
            self._apply_peer_slots(peer_slots_payload)

            if msg_type == "OWNERSHIP_REQUEST":
                unit_id = payload.get("unit_id")
                requester_id = payload.get("requester_id")
                if unit_id and requester_id:
                    ownership.request_ownership(unit_id, requester_id)
                    # Automatically grant ownership if we are the current owner (for demonstration)
                    if ownership.grant_ownership(unit_id, requester_id):
                        print(f"[Ownership] Accord de la propriete de {unit_id} a {requester_id}")
                        
                        # IMPORTANT: If we granted ownership, we must remove it from our army locally!
                        if self.my_army:
                            u = self.my_army.get_unit_by_id(unit_id)
                            if u:
                                self.my_army.remove_unit(u)
                                
                        for ip in self.know_ip:
                            self.network_bridge.send_message("OWNERSHIP_GRANT", ip, {
                                "unit_id": unit_id,
                                "new_owner_id": requester_id
                            })
                continue
            elif msg_type == "OWNERSHIP_GRANT":
                unit_id = payload.get("unit_id")
                new_owner_id = payload.get("new_owner_id")
                if unit_id and new_owner_id:
                    print(f"[Ownership] Transfert de {unit_id} vers {new_owner_id} confirme")
                    ownership.handle_grant(unit_id, new_owner_id)
                    
                    # If someone else gained ownership, make sure we don't accidentally keep it
                    if new_owner_id != self.my_id and self.my_army:
                        u = self.my_army.get_unit_by_id(unit_id)
                        if u:
                            self.my_army.remove_unit(u)
                continue

            if "map" in payload and payload["map"]:
                try:
                    self.map.fussionner(json_to_map(payload["map"]))
                    self._deploy_my_army_for_current_map()
                    self._log_map_if_changed()
                except Exception as e:
                    print(f"[Online] Erreur lors du chargement de la map : {e}")

            # Apply damage the remote peer computed against our units
            enemy_damage = payload.get("enemy_damage", {})
            if enemy_damage:
                for unit_id, reported_hp in enemy_damage.items():
                    if self._apply_hp_report_to_army(self.my_army, unit_id, reported_hp):
                        self._bump_army_version(self.my_id)
                    for army_id, army in self.othersArmy.items():
                        self._apply_hp_report_to_army(army, unit_id, reported_hp)

            armies_payload = payload.get("armies", payload)
            if not isinstance(armies_payload, dict):
                continue
            raw_army_versions = payload.get("army_versions", {})
            army_versions_payload = raw_army_versions if isinstance(raw_army_versions, dict) else {}


            for army_id, army_data in armies_payload.items():
                if army_id == self.my_id:
                    if sender_id == self._slot_zero_peer_id():
                        if self._apply_hp_reductions_from_army_data(army_data):
                            self._bump_army_version(self.my_id)
                    continue
                if not self._can_accept_army_snapshot(army_id, sender_id):
                    continue

                incoming_version = self._incoming_army_version(army_id, army_versions_payload, msg)
                if self._is_stale_army_snapshot(army_id, incoming_version):
                    continue

                if army_id != self.my_id:
                    ownership.register_peer(army_id)
                    if self.is_first:
                        self._ensure_peer_slot(army_id)
                    if army_id in peer_ips_payload:
                        self.peer_ips[army_id] = peer_ips_payload[army_id]
                    elif sender_id == army_id and sender_ip:
                        self.peer_ips[army_id] = sender_ip
                    if army_id in peer_slots_payload:
                        try:
                            self.peer_slots[army_id] = int(peer_slots_payload[army_id])
                        except (TypeError, ValueError):
                            pass
                    self.last_recv_time[army_id] = time.time()
                    try:
                        if army_id not in self.othersArmy:
                            # First time we see this army: create it fresh
                            new_army = json_to_army(army_data)
                            self._mark_army_owner(new_army, army_id)
                            self.othersArmy[army_id] = new_army
                            for unit in new_army.units:
                                ownership.assign_ownership(unit.id, army_id)
                        else:
                            # Subsequent updates: patch units IN-PLACE by ID
                            # This preserves object identity so PyScreen animation
                            # continues tracking the same objects without restarting.
                            existing_army = self.othersArmy[army_id]
                            existing_by_id = {u.id: u for u in existing_army.units}
                            
                            incoming_units = army_data.get("units", [])
                            incoming_ids = set()
                            
                            for unit_data in incoming_units:
                                uid = unit_data.get("id")
                                if uid is None:
                                    continue
                                incoming_ids.add(uid)
                                remote_hp = unit_data.get("hp", 0)
                                remote_pos = unit_data.get("position")
                                remote_cooldown = unit_data.get("cooldown", 0)
                                
                                if uid in existing_by_id:
                                    # Update in-place: always trust remote for position,
                                    # keep min HP so damage is never undone.
                                    u = existing_by_id[uid]
                                    if remote_pos is not None:
                                        u.position = tuple(remote_pos)
                                    u.hp = min(u.hp, remote_hp)
                                    u.cooldown = remote_cooldown
                                else:
                                    # New unit joined mid-game
                                    cls_name = unit_data.get("type")
                                    from backend.Utils.convert_json import json_to_army as _j2a
                                    try:
                                        cls = globals().get(cls_name)
                                        if cls is None:
                                            import importlib, backend.Class.Units
                                            mod = importlib.import_module(
                                                f"backend.Class.Units.{cls_name}")
                                            cls = getattr(mod, cls_name)
                                        pos = tuple(remote_pos) if remote_pos else (0, 0)
                                        new_unit = cls(position=pos)
                                        new_unit._Unit__id = uid
                                        new_unit.hp = remote_hp
                                        new_unit.cooldown = remote_cooldown
                                        new_unit.network_owner_id = army_id
                                        existing_army.units.append(new_unit)
                                        ownership.assign_ownership(uid, army_id)
                                    except Exception:
                                        pass
                            
                            # Mark units absent from network as dead (hp=0)
                            for uid, u in existing_by_id.items():
                                if uid not in incoming_ids:
                                    u.hp = 0
                        self._remember_army_version(army_id, incoming_version)
                    except Exception as e:
                        print(f"[Online] Erreur lors du merge de l'armee de {army_id} : {e}")
        
        known_remote_armies = len(self.othersArmy)
        if known_remote_armies != self._last_known_remote_armies:
            print(f"[Online] Armees distantes connues : {known_remote_armies}")
            self._last_known_remote_armies = known_remote_armies
        return updated

    def run(self):
        """
        Étape principale de la simulation pour le mode Online :
        1. Si aucun pair, attendre (la diffusion est gérée par le thread réseau)
        2. Si pair trouvé, exécuter la simulation locale
        Note: message_receive() et _broadcast_state() sont gérés par le thread réseau
        """
        if not self.othersArmy:
            if self.tick % 100 == 0:
                print("En attente d'un autre joueur...")
            return

        if not self.has_started:
            print("Joueur rejoint ! Début de la bataille.")
            self.has_started = True

        # Register our own units' ownership if not done
        ownership = get_ownership_manager()
        for unit in self.my_army.units:
            ownership.assign_ownership(unit.id, self.my_id)



        # Build enemy reference BEFORE fight so we can snapshot HP
        all_enemies = self.flat()
        hp_before = {u.id: u.hp for u in all_enemies.units}

        self.current_sender_id = self.my_id
        self.my_army.fight(self.map, otherArmy=all_enemies)

        # Record HP reductions we dealt to enemy units.
        # These are broadcast so the remote peer can apply them to its own army.
        damage_report = {}
        for u in all_enemies.units:
            if u.hp < hp_before.get(u.id, u.hp):
                damage_report[u.id] = u.hp  # HP after damage
        self._enemy_damage = damage_report

        report = self.Test_coherence.test_coherence(self)
        self.Test_coherence.print_report(report)

        self.Test_coherence.set_armies(self.my_army, self.othersArmy)

        # Incrémenter le tick
        self.tick += 1


    def _broadcast_state(self):
        payload = self.create_payload()

        if not self.know_ip:
            # Envoie un paquet bidon pour enregistrer le port Python auprès du proxy C
            self.network_bridge.send_message("SYNC_UPDATE", "0.0.0.0", payload)
            return

        # Broadcast to all known IPs
        # In multi-peer mode, we must send to the IP associated with each peer ID
        # using the correct session key.
        sent_ips = set()
        for peer_id, info in self.peer_ips.items():
            if peer_id == self.my_id:
                continue
            
            ip = info[0] if isinstance(info, (list, tuple)) else info
            sent_ips.add(ip)
            
            security = self.network_bridge.security_manager
            if security and peer_id in security.peer_session_keys:
                self.network_bridge.send_message("SYNC_UPDATE", ip, payload, peer_id=peer_id)
            else:
                self.network_bridge.send_message("SYNC_UPDATE", ip, payload)

        # Fallback for IPs in know_ip that are not in peer_ips yet (handshake phase)
        for ip in self.know_ip:
            if ip not in sent_ips:
                self.network_bridge.send_message("SYNC_UPDATE", ip, payload)

    def update_dead(self, all_enemies):
        # Ne pas supprimer les unités mortes de self.othersArmy.
        # Cela permet de garder leur HP = 0 dans 'old_hp' lors de la réception UDP, 
        # empêchant les troupes de ressusciter via les paquets réseau décalés.
        pass

    @property
    def army1(self):
        return self.my_army

    @property
    def army2(self):
        return self.flat()

    def launch(self):
        if self.my_army:
            self.my_army.gameMode = self
            self._mark_army_owner(self.my_army, self.my_id)
        self._remember_base_positions()
        self._deploy_my_army_for_current_map()
        self._log_map_if_changed()

        self.affichage.initialiser()
        remote_ip = list(self.know_ip)[0] if self.know_ip else None
        self.network_bridge.connect(remote_ip=remote_ip, lan_port=self.lan_port, remote_port=self.remote_port)
        
        # Démarrer le thread de communication réseau rapide (découplé du tick de combat)
        import threading
        self._network_thread_running = True
        def network_loop():
            while self._network_thread_running:
                try:
                    self.message_receive()
                    self._broadcast_state()
                except Exception as e:
                    if getattr(self, "verbose", False):
                        print(f"[Online] Erreur boucle reseau : {e}")
                time.sleep(0.02) # 50 updates/second
        
        self._network_thread = threading.Thread(target=network_loop, daemon=True)
        self._network_thread.start()
        
        # Envoyer immédiatement un premier paquet pour s'enregistrer auprès du proxy C
        self._broadcast_state()

    def save(self):
        pass

    def load_payload(self, json_payload):
        print("ef", json_payload)
        army = ast.literal_eval(json_payload)
        print(army)
        for k in army.keys():
            if k == self.my_id:
                self.my_army = json_to_army(army[k])
            else:
                self.othersArmy[k] = json_to_army(army[k])

    def create_payload(self):
        if self.my_army:
            self._mark_army_owner(self.my_army, self.my_id)
        self._army_versions[self.my_id] = max(
            self._army_versions.get(self.my_id, 0),
            self.tick
        )

        # Each peer is authoritative for its OWN army ONLY for positions.
        # We also include "enemy_damage": HP values we computed for enemy units
        # so the remote peer can apply damage to its own units.
        armies = {
            self.my_id: army_to_dict(self.my_army)
        }

        # The host acts as the rendezvous point in 3+ player games.
        # It relays every known army so B can discover C and C can discover B.
        if self.is_first:
            for army_id, army in self.othersArmy.items():
                if army_id != self.my_id:
                    self._mark_army_owner(army, army_id)
                    armies[army_id] = army_to_dict(army)

        payload = {
            "armies": armies,
            "army_versions": {
                army_id: self._army_versions.get(army_id, 0)
                for army_id in armies
            },
            "peer_ips": self.peer_ips,
            "peer_slots": self.peer_slots,
            "my_port": self.lan_port
        }

        # Include damage report so the remote peer knows its units took hits
        if self._enemy_damage:
            payload["enemy_damage"] = self._enemy_damage

        # Only host (is_first) decides the map to avoid conflicts.
        # We send the map more frequently during the first few hundred ticks 
        # to ensure joiners get it quickly.
        if self.is_first and self.map is not None:
            if self.tick < 500:
                if self.tick % 20 == 0:
                    payload["map"] = map_to_dict(self.map)
            elif self.tick % 100 == 0:
                payload["map"] = map_to_dict(self.map)

        return payload


    @army1.setter
    def army1(self, value):
        value.gameMode = self
        self.my_army = value
        self._mark_army_owner(self.my_army, self.my_id)

    @army2.setter
    def army2(self, value):
        value.gameMode = self

    def to_dict(self):
        """Serialize battle state to dictionary for saving."""
        # Serialize units with their IDs
        units_by_id = {}
        for unit in self.army1.units + self.army2.units:
            units_by_id[unit.id] = {
                "id": unit.id,
                "unit_type": unit.unit_type(),
                "hp": unit.hp,
                "position": list(unit.position) if unit.position else None,
                "cooldown": unit.cooldown,
                "army": "army1" if unit in self.army1.units else "army2"
            }

        # Serialize generals (including AI state)
        general1_state = {}
        general2_state = {}
        if self.army1.general:
            general1_state = {
                "class": self.army1.general.__class__.__name__,
                "state": self._serialize_general_state(self.army1.general)
            }
        if self.army2.general:
            general2_state = {
                "class": self.army2.general.__class__.__name__,
                "state": self._serialize_general_state(self.army2.general)
            }

        return {
            "tick": self.tick,
            "max_tick": self.max_tick,
            "map": {
                "width": self.map.width if hasattr(self.map, 'width') else 100,
                "height": self.map.height if hasattr(self.map, 'height') else 100,
                "obstacles": [{"position": list(obs.position)} for obs in self.map.obstacles if
                              hasattr(obs, 'position')]
            },
            "army1": self.army1.to_dict(),
            "army2": self.army2.to_dict(),
            "units": units_by_id,
            "general1": general1_state,
            "general2": general2_state
        }

    def _serialize_general_state(self, general):
        """Serialize general's AI state (state of mind, planning, etc.)."""
        state = {}
        # Save GeneralClever specific state
        if hasattr(general, '_is_deployed'):
            state['_is_deployed'] = general._is_deployed
        if hasattr(general, '_max_hp_cache'):
            state['_max_hp_cache'] = general._max_hp_cache
        if hasattr(general, '_deployment_threshold'):
            state['_deployment_threshold'] = general._deployment_threshold
        return state

    @classmethod
    def from_dict(cls, data):
        """Reconstruct Battle from dictionary."""
        battle = cls()
        battle.tick = data.get("tick", 0)
        battle.max_tick = data.get("max_tick", None)

        # Reconstruct map
        from backend.Class.Map import Map
        map_data = data.get("map", {})
        battle.map = Map(map_data.get("width", 100), map_data.get("height", 100))

        # Reconstruct units
        units_by_id = {}
        units_data = data.get("units", {})
        for unit_id, unit_data in units_data.items():
            unit_type = unit_data["unit_type"]
            position = tuple(unit_data["position"]) if unit_data.get("position") else None
            army_name = unit_data.get("army", "army1")

            if unit_type == "Knight":
                unit = Knight(position)
            elif unit_type == "Pikeman":
                unit = Pikeman(position)
            elif unit_type == "Crossbowman":
                unit = Crossbowman(position)
            else:
                continue

            # Restore unit ID (override the auto-generated one)
            unit._Unit__id = unit_id

            # Restore unit state
            unit.hp = unit_data.get("hp", unit.hp)
            unit.cooldown = unit_data.get("cooldown", 0)
            units_by_id[unit_id] = unit

        # Reconstruct armies
        from backend.Class.Army import Army
        army1_data = data.get("army1", {})
        army2_data = data.get("army2", {})

        battle.army1 = Army(army1_data.get("owner"))
        battle.army2 = Army(army2_data.get("owner"))

        for unit_id in army1_data.get("unit_ids", []):
            if unit_id in units_by_id:
                battle.army1.add_unit(units_by_id[unit_id])

        for unit_id in army2_data.get("unit_ids", []):
            if unit_id in units_by_id:
                battle.army2.add_unit(units_by_id[unit_id])

        # Reconstruct generals with AI state
        general1_data = data.get("general1", {})
        general2_data = data.get("general2", {})

        if general1_data:
            general1 = general_from_name(general1_data["class"])()
            battle._restore_general_state(general1, general1_data.get("state", {}))
            battle.army1.general = general1
            general1.army = battle.army1

        if general2_data:
            general2 = general_from_name(general2_data["class"])()
            battle._restore_general_state(general2, general2_data.get("state", {}))
            battle.army2.general = general2
            general2.army = battle.army2

        # Link armies and map to battle
        battle.army1.gameMode = battle
        battle.army2.gameMode = battle
        battle.map.gameMode = battle

        return battle

    def _restore_general_state(self, general, state):
        """Restore general's AI state."""
        if hasattr(general, '_is_deployed') and '_is_deployed' in state:
            general._is_deployed = state['_is_deployed']
        if hasattr(general, '_max_hp_cache') and '_max_hp_cache' in state:
            general._max_hp_cache = state['_max_hp_cache']
        if hasattr(general, '_deployment_threshold') and '_deployment_threshold' in state:
            general._deployment_threshold = state['_deployment_threshold']
