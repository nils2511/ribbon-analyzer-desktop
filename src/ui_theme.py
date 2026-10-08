"""Consistent native Tk styles for the annotation workspace."""
from tkinter import ttk
from .config import UI_BG, UI_PANEL, UI_TEXT, UI_TEXT_DIM, UI_BORDER


def apply_theme(root):
    style = ttk.Style(root)
    base = '#293b49'
    definitions = {
        'Green': ('#216b5c', '#287e6c'), 'BigGreen': ('#216b5c', '#287e6c'),
        'Blue': ('#285775', '#326e94'), 'BigBlue': ('#285775', '#326e94'),
        'Save': ('#216b5c', '#287e6c'), 'Active': ('#216b5c', '#287e6c'),
        'Orange': ('#755327', '#876032'), 'Red': ('#7c3439', '#94444a'),
        'Purple': (base, '#354b5c'), 'BigPurple': (base, '#354b5c'),
        'Dark': (base, '#354b5c'), 'Gray': (base, '#354b5c'),
        'Nav': (base, '#354b5c'),
    }
    for prefix in ('', 'App.'):
        for name, (background, hover) in definitions.items():
            key = f'{prefix}{name}.TButton'
            style.configure(key, background=background, foreground=UI_TEXT,
                bordercolor=background, lightcolor=background, darkcolor=background,
                borderwidth=0, relief='flat', focusthickness=2, focuscolor=UI_TEXT,
                font=('Helvetica', 10), padding=(10, 6))
            style.map(key, background=[('disabled', UI_PANEL), ('pressed', hover), ('active', hover)],
                foreground=[('disabled', UI_TEXT_DIM), ('active', UI_TEXT), ('pressed', UI_TEXT)])
    style.configure('TNotebook', background=UI_BG, borderwidth=0,
                    bordercolor=UI_BG, lightcolor=UI_BG, darkcolor=UI_BG)
    style.configure('TNotebook.Tab', background=UI_PANEL, foreground=UI_TEXT_DIM,
        borderwidth=0, bordercolor=UI_BG, lightcolor=UI_BG, darkcolor=UI_BG,
        padding=(14, 9), font=('Helvetica', 10))
    style.map('TNotebook.Tab', background=[('selected', UI_BG), ('active', '#293b49')],
              foreground=[('selected', UI_TEXT), ('active', UI_TEXT)])
    style.configure('Custom.Treeview', background='#10171d', fieldbackground='#10171d',
        foreground=UI_TEXT, rowheight=26, borderwidth=0, bordercolor=UI_BORDER,
        lightcolor=UI_BORDER, darkcolor=UI_BORDER)
    style.configure('Custom.Treeview.Heading', background=UI_PANEL, foreground=UI_TEXT_DIM,
        borderwidth=0, bordercolor=UI_PANEL, lightcolor=UI_PANEL, darkcolor=UI_PANEL,
        relief='flat', padding=(6, 6))
    style.configure('TScrollbar', background='#354550', troughcolor=UI_PANEL,
        bordercolor=UI_PANEL, lightcolor=UI_PANEL, darkcolor=UI_PANEL, arrowsize=12)
