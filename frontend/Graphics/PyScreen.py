import sys
import time
import zlib
import os
from time import sleep

import pygame

from backend.Class.Army import Army
from backend.Class.Map import Map
from backend.Class.Obstacles.Rocher import Rocher
from backend.Class.Units.Castle import Castle
from backend.Class.Units.Crossbowman import Crossbowman
from backend.Class.Units.Elephant import Elephant
from backend.Class.Units.Knight import Knight
from backend.Class.Units.Monk import Monk
from backend.Class.Units.Pikeman import Pikeman
from frontend.Affichage import Affichage


class PyScreen(Affichage):

    def initialiser(self):
        # Initialisation de Pygame
        pygame.init()
        # Création de la fenêtre principale
        self.WIDTH, self.HEIGHT = 1280, 720
        self.screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT))
        pygame.display.set_caption("Affichage de la Bataille - Projet Réseau")

        self.offset_x, self.offset_y = 0, 0
        self.zoom_factor = 20
        self.unit_scale_multiplier = 4.5  # Multiplicateur pour agrandir les unités

        # Paramètres de la vue isométrique
        self.tile_size = 10  # Taille de base d'une tuile

        # Charger les images (tuiles et unités)
        # Utiliser .png par défaut pour une meilleure gestion de la transparence sur Linux
        self.TILE_IMAGE = pygame.image.load(os.path.join(self.path, "tile.png")).convert_alpha()
        self.KNIGHT_IMAGE = pygame.image.load(os.path.join(self.path, "knight.png")).convert_alpha()
        self.PIKEMAN_IMAGE = pygame.image.load(os.path.join(self.path, "pikeman.png")).convert_alpha()
        self.CROSSBOWMAN_IMAGE = pygame.image.load(os.path.join(self.path, "crossbowman.png")).convert_alpha()
        self.ROCHER_IMAGE = pygame.image.load(os.path.join(self.path, "rocher.png")).convert_alpha()
        self.CASTLE_IMAGE = pygame.image.load(os.path.join(self.path, "castle.png")).convert_alpha()
        self.ELEPHANT_IMAGE = pygame.image.load(os.path.join(self.path, "elephant.png")).convert_alpha()
        self.MONK_IMAGE = pygame.image.load(os.path.join(self.path, "monk.png")).convert_alpha()

        # Cache pour les tuiles transformées
        self._last_zoom = None
        self.TILE_LIGHT = None
        self.TILE_DARK = None

        # Variables pour les animations fluides
        self.unit_previous_positions = {}
        self.unit_animation_start_pos = {}
        self.animation_start_time = {}
        self.animation_duration = 0.45

        # Paramètres de la minimap et de l'UI
        self.show_minimap = True
        self.minimap_size = 200
        self.minimap_position = (self.WIDTH - self.minimap_size - 10, 10)

        # Affichage des statistiques
        self.show_army_stats = True
        self.show_army1_details = True
        self.show_army2_details = True
        self.show_unit_counts = True

        # Contrôle de la vitesse et de la pause
        self.battle_speed_multiplier = 1.0
        self.is_paused_state = False

        # Sauvegardes
        self.quick_save_filename = "quicksave.json"
        self.battle_instance = None
        self.show_load_menu = False
        self.load_menu_selected_index = 0

        # Initialisation de la police d'écriture
        pygame.font.init()
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)

        # Variables pour le contrôle à la souris (Glisser / Drag)
        self.is_dragging = False
        self.last_mouse_pos = (0, 0)

        # Variable pour centrer la caméra initialement
        self.camera_centered = False
        self.current_map_bounds = (0, 0, 0, 0) # (x_max, x_min, y_max, y_min)
        self.player_styles = {}
        self.color_palette = [
            (50, 100, 255),
            (255, 50, 50),
            (40, 200, 120),
            (240, 180, 40),
            (180, 80, 240),
            (40, 210, 220),
            (255, 120, 40),
            (230, 230, 80),
        ]

    def _label_for_slot(self, slot):
        if isinstance(slot, int):
            if 0 <= slot < 26:
                return f"Player {chr(ord('A') + slot)}"
            if slot < 0:
                return "Joining..."
        return f"Player {slot}"

    def _style_for_owner(self, owner_id, fallback_index=None):
        # 1. Handle special/fixed offline styles (Army 1 = Blue, Army 2 = Red)
        offline_styles = {
            "army1": ("Army 1", 0),
            "army2": ("Army 2", 1),
            "army": (f"Army {fallback_index or 1}", (fallback_index or 1) - 1),
        }
        if owner_id in offline_styles:
            label, color_index = offline_styles[owner_id]
            return {
                "label": label,
                "color": self.color_palette[color_index % len(self.color_palette)]
            }

        if getattr(self, "player_styles", None) is None:
            self.player_styles = {}

        # If already assigned this session, check if we need to update the label based on current peer_slots
        if owner_id in self.player_styles:
            style = self.player_styles[owner_id]
            peer_slots = getattr(getattr(self, "battle_instance", None), "peer_slots", {})
            if owner_id in peer_slots:
                try:
                    slot = int(peer_slots[owner_id])
                    new_label = self._label_for_slot(slot)
                    # Update label if it changed (e.g. from "Joining..." to "Player C")
                    if style["label"] != new_label:
                        style["label"] = new_label
                except (TypeError, ValueError):
                    pass
            return style

        # 2. Use stable hash for persistent colors based on owner_id (UID)
        # This ensures the same player (UID) always gets the same color from the palette.
        uid_str = str(owner_id)
        uid_hash = zlib.adler32(uid_str.encode('utf-8'))
        color_index = uid_hash % len(self.color_palette)

        # 3. Handle Label - we still try to use the peer_slots if available
        peer_slots = getattr(getattr(self, "battle_instance", None), "peer_slots", {})
        if owner_id in peer_slots:
            try:
                slot = int(peer_slots[owner_id])
                label = self._label_for_slot(slot)
            except (TypeError, ValueError):
                label = self._label_for_slot(color_index)
        else:
            # Fallback to order of discovery in the UI
            index = (fallback_index - 1) if fallback_index else len(self.player_styles)
            label = self._label_for_slot(index)
            
        style = {
            "label": label,
            "color": self.color_palette[color_index]
        }
        self.player_styles[owner_id] = style
        return style

    def _color_for_unit(self, unit, fallback_color):
        owner_id = getattr(unit, "network_owner_id", None)
        if owner_id is None:
            return fallback_color
        return self._style_for_owner(owner_id)["color"]

    def _label_for_owner(self, owner_id, fallback_index):
        return self._style_for_owner(owner_id, fallback_index)["label"]

    def _slot_for_owner(self, owner_id, fallback_index=None):
        peer_slots = getattr(getattr(self, "battle_instance", None), "peer_slots", {})
        if owner_id in peer_slots:
            try:
                return int(peer_slots[owner_id])
            except (TypeError, ValueError):
                pass
        return fallback_index if fallback_index is not None else 999

    def _get_interpolated_position(self, unit):
        """Obtenir la position interpolée pour une animation fluide."""
        if unit.position is None:
            return None

        unit_id = unit.id
        current_pos = unit.position

        if unit_id not in self.unit_previous_positions:
            # First time we see this unit: register and draw at its position
            self.unit_previous_positions[unit_id] = current_pos
            return current_pos

        stored_pos = self.unit_previous_positions[unit_id]

        if stored_pos != current_pos:
            # Position changed: start a new animation from stored_pos → current_pos
            self.unit_animation_start_pos[unit_id] = stored_pos
            self.animation_start_time[unit_id] = time.time()
            self.unit_previous_positions[unit_id] = current_pos
            # Return interpolated at t=0 (start of animation = old position)
            return stored_pos

        # Position stable: if an animation is in progress, continue it
        if unit_id in self.animation_start_time and unit_id in self.unit_animation_start_pos:
            elapsed = time.time() - self.animation_start_time[unit_id]
            if elapsed < self.animation_duration:
                start_pos = self.unit_animation_start_pos[unit_id]
                t = min(1.0, elapsed / self.animation_duration)
                # Utiliser une interpolation linéaire pour simuler la marche plutôt qu'un 'téléport' glissant
                interp_x = start_pos[0] + (current_pos[0] - start_pos[0]) * t
                interp_y = start_pos[1] + (current_pos[1] - start_pos[1]) * t
                return (interp_x, interp_y)
            else:
                # Animation finished, clean up
                del self.animation_start_time[unit_id]
                del self.unit_animation_start_pos[unit_id]

        return current_pos


    def _get_max_hp(self, unit):
        """Obtenir les points de vie max."""
        return unit.max_hp

    def _draw_hp_bar(self, unit, iso_x, iso_y, unit_size):
        """Dessiner la barre de vie."""
        max_hp = self._get_max_hp(unit)
        current_hp = max(0, unit.hp)
        hp_percentage = current_hp / max_hp if max_hp > 0 else 0

        bar_width = unit_size
        bar_height = 4
        bar_x = int(iso_x - bar_width // 2)
        bar_y = int(iso_y - unit_size // 2 - 10)

        pygame.draw.rect(self.screen, (40, 40, 40), (bar_x, bar_y, bar_width, bar_height))

        if hp_percentage > 0:
            hp_width = int(bar_width * hp_percentage)
            if hp_percentage > 0.6:
                hp_color = (50, 200, 50)  # Vert
            elif hp_percentage > 0.3:
                hp_color = (200, 200, 50)  # Jaune
            else:
                hp_color = (200, 50, 50)  # Rouge
            pygame.draw.rect(self.screen, hp_color, (bar_x, bar_y, hp_width, bar_height))

        pygame.draw.rect(self.screen, (255, 255, 255), (bar_x, bar_y, bar_width, bar_height), 1)

    def _draw_unit(self, unit, army_color):
        """Fonction pour dessiner une unité."""
        interp_pos = self._get_interpolated_position(unit)
        if interp_pos is None:
            return

        iso_x, iso_y = self.convert_to_iso(interp_pos)
        IMAGE = self.PIKEMAN_IMAGE
        if isinstance(unit, Knight):
            IMAGE = self.KNIGHT_IMAGE
        elif isinstance(unit, Pikeman):
            IMAGE = self.PIKEMAN_IMAGE
        elif isinstance(unit, Crossbowman):
            IMAGE = self.CROSSBOWMAN_IMAGE
        elif isinstance(unit, Monk):
            IMAGE = self.MONK_IMAGE
        elif isinstance(unit, Castle):
            IMAGE = self.CASTLE_IMAGE
        elif isinstance(unit, Elephant):
            IMAGE = self.ELEPHANT_IMAGE
        elif isinstance(unit, Rocher):
            IMAGE = self.ROCHER_IMAGE

        unit_size = int(unit.size * self.zoom_factor * self.unit_scale_multiplier)
        unit_image = pygame.transform.scale(IMAGE, (unit_size, unit_size))
        rect = unit_image.get_rect(center=(iso_x, iso_y))
        self.screen.blit(unit_image, rect.topleft)

        if army_color is not None:
            border_radius = unit_size // 2 + 3
            pygame.draw.circle(self.screen, army_color, (int(iso_x), int(iso_y)), border_radius, 2)
            self._draw_hp_bar(unit, iso_x, iso_y, unit_size)

    def afficher(self, map: Map, army1: Army, army2: Army):
        # Mettre à jour les limites actuelles pour la minimap et le centrage
        self.current_map_bounds = Affichage.get_sizeMap(map, army1, army2)

        # Centrer la caméra une seule fois au début
        if not self.camera_centered:
            x_max, x_min, y_max, y_min = self.current_map_bounds
            center_x = (x_max + x_min) / 2
            center_y = (y_max + y_min) / 2
            scaled_tile_size = self.tile_size * self.zoom_factor

            # Calcul de l'offset pour mettre le centre au milieu de l'écran
            self.offset_x = -((center_x - center_y) * scaled_tile_size / 2)
            self.offset_y = -((center_x + center_y) * scaled_tile_size / 4) + self.HEIGHT / 4
            self.camera_centered = True

        input_result = self.handle_input()
        if input_result == "QUIT":
            return "QUIT"
        elif input_result == "LOAD":
            return "LOAD"

        self.screen.fill((0, 0, 0))
        x_max, x_min, y_max, y_min = self.current_map_bounds

        actual_tile_size = int(self.tile_size * self.zoom_factor)
        tile_overlap = 4

        # On met à jour les tuiles avec le niveau de zoom actuel (optimisé avec cache)
        if self._last_zoom != self.zoom_factor or self.TILE_LIGHT is None:
            self._last_zoom = self.zoom_factor
            base_tile = pygame.transform.scale(self.TILE_IMAGE, (actual_tile_size + tile_overlap, actual_tile_size + tile_overlap))
            self.TILE_LIGHT = base_tile.copy()
            self.TILE_LIGHT.fill((60, 180, 40), special_flags=pygame.BLEND_RGB_MULT)
            self.TILE_DARK = base_tile.copy()
            self.TILE_DARK.fill((45, 150, 30), special_flags=pygame.BLEND_RGB_MULT)

        # Dessiner la carte (Tuiles)
        for x in range(int(x_min) - 1, int(x_max) + 1):
            for y in range(int(y_min) - 1, int(y_max) + 1):
                iso_x, iso_y = self.convert_to_iso((x, y))
                current_tile = self.TILE_LIGHT if (x + y) % 2 == 0 else self.TILE_DARK
                rect = current_tile.get_rect(center=(int(iso_x), int(iso_y)))
                self.screen.blit(current_tile, rect.topleft)

        # Dessiner les unités de l'armée 1
        for unit in army1.living_units():
            self._draw_unit(unit, self._color_for_unit(unit, (50, 100, 255)))

        # Dessiner les unités de l'armée 2
        for unit in army2.living_units():
            self._draw_unit(unit, self._color_for_unit(unit, (255, 50, 50)))

        # Dessiner les obstacles
        for unit in map.obstacles:
            self._draw_unit(unit, None)

        # Afficher l'UI
        if self.show_minimap:
            self._draw_minimap(map, army1, army2)

        if self.show_army_stats:
            self._draw_army_stats(army1, army2)

        if self.is_paused_state:
            self._draw_pause_indicator()

        if self.show_load_menu:
            self._draw_load_menu()

        pygame.display.flip()

    def is_paused(self):
        return self.is_paused_state

    def _draw_pause_indicator(self):
        overlay = pygame.Surface((self.WIDTH, self.HEIGHT))
        overlay.set_alpha(128)
        overlay.fill((0, 0, 0))
        self.screen.blit(overlay, (0, 0))

        paused_text = self.font.render("PAUSED", True, (255, 255, 255))
        paused_rect = paused_text.get_rect(center=(self.WIDTH // 2, self.HEIGHT // 2))

        bg_rect = paused_rect.inflate(20, 10)
        pygame.draw.rect(self.screen, (40, 40, 40), bg_rect)
        pygame.draw.rect(self.screen, (255, 255, 255), bg_rect, 2)

        self.screen.blit(paused_text, paused_rect)

        instruction = self.small_font.render("Press SPACE to resume", True, (200, 200, 200))
        inst_rect = instruction.get_rect(center=(self.WIDTH // 2, self.HEIGHT // 2 + 40))
        self.screen.blit(instruction, inst_rect)

    def __init__(self, *args):
        super().__init__(*args)
        self.uses_pygame = True
        self.wait_for_close = True
        if len(args) > 0:
            self.path = args[0] if args[0].endswith('/') or args[0].endswith('\\') else args[0] + '/'
        else:
            self.path = "frontend/Graphics/pygame_assets/"

    def _is_point_in_minimap(self, pos):
        """Vérifier si un point de la souris est dans la minimap."""
        mx, my = pos
        minimap_x, minimap_y = self.minimap_position
        return (minimap_x <= mx <= minimap_x + self.minimap_size and
                minimap_y <= my <= minimap_y + self.minimap_size)

    def _move_camera_to_minimap_click(self, pos):
        """Déplacer la caméra à l'endroit cliqué sur la minimap (Calcul Inverse Isométrique)."""
        mx, my = pos
        minimap_x, minimap_y = self.minimap_position
        local_x = mx - minimap_x
        local_y = my - minimap_y

        x_max, x_min, y_max, y_min = self.current_map_bounds
        map_width = max(x_max - x_min + 1, 1)
        map_height = max(y_max - y_min + 1, 1)

        center_x = self.minimap_size / 2
        center_y = self.minimap_size / 2
        scale = (self.minimap_size * 0.8) / (map_width + map_height)

        # Calcul inverse: récupérer A et B
        A = (local_x - center_x) / scale
        offset_y = (map_width + map_height) * (scale / 4)
        B = (local_y - center_y + offset_y) / (scale / 2)

        rel_x = (A + B) / 2
        rel_y = (B - A) / 2

        target_map_x = rel_x + x_min
        target_map_y = rel_y + y_min

        # Mettre à jour l'offset de la caméra principale
        scaled_tile_size = self.tile_size * self.zoom_factor
        self.offset_x = -((target_map_x - target_map_y) * scaled_tile_size / 2)
        self.offset_y = -((target_map_x + target_map_y) * scaled_tile_size / 4) + self.HEIGHT / 4

    def handle_input(self):
        # Traitement des événements
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "QUIT"
            elif event.type == pygame.MOUSEWHEEL:
                # Zoom avec la molette de la souris
                if event.y > 0:
                    self.zoom_factor *= 1.1
                elif event.y < 0:
                    self.zoom_factor /= 1.1

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Clic gauche
                    mouse_pos = pygame.mouse.get_pos()
                    if self.show_minimap and self._is_point_in_minimap(mouse_pos):
                        # Clic sur la minimap = téléportation de la caméra
                        self._move_camera_to_minimap_click(mouse_pos)
                        self.is_dragging = False
                    else:
                        # Commencer à glisser
                        self.is_dragging = True
                        self.last_mouse_pos = mouse_pos

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    self.is_dragging = False

            elif event.type == pygame.MOUSEMOTION:
                mouse_pos = pygame.mouse.get_pos()
                if self.is_dragging:
                    # Déplacer la carte avec la souris
                    dx = mouse_pos[0] - self.last_mouse_pos[0]
                    dy = mouse_pos[1] - self.last_mouse_pos[1]
                    self.offset_x += dx
                    self.offset_y += dy
                    self.last_mouse_pos = mouse_pos
                elif pygame.mouse.get_pressed()[0]:
                    # Si on glisse tout en étant sur la minimap
                    if self.show_minimap and self._is_point_in_minimap(mouse_pos):
                        self._move_camera_to_minimap_click(mouse_pos)

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self.show_load_menu:
                        self.show_load_menu = False
                    else:
                        return "QUIT"
                elif event.key == pygame.K_m:
                    self.show_minimap = not self.show_minimap
                elif event.key == pygame.K_F1:
                    self.show_army_stats = not self.show_army_stats
                elif event.key == pygame.K_F2:
                    self.show_army1_details = not self.show_army1_details
                elif event.key == pygame.K_F3:
                    self.show_army2_details = not self.show_army2_details
                elif event.key == pygame.K_F4:
                    self.show_unit_counts = not self.show_unit_counts
                elif event.key == pygame.K_z:
                    self.battle_speed_multiplier = max(0.1, self.battle_speed_multiplier * 0.7)
                elif event.key == pygame.K_x:
                    self.battle_speed_multiplier = min(5.0, self.battle_speed_multiplier * 1.4)
                elif event.key == pygame.K_SPACE:
                    self.is_paused_state = not self.is_paused_state
                elif event.key == pygame.K_F11:
                    if self.battle_instance:
                        self._quick_save()
                elif event.key == pygame.K_F12:
                    if self.battle_instance:
                        self.show_load_menu = True
                        self.load_menu_selected_index = 0
                elif event.key == pygame.K_ESCAPE and self.show_load_menu:
                    self.show_load_menu = False
                elif event.key == pygame.K_RETURN and self.show_load_menu:
                    self.show_load_menu = False
                    return "LOAD"
                elif self.show_load_menu:
                    if event.key == pygame.K_UP:
                        self.load_menu_selected_index = max(0, self.load_menu_selected_index - 1)
                    elif event.key == pygame.K_DOWN:
                        save_files = self._get_save_files()
                        self.load_menu_selected_index = min(len(save_files) - 1, self.load_menu_selected_index + 1)
                    elif event.key in [pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8, pygame.K_9]:     
                        num = event.key - pygame.K_1
                        save_files = self._get_save_files()
                        if num < len(save_files):
                            self.load_menu_selected_index = num
                            self.show_load_menu = False
                            return "LOAD"

        # Déplacement continu de la caméra avec les flèches du clavier
        keys = pygame.key.get_pressed()
        base_camera_speed = 15
        camera_speed = int(base_camera_speed * (self.zoom_factor / 20))
        if keys[pygame.K_LEFT]:
            self.offset_x += camera_speed
        if keys[pygame.K_RIGHT]:
            self.offset_x -= camera_speed
        if keys[pygame.K_UP]:
            self.offset_y += camera_speed
        if keys[pygame.K_DOWN]:
            self.offset_y -= camera_speed

        if keys[pygame.K_c]:
            self.camera_centered = False # Forcer le recentrage au prochain cycle

        return True

    def convert_to_iso(self, coor: tuple):
        x, y = coor
        scaled_tile_size = self.tile_size * self.zoom_factor
        iso_x = ((x - y) * scaled_tile_size // 2 + self.WIDTH // 2 + self.offset_x)
        iso_y = ((x + y) * scaled_tile_size // 4 + self.HEIGHT // 4 + self.offset_y)
        return (iso_x, iso_y)

    def _draw_minimap(self, map: Map, army1: Army, army2: Army):
        """Dessiner la minimap en perspective Isométrique (2.5D)."""
        minimap_x, minimap_y = self.minimap_position
        minimap_surface = pygame.Surface((self.minimap_size, self.minimap_size), pygame.SRCALPHA)
        minimap_surface.fill((40, 40, 40, 200))  # Fond sombre transparent

        x_max, x_min, y_max, y_min = self.current_map_bounds
        map_width = max(x_max - x_min + 1, 1)
        map_height = max(y_max - y_min + 1, 1)

        center_x = self.minimap_size / 2
        center_y = self.minimap_size / 2

        # Calculer l'échelle pour rentrer le losange dans la minimap
        scale = (self.minimap_size * 0.8) / (map_width + map_height)

        def get_mini_iso(x, y):
            rel_x = x - x_min
            rel_y = y - y_min
            # Projection isométrique adaptée pour la petite surface
            iso_x = center_x + (rel_x - rel_y) * scale
            iso_y = center_y + (rel_x + rel_y) * (scale / 2) - ((map_width + map_height) * (scale / 4))
            return iso_x, iso_y

        # Dessiner le fond (Losange représentant le sol)
        pts = [
            get_mini_iso(x_min, y_min),
            get_mini_iso(x_max, y_min),
            get_mini_iso(x_max, y_max),
            get_mini_iso(x_min, y_max)
        ]
        pygame.draw.polygon(minimap_surface, (50, 120, 50), pts)
        pygame.draw.polygon(minimap_surface, (100, 200, 100), pts, 1) # Bordure du losange

        # Dessiner les unités de l'armée 1
        for unit in army1.living_units():
            if unit.position is not None:
                mx, my = get_mini_iso(*unit.position)
                mini_pos = (int(mx), int(my))
                pygame.draw.circle(minimap_surface, (10, 10, 10), mini_pos, 4)
                pygame.draw.circle(minimap_surface, self._color_for_unit(unit, (50, 100, 255)), mini_pos, 3)

        # Dessiner les unités de l'armée 2
        for unit in army2.living_units():
            if unit.position is not None:
                mx, my = get_mini_iso(*unit.position)
                mini_pos = (int(mx), int(my))
                pygame.draw.circle(minimap_surface, (10, 10, 10), mini_pos, 4)
                pygame.draw.circle(minimap_surface, self._color_for_unit(unit, (255, 50, 50)), mini_pos, 3)

        # Dessiner le cadre extérieur global de la minimap
        pygame.draw.rect(minimap_surface, (255, 255, 255), (0, 0, self.minimap_size, self.minimap_size), 2)

        # Afficher la minimap
        self.screen.blit(minimap_surface, (minimap_x, minimap_y))

        # Afficher le texte "Minimap"
        label = self.small_font.render("Minimap Iso (M)", True, (255, 255, 255))
        self.screen.blit(label, (minimap_x, minimap_y - 20))

    def _draw_army_stats(self, army1: Army, army2: Army):
        panel_x = 10
        panel_y = 10
        panel_width = min(560, self.WIDTH - 20)
        line_height = 25
        current_y = panel_y

        groups = []
        seen_owners = set()
        local_owner = None
        if army1.living_units():
            local_owner = getattr(army1.living_units()[0], "network_owner_id", None)

        unit_sources = (
            [(unit, getattr(unit, "network_owner_id", None) or "army1") for unit in army1.living_units()]
            + [(unit, getattr(unit, "network_owner_id", None) or "army2") for unit in army2.living_units()]
        )

        for unit, owner_id in unit_sources:
            if owner_id in seen_owners:
                continue
            units = [
                other for other, other_owner_id in unit_sources
                if other_owner_id == owner_id
            ]
            seen_owners.add(owner_id)
            groups.append((owner_id, units))

        peer_slots = getattr(getattr(self, "battle_instance", None), "peer_slots", {})
        if isinstance(peer_slots, dict):
            for owner_id in peer_slots:
                if owner_id not in seen_owners:
                    seen_owners.add(owner_id)
                    groups.append((owner_id, []))

        groups.sort(key=lambda item: self._slot_for_owner(item[0], len(groups)))

        panel_height = min(self.HEIGHT - 20, max(400, 80 + len(groups) * 95))
        panel_surface = pygame.Surface((panel_width, panel_height))
        panel_surface.set_alpha(200)
        panel_surface.fill((20, 20, 20))
        self.screen.blit(panel_surface, (panel_x, panel_y))

        title = self.font.render("Army Statistics (F1-F4)", True, (255, 255, 255))
        self.screen.blit(title, (panel_x + 5, current_y))
        current_y += line_height + 5

        for index, (owner_id, units) in enumerate(groups, start=1):
            color = self._style_for_owner(owner_id, index)["color"]
            general_name = ""
            if units and owner_id == local_owner and army1.general:
                general_name = f" ({type(army1.general).__name__})"

            ip_suffix = ""
            if hasattr(self.battle_instance, 'peer_ips'):
                ip = self.battle_instance.peer_ips.get(owner_id)
                if ip:
                    ip_suffix = f" [{ip}]"

            owner_label = self._label_for_owner(owner_id, index)
            header_text = f"{owner_label}{general_name}{ip_suffix}: {len(units)} units"
            header_font = self.font
            if self.font.size(header_text)[0] > panel_width - 10:
                header_font = self.small_font
            header = header_font.render(header_text, True, color)
            self.screen.blit(header, (panel_x + 5, current_y))
            current_y += line_height

            if self.show_unit_counts:
                unit_counts = [
                    ("Knights", sum(1 for u in units if isinstance(u, Knight))),
                    ("Pikemen", sum(1 for u in units if isinstance(u, Pikeman))),
                    ("Crossbowmen", sum(1 for u in units if isinstance(u, Crossbowman))),
                    ("Monks", sum(1 for u in units if isinstance(u, Monk))),
                    ("Elephants", sum(1 for u in units if isinstance(u, Elephant))),
                    ("Castles", sum(1 for u in units if isinstance(u, Castle))),
                ]
                count_text = ", ".join(f"{label}: {count}" for label, count in unit_counts if count > 0)
                if count_text:
                    self.screen.blit(self.small_font.render(f"  {count_text}", True, (200, 200, 200)), (panel_x + 5, current_y))
                    current_y += line_height - 5

            current_y += 8
            if index < len(groups):
                pygame.draw.line(self.screen, (100, 100, 100), (panel_x + 5, current_y), (panel_x + panel_width - 5, current_y))
                current_y += 12

        current_y += 10
        help_text = [
            "Controles (Souris):",
            "Molette - Zoom / Defilement",
            "Clic Gauche - Glisser la carte",
            "Clic sur Minimap - Teleportation",
            "Controles (Clavier):",
            "M - Afficher/Masquer Minimap",
            "F1-F4 - Statistiques et Details",
            "F11 - Sauvegarde Rapide",
            "F12 - Menu de Chargement",
            "ESPACE - Pause / Reprise",
            "Z / X - Vitesse +/-",
            "C - Centrer la camera",
            "ECHAP - Quitter le jeu"
        ]
        for line in help_text:
            if current_y > panel_y + panel_height - 20:
                break
            self.screen.blit(self.small_font.render(line, True, (150, 150, 150)), (panel_x + 5, current_y))
            current_y += line_height - 5
    def _quick_save(self):
        import os
        from pathlib import Path

        if not self.battle_instance:
            print("Erreur: Aucune bataille à sauvegarder")
            return

        save_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "saves")
        os.makedirs(save_dir, exist_ok=True)
        filepath = os.path.join(save_dir, self.quick_save_filename)

        try:
            data = self.battle_instance.to_dict()
            tmp = Path(filepath).with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                import json
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, filepath)
            print(f"Sauvegarde réussie: {filepath}")
        except Exception as e:
            print(f"Erreur de sauvegarde: {e}")

    def set_battle_instance(self, battle):
        self.battle_instance = battle

    def _get_save_files(self):
        import os
        import glob

        save_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "saves")
        if not os.path.exists(save_dir):
            return []

        pattern = os.path.join(save_dir, "*.json")
        files = glob.glob(pattern)
        files.sort(key=os.path.getmtime, reverse=True)
        return [os.path.basename(f) for f in files]

    def _draw_load_menu(self):
        # [Logique de menu de sauvegarde inchangée]
        save_files = self._get_save_files()

        if not save_files:
            overlay = pygame.Surface((self.WIDTH, self.HEIGHT))
            overlay.set_alpha(200)
            overlay.fill((0, 0, 0))
            self.screen.blit(overlay, (0, 0))
            no_saves_text = self.font.render("Aucun fichier de sauvegarde", True, (255, 255, 255))
            no_saves_rect = no_saves_text.get_rect(center=(self.WIDTH // 2, self.HEIGHT // 2))
            self.screen.blit(no_saves_text, no_saves_rect)
            esc_text = self.small_font.render("Échap pour fermer", True, (200, 200, 200))
            esc_rect = esc_text.get_rect(center=(self.WIDTH // 2, self.HEIGHT // 2 + 40))
            self.screen.blit(esc_text, esc_rect)
            return

        menu_width = 500
        menu_height = min(600, 50 + len(save_files) * 40)
        menu_x = (self.WIDTH - menu_width) // 2
        menu_y = (self.HEIGHT - menu_height) // 2

        menu_surface = pygame.Surface((menu_width, menu_height))
        menu_surface.fill((40, 40, 40))
        pygame.draw.rect(menu_surface, (255, 255, 255), (0, 0, menu_width, menu_height), 2)
        self.screen.blit(menu_surface, (menu_x, menu_y))

        title = self.font.render("Sélectionner une Sauvegarde", True, (255, 255, 255))
        title_rect = title.get_rect(center=(menu_x + menu_width // 2, menu_y + 25))
        self.screen.blit(title, title_rect)

        start_y = menu_y + 60
        max_visible = min(len(save_files), 12)
        start_index = max(0, min(self.load_menu_selected_index - 5, len(save_files) - max_visible))

        for i in range(start_index, min(start_index + max_visible, len(save_files))):
            filename = save_files[i]
            y_pos = start_y + (i - start_index) * 40

            if i == self.load_menu_selected_index:
                pygame.draw.rect(self.screen, (100, 100, 200), (menu_x + 10, y_pos - 5, menu_width - 20, 35))

            display_name = filename
            if len(display_name) > 40:
                display_name = display_name[:37] + "..."

            self.screen.blit(self.small_font.render(f"{i + 1}.", True, (200, 200, 200)), (menu_x + 20, y_pos))
            self.screen.blit(self.small_font.render(display_name, True, (255, 255, 255)), (menu_x + 60, y_pos))

        inst_y = menu_y + menu_height - 40
        instructions = [
            "HAUT/BAS: Naviguer  |  ENTRÉE: Charger  |  ECHAP: Annuler",
            "Ou appuyez sur 1-9 pour charger directement"
        ]
        for j, inst in enumerate(instructions):
            inst_rect = self.small_font.render(inst, True, (150, 150, 150)).get_rect(center=(menu_x + menu_width // 2, inst_y + j * 20))
            self.screen.blit(self.small_font.render(inst, True, (150, 150, 150)), inst_rect)

    def _quick_load(self, filename=None):
        import os
        save_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "saves")

        if filename is None:
            save_files = self._get_save_files()
            if not save_files:
                print("Erreur: Aucune sauvegarde trouvée")
                return None
            if 0 <= self.load_menu_selected_index < len(save_files):
                filename = save_files[self.load_menu_selected_index]
            else:
                filename = self.quick_save_filename

        filepath = os.path.join(save_dir, filename)
        if not os.path.exists(filepath):
            print(f"Erreur: Sauvegarde introuvable: {filepath}")
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                import json
                data = json.load(f)

            from backend.GameModes.Battle import Battle
            loaded_battle = Battle.from_dict(data)
            print(f"Chargement réussi: {filepath}")
            return loaded_battle
        except Exception as e:
            print(f"Erreur lors du chargement: {e}")
            return None
