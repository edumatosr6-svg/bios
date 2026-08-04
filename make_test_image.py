"""Generates synthetic BIOS-like screenshots for pipeline testing, until
real camera photos of the 3 target BIOS models are available.

Produces several variants with known ground truth, so selection/highlight
detection can be scored automatically (see `TEST_CASES`):
  test_bios.png           navy theme, "Main" highlighted
  test_bios_noselect.png  navy theme, nothing highlighted  (negative case)
  test_bios_dark.png      black theme, a settings row highlighted white
"""
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1024, 768

THEMES = {
    "navy": {"bg": (0, 0, 128), "fg": (255, 255, 255),
             "hl_bg": (192, 192, 192), "hl_fg": (0, 0, 0)},
    "dark": {"bg": (0, 0, 0), "fg": (220, 220, 220),
             "hl_bg": (255, 255, 255), "hl_fg": (0, 0, 0)},
}

ROWS = [
    ("System Time", "14:32:07"),
    ("System Date", "Thu 07/30/2026"),
    ("CPU Type", "AMD Ryzen AI MAX 395"),
    ("Total Memory", "32768 MB"),
    ("SATA Port 1", "Not Detected"),
    ("Secure Boot", "Enabled"),
]
MENU_ITEMS = ["Main", "Advanced", "Boot", "Security", "Save & Exit"]

# filename -> set of line texts that are genuinely highlighted
TEST_CASES = {
    "test_bios.png": {"Main"},
    "test_bios_noselect.png": set(),
    "test_bios_dark.png": {"CPU Type", "AMD Ryzen AI MAX 395"},
}


def build(theme="navy", highlight_menu=0, highlight_row=None):
    """highlight_menu: index into MENU_ITEMS, or None for no menu highlight.
    highlight_row: index into ROWS, or None. Row highlights span the full
    content width (label + value), like a real BIOS selection bar.
    """
    colors = THEMES[theme]
    img = Image.new("RGB", (WIDTH, HEIGHT), colors["bg"])
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("consola.ttf", 20)
        font_bold = ImageFont.truetype("consolab.ttf", 20)
    except OSError:
        font = ImageFont.load_default()
        font_bold = font

    draw.text((20, 20), "AMI BIOS SETUP UTILITY", font=font_bold, fill=colors["fg"])
    draw.text((20, 50), "BIOS Version: F.31", font=font, fill=colors["fg"])
    draw.text((20, 80), "Build Date: 07/15/2026", font=font, fill=colors["fg"])

    x = 20
    for i, item in enumerate(MENU_ITEMS):
        w = draw.textlength(item, font=font) + 20
        if i == highlight_menu:
            draw.rectangle([x, 120, x + w, 150], fill=colors["hl_bg"])
            draw.text((x + 10, 124), item, font=font, fill=colors["hl_fg"])
        else:
            draw.text((x + 10, 124), item, font=font, fill=colors["fg"])
        x += w + 10

    y = 200
    for i, (label, value) in enumerate(ROWS):
        if i == highlight_row:
            draw.rectangle([30, y - 6, 700, y + 28], fill=colors["hl_bg"])
            draw.text((40, y), label, font=font, fill=colors["hl_fg"])
            draw.text((400, y), value, font=font, fill=colors["hl_fg"])
        else:
            draw.text((40, y), label, font=font, fill=colors["fg"])
            draw.text((400, y), value, font=font, fill=colors["fg"])
        y += 35

    draw.text((20, 700), "F1 Help   F10 Save and Exit   ESC Discard Changes",
              font=font, fill=colors["fg"])
    return img


if __name__ == "__main__":
    build(theme="navy", highlight_menu=0).save("test_bios.png")
    build(theme="navy", highlight_menu=None).save("test_bios_noselect.png")
    build(theme="dark", highlight_menu=None, highlight_row=2).save("test_bios_dark.png")
    for name in TEST_CASES:
        print(f"Wrote {name}")
