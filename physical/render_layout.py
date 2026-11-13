#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Render actual GDS geometry with KLayout: klayout -b -r render_layout.py -rd input=... -rd output=..."""
from pathlib import Path
import klayout.lay as lay

view = lay.LayoutView()
view.load_layout(str(Path(input).resolve()), 0)
view.max_hier()
view.set_config("background-color", "#0c1420")
view.set_config("grid-visible", "false")
view.set_config("text-visible", "false")
colors = {64: 0x304369, 65: 0x489477, 66: 0xD76B66, 67: 0xBCC9D6,
          68: 0x6A8CC9, 69: 0xE2736D, 70: 0x75B997, 71: 0xE4B966,
          72: 0xB7A0D9, 79: 0xB6A47A, 89: 0xD4CB9E}
for props in view.each_layer():
    layer, purpose = props.source_layer, props.source_datatype
    props.visible = layer in colors and purpose in (20, 44, 13)
    if layer in colors:
        props.fill_color = colors[layer]
        props.frame_color = colors[layer]
        props.dither_pattern = 0
view.zoom_fit()
view.save_image(str(Path(output).resolve()), 1800, 1000)
