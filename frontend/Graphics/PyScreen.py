import sys
import time
from time import sleep
import random
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
        self.TILE_IMAGE = pygame.image.load(self.path + "tile.bmp").convert_alpha()
        self.KNIGHT_IMAGE = pygame.image.load(self.path + "knight.bmp").convert_alpha()
        self.PIKEMAN_IMAGE = pygame.image.load(self.path + "pikeman.bmp").convert_alpha()
        self.CROSSBOWMAN_IMAGE = pygame.image.load(self.path + "crossbowman.bmp").convert_alpha()
        self.ROCHER_IMAGE = pygame.image.load(self.path + "rocher.png")
        self.CASTLE_IMAGE = pygame.image.load(self.path + "castle.png")
        self.ELEPHANT_IMAGE = pygame.image.load(self.path + "elephant.png")
        self.MONK_IMAGE = pygame.image.load(self.path + "monk.png")

        # Variables pour les animations fluides
        self.unit_previous_positions = {}
        self.unit_animation_start_pos = {}
        self.animation_start_time = {}
        self.animation_duration = 1.15

        # Paramètres de la minimap et de l'UI
        self.show_minimap = True
        self.minimap_size = 200
        self.minimap_position = (self.WIDTH - self.minimap_size - 10, 10)

        # Affichage des statistiques
        self.show_army_stats = True
        self.show_army1_details = True
        self.show_army2_details = True
        self.show_unit_counts = True

        #Ajouter une structure de rangement par couleur pour les équipes
        self.army_colors = {
            0: (50, 100, 255), #L'équipe 1 est désormais désignée comme bleue.
            1: (255, 50, 50)   # L'équipe 2 est fixée comme étant rouge.
        }
        self.show_army_details_dict = {}
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

        # Préparation des tuiles (claires et sombres) pour l'échiquier
        actual_tile_size = int(self.tile_size * self.zoom_factor) + 4
        base_tile = pygame.transform.scale(self.TILE_IMAGE, (actual_tile_size, actual_tile_size))

        self.TILE_LIGHT = base_tile.copy()
        self.TILE_LIGHT.fill((60, 180, 40), special_flags=pygame.BLEND_RGB_MULT)

        self.TILE_DARK = base_tile.copy()
        self.TILE_DARK.fill((45, 150, 30), special_flags=pygame.BLEND_RGB_MULT)

        # Variables pour le contrôle à la souris (Glisser / Drag)
        self.is_dragging = False
        self.last_mouse_pos = (0, 0)

        # Variable pour centrer la caméra initialement
        self.camera_centered = False
        self.current_map_bounds = (0, 0, 0, 0) # (x_max, x_min, y_max, y_min)

    def _get_army_color(self, army_index):
        """Récupérer la couleur de l'équipe, en générer automatiquement une aléatoire si elle n'est pas déjà présente."""
        if army_index not in self.army_colors:
            # Générer des couleurs aléatoires
            r = random.randint(50, 255)
            g = random.randint(50, 255)
            b = random.randint(50, 255)
            self.army_colors[army_index] = (r, g, b)
        return self.army_colors[army_index]
    
    def _get_interpolated_position(self, unit):
        """Obtenir la position interpolée pour une animation fluide."""
        if unit.position is None:
            return None

        unit_id = unit.id
        current_pos = unit.position

        if unit_id in self.unit_previous_positions:
            stored_pos = self.unit_previous_positions[unit_id]

            if stored_pos != current_pos:
                self.unit_animation_start_pos[unit_id] = stored_pos
                self.animation_start_time[unit_id] = time.time()
                self.unit_previous_positions[unit_id] = current_pos
                return stored_pos
            else:
                if unit_id in self.animation_start_time and unit_id in self.unit_animation_start_pos:
                    elapsed = time.time() - self.animation_start_time[unit_id]
                    if elapsed < self.animation_duration:
                        start_pos = self.unit_animation_start_pos[unit_id]
                        t = elapsed / self.animation_duration
                        t = t * t * (3.0 - 2.0 * t)  # Smoothstep (interpolation douce)
                        interp_x = start_pos[0] + (current_pos[0] - start_pos[0]) * t
                        interp_y = start_pos[1] + (current_pos[1] - start_pos[1]) * t
                        return (interp_x, interp_y)
                    else:
                        if unit_id in self.animation_start_time:
                            del self.animation_start_time[unit_id]
                        if unit_id in self.unit_animation_start_pos:
                            del self.unit_animation_start_pos[unit_id]

        if unit_id not in self.unit_previous_positions:
            self.unit_previous_positions[unit_id] = current_pos
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

    def afficher(self, map: Map, *armies):
        """
        Affiche la carte, les unités de toutes les armées et l'interface utilisateur.
        Prend en charge un nombre dynamique d'armées.
        """
        # Mettre à jour les limites actuelles de la carte pour la minimap et le centrage.
        # Note : Assurez-vous que la méthode get_sizeMap de la classe mère (Affichage) 
        # accepte également *armies au lieu de (army1, army2)
        self.current_map_bounds = Affichage.get_sizeMap(map, *armies)

        # Centrer la caméra une seule fois au début du jeu
        if not self.camera_centered:
            x_max, x_min, y_max, y_min = self.current_map_bounds
            center_x = (x_max + x_min) / 2
            center_y = (y_max + y_min) / 2
            scaled_tile_size = self.tile_size * self.zoom_factor

            # Calcul de l'offset pour placer le centre de la carte au milieu de l'écran
            self.offset_x = -((center_x - center_y) * scaled_tile_size / 2)
            self.offset_y = -((center_x + center_y) * scaled_tile_size / 4) + self.HEIGHT / 4
            self.camera_centered = True

        # Gestion des entrées clavier et souris
        input_result = self.handle_input()
        if input_result == "QUIT":
            return "QUIT"
        elif input_result == "LOAD":
            return "LOAD"

        # Effacer l'écran (remplir avec la couleur noire)
        self.screen.fill((0, 0, 0))
        x_max, x_min, y_max, y_min = self.current_map_bounds

        # Calculer la taille réelle des tuiles en fonction du niveau de zoom actuel
        actual_tile_size = int(self.tile_size * self.zoom_factor)
        tile_overlap = 4

        # Préparation et redimensionnement des tuiles de base (claires et sombres)
        base_tile = pygame.transform.scale(self.TILE_IMAGE, (actual_tile_size + tile_overlap, actual_tile_size + tile_overlap))
        self.TILE_LIGHT = base_tile.copy()
        self.TILE_LIGHT.fill((60, 180, 40), special_flags=pygame.BLEND_RGB_MULT)
        self.TILE_DARK = base_tile.copy()
        self.TILE_DARK.fill((45, 150, 30), special_flags=pygame.BLEND_RGB_MULT)

        # Dessiner la carte (les tuiles isométriques)
        for x in range(int(x_min) - 1, int(x_max) + 1):
            for y in range(int(y_min) - 1, int(y_max) + 1):
                iso_x, iso_y = self.convert_to_iso((x, y))
                # Alterner les couleurs des tuiles pour créer un effet d'échiquier
                current_tile = self.TILE_LIGHT if (x + y) % 2 == 0 else self.TILE_DARK
                rect = current_tile.get_rect(center=(int(iso_x), int(iso_y)))
                self.screen.blit(current_tile, rect.topleft)

        # Parcourir et dessiner les unités de TOUTES les armées
        for index, army in enumerate(armies):
            # Récupérer la couleur spécifique à cette armée (générée dynamiquement)
            army_color = self._get_army_color(index)
            for unit in army.living_units():
                self._draw_unit(unit, army_color)

        # Dessiner les obstacles (comme les rochers)
        for unit in map.obstacles:
            self._draw_unit(unit, None)

        # Affichage de l'interface utilisateur (UI)
        if self.show_minimap:
            # Passer toutes les armées à la fonction de la minimap
            self._draw_minimap(map, *armies)

        if self.show_army_stats:
            # Passer toutes les armées au panneau des statistiques
            self._draw_army_stats(*armies)

        if self.is_paused_state:
            # Afficher l'indicateur de pause
            self._draw_pause_indicator()

        if self.show_load_menu:
            # Afficher le menu de chargement des sauvegardes
            self._draw_load_menu()

        # Rafraîchir l'écran complet
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

    def _draw_minimap(self, map: Map, *armies):
        """
        Dessine la minimap en perspective Isométrique (2.5D).
        Affiche le terrain et la position des unités pour toutes les armées.
        """
        minimap_x, minimap_y = self.minimap_position
        
        # Création de la surface de la minimap avec prise en charge de la transparence (SRCALPHA)
        minimap_surface = pygame.Surface((self.minimap_size, self.minimap_size), pygame.SRCALPHA)
        minimap_surface.fill((40, 40, 40, 200))  # Fond sombre semi-transparent

        # Récupération des limites de la carte
        x_max, x_min, y_max, y_min = self.current_map_bounds
        map_width = max(x_max - x_min + 1, 1)
        map_height = max(y_max - y_min + 1, 1)

        center_x = self.minimap_size / 2
        center_y = self.minimap_size / 2

        # Calculer l'échelle pour faire rentrer le losange (la carte) dans la minimap
        scale = (self.minimap_size * 0.8) / (map_width + map_height)

        def get_mini_iso(x, y):
            """Convertit les coordonnées cartésiennes en coordonnées isométriques pour la minimap."""
            rel_x = x - x_min
            rel_y = y - y_min
            # Projection isométrique adaptée pour la petite surface
            iso_x = center_x + (rel_x - rel_y) * scale
            iso_y = center_y + (rel_x + rel_y) * (scale / 2) - ((map_width + map_height) * (scale / 4))
            return iso_x, iso_y

        # 1. Dessiner le fond (Losange représentant le sol de la carte)
        pts = [
            get_mini_iso(x_min, y_min),
            get_mini_iso(x_max, y_min),
            get_mini_iso(x_max, y_max),
            get_mini_iso(x_min, y_max)
        ]
        pygame.draw.polygon(minimap_surface, (50, 120, 50), pts)      # Remplissage vert
        pygame.draw.polygon(minimap_surface, (100, 200, 100), pts, 1) # Bordure claire du losange

        # 2. Parcourir et dessiner les unités de TOUTES les armées
        for index, army in enumerate(armies):
            # Récupérer la couleur assignée à cette armée
            army_color = self._get_army_color(index)
            
            for unit in army.living_units():
                if unit.position is not None:
                    mx, my = get_mini_iso(*unit.position)
                    # Dessiner un petit point (cercle) coloré pour chaque unité
                    pygame.draw.circle(minimap_surface, army_color, (int(mx), int(my)), 2)

        # 3. Dessiner le cadre extérieur global de la minimap
        pygame.draw.rect(minimap_surface, (255, 255, 255), (0, 0, self.minimap_size, self.minimap_size), 2)

        # 4. Afficher la surface de la minimap sur l'écran principal
        self.screen.blit(minimap_surface, (minimap_x, minimap_y))

        # 5. Afficher le texte "Minimap Iso (M)" au-dessus de la minimap
        label = self.small_font.render("Minimap Iso (M)", True, (255, 255, 255))
        self.screen.blit(label, (minimap_x, minimap_y - 20))

    def _draw_army_stats(self, *armies):
        """
        Affiche les statistiques pour un nombre dynamique d'armées.
        Calcule dynamiquement la hauteur du panneau et compte les unités par type.
        """
        panel_x = 10
        panel_y = 10
        panel_width = 300
        line_height = 25

        # 1. Calculer dynamiquement la hauteur requise pour le panneau
        # Hauteur de base : Titre + Espace + Texte d'aide (environ 14 lignes)
        estimated_height = 40 + (14 * 20) 
        for index, army in enumerate(armies):
            # Assurez-vous que le dictionnaire existe
            if not hasattr(self, 'show_army_details_dict'):
                self.show_army_details_dict = {}
                
            if self.show_army_details_dict.get(index, True):
                # En-tête + types d'unités (estimé max 6 types) + ligne de séparation
                estimated_height += line_height + (6 * 20) + line_height
            else:
                # Texte masqué + ligne de séparation
                estimated_height += line_height * 2

        # Dessiner le panneau d'arrière-plan avec la hauteur calculée
        panel_surface = pygame.Surface((panel_width, estimated_height), pygame.SRCALPHA)
        panel_surface.fill((20, 20, 20, 200)) # Noir avec transparence (Alpha=200)
        self.screen.blit(panel_surface, (panel_x, panel_y))

        current_y = panel_y + 5

        # Afficher le titre
        title = self.font.render("Army Statistics", True, (255, 255, 255))
        self.screen.blit(title, (panel_x + 10, current_y))
        current_y += line_height + 5

        # 2. Itérer sur toutes les armées pour afficher leurs stats
        for index, army in enumerate(armies):
            army_color = self._get_army_color(index)

            # Initialiser l'état visible par défaut pour cette armée
            if index not in self.show_army_details_dict:
                self.show_army_details_dict[index] = True

            if self.show_army_details_dict[index]:
                army_units = army.living_units()
                army_count = len(army_units)
                
                # Récupérer le nom de la classe du général
                general_name = type(army.general).__name__ if hasattr(army, 'general') else "General"
                
                header = self.font.render(f"Army {index + 1} ({general_name}): {army_count} units", True, army_color)
                self.screen.blit(header, (panel_x + 10, current_y))
                current_y += line_height

                # Afficher le décompte par type d'unité si activé (F4)
                if getattr(self, 'show_unit_counts', True):
                    # Utiliser un dictionnaire pour compter dynamiquement TOUS les types d'unités
                    # Cela évite de coder en dur "Knight", "Pikeman", etc.
                    unit_counts = {}
                    for u in army_units:
                        u_type = type(u).__name__
                        unit_counts[u_type] = unit_counts.get(u_type, 0) + 1

                    # Afficher les résultats du comptage
                    for u_type, count in unit_counts.items():
                        text = self.small_font.render(f"  {u_type}s: {count}", True, (200, 200, 200))
                        self.screen.blit(text, (panel_x + 10, current_y))
                        current_y += 20 # Espacement plus serré pour les sous-éléments
                current_y += 5
            else:
                # Texte affiché si les détails de l'armée sont masqués
                hidden_text = self.small_font.render(f"Army {index + 1}: (Hidden)", True, (150, 150, 150))
                self.screen.blit(hidden_text, (panel_x + 10, current_y))
                current_y += line_height

            # Dessiner une ligne de séparation entre les armées
            pygame.draw.line(self.screen, (100, 100, 100), (panel_x + 10, current_y), (panel_x + panel_width - 10, current_y))
            current_y += line_height

        # 3. Afficher les instructions et contrôles en bas du panneau
        current_y += 5
        help_text = [
            "Contrôles (Souris):",
            "Molette - Zoom / Défilement",
            "Clic Gauche - Glisser la carte",
            "Clic sur Minimap - Téléportation",
            "Contrôles (Clavier):",
            "M - Afficher/Masquer Minimap",
            "F1 - Afficher/Masquer UI",
            "F4 - Afficher/Masquer détails",
            "F11 - Sauvegarde Rapide",
            "F12 - Menu de Chargement",
            "ESPACE - Pause / Reprise",
            "Z / X - Vitesse +/-",
            "C - Centrer la caméra",
            "ECHAP - Quitter le jeu"
        ]
        
        for line in help_text:
            text = self.small_font.render(line, True, (150, 150, 150))
            self.screen.blit(text, (panel_x + 10, current_y))
            current_y += 20

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
