# Python Project 2025–2026: MedievAIl BAIttle GenerAIl

Source :
https://drive.google.com/file/d/1BHxEBfnQlzLeh-AHwUvqT_n3qOcvhRAp/view?usp=drive_link
https://drive.google.com/file/d/1T1PBgwUbtoPRrT4uYkOi8iOA9RJ1wf_O/view?usp=drive_link

<details>
<summary>📑 Contents</summary>

- [About The Project](#about-the-project)
- [Built With](#built-with)
- [Installation](#installation)

</details>

## Built With

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Pygame](https://img.shields.io/badge/Pygame-00A300?style=for-the-badge)

## Usage

### Online Battle Commands

- `python main.py online --create --pygame --army_file army\*.army --map_file map\*.map --general MajorDaft`
  Crée une bataille et attend que quelqu'un se connecte
- `python main.py online --join 192.168.10.3 --curses --army_file army\*.army --map_file map\*.map --general MajorDaft`  
  Rejoin une bataille auquel participe l'ordinateur avec l'ip 192.168.10.3.

### Offline Battle Commands

- `python main.py run --pygame --army_file army\*.army --map_file map\*.map --general1 (choose general ex: MajorDaft) --general2 (choose general ex: MajorDaft)`  
  Launches a **pygame battle** (60 FPS display).

- `python main.py run --curses --army_file army\*.army --map_file map\*.map --general1 (choose general ex: MajorDaft) --general2 (choose general ex: MajorDaft)`  
  Same setup but with the **ASCII / curses terminal view**.  
  Requires a curses-capable terminal  
  (`pip install windows-curses` on Windows).

---

### In-game Controls

#### Pygame (`PyScreen.py`)

- **Arrow keys**: pan camera (speed scales with zoom)
- **1 / 2**: zoom in / zoom out
- **C**: reset camera to center
- **Space**: pause / resume simulation (big overlay in middle)
- **Esc**: close the window (or exit load menu)
- **M**: toggle minimap
- **F1**: toggle stats panel
- **F2 / F3**: show / hide Army 1 / Army 2 details
- **F4**: toggle per-unit-type counts
- **Tab**: open quick-load menu (if implemented)
- **Mouse wheel / HZ**: not configured
- Army units show colored outlines; smooth motion handled automatically

---

#### Curses terminal view (`Screen.py`)

- **Arrow keys** or **H / J / K / L**: scroll viewport  
  (use uppercase **HJKL** or **Shift + arrows** to move faster)
- **Z / S / Q / D**: alternative ZQSD movement (uppercase for faster)
- **P**: pause / resume battle ticks
- **Tab**: pause and generate an **HTML snapshot**  
  (`battle_snapshot_*.html`) which opens in your browser
- **Esc**: exit the battle view
- **Save / Load menu** (if visible):
  - **S**: quick-save
  - **L**: open load menu

---

### Mode multi-pairs (P2P) & Ownership Manager

Ce projet supporte désormais le jeu en multi-pairs (plus de 2 joueurs) et utilise un **Ownership Manager** pour garantir la cohérence.

#### Comment tester localement (même machine / LAN)

Grâce à l'allocation automatique des ports, vous n'avez plus besoin de spécifier les ports manuellement pour tester sur une même machine.

**Terminal 1 (Host - Créateur)**
```powershell
python main.py online --create --general MajorDaft --army_file army/two.army --map_file map/superflat.map --pygame
```

**Terminal 2 (Client 1)**
```powershell
python main.py online --join 127.0.0.1 --general MajorDaft --army_file army/two.army --map_file map/superflat.map --pygame
```

**Terminal 3 (Client 2)**
```powershell
python main.py online --join 127.0.0.1 --general MajorDaft --army_file army/two.army --map_file map/superflat.map --pygame
```

**Terminal 4 (Client 3)**
```powershell
python main.py online --join 127.0.0.1 --general MajorDaft --army_file army/two.army --map_file map/superflat.map --pygame
```

---

#### Comment tester via Internet (vraie IP / VPN) — `proxy_udp_real_ip` gcc -o network/proxy_udp_real_ip.exe network/proxy_udp_real_ip.c -lws2_32


Le proxy `proxy_udp_real_ip.exe` gère automatiquement la traversée NAT (UDP hole-punching).

> **Prérequis** : Le port **6000 UDP** doit être ouvert / forwardé sur le routeur du host, **OU** les deux machines doivent être sur le même VPN.

**Machine A — Host (attend la connexion)**
```powershell
python main.py online --create --general MajorDaft --army_file army/two.army --map_file map/superflat.map --pygame
```
Le proxy affichera `[LAN] Waiting for discovery` et votre IP locale. Communiquez votre IP publique (ou VPN) au joueur B.

**Machine B — Joiner (connaît l'IP du host)**
```powershell
python main.py online --join <IP_DU_HOST> --general MajorDaft --army_file army/two.army --map_file map/superflat.map --pygame
```
Remplacez `<IP_DU_HOST>` par l'IP publique (ou VPN) de la machine A.

**Ce qui se passe automatiquement :**
1. Le proxy du Joiner envoie des paquets `HELLO` toutes les 2 secondes vers le Host pour ouvrir le NAT.
2. Le proxy du Host détecte le premier paquet entrant et enregistre l'IP/port du Joiner.
3. Une fois les deux proxies synchronisés, les paquets de jeu s'échangent normalement.
4. La console affichera `-> [LAN] Peer discovered:` suivi de l'IP distante.

#### Ownership Manager
L'Ownership Manager (`backend/Utils/network_ownership.py`) assure que :
- Chaque unité a un unique propriétaire identifié par son UUID.
- Seul le propriétaire peut exécuter les actions (mouvements, attaques) de ses unités.
- Les autres clients reçoivent l'état mis à jour et l'appliquent localement.
- Supporte la découverte dynamique de nouveaux pairs.

###Linux
gcc -o network/proxy_udp_real_ip.x network/proxy_udp_real_ip.c -pthread
python3 main.py online --create --general MajorDaft --army_file army/cube2.army --map_file map/superflat.map --pygame
python3 main.py online --join [ip] --general MajorDaft --army_file army/cube2.army --map_file map/superflat.map --pygame
