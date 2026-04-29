import socket
import json
import threading
import queue

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

# Types de messages dont l'ordre est critique :
# si un paquet plus récent est arrivé avant, l'ancien est ignoré.
_TYPES_SEQUENCES = {"SYNC_UPDATE"}


class NetworkBridge:
    def __init__(self, host='127.0.0.1', port=5000):
        self.host = host
        self.port = port
        self.sock = None
        self.is_connected = False

        # File d'attente thread-safe
        # Sépare le thread réseau de la boucle principale du jeu
        self.incoming_queue = queue.Queue()
        self.receive_thread = None

        # Handle to the Proxy C subprocess
        self.proxy_process = None

        # Numéro de séquence sortant : incrémenté à chaque envoi
        self._seq_out = 0

        # Dernier numéro de séquence reçu par type de message
        # (seuls les types dans _TYPES_SEQUENCES sont filtrés)
        self._seq_in = {}

    # ---- Connexion ----
    def connect(self, remote_ip=None, lan_port=6000, remote_port=6000):
        """Ouvre le socket UDP local, démarre le proxy C et le thread de réception."""
        
        # Démarrage automatique du programme C Proxy
        try:
            import subprocess
            import os

            program_name = "proxy_udp_real_ip"
            if os.name == 'nt' :
                program_name = "proxy_udp_real_ip.exe"
            
            # Paths relative to project root or current dir
            proxy_path = os.path.join("network", program_name)
            if not os.path.exists(proxy_path):
                # Try local dir if not in network/
                proxy_path = program_name

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

        # Give Proxy C a moment to bind to its ports
        import time
        time.sleep(0.5)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Timeout de 1 s : le thread peut vérifier is_connected périodiquement
        self.sock.settimeout(1.0)
        self.server_addr = (self.host, self.port)
        self.is_connected = True

        # Premier paquet pour que le Proxy C enregistre notre port éphémère
        self.sock.sendto(b"\n", self.server_addr)

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
        while self.is_connected:
            try:
                data, addr = self.sock.recvfrom(65535)
                if not data:
                    continue

                ligne = data.decode('utf-8').strip()
                if not ligne:
                    continue

                try:
                    msg = json.loads(ligne)
                    # Include sender IP for peer discovery
                    msg["_sender_ip"] = addr[0]
                except json.JSONDecodeError:
                    # Paquet corrompu ou tronqué (fragmentation UDP) → ignorer
                    print(f"[NetworkBridge] Erreur JSON ignorée "
                          f"({len(ligne)} octets reçus)")
                    continue

                msg_type = msg.get("type")
                seq      = msg.get("seq", -1)

                # ---- Filtre de réordonnancement ----
                # Pour les types sensibles à l'ordre (ex: SYNC_UPDATE),
                # on ignore tout paquet dont le seq est inférieur ou égal
                # au dernier seq reçu : c'est un paquet retardé.
                if msg_type in _TYPES_SEQUENCES and seq != -1:
                    dernier = self._seq_in.get(msg_type, -1)
                    if seq <= dernier:
                        # Paquet hors ordre → ignorer silencieusement
                        continue
                    self._seq_in[msg_type] = seq

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
    def send_message(self, msg_type, destination, payload_dict=None):
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

        message = {
            "size": len(payload_dict),
            "dest": destination,
            "dep": None , #recuperer l'ip de la machine
            "seq":     self._seq_out,
            "type":    msg_type,
            "payload": payload_dict
        }

        try:
            # JSON compact : pas d'espaces → taille minimale
            donnees = json.dumps(message, separators=(',', ':')) + '\n'
            self.sock.sendto(donnees.encode('utf-8'), self.server_addr)

            # Avertir si le datagramme dépasse le MTU standard (1500 octets)
            taille = len(donnees.encode('utf-8'))
            if taille > 1400:
                print(f"[NetworkBridge] ATTENTION : datagramme volumineux "
                      f"({taille} octets, MTU ≈ 1500). Risque de fragmentation !")
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