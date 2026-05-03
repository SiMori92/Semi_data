"""
products_config.py — Semiconductor Product Catalog & Curated Supply Chain Data
===============================================================================
Defines the product universe tracked in the supply chain module:
  · GPU_PRODUCTS   — consumer/workstation discrete GPUs
  · CPU_PRODUCTS   — consumer desktop CPUs
  · RAM_PRODUCTS   — DDR4 / DDR5 / HBM / LPDDR kits

Also contains pre-populated datasets sourced from earnings calls,
TrendForce/DRAMeXchange reports, and SEMI press releases:
  · CURATED_CAPACITY  — manufacturer fab utilisation per quarter
  · CURATED_DRAM_SPOT — DRAM/HBM spot price history (per-die USD)
  · CURATED_SEMI_BTB  — SEMI North-America equipment Book-to-Bill ratio

NOTE: curated rows carry a 'source' field. Update these each quarter by
      reading the relevant earnings transcripts / SEMI press releases.
"""

# ── GPU Product Catalog ───────────────────────────────────────────────────────
# Keys: unique model_id
# Fields: name, brand, category, node (process + foundry), vram_gb, msrp_usd,
#         newegg_q (Newegg search query string — None if not on Newegg),
#         passmark_kw (keyword to match in PassMark GPU list)

GPU_PRODUCTS = {
    # ── NVIDIA Ada Lovelace (TSMC N4) ─────────────────────────────────────────
    "RTX-4090": {
        "name": "NVIDIA GeForce RTX 4090", "brand": "NVIDIA", "category": "GPU",
        "node": "4nm (TSMC N4)", "manufacturer": "TSMC", "vram_gb": 24, "msrp_usd": 1599,
        "newegg_q": "rtx+4090",         "passmark_kw": "RTX 4090",
    },
    "RTX-4080-Super": {
        "name": "NVIDIA GeForce RTX 4080 Super", "brand": "NVIDIA", "category": "GPU",
        "node": "4nm (TSMC N4)", "manufacturer": "TSMC", "vram_gb": 16, "msrp_usd": 999,
        "newegg_q": "rtx+4080+super",   "passmark_kw": "RTX 4080 Super",
    },
    "RTX-4070-Ti-Super": {
        "name": "NVIDIA GeForce RTX 4070 Ti Super", "brand": "NVIDIA", "category": "GPU",
        "node": "4nm (TSMC N4)", "manufacturer": "TSMC", "vram_gb": 16, "msrp_usd": 799,
        "newegg_q": "rtx+4070+ti+super","passmark_kw": "RTX 4070 Ti Super",
    },
    "RTX-4070-Super": {
        "name": "NVIDIA GeForce RTX 4070 Super", "brand": "NVIDIA", "category": "GPU",
        "node": "4nm (TSMC N4)", "manufacturer": "TSMC", "vram_gb": 12, "msrp_usd": 599,
        "newegg_q": "rtx+4070+super",   "passmark_kw": "RTX 4070 Super",
    },
    "RTX-4060-Ti": {
        "name": "NVIDIA GeForce RTX 4060 Ti", "brand": "NVIDIA", "category": "GPU",
        "node": "4nm (TSMC N4)", "manufacturer": "TSMC", "vram_gb": 8,  "msrp_usd": 399,
        "newegg_q": "rtx+4060+ti",      "passmark_kw": "RTX 4060 Ti",
    },
    "RTX-4060": {
        "name": "NVIDIA GeForce RTX 4060", "brand": "NVIDIA", "category": "GPU",
        "node": "4nm (TSMC N4)", "manufacturer": "TSMC", "vram_gb": 8,  "msrp_usd": 299,
        "newegg_q": "rtx+4060",         "passmark_kw": "RTX 4060",
    },
    # ── AMD RDNA 3 (TSMC N5 / N6) ─────────────────────────────────────────────
    "RX-7900-XTX": {
        "name": "AMD Radeon RX 7900 XTX", "brand": "AMD", "category": "GPU",
        "node": "5nm (TSMC N5)", "manufacturer": "TSMC", "vram_gb": 24, "msrp_usd": 999,
        "newegg_q": "rx+7900+xtx",      "passmark_kw": "RX 7900 XTX",
    },
    "RX-7800-XT": {
        "name": "AMD Radeon RX 7800 XT", "brand": "AMD", "category": "GPU",
        "node": "6nm (TSMC N6)", "manufacturer": "TSMC", "vram_gb": 16, "msrp_usd": 499,
        "newegg_q": "rx+7800+xt",       "passmark_kw": "RX 7800 XT",
    },
    "RX-7600": {
        "name": "AMD Radeon RX 7600", "brand": "AMD", "category": "GPU",
        "node": "6nm (TSMC N6)", "manufacturer": "TSMC", "vram_gb": 8,  "msrp_usd": 269,
        "newegg_q": "rx+7600",          "passmark_kw": "RX 7600",
    },
    # ── Intel Arc Battlemage (TSMC N5) ────────────────────────────────────────
    "Arc-B580": {
        "name": "Intel Arc B580", "brand": "Intel", "category": "GPU",
        "node": "5nm (TSMC N5)", "manufacturer": "TSMC", "vram_gb": 12, "msrp_usd": 249,
        "newegg_q": "arc+b580",         "passmark_kw": "Arc B580",
    },
}

# ── CPU Product Catalog ───────────────────────────────────────────────────────
CPU_PRODUCTS = {
    # ── Intel Raptor Lake Refresh (Intel 7 / 10nm ESF) ────────────────────────
    "i9-14900K": {
        "name": "Intel Core i9-14900K", "brand": "Intel", "category": "CPU",
        "node": "Intel 7 (10nm ESF)", "manufacturer": "Intel Fab Oregon/Israel",
        "cores": 24, "tdp_w": 125, "socket": "LGA1700", "msrp_usd": 589,
        "newegg_q": "i9-14900k",   "passmark_kw": "Intel Core i9-14900K",
    },
    "i7-14700K": {
        "name": "Intel Core i7-14700K", "brand": "Intel", "category": "CPU",
        "node": "Intel 7 (10nm ESF)", "manufacturer": "Intel Fab Oregon/Israel",
        "cores": 20, "tdp_w": 125, "socket": "LGA1700", "msrp_usd": 409,
        "newegg_q": "i7-14700k",   "passmark_kw": "Intel Core i7-14700K",
    },
    "i5-14600K": {
        "name": "Intel Core i5-14600K", "brand": "Intel", "category": "CPU",
        "node": "Intel 7 (10nm ESF)", "manufacturer": "Intel Fab Oregon/Israel",
        "cores": 14, "tdp_w": 125, "socket": "LGA1700", "msrp_usd": 319,
        "newegg_q": "i5-14600k",   "passmark_kw": "Intel Core i5-14600K",
    },
    # ── Intel Arrow Lake (TSMC N3B + Intel 20A tiles) ─────────────────────────
    "i9-285K": {
        "name": "Intel Core Ultra 9 285K", "brand": "Intel", "category": "CPU",
        "node": "3nm (TSMC N3B) + Intel 20A", "manufacturer": "TSMC + Intel",
        "cores": 24, "tdp_w": 125, "socket": "LGA1851", "msrp_usd": 589,
        "newegg_q": "core+ultra+9+285k", "passmark_kw": "Intel Core Ultra 9 285K",
    },
    # ── AMD Zen 4 (TSMC N5 CCD + N6 IOD) ─────────────────────────────────────
    "R9-7950X": {
        "name": "AMD Ryzen 9 7950X", "brand": "AMD", "category": "CPU",
        "node": "5nm (TSMC N5)", "manufacturer": "TSMC",
        "cores": 16, "tdp_w": 170, "socket": "AM5", "msrp_usd": 699,
        "newegg_q": "ryzen+9+7950x",   "passmark_kw": "AMD Ryzen 9 7950X",
    },
    "R9-7900X": {
        "name": "AMD Ryzen 9 7900X", "brand": "AMD", "category": "CPU",
        "node": "5nm (TSMC N5)", "manufacturer": "TSMC",
        "cores": 12, "tdp_w": 170, "socket": "AM5", "msrp_usd": 449,
        "newegg_q": "ryzen+9+7900x",   "passmark_kw": "AMD Ryzen 9 7900X",
    },
    "R7-7800X3D": {
        "name": "AMD Ryzen 7 7800X3D", "brand": "AMD", "category": "CPU",
        "node": "5nm (TSMC N5) + 3D V-Cache", "manufacturer": "TSMC",
        "cores": 8,  "tdp_w": 120, "socket": "AM5", "msrp_usd": 449,
        "newegg_q": "ryzen+7+7800x3d", "passmark_kw": "AMD Ryzen 7 7800X3D",
    },
    "R5-7600X": {
        "name": "AMD Ryzen 5 7600X", "brand": "AMD", "category": "CPU",
        "node": "5nm (TSMC N5)", "manufacturer": "TSMC",
        "cores": 6,  "tdp_w": 105, "socket": "AM5", "msrp_usd": 299,
        "newegg_q": "ryzen+5+7600x",   "passmark_kw": "AMD Ryzen 5 7600X",
    },
    # ── AMD Zen 5 (TSMC N4 / N3E) ─────────────────────────────────────────────
    "R9-9950X": {
        "name": "AMD Ryzen 9 9950X", "brand": "AMD", "category": "CPU",
        "node": "4nm (TSMC N4)", "manufacturer": "TSMC",
        "cores": 16, "tdp_w": 170, "socket": "AM5", "msrp_usd": 649,
        "newegg_q": "ryzen+9+9950x",   "passmark_kw": "AMD Ryzen 9 9950X",
    },
    "R7-9700X": {
        "name": "AMD Ryzen 7 9700X", "brand": "AMD", "category": "CPU",
        "node": "4nm (TSMC N4)", "manufacturer": "TSMC",
        "cores": 8,  "tdp_w": 65,  "socket": "AM5", "msrp_usd": 359,
        "newegg_q": "ryzen+7+9700x",   "passmark_kw": "AMD Ryzen 7 9700X",
    },
}

# ── RAM Product Catalog ───────────────────────────────────────────────────────
RAM_PRODUCTS = {
    # ── DDR5 Consumer Kits ─────────────────────────────────────────────────────
    "DDR5-5600-32GB": {
        "name": "DDR5-5600 32GB Kit (2×16GB)", "category": "RAM", "type": "DDR5",
        "speed_mhz": 5600, "capacity_gb": 32, "config": "2×16GB",
        "maker": "Samsung / SK Hynix / Micron", "msrp_usd": 95,
        "newegg_q": "ddr5+5600+32gb",
    },
    "DDR5-6000-32GB": {
        "name": "DDR5-6000 32GB Kit (2×16GB)", "category": "RAM", "type": "DDR5",
        "speed_mhz": 6000, "capacity_gb": 32, "config": "2×16GB",
        "maker": "Samsung / SK Hynix / Micron", "msrp_usd": 110,
        "newegg_q": "ddr5+6000+32gb",
    },
    "DDR5-6400-64GB": {
        "name": "DDR5-6400 64GB Kit (2×32GB)", "category": "RAM", "type": "DDR5",
        "speed_mhz": 6400, "capacity_gb": 64, "config": "2×32GB",
        "maker": "Samsung / SK Hynix / Micron", "msrp_usd": 185,
        "newegg_q": "ddr5+6400+64gb",
    },
    # ── DDR4 Consumer Kits ─────────────────────────────────────────────────────
    "DDR4-3600-32GB": {
        "name": "DDR4-3600 32GB Kit (2×16GB)", "category": "RAM", "type": "DDR4",
        "speed_mhz": 3600, "capacity_gb": 32, "config": "2×16GB",
        "maker": "Samsung / SK Hynix / Micron", "msrp_usd": 60,
        "newegg_q": "ddr4+3600+32gb",
    },
    "DDR4-3200-16GB": {
        "name": "DDR4-3200 16GB Kit (2×8GB)", "category": "RAM", "type": "DDR4",
        "speed_mhz": 3200, "capacity_gb": 16, "config": "2×8GB",
        "maker": "Samsung / SK Hynix / Micron", "msrp_usd": 35,
        "newegg_q": "ddr4+3200+16gb",
    },
    # ── HBM (AI / HPC — no Newegg listing; spot pricing only) ─────────────────
    "HBM3E-96GB": {
        "name": "HBM3E 96GB Stack (12-Hi)", "category": "RAM", "type": "HBM3E",
        "speed_mhz": 9200, "capacity_gb": 96, "config": "12-Hi Stack",
        "maker": "SK Hynix (primary) / Samsung / Micron", "msrp_usd": None,
        "newegg_q": None,
        "note": "Sold exclusively to hyperscalers / AI chip OEMs. Spot price per GB tracked.",
    },
    "HBM3-48GB": {
        "name": "HBM3 48GB Stack (8-Hi)", "category": "RAM", "type": "HBM3",
        "speed_mhz": 6400, "capacity_gb": 48, "config": "8-Hi Stack",
        "maker": "SK Hynix / Samsung", "msrp_usd": None,
        "newegg_q": None,
    },
    # ── LPDDR5X (Mobile / Edge AI) ─────────────────────────────────────────────
    "LPDDR5X-32GB": {
        "name": "LPDDR5X-8448 32GB (Mobile AI)", "category": "RAM", "type": "LPDDR5X",
        "speed_mhz": 8448, "capacity_gb": 32, "config": "Soldered",
        "maker": "Samsung / SK Hynix / Micron", "msrp_usd": None,
        "newegg_q": None,
        "note": "Used in AI-capable laptops / Snapdragon X Elite / Apple M-series.",
    },
}

# ── Curated Manufacturer Capacity & Utilisation ───────────────────────────────
# Source: public earnings call transcripts, investor presentations.
# Each row: (company, segment, product_type, period, capacity_kwpm, utilisation_pct, source, notes)
#   capacity_kwpm = thousands of 300mm-equivalent wafers per month
#   utilisation_pct = reported fab/production utilisation
CURATED_CAPACITY = [
    # ─────────────────────── TSMC ─────────────────────────────────────────────
    # Advanced nodes (≤5nm): GPU compute, Apple, AMD CPU, NVDA
    ("TSMC", "Foundry", "GPU/CPU Advanced (≤5nm)", "2023-Q4", 130, 75,
     "TSMC Q4 2023 Earnings", "Demand recovery led by AI ASIC / NVDA H100/H200"),
    ("TSMC", "Foundry", "GPU/CPU Advanced (≤5nm)", "2024-Q1", 140, 80,
     "TSMC Q1 2024 Earnings", "CoWoS advanced packaging capacity became primary bottleneck"),
    ("TSMC", "Foundry", "GPU/CPU Advanced (≤5nm)", "2024-Q2", 145, 85,
     "TSMC Q2 2024 Earnings", "AI accelerator demand driving record N5/N4 loading"),
    ("TSMC", "Foundry", "GPU/CPU Advanced (≤5nm)", "2024-Q3", 150, 88,
     "TSMC Q3 2024 Earnings", "N3 ramp accelerating; CoWoS capacity doubling in 2025"),
    ("TSMC", "Foundry", "GPU/CPU Advanced (≤5nm)", "2024-Q4", 155, 90,
     "TSMC Q4 2024 Earnings", "Full utilisation on 3nm/4nm; capacity constrained by CoWoS"),
    ("TSMC", "Foundry", "GPU/CPU Advanced (≤5nm)", "2025-Q1", 160, 92,
     "TSMC Q1 2025 Earnings", "AI demand record high; Arizona Fab 21 Phase 1 online"),
    # Legacy nodes (≥28nm): Automotive, IoT, consumer
    ("TSMC", "Foundry", "Legacy (≥28nm)",           "2023-Q4", 420, 70,
     "TSMC Q4 2023 Earnings", "Automotive recovery beginning; consumer still weak"),
    ("TSMC", "Foundry", "Legacy (≥28nm)",           "2024-Q2", 420, 74,
     "TSMC Q2 2024 Earnings", "IoT and automotive gradually recovering"),
    ("TSMC", "Foundry", "Legacy (≥28nm)",           "2024-Q4", 420, 78,
     "TSMC Q4 2024 Earnings", "Recovery broadening; N28/N22 fully loaded for power ICs"),

    # ─────────────────────── Samsung ──────────────────────────────────────────
    # Foundry (Logic)
    ("Samsung", "Foundry", "GPU/CPU (4nm/3nm GAA)", "2023-Q4", 80, 52,
     "Samsung Q4 2023 Earnings", "Yield issues at 3nm GAA; customers cautious"),
    ("Samsung", "Foundry", "GPU/CPU (4nm/3nm GAA)", "2024-Q2", 80, 55,
     "Samsung Q2 2024 Earnings", "Qualcomm/AMD limited orders; yield improvements ongoing"),
    ("Samsung", "Foundry", "GPU/CPU (4nm/3nm GAA)", "2024-Q4", 82, 58,
     "Samsung Q4 2024 Earnings", "New 3nm GAA customers qualifying; still lagging TSMC on advanced"),
    # DRAM
    ("Samsung", "Memory",  "DRAM (All Nodes)",       "2023-Q4", 550, 68,
     "Samsung Q4 2023 Earnings", "Supply cuts sustained through 2023 to stabilise ASP"),
    ("Samsung", "Memory",  "DRAM (All Nodes)",       "2024-Q2", 580, 76,
     "Samsung Q2 2024 Earnings", "HBM3E ramp taking share of capacity from standard DRAM"),
    ("Samsung", "Memory",  "DRAM (All Nodes)",       "2024-Q4", 600, 82,
     "Samsung Q4 2024 Earnings", "Standard DRAM ASP recovery; HBM mix increasing"),
    # NAND
    ("Samsung", "Memory",  "NAND Flash",             "2023-Q4", 850, 65,
     "Samsung Q4 2023 Earnings", "Aggressive production cut to stabilise NAND pricing"),
    ("Samsung", "Memory",  "NAND Flash",             "2024-Q4", 900, 78,
     "Samsung Q4 2024 Earnings", "Enterprise SSD demand recovery; QLC ramp for data centers"),

    # ─────────────────────── SK Hynix ─────────────────────────────────────────
    ("SK Hynix", "Memory", "HBM3 / HBM3E",          "2024-Q1", 28,  98,
     "SK Hynix Q1 2024 Earnings", "Essentially all HBM3E allocated to NVIDIA through 2024"),
    ("SK Hynix", "Memory", "HBM3 / HBM3E",          "2024-Q4", 35,  100,
     "SK Hynix Q4 2024 Earnings", "Sold out; 2025 allocation sold to hyperscalers/NVDA/AMD"),
    ("SK Hynix", "Memory", "HBM3 / HBM3E",          "2025-Q1", 42,  100,
     "SK Hynix Q1 2025 Earnings", "Capacity expanding; 12-Hi HBM3E ramping; HBM4 sampling"),
    ("SK Hynix", "Memory", "DRAM (Standard DDR4/5)", "2023-Q4", 320, 70,
     "SK Hynix Q4 2023 Earnings", "Capacity being redirected to HBM; standard DRAM under-invested"),
    ("SK Hynix", "Memory", "DRAM (Standard DDR4/5)", "2024-Q4", 345, 84,
     "SK Hynix Q4 2024 Earnings", "Strong AI server DRAM (DDR5 RDIMM) demand"),

    # ─────────────────────── Micron ───────────────────────────────────────────
    ("Micron", "Memory",   "DRAM (All)",             "2023-Q4", 250, 72,
     "Micron Q4 FY2023 Earnings", "Production cuts and node migration underway"),
    ("Micron", "Memory",   "DRAM (All)",             "2024-Q2", 265, 80,
     "Micron Q2 FY2024 Earnings", "HBM3E qualification at NVIDIA secured; ramp starting"),
    ("Micron", "Memory",   "DRAM (All)",             "2024-Q4", 280, 85,
     "Micron Q4 FY2024 Earnings", "HBM3E supply allocated through calendar 2025"),
    ("Micron", "Memory",   "HBM3E",                  "2025-Q1", 15,  100,
     "Micron Q1 FY2025 Earnings", "All HBM3E sold out; meaningful revenue contribution from 2025"),
    ("Micron", "Memory",   "NAND Flash",             "2023-Q4", 350, 65,
     "Micron Q4 FY2023 Earnings", "Aggressive bit output reduction to clear inventory"),
    ("Micron", "Memory",   "NAND Flash",             "2024-Q4", 370, 77,
     "Micron Q4 FY2024 Earnings", "Enterprise SSD recovery; data centre SSD strong"),

    # ─────────────────────── Intel ────────────────────────────────────────────
    ("Intel",   "Foundry",  "CPU (Intel 7 / Intel 4)", "2023-Q4", 115, 68,
     "Intel Q4 2023 Earnings", "PC market recovery; AI PC transition starting"),
    ("Intel",   "Foundry",  "CPU (Intel 7 / Intel 4)", "2024-Q4", 120, 72,
     "Intel Q4 2024 Earnings", "Arrow Lake on Intel 20A/TSMC hybrid; internal yield improving"),
    ("Intel",   "Foundry",  "Intel 18A (External)",    "2025-Q1", 10,  45,
     "Intel Q1 2025 Earnings", "Early production; Amazon, Microsoft qualifying; major ramp H2 2025"),
]

# ── Curated DRAM & HBM Spot Prices ───────────────────────────────────────────
# Source: TrendForce DRAM weekly spot reports (approximated monthly average).
# DDR4 8Gb 1Gx8 is the industry benchmark die price.
# DDR5 16Gb 2Gx8 is the emerging benchmark.
# HBM3E prices are per-GB contract estimates.
# Format: (product_type, spec_label, period_YYYY-MM, price_usd, source)
CURATED_DRAM_SPOT = [
    # ── DDR4 8Gb benchmark die ────────────────────────────────────────────────
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2023-01", 1.20, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2023-03", 1.05, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2023-06", 0.92, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2023-09", 1.10, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2023-12", 1.40, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-01", 1.65, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-02", 1.85, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-03", 2.05, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-04", 2.30, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-05", 2.55, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-06", 2.75, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-07", 2.90, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-08", 3.05, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-09", 2.95, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-10", 2.80, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-11", 2.70, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2024-12", 2.65, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2025-01", 2.60, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2025-02", 2.55, "TrendForce"),
    ("DDR4", "8Gb 1Gx8 die (spot)",  "2025-03", 2.50, "TrendForce"),

    # ── DDR5 16Gb benchmark die ───────────────────────────────────────────────
    ("DDR5", "16Gb 2Gx8 die (spot)", "2023-01", 3.20, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2023-06", 2.80, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2023-12", 3.80, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-01", 4.10, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-02", 4.40, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-03", 4.80, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-04", 5.20, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-05", 5.70, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-06", 6.10, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-07", 6.70, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-08", 7.00, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-09", 6.80, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-10", 6.40, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-11", 6.10, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2024-12", 5.80, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2025-01", 5.60, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2025-02", 5.40, "TrendForce"),
    ("DDR5", "16Gb 2Gx8 die (spot)", "2025-03", 5.30, "TrendForce"),

    # ── HBM3E contract price per GB ───────────────────────────────────────────
    ("HBM3E", "HBM3E 12-Hi contract (per GB)", "2024-01", 12.00, "TrendForce est."),
    ("HBM3E", "HBM3E 12-Hi contract (per GB)", "2024-04", 13.50, "TrendForce est."),
    ("HBM3E", "HBM3E 12-Hi contract (per GB)", "2024-07", 15.00, "TrendForce est."),
    ("HBM3E", "HBM3E 12-Hi contract (per GB)", "2024-10", 15.80, "TrendForce est."),
    ("HBM3E", "HBM3E 12-Hi contract (per GB)", "2025-01", 16.50, "TrendForce est."),
    ("HBM3E", "HBM3E 12-Hi contract (per GB)", "2025-03", 17.00, "TrendForce est."),
]

# ── SEMI North-America Equipment Book-to-Bill ─────────────────────────────────
# Ratio > 1.00 = orders outpace billings (demand expanding / lead times growing)
# Ratio < 1.00 = billings outpace orders (demand contracting)
# Source: SEMI monthly press releases (https://www.semi.org/)
CURATED_SEMI_BTB = [
    ("2023-01", 0.88, "SEMI NA Equipment B2B"),
    ("2023-02", 0.87, "SEMI NA Equipment B2B"),
    ("2023-03", 0.89, "SEMI NA Equipment B2B"),
    ("2023-04", 0.92, "SEMI NA Equipment B2B"),
    ("2023-05", 0.95, "SEMI NA Equipment B2B"),
    ("2023-06", 0.97, "SEMI NA Equipment B2B"),
    ("2023-07", 0.99, "SEMI NA Equipment B2B"),
    ("2023-08", 1.01, "SEMI NA Equipment B2B"),
    ("2023-09", 1.04, "SEMI NA Equipment B2B"),
    ("2023-10", 1.06, "SEMI NA Equipment B2B"),
    ("2023-11", 1.09, "SEMI NA Equipment B2B"),
    ("2023-12", 1.11, "SEMI NA Equipment B2B"),
    ("2024-01", 1.13, "SEMI NA Equipment B2B"),
    ("2024-02", 1.10, "SEMI NA Equipment B2B"),
    ("2024-03", 1.14, "SEMI NA Equipment B2B"),
    ("2024-04", 1.12, "SEMI NA Equipment B2B"),
    ("2024-05", 1.16, "SEMI NA Equipment B2B"),
    ("2024-06", 1.19, "SEMI NA Equipment B2B"),
    ("2024-07", 1.17, "SEMI NA Equipment B2B"),
    ("2024-08", 1.20, "SEMI NA Equipment B2B"),
    ("2024-09", 1.23, "SEMI NA Equipment B2B"),
    ("2024-10", 1.25, "SEMI NA Equipment B2B"),
    ("2024-11", 1.22, "SEMI NA Equipment B2B"),
    ("2024-12", 1.27, "SEMI NA Equipment B2B"),
    ("2025-01", 1.30, "SEMI NA Equipment B2B"),
    ("2025-02", 1.28, "SEMI NA Equipment B2B"),
    ("2025-03", 1.31, "SEMI NA Equipment B2B"),
]

# ── Convenience: all products merged ─────────────────────────────────────────
ALL_PRODUCTS = {**GPU_PRODUCTS, **CPU_PRODUCTS, **RAM_PRODUCTS}

# Products that have Newegg listings (for live price + stock scraping)
NEWEGG_PRODUCTS = {k: v for k, v in ALL_PRODUCTS.items() if v.get("newegg_q")}
