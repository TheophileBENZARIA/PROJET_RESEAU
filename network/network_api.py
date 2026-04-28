import socket
import json
import threading
import queue
import re

_TYPES_SEQUENCES = {"SYNC_UPDATE"}

class NetworkBridge:
    def __init__(self, host='127.0.0.1', port=5000):
        self.host = host
        self.port = port
        self.sock = None
        self.is_connected = False
        self.incoming_queue = queue.Queue()
        self.receive_thread = None
        self.proxy_process = None
        self._seq_out = 0
        # Track sequence numbers per sender: self._seq_in[sender_addr][msg_type]
        self._seq_in = {}

    def connect(self, remote_ip=None, lan_port=6000, remote_port=6000):
        try:
            import subprocess
            import os
            proxy_path = os.path.join("network", "proxy_udp_multiplayers.exe")
            if not os.path.exists(proxy_path): proxy_path = "proxy_udp_multiplayers.exe"

            args = [proxy_path, (remote_ip if remote_ip else "server"), str(self.port), str(lan_port), str(remote_port)]
            print(f"[NetworkBridge] Launching Proxy: {args}")
            self.proxy_process = subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
        except Exception as e:
            print(f"[NetworkBridge] Warning: Proxy start failed: {e}")

        import time
        time.sleep(0.5)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(1.0)
        self.server_addr = (self.host, self.port)
        self.is_connected = True
        self.sock.sendto(b"\n", self.server_addr) # Poke proxy

        self.receive_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.receive_thread.start()
        return True

    def _listen_loop(self):
        # Regex to match "[IP:PORT]JSON"
        tag_regex = re.compile(r"^\[(\d+\.\d+\.\d+\.\d+):(\d+)\](.*)$")
        
        while self.is_connected:
            try:
                data, addr = self.sock.recvfrom(65535)
                if not data: continue
                
                raw_str = data.decode('utf-8', errors='ignore').strip()
                if not raw_str: continue

                # Extract sender info from tag
                match = tag_regex.match(raw_str)
                if not match: continue # Ignore untagged packets (like proxy startup pokes)
                
                sender_ip = match.group(1)
                sender_port = int(match.group(2))
                json_str = match.group(3)
                sender_id = f"{sender_ip}:{sender_port}"

                try:
                    msg = json.loads(json_str)
                    msg["_sender_ip"] = sender_ip
                    msg["_sender_port"] = sender_port
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")
                seq = msg.get("seq", -1)

                if msg_type in _TYPES_SEQUENCES and seq != -1:
                    if sender_id not in self._seq_in: self._seq_in[sender_id] = {}
                    dernier = self._seq_in[sender_id].get(msg_type, -1)
                    if seq <= dernier: continue
                    self._seq_in[sender_id][msg_type] = seq

                self.incoming_queue.put(msg)

            except socket.timeout: continue
            except Exception as e:
                if self.is_connected: print(f"[NetworkBridge] Recv error: {e}")
                break

    def send_message(self, msg_type, destination, payload_dict=None, dest_port=None):
        if not self.is_connected: return False
        self._seq_out += 1
        message = {
            "dest": destination,
            "dest_port": dest_port,
            "seq": self._seq_out,
            "type": msg_type,
            "payload": payload_dict if payload_dict else {}
        }
        try:
            donnees = json.dumps(message, separators=(',', ':')) + '\n'
            self.sock.sendto(donnees.encode('utf-8'), self.server_addr)
            return True
        except Exception as e:
            print(f"[NetworkBridge] Send error: {e}")
            return False

    def get_updates(self):
        updates = []
        while not self.incoming_queue.empty(): updates.append(self.incoming_queue.get())
        return updates

    def disconnect(self):
        self.is_connected = False
        if self.proxy_process:
            try: self.proxy_process.terminate()
            except: pass
        if self.sock: self.sock.close()
