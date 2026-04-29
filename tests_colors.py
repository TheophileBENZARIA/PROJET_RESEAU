import time
from backend.Class.Map import Map
from backend.Class.Army import Army
from backend.Class.Units.Knight import Knight

# Nhớ chỉnh lại đường dẫn import PyScreen cho khớp với cấu trúc thư mục của bạn
from frontend.Graphics.PyScreen import PyScreen as GiaoDien
# from frontend.Terminal.Screen import Screen as GiaoDien 

def run_test():
    # 1. Tạo bản đồ kích thước 20x20
    game_map = Map(20, 20)

    # 2. Tạo 4 đội quân và truyền trực tiếp position vào lúc khởi tạo Knight
    army1 = Army()
    unit1 = Knight(position=(5, 5))
    army1.add_unit(unit1)

    army2 = Army()
    unit2 = Knight(position=(15, 5))
    army2.add_unit(unit2)

    army3 = Army()
    unit3 = Knight(position=(5, 15))
    army3.add_unit(unit3)

    army4 = Army()
    unit4 = Knight(position=(15, 15))
    army4.add_unit(unit4)

    # 3. Khởi tạo giao diện
    screen = GiaoDien()
    screen.initialiser()

    print("Đang mở giao diện test 4 đội quân...")
    print("Nhấn ESC hoặc Q (với Terminal) để thoát.")

    # 4. Vòng lặp render
    while True:
        action = screen.afficher(game_map, army1, army2, army3, army4)
        
        if action in ["QUIT", "quit"]:
            break
            
        time.sleep(0.05)

if __name__ == "__main__":
    run_test()