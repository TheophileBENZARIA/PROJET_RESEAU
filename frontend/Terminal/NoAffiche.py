from backend.Class.Army import Army
from backend.Class.Map import Map
from frontend.Affichage import Affichage


class NoAffiche(Affichage):
    def __init__(self):
        super().__init__()
        self.wait_for_close = False
        self.uses_pygame = False

    def initialiser(self):
        pass

    def afficher(self, map: Map, *armies):
        return None
