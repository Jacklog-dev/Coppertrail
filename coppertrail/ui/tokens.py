# Coppertrail design tokens (from the handover package, HANDOVER 8b)
DARK = {
    # Surfaces
    "bg0": "#0A0B0D",  # window base: nav, filter bar, status strip
    "bg1": "#101114",  # view background
    "surface": "#16181C",  # cards, panels
    "raised": "#1E2126",  # inputs, buttons, hover rows
    "overlay": "#23262C",  # popovers, menus, dialogs
    # Text
    "text1": "#F1EDE4",  # primary text, values
    "text2": "#BDB8AE",  # secondary text, legends
    "text3": "#8F8B83",  # labels, axes, captions
    "textDis": "#5A5852",  # disabled
    # Borders & grid
    "border": "#2C3037",  # 1 px borders
    "borderStrong": "#6E5A3C",  # hover, popovers, focus
    "grid": "#22252A",  # chart grid, table row lines
    "scroll": "#33373E",  # scrollbar thumb
    # Accent
    "accent": "#D9894B",
    "accentHover": "#E89E64",
    "accentPressed": "#B5733D",
    "accentMuted": "#2C2119",  # selected background
    "accentOn": "#1A0F07",  # text on accent
    # Data series (fixed order)
    "s1": "#D9894B",  # copper: primary series
    "s2": "#6FAEE0",  # cool blue: secondary series
    "s3": "#A990D8",  # violet: supply shocks
    "s4": "#D97B98",  # rose: mispricings
    "s5": "#9DB96F",  # sage
    "s6": "#8F949C",  # slate: volume, neutral bars
    # Semantic
    "rise": "#4FBFA6",
    "fall": "#E8675C",
    # attention: stale data, notices (deliberately not amber: too close to gold/copper)
    "attention": "#A9B8F0",
    "attentionBg": "#1E2032",
    # Coins: price values only
    "gold": "#E3BE4F",
    "goldRing": "#97781E",
    "silver": "#C9CED6",
    "silverRing": "#7F8793",
    "copper": "#BF6E3B",
    "copperRing": "#7A401E",
}
LIGHT = {  # parchment variant
    "bg0": "#E9E1CF",
    "bg1": "#F4EFE3",
    "surface": "#FCF9F2",
    "raised": "#F0E9DA",
    "overlay": "#FFFDF8",
    "text1": "#2A1F14",
    "text2": "#55432F",
    "text3": "#6E5B43",
    "textDis": "#A8977A",
    "border": "#DACFB8",
    "borderStrong": "#A88B5E",
    "grid": "#ECE5D6",
    "scroll": "#DACFB8",
    "accent": "#9A4D1F",
    "accentHover": "#AE5C2B",
    "accentPressed": "#823F17",
    "accentMuted": "#EED6BC",
    "accentOn": "#FFF8EC",
    "s1": "#A9571F",
    "s2": "#2F6C9E",
    "s3": "#6A4FB0",
    "s4": "#A8406A",
    "s5": "#5A7D2E",
    "s6": "#7A6D5C",
    "rise": "#13786A",
    "fall": "#B83A30",
    "attention": "#3E4FAE",
    "attentionBg": "#E5E3F2",
    "gold": "#B98A0E",
    "goldRing": "#7E5F08",
    "silver": "#8E97A3",
    "silverRing": "#5F6873",
    "copper": "#9C4F22",
    "copperRing": "#633011",
}

FONT_UI = "Caudex"  # SIL OFL. Bundle Regular, Italic, Bold, BoldItalic .ttf
FONT_DISPLAY = "Almendra"  # SIL OFL. Bundle Regular, Bold. h1 + card titles only, always uppercase
FONT_MONO = "JetBrains Mono"  # SIL OFL. Logs only (optional)

TYPE = {  # name: (family, weight, px, uppercase, letter_spacing_percent)
    "h1": ("Almendra", 700, 22, True, 6),  # view title
    "title": ("Almendra", 700, 15, True, 6),  # card title
    "display": ("Caudex", 700, 28, False, 1),  # wordmark (nav uses 17 px)
    "h2": ("Caudex", 700, 17, False, 0),  # section, dialog title
    "kpi": ("Caudex", 400, 26, False, 0),  # headline numbers
    "body": ("Caudex", 400, 14, False, 0),  # body, tables, controls
    "th": ("Caudex", 400, 13, False, 0),  # table headers (text3)
    "sub": ("Caudex", 400, 13, False, 0),  # card subtitles (text3)
    "small": ("Caudex", 400, 12, False, 0),  # legends, axes, status strip
}
SPACE = [4, 8, 12, 16, 24, 32, 48]
RADIUS = {"control": 3, "card": 4, "panel": 6, "dialog": 6, "chip": 11}
SIZES = {
    "control_h": 32,
    "row_h": 36,
    "filterbar_h": 64,
    "status_h": 32,
    "nav_w": 200,
    "nav_w_compact": 56,
    "card_pad": 16,
    "view_pad": 24,
    "view_pad_compact": 16,
    "gap": 16,
    "item_icon": 18,  # item icon beside names in lists and tables
    "item_icon_large": 40,  # item icon in the Item detail header
}
CHART = {
    "line_primary": 2.25,
    "line_secondary": 2.0,
    "line_tertiary": 1.5,
    "grid": ("grid", 1, "solid"),  # horizontal only, no vertical grid
    "reference": ("text3", 1, [4, 4]),  # baselines like index 100, vendor floor
    "crosshair": ("text3", 1, [4, 4]),
    "area_alpha": 0.12,
    "band_alpha": 0.12,
    "bar_gap": 0.28,
    "axis_font_px": 12,
    "marker_dot_px": 8,  # dot with 2 px ring in `surface`
}
# Window widths (HANDOVER 8b "Resizing"): compact at or below, ultrawide at or above.
BREAKPOINTS = {"compact_max": 1440, "ultrawide_min": 2400}
SERIES = ["s1", "s2", "s3", "s4", "s5", "s6"]
COIN = {"mark_px": 7, "gap_px": 3, "ring_px": 1, "short_from_gold": 100}
