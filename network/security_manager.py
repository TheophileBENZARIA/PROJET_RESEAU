import time
import json
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import os

class SecurityManager:
    def __init__(self, ttl_limit=5.0):
        self.ttl_limit = ttl_limit
        # Generate our own keys
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        self.public_key = self.private_key.public_key()
        
        # Store peer public keys: {peer_id: public_key_object}
        self.peer_public_keys = {}
        # Store peer session keys: {peer_id: aes_key}
        self.peer_session_keys = {}
        
        # Replay protection: track highest seq seen per peer
        self.peer_last_timestamp = {}
        # Outgoing sequence counter (monotonic, per instance)
        self._send_seq = 0

    def get_my_public_key_pem(self):
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

    def register_peer(self, peer_id, public_key_pem):
        """Registers a peer's public key."""
        try:
            public_key = serialization.load_pem_public_key(
                public_key_pem.encode('utf-8'),
                backend=default_backend()
            )
            self.peer_public_keys[peer_id] = public_key
            return True
        except Exception as e:
            print(f"[SecurityManager] Error registering peer {peer_id}: {e}")
            return False

    def create_session_key(self, peer_id):
        """Generates a symmetric key for a peer and returns it encrypted with their public key."""
        if peer_id not in self.peer_public_keys:
            return None
        
        if peer_id in self.peer_session_keys:
            session_key = self.peer_session_keys[peer_id]
        else:
            session_key = os.urandom(32) # AES-256
            self.peer_session_keys[peer_id] = session_key
        
        encrypted_key = self.peer_public_keys[peer_id].encrypt(
            session_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        return base64.b64encode(encrypted_key).decode('utf-8')

    def handle_session_key(self, peer_id, encrypted_key_b64):
        """Decrypts a session key sent by a peer."""
        try:
            encrypted_key = base64.b64decode(encrypted_key_b64)
            session_key = self.private_key.decrypt(
                encrypted_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            self.peer_session_keys[peer_id] = session_key
            return True
        except Exception as e:
            print(f"[SecurityManager] Error handling session key from {peer_id}: {e}")
            return False

    def sign_and_encrypt(self, peer_id, payload):
        """Signs and encrypts a payload for a specific peer."""
        # Work on a copy to avoid modifying the original dictionary (important for multi-peer broadcast)
        payload = payload.copy()
        
        # 1. Add TTL (timestamp) + monotonic sequence for replay protection
        self._send_seq += 1
        payload["timestamp"] = time.time()
        payload["_seq"] = self._send_seq
        
        json_payload = json.dumps(payload).encode('utf-8')
        
        # 2. Digital Signature
        signature = self.private_key.sign(
            json_payload,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        # 3. Symmetric Encryption (AES)
        # We use AES-GCM for authenticated encryption (encryption + integrity)
        if peer_id not in self.peer_session_keys:
            # Fallback to signing only or fail? 
            # For strict security, we should have a session key.
            return None, None
            
        session_key = self.peer_session_keys[peer_id]
        iv = os.urandom(12)
        encryptor = Cipher(
            algorithms.AES(session_key),
            modes.GCM(iv),
            backend=default_backend()
        ).encryptor()
        
        ciphertext = encryptor.update(json_payload) + encryptor.finalize()
        
        secure_msg = {
            "iv": base64.b64encode(iv).decode('utf-8'),
            "ciphertext": base64.b64encode(ciphertext).decode('utf-8'),
            "tag": base64.b64encode(encryptor.tag).decode('utf-8'),
            "signature": base64.b64encode(signature).decode('utf-8')
        }
        
        return secure_msg

    def decrypt_and_verify(self, peer_id, secure_msg):
        """Decrypts and verifies a message from a peer."""
        try:
            if peer_id not in self.peer_session_keys or peer_id not in self.peer_public_keys:
                return None, "Missing keys for peer"

            iv = base64.b64decode(secure_msg["iv"])
            ciphertext = base64.b64decode(secure_msg["ciphertext"])
            tag = base64.b64decode(secure_msg["tag"])
            signature = base64.b64decode(secure_msg["signature"])
            
            # 1. Decrypt
            session_key = self.peer_session_keys[peer_id]
            decryptor = Cipher(
                algorithms.AES(session_key),
                modes.GCM(iv, tag),
                backend=default_backend()
            ).decryptor()
            
            json_payload_bytes = decryptor.update(ciphertext) + decryptor.finalize()
            
            # 2. Verify Signature
            self.peer_public_keys[peer_id].verify(
                signature,
                json_payload_bytes,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            payload = json.loads(json_payload_bytes.decode('utf-8'))
            
            # 3. Verify TTL and replay protection via monotonic sequence
            msg_timestamp = payload.get("timestamp", 0)
            current_time = time.time()
            
            if current_time - msg_timestamp > self.ttl_limit:
                return None, "Message expired (TTL)"
            
            # Use _seq for replay detection (strictly increasing per sender)
            msg_seq = payload.get("_seq", None)
            last_seq = self.peer_last_timestamp.get(peer_id, -1)
            if msg_seq is not None:
                if msg_seq <= last_seq:
                    return None, "Replay attack detected (seq older or equal to last seen)"
                self.peer_last_timestamp[peer_id] = msg_seq
            else:
                # Legacy fallback: timestamp-based (allow equal timestamps)
                if msg_timestamp < self.peer_last_timestamp.get(peer_id + "_ts", 0):
                    return None, "Replay attack detected (timestamp too old)"
                self.peer_last_timestamp[peer_id + "_ts"] = msg_timestamp
            
            return payload, None
            
        except Exception as e:
            return None, f"Security verification failed: {str(e)}"
