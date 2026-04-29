from backend.Class.Obstacles.Obstacle import Obstacle


class Map:
    def __init__(self, width=100, height=100):
        self.width = width
        self.height = height
        self.obstacles = set()
        self.gameMode=None

    def add_obstacle(self, obstacle : Obstacle):
        self.map = self
        self.obstacles.add(obstacle)


    def fussionner(self, map):
        for new_obstacle in map.obstacles:
            valid = True
            for obstacle in self.obstacles:
                if new_obstacle.position == obstacle.position:
                    valid = False
                    break
            if valid :
                self.obstacles.append(new_obstacle)