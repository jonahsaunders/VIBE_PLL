# Chipalooza #4 floorplan check

This page records the original compact build. For the current layout, use
the [physical implementation](../physical/README.md). The [rev. 3 results](rev3.md)
record the schematic-based replays and sensitivity studies.

The Challenge #4 organizer will specify the assigned outline and wrapper in the harness repository. This check uses a provisional **400 × 250 µm** rectangle based on the PLL's **0.10 mm²** planning target. It reserves a **100 × 100 µm** corner for the DCO and its guard ring, and **5 µm** per edge for wrapper access. The DCO reservation is a layout allocation. [Challenge #4 rules](https://opencircuitdesign.com/chipalooza/rules-4.html)

## Sky130 HD mapping

| Build | Mapped digital area | Digital row utilization | Fits planning model |
| --- | ---: | ---: | --- |
| Prior revision `697ebea` | 133,186 µm² | 160.1% | No |
| Current, on-chip calibration | 125,361 µm² | 150.7% | No |
| Current, fixed phase centers | 51,825 µm² | 62.3% | Yes |

The checker subtracts the DCO reservation from site-aligned rows, packs the actual mapped cell widths and tests a 65% utilization cap. In the fixed-center build it places 5,743 cell footprints into 83,167 µm² of available digital rows, with 2,233 µm² of cell-area allowance left at the cap. The 383 registered thermometer controls and the 40-bin detector remain in the compact build. The table's size savings come primarily from omitting the on-chip histogram and shadow lookup table. The previous RTL is available at [`697ebea`](https://github.com/jonahsaunders/VIBE_PLL/tree/697ebea377d40f29d67a4f7f58210523f8da28ba).

Use Yosys 0.66 and matching Sky130 HD Liberty and LEF. The run used the OpenROAD-flow-scripts Sky130 HD [TT Liberty](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/blob/b5dceb3c08fd30c9a1c5c0587bc6a57e0392080a/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib) and [cell LEF](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/blob/46e03f5e1aca8008f024bb45d406e172f3de96b5/flow/platforms/sky130hd/lef/sky130_fd_sc_hd_merged.lef).

```sh
python tests/check_slot.py --liberty "$SKY130_HD_TT_LIB" --lef "$SKY130_HD_LEF" \
  --slot 400 250 --dco-reserve 100 100 --edge-reserve 5 --utilization 0.65
```

Use `--on-chip-cal` to measure the larger build. Use the official width, height, DCO keepout and edge margins once known. The packing check uses LEF rectangles. A routed fit requires the real analog layout, pin access, clock trees, power routing, and standalone and wrapper DRC/LVS.

## Fixed-center loop verification

The original Sky130A DCO data feed all three replays. The same nominal fixed lookup table is used at every corner. The tests cover startup, retune, reference loss and recovery. The worst mean error was 13.57 ppm over 4,096 DCO periods.

| Replay | Reference | Initial lock | Retune and recovery | Peak modeled DCO |
| --- | ---: | ---: | ---: | ---: |
| TT | 25 MHz | 27.24 µs | 29.48–29.92 µs | 308.52 MHz |
| Slow-cold | 16 MHz | 41.50 µs | 46.69–74.63 µs | 301.71 MHz |
| Fast | 32 MHz | 20.00 µs | 14.97–18.87 µs | 312.41 MHz |

TT deterministic TIE in the 10 kHz–10 MHz band was **7.97 ps RMS** at 256.25 MHz and **19.29 ps RMS** at 250.0061 MHz, with peak lines of **−45.95 dBc** and **−35.07 dBc**. Each replay captured 131,072 clock edges. These are noiseless replays of static DCO data.

```sh
python tests/run_rtl.py --fixed-centers
python tests/run_rtl.py --fixed-centers --spice-data results/rev2-tt.csv
python tests/run_rtl.py --fixed-centers --spice-data results/rev2-ss-cold.csv \
  --ref 16 --edge 76800
python tests/run_rtl.py --fixed-centers --spice-data results/rev2-ff.csv \
  --ref 32 --start 37888 --retune 36864 --edge 20480
python tests/run_rtl.py --fixed-centers --spice-data results/rev2-tt.csv \
  --start 41984 --spectrum edges.csv
python analysis/spectrum.py edges.csv
```
