# frontend/terminal_view.py
from backend.Class.Map import Map

def print_map(game_map: Map):   
    # Simple terminal-based map visualization
    for y in range(game_map.height):
        row = ""
        for x in range(game_map.width):
            tile = game_map.grid[x][y]
            if tile.unit:
                owner_name = getattr(tile.unit, "owner", "U")
                # Lấy chữ cái đầu tiên của tên chủ sở hữu (ví dụ: Player1 -> P)
                row += str(owner_name)[0].upper() if owner_name else "U"
            else:
                row += "."
        print(row)
    print()

# New convenience: launch curses-based realtime display for a Battle.
def launch_curses_battle(battle, delay: float = 0.5):
    """
    Launch the curses front-end and run the provided Battle with a curses display.
    Requires frontend.Terminal to be present.
    """
    try:
        from frontend.Terminal import run_battle_with_curses
    except Exception as e:
        print("Curses Terminal frontend not available:", e)
        raise
    run_battle_with_curses(battle, delay=delay)