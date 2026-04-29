import socket
import json
import threading
import queue
import zlib
import uuid

# ============================================================
#   NetworkBridge — Pont réseau Python ↔ Proxy C (UDP)
#
#   Fonctionnalités clés :
#   - Numérotation de séquence : chaque paquet sortant estampillé
#     "seq". Les paquets de type SYNC_UPDATE reçus hors ordre
#     (seq ≤ dernier seq reçu) sont ignorés, évitant l'erreur
#     de logique causée par le réordonnancement UDP.
#   - JSON compact : separators=(',',':') supprime les espaces
#     inutiles et minimise la taille du datagramme UDP pour
#     rester sous la limite MTU de 1500 octets.
#   - Socket timeout de 1 s : le thread peut vérifier
#     is_connected et sortir proprement sans WinError 10038.
# ============================================================

from network.security_manager import SecurityManager

# Types de messages dont l'ordre est critique :
# si un paquet plus récent est arrivé avant, l'ancien est ignoré.
_TYPES_SEQUENCES = {"SYNC_UPDATE"}


class NetworkBridge:
    def __init__(self, host='127.0.0.1', port=5000, security_enabled=True):
        self.host = host
        self.port = port
        self.sock = None
        self.is_connected = False
        self.security_manager = SecurityManager() if security_enabled else None

        # File d'attente thread-safe
        # Sépare le thread réseau de la boucle principale du jeu
        self.incoming_queue = queue.Queue()
        self.receive_thread = None
        self._partial_messages = {}  # For reassembling chunked packets

        # Handle to the Proxy C subprocess
        self.proxy_process = None

        # Numéro de séquence sortant : incrémenté à chaque envoi
        self._seq_out = 0

        # Dernier numéro de séquence reçu par type de message
        # (seuls les types dans _TYPES_SEQUENCES sont filtrés)
        self._seq_in = {}

        # Our own public/LAN IP — embedded in every outgoing packet
        # so that the remote peer can discover our address even though
        # ALL packets arrive locally from 127.0.0.1 (proxy loopback).
        self._my_ip = self._detect_my_ip()

    @staticmethod
    def _detect_my_ip():
        """Best-effort detection of the machine's outbound IP address."""
        import socket as _sock
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))        # doesn't actually send anything
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _sender_key_from_message(self, msg):
        if "sender_id" in msg:
            return msg["sender_id"]
        payload = msg.get("payload", {})
        if isinstance(payload, dict):
            if "peer_id" in payload:
                return payload["peer_id"]
            armies = payload.get("armies", payload)
            if isinstance(armies, dict) and armies:
                return next(iter(armies.keys()))
        return msg.get("dep") or msg.get("_sender_ip") or "unknown"


    # ---- Connexion ----
    def connect(self, remote_ip=None, lan_port=6000, remote_port=6000):
        """Ouvre le socket UDP local, démarre le proxy C et le thread de réception."""
        
        # Démarrage automatique du programme C Proxy
        try:
            import subprocess
            import os

            program_extension = ""
            if os.name == "nt":
                program_extension = ".exe"

            # Prefer proxy_udp_real_ip.exe for multi-device testing if available
            proxy_real_ip = os.path.join("network", "proxy_udp_real_ip" + program_extension)
            proxy_standard = os.path.join("network", "proxy_udp" + program_extension)

            if os.path.exists(proxy_real_ip):
                proxy_path = proxy_real_ip
            elif os.path.exists(proxy_standard):
                proxy_path = proxy_standard
            else:
                # Fallback to local dir
                proxy_path = "proxy_udp" + program_extension

            args = [proxy_path]
            if remote_ip:
                args.append(remote_ip)
            else:
                args.append("peer")
            
            # Use provided ports
            args.append(str(self.port))      # py_port
            args.append(str(lan_port))     # lan_listen_port
            args.append(str(remote_port))  # remote_dest_port

            print(f"[NetworkBridge] Starting Proxy C: {args}")
            self.proxy_process = subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
        except Exception as e:
            print(f"[NetworkBridge] Warning: Could not start Proxy C automatically: {e}")

        # Give Proxy C a moment to bind to its ports and punch through NAT
        import time
        time.sleep(1.0)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65535)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65535)
        except Exception as e:
            print(f"[NetworkBridge] Warning: Could not set socket buffer size: {e}")
        
        # Timeout de 1 s : le thread peut vérifier is_connected périodiquement
        self.sock.settimeout(1.0)
        self.server_addr = (self.host, self.port)

        self.is_connected = True

        # Premier paquet pour que le Proxy C enregistre notre port éphémère
        self.sock.sendto(b"\n", self.server_addr)

        print(f"[NetworkBridge] Mon IP détectée : {self._my_ip}")
        print("[NetworkBridge] Prêt en UDP ! (Proxy C sur port {})".format(self.port))

        # Lancer le thread de réception en arrière-plan (daemon = stoppe avec le jeu)
        self.receive_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.receive_thread.start()
        return True

    # ---- Thread de réception ----
    def _listen_loop(self):
        """
        Thread en arrière-plan :
        - Reçoit les datagrammes UDP depuis le Proxy C.
        - Filtre les paquets obsolètes (numéro de séquence trop ancien).
        - Place les messages valides dans la file d'attente.
        """
        _recv_count = 0
        while self.is_connected:
            try:
                data, addr = self.sock.recvfrom(65535)
                if not data:
                    continue

                # ---- Chunk reassembly ----
                if data[:6] == b"CHUNK\0":
                    try:
                        parts = data[6:].split(b"\0", 2)
                        msg_id = parts[0].decode('utf-8')
                        info = parts[1].split(b":")
                        chunk_idx = int(info[0])
                        total = int(info[1])
                        chunk_data = parts[2]

                        if msg_id not in self._partial_messages:
                            self._partial_messages[msg_id] = [None] * total
                        self._partial_messages[msg_id][chunk_idx] = chunk_data

                        if None not in self._partial_messages[msg_id]:
                            data = b"".join(self._partial_messages[msg_id])
                            del self._partial_messages[msg_id]
                        else:
                            continue
                    except Exception as e:
                        print(f"[NetworkBridge] Erreur reassemblage chunk: {e}")
                        continue

                    # Purge stale incomplete messages (older than 64 entries)
                    if len(self._partial_messages) > 64:
                        oldest = list(self._partial_messages.keys())[:len(self._partial_messages) - 32]
                        for k in oldest:
                            del self._partial_messages[k]

                try:
                    data = zlib.decompress(data)
                except zlib.error:
                    pass # Fallback to uncompressed
                    
                try:
                    ligne = data.decode('utf-8').strip()
                except UnicodeDecodeError:
                    continue
                    
                _recv_count += 1
                if _recv_count <= 5 or _recv_count % 50 == 0:
                    print(f"[NetworkBridge] RAW recv #{_recv_count}: {len(data)} bytes from {addr}")
                if not ligne:
                    continue

                try:
                    msg = json.loads(ligne)
                    # The proxy always forwards from 127.0.0.1, so addr[0]
                    # is useless for peer discovery.  Instead we read the
                    # "dep" field that the sender embedded in the packet.
                    dep = msg.get("dep")
                    if dep and dep != "127.0.0.1":
                        msg["_sender_ip"] = dep
                    else:
                        msg["_sender_ip"] = addr[0]   # fallback (LAN / same machine)
                except json.JSONDecodeError:
                    # Paquet corrompu ou tronqué (fragmentation UDP) → ignorer
                    print(f"[NetworkBridge] Erreur JSON ignorée "
                          f"({len(ligne)} octets reçus)")
                    continue

                msg_type = msg.get("type")
                seq      = msg.get("seq", -1)
                sender_key = self._sender_key_from_message(msg)

                # ---- Security Decryption & Verification ----
                if self.security_manager and msg_type not in ["SECURE_HELLO", "SECURE_KEY_EXCHANGE"]:
                    payload = msg.get("payload")
                    if isinstance(payload, dict) and "ciphertext" in payload:
                        # Find peer_id (sender_key might be the ID if already known)
                        peer_id = sender_key
                        decrypted_payload, error = self.security_manager.decrypt_and_verify(peer_id, payload)
                        if decrypted_payload:
                            msg["payload"] = decrypted_payload
                        else:
                            print(f"[NetworkBridge] Security Error from {peer_id}: {error}")
                            continue

                # ---- Filtre de réordonnancement ----
                # Pour les types sensibles à l'ordre (ex: SYNC_UPDATE),
                # on ignore tout paquet dont le seq est inférieur ou égal
                # au dernier seq reçu : c'est un paquet retardé.
                if msg_type in _TYPES_SEQUENCES and seq != -1:
                    seq_key = (msg_type, sender_key)
                    dernier = self._seq_in.get(seq_key, -1)
                    if seq <= dernier:
                        # Paquet hors ordre → ignorer silencieusement
                        continue
                    self._seq_in[seq_key] = seq

                self.incoming_queue.put(msg)

            except socket.timeout:
                # Timeout normal : reboucler et vérifier is_connected
                continue
            except ConnectionResetError:
                # Sur Windows, se produit si le Proxy n'est pas encore prêt (ICMP Port Unreachable)
                # On ignore et on continue d'écouter
                continue
            except OSError:
                # Socket fermé par disconnect() → sortie propre
                break
            except Exception as e:
                if self.is_connected:
                    print(f"[NetworkBridge] Erreur dans le thread de réception : {e}")
                break

        print("[NetworkBridge] Thread de réception arrêté.")

    # ---- Envoi de messages ----
    def send_message(self, msg_type, destination, payload_dict=None, peer_id=None):
        """
        Envoie un message JSON vers le Proxy C en UDP.

        Structure du datagramme :
        {
            "size": <taille en octets>
            "dest" : <ip destination>
            "dep" : <ip depart>
            "seq":     <numéro de séquence entier croissant>,
            "type":    <type du message>,
            "payload": <données utiles>
        }

        Le JSON est sérialisé sans espaces (separators=(',',':'))
        pour minimiser la taille et rester sous le MTU de 1500 octets.
        """
        if not self.is_connected:
            return False

        if payload_dict is None:
            payload_dict = {}

        # Horodatage par numéro de séquence
        self._seq_out += 1

        # ---- Security Encryption & Signing ----
        if self.security_manager and msg_type not in ["SECURE_HELLO", "SECURE_KEY_EXCHANGE"] and peer_id:
            secure_payload = self.security_manager.sign_and_encrypt(peer_id, payload_dict)
            if secure_payload:
                payload_dict = secure_payload
            else:
                # If we have a peer_id but no session key, we might need to handshake first
                if peer_id in self.security_manager.peer_public_keys:
                    print(f"[NetworkBridge] Warning: No session key for {peer_id}, sending unencrypted.")

        message = {
            "size": len(payload_dict),
            "dest": destination,
            "dep":  self._my_ip,   # our real IP so the remote side can add us to know_ip
            "sender_id": getattr(self, "my_id", "unknown"),
            "seq":  self._seq_out,
            "type": msg_type,
            "payload": payload_dict
        }


        try:
            # JSON compact : pas d'espaces → taille minimale
            donnees_str = json.dumps(message, separators=(',', ':'))
            donnees = zlib.compress(donnees_str.encode('utf-8'))

            # ---- Chunking : split large datagrams to avoid IP fragmentation ----
            CHUNK_SIZE = 1200  # Safe margin below 1500 MTU (header overhead)
            if len(donnees) > CHUNK_SIZE:
                msg_id = uuid.uuid4().hex
                total = (len(donnees) + CHUNK_SIZE - 1) // CHUNK_SIZE
                for i in range(total):
                    chunk = donnees[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
                    header = b"CHUNK\0" + msg_id.encode() + b"\0" + f"{i}:{total}".encode() + b"\0"
                    self.sock.sendto(header + chunk, self.server_addr)
            else:
                self.sock.sendto(donnees, self.server_addr)

            # Avertir si le datagramme dépasse le MTU standard (1500 octets)
            taille = len(donnees)
            if taille > 1400 and taille <= CHUNK_SIZE:
                print(f"[NetworkBridge] ATTENTION : datagramme volumineux "
                      f"({taille} octets, MTU ~ 1500). Risque de fragmentation !")
            return True
        except Exception as e:
            print(f"[NetworkBridge] Erreur lors de l'envoi ({msg_type}) : {e}")
            return False

    # ---- Lecture non-bloquante ----
    def get_updates(self):
        """
        Retourne tous les messages disponibles dans la file,
        sans bloquer la boucle de jeu principale.
        """
        messages = []
        while not self.incoming_queue.empty():
            messages.append(self.incoming_queue.get())
        return messages

    # ---- Déconnexion propre ----
    def disconnect(self):
        """
        Ferme la connexion de façon sécurisée :
        is_connected = False d'abord → le thread sort à son prochain
        timeout → puis on ferme le socket (évite WinError 10038).
        """
        self.is_connected = False   # Signal au thread de s'arrêter
        
        # Terminer le processus Proxy C s'il est en cours
        if self.proxy_process:
            try:
                self.proxy_process.terminate()
                print("[NetworkBridge] Proxy C terminé.")
            except Exception as e:
                print(f"[NetworkBridge] Erreur lors de la fermeture du Proxy C : {e}")
            self.proxy_process = None

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None