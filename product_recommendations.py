"""
Built-in product → accessory recommendations for Performance Cycle (Englewood, CO).

Uses explicit product mappings + category fallback so EVERY product gets recommendations.
If a product slug isn't found, it matches by keyword (helmet, oil, air-filter, etc.).
"""

# ═══════════════════════════════════════════════════════════════
# EXPLICIT PRODUCT MAPPINGS
# ═══════════════════════════════════════════════════════════════
RECOMMENDATIONS = {
    # HELMETS
    "agv-pista-gp-rr-mono-carbon-helmet": [
        {"id": "agv-pista-gp-rr-face-shield", "label": "AGV Pista GP-RR Face Shield"},
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "pinlock-earplug-set-w-case", "label": "Hearing protection"},
    ],
    "agv-pista-gp-rr-soleluna-2023-limited-edition": [
        {"id": "agv-pista-gp-rr-face-shield", "label": "Face Shield"},
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "alpinestars-supertech-r10-flyte-le-helmet": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "fly-racing-garage-helmet-bag", "label": "Garage helmet bag"},
        {"id": "sena-30k-hd-communication-system-single-unit", "label": "Bluetooth headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "alpinestars-supertech-r10-limited-edition-pedro-acosta-helmet": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "sena-30k-hd-communication-system-single-unit", "label": "Bluetooth headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "alpinestars-supertech-r10-team-helmet": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "alpinestars-supertech-r10-element-helmet": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "alpinestars-supertech-r10-helmet": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "shoei-x-15-daijiro-tc-1-helmet": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "sena-srl-mesh-communication-system", "label": "SRL Mesh headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "shoei-x-15-marquez-73-v2-helmet": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "sena-srl-mesh-communication-system", "label": "SRL Mesh headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "shoei-x-15-escalate-helmet": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "sena-srl-mesh-communication-system", "label": "SRL Mesh headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "shoei-x-15-marquez-7-helmet": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "sena-srl-mesh-communication-system", "label": "SRL Mesh headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "shoei-x-15-helmet": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "sena-srl-mesh-communication-system", "label": "SRL Mesh headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "shoei-neotec-3-modular-helmet": [
        {"id": "shoei-evo-cns-2-pinlock-lens", "label": "Pinlock anti-fog insert"},
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "sena-srl-mesh-communication-system", "label": "SRL Mesh headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "schuberth-c5-helmet": [
        {"id": "schuberth-sc2-bluetooth-intercom", "label": "Schuberth SC2 intercom"},
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "hjc-rpha-1n-jerez-redbull-helmet": [
        {"id": "hjc-hj-26st-pinlock-face-shield", "label": "Pinlock face shield"},
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "sena-20s-evo-hd-communication-system-single", "label": "Bluetooth headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "kyt-tt-revo-replica-helmet": [
        {"id": "kyt-tt-revo-visor", "label": "Replacement visor"},
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "sena-20s-evo-hd-communication-system-single", "label": "Bluetooth headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "ls2-dragon-forged-carbon-helmet": [
        {"id": "ls2-pinlock-ready-iridium-shield-for-assault-rapid-stream-helmets", "label": "Pinlock-ready face shield"},
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "sena-20s-evo-hd-communication-system-single", "label": "Bluetooth headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "airoh-2025-commander-2-dot-helmet": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "fly-racing-garage-helmet-bag", "label": "Garage helmet bag"},
        {"id": "sena-30k-hd-communication-system-single-unit", "label": "Bluetooth headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "leatt-moto-7-5-v26-red-helmet-kit": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "agv-k3-pinlock-face-shield": [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "shoei-rf-1400-helmet-shield-cwr-f2": [
        {"id": "shoei-evo-pinlock-lens-insert", "label": "Pinlock anti-fog insert"},
    ],
    "shoei-srl-ext-for-rf-1400-communication-system": [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],

    # JACKETS & RIDING GEAR
    "klim-badlands-pro-jacket": [
        {"id": "alpinestars-nucleon-plasma-back-protector-with-strap", "label": "CE back protector"},
        {"id": "revit-slingshot-back-protector", "label": "REV'IT! Slingshot back protector"},
        {"id": "alpinestars-nucleon-plasma-back-protector", "label": "Back protector insert"},
    ],
    "alpinestars-fusion-1-piece-race-suit": [
        {"id": "alpinestars-nucleon-plasma-back-protector-with-strap", "label": "CE back protector"},
    ],
    "alpinestars-2025-missile-v2-1-piece-ignition-leather-suit": [
        {"id": "alpinestars-nucleon-plasma-back-protector-with-strap", "label": "CE back protector"},
    ],

    # BOOTS
    "alpinestars-tech-7-enduro-boots-2026": [
        {"id": "revit-expedition-gtx-boots", "label": "Waterproof ADV boot option"},
        {"id": "motorex-adventure-chain-lube", "label": "Chain lube for your ride"},
    ],
    "alpinestars-tech-10-enduro-boots": [
        {"id": "alpinestars-tech-10-boots-2025", "label": "Latest Tech 10 boot"},
    ],
    "alpinestars-tech-10-supervented-boots-2025": [
        {"id": "alpinestars-tech-10-boots-2025", "label": "Tech 10 boot"},
    ],
    "revit-expedition-gtx-boots": [
        {"id": "sidi-taurus-gtx-boots", "label": "SIDI Taurus GTX – alternative ADV boot"},
    ],
    "sidi-taurus-gtx-boots": [
        {"id": "revit-expedition-gtx-boots", "label": "REV'IT! Expedition GTX – alternative ADV boot"},
    ],
    "alpinestars-womens-stella-faster-4-shoes": [
        {"id": "alpinestars-supertech-r-vented-mm93-replica-boots", "label": "Racing boot option"},
    ],

    # TIRES
    "michelin-pilot-road-5-sport-touring-tires": [
        {"id": "continental-trail-attack-3-dual-sport-tires", "label": "Trail Attack 3 – ADV tire"},
    ],
    "continental-trail-attack-3-dual-sport-tires": [
        {"id": "continental-tkc70-rocks-dual-sport-tires", "label": "TKC70 Rocks – more off-road"},
    ],
    "continental-tkc70-rocks-dual-sport-tires": [
        {"id": "continental-trail-attack-3-dual-sport-tires", "label": "Trail Attack 3 – more on-road"},
    ],
    "michelin-scorcher-31-cruiser-tire": [
        {"id": "michelin-scorcher-11-cruiser-tire", "label": "Scorcher 11 cruiser tire"},
    ],
    "dunlop-sportmax-q5-sportbike-tires": [
        {"id": "michelin-power-gp2-sport-tires", "label": "Michelin Power GP2 – track tire"},
    ],
    "dunlop-elite-4-touring-tires": [
        {"id": "dunlop-roadsmart-4-sport-touring-tires", "label": "Roadsmart 4 – sport touring"},
    ],

    # COMMUNICATION SYSTEMS
    "sena-30k-hd-communication-system-single-unit": [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs for hearing protection"},
    ],
    "sena-60s-communication-system-with-harman-kardon-speakers-single-unit": [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "sena-50r-communication-system-with-harman-kardon-speakers-single-unit": [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "sena-50s-communication-system-with-harman-kardon-speakers-single-unit": [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "sena-srl-mesh-communication-system": [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],

    # OILS & LUBRICANTS
    "motorex-gear-oil-10w30": [
        {"id": "hiflo-hf-138rc-race-oil-filter", "label": "Oil filter"},
        {"id": "motorex-chain-cleaner-degreaser", "label": "Chain cleaner"},
    ],
    "yamalube-regular-motorcycle-oil": [
        {"id": "hiflo-hf-138rc-race-oil-filter", "label": "Oil filter"},
        {"id": "motorex-chain-cleaner-degreaser", "label": "Chain cleaner"},
    ],
    "motul-transoil-expert-10w40-synthetic-transmission-oil": [
        {"id": "hiflo-hf-138rc-race-oil-filter", "label": "Oil filter"},
    ],
    "no-toil-foam-air-filter-oil": [
        {"id": "twin-air-air-filter-for-2024-kawasaki-kx450", "label": "Twin Air air filter"},
        {"id": "pj1-foam-filter-oil-13oz", "label": "Extra filter oil"},
    ],
    "belray-high-performance-fork-oil": [
        {"id": "motorex-gear-oil-10w30", "label": "Gear oil for transmission"},
    ],
    "pj1-foam-filter-oil-13oz": [
        {"id": "no-toil-foam-air-filter-oil", "label": "No Toil air filter oil"},
    ],

    # AIR FILTERS
    "twin-air-air-filter-for-2024-kawasaki-kx450": [
        {"id": "no-toil-foam-air-filter-oil", "label": "Air filter oil"},
        {"id": "pj1-foam-filter-oil-13oz", "label": "PJ1 filter oil"},
    ],
    "twin-air-air-filter-for-2023-yamaha-yz-450f": [
        {"id": "no-toil-foam-air-filter-oil", "label": "Air filter oil"},
    ],
    "twin-air-air-filter-for-2013-2019-beta": [
        {"id": "no-toil-foam-air-filter-oil", "label": "Air filter oil"},
    ],
    "twin-air-air-filter-for-2019-2022-kawasaki-kx": [
        {"id": "no-toil-foam-air-filter-oil", "label": "Air filter oil"},
    ],
    "twin-air-air-filter-for-1999-2023-rm-and-drz": [
        {"id": "no-toil-foam-air-filter-oil", "label": "Air filter oil"},
    ],

    # CHAIN LUBE & CARE
    "motorex-adventure-chain-lube": [
        {"id": "motorex-chain-cleaner-degreaser", "label": "Chain cleaner"},
        {"id": "motul-chain-care-kit-offroad", "label": "Motul chain care kit"},
    ],
    "pj1-blue-label-chain-lube": [
        {"id": "motorex-chain-cleaner-degreaser", "label": "Chain cleaner"},
    ],
    "motorex-road-strong-chain-lube": [
        {"id": "motorex-chain-cleaner-degreaser", "label": "Chain cleaner"},
    ],
    "bel-ray-super-clean-chain-lube": [
        {"id": "motorex-chain-cleaner-degreaser", "label": "Chain cleaner"},
    ],
    "maxima-chain-wax": [
        {"id": "motorex-chain-cleaner-degreaser", "label": "Chain cleaner"},
    ],
    "motul-chain-care-kit-offroad": [
        {"id": "motorex-chain-cleaner-degreaser", "label": "Chain cleaner"},
    ],
    "motul-chain-care-kit-road": [
        {"id": "motorex-chain-cleaner-degreaser", "label": "Chain cleaner"},
    ],

    # OIL FILTERS
    "hiflo-hf-138rc-race-oil-filter": [
        {"id": "motorex-gear-oil-10w30", "label": "Gear oil for change"},
    ],
    "hiflo-hf-303rc-race-oil-filter": [
        {"id": "motorex-gear-oil-10w30", "label": "Gear oil for change"},
    ],

    # BRAKE PADS
    "ebc-fa103-brake-pad": [
        {"id": "bel-ray-super-clean-chain-lube", "label": "Chain lube"},
    ],
    "ebc-fa434-brake-pad": [
        {"id": "bel-ray-super-clean-chain-lube", "label": "Chain lube"},
    ],
    "ebc-fa458v-semi-sintered-brake-pad": [
        {"id": "bel-ray-super-clean-chain-lube", "label": "Chain lube"},
    ],

    # BACKPACKS & BAGS
    "kriega-r20-backpack": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "kriega-r25-v2-backpack": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
    ],
    "kriega-r30-backpack": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
    ],
    "alpinestars-amp3-backpack": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
    ],
    "klim-2025-arsenal-15-backpack": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "klim-2025-arsenal-trail-10l-backpack": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
    ],
    "klim-2025-arsenal-xc-5l-backpack": [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ],
    "ogio-no-drag-mach-s-backpack": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
    ],
    "ogio-no-drag-backpack-mach-3": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
    ],
    "fox-racing-180-backpack": [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
    ],

    # TECH-AIR / AIRBAG
    "alpinestars-tech-air-mx": [
        {"id": "alpinestars-nucleon-plasma-back-protector", "label": "Additional back protection"},
    ],
    "garmin-fenix-8-51mm-amoled-watch": [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs for rides"},
    ],
}

# ═══════════════════════════════════════════════════════════════
# CATEGORY FALLBACK - matches product slugs by keyword
# Ensures EVERY product in the store gets recommendations
# ═══════════════════════════════════════════════════════════════
CATEGORY_RULES = [
    # (keywords in slug, recommendations)
    (["helmet", "visor", "shield"], [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "sena-30k-hd-communication-system-single-unit", "label": "Bluetooth headset"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ]),
    (["boot", "shoe"], [
        {"id": "bel-ray-super-clean-chain-lube", "label": "Chain lube"},
        {"id": "motorex-adventure-chain-lube", "label": "Chain lube"},
    ]),
    (["jacket", "suit", "race-suit", "leather"], [
        {"id": "alpinestars-nucleon-plasma-back-protector-with-strap", "label": "CE back protector"},
        {"id": "revit-slingshot-back-protector", "label": "REV'IT! back protector"},
    ]),
    (["glove"], [
        {"id": "alpinestars-nucleon-plasma-back-protector", "label": "Back protector"},
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
    ]),
    (["oil", "gear-oil", "transoil", "transmission", "fork-oil", "motorcycle-oil"], [
        {"id": "hiflo-hf-138rc-race-oil-filter", "label": "Oil filter"},
        {"id": "motorex-chain-cleaner-degreaser", "label": "Chain cleaner"},
    ]),
    (["air-filter"], [
        {"id": "no-toil-foam-air-filter-oil", "label": "Air filter oil"},
        {"id": "pj1-foam-filter-oil-13oz", "label": "PJ1 filter oil"},
    ]),
    (["filter-oil", "foam-filter"], [
        {"id": "twin-air-air-filter-for-2024-kawasaki-kx450", "label": "Twin Air air filter"},
    ]),
    (["oil-filter", "oil-filter"], [
        {"id": "motorex-gear-oil-10w30", "label": "Gear oil"},
    ]),
    (["chain", "lube", "chain-lube", "chain-wax"], [
        {"id": "motorex-chain-cleaner-degreaser", "label": "Chain cleaner"},
        {"id": "motul-chain-care-kit-offroad", "label": "Chain care kit"},
    ]),
    (["chain-cleaner", "degreaser"], [
        {"id": "motorex-adventure-chain-lube", "label": "Chain lube"},
    ]),
    (["brake", "pad"], [
        {"id": "bel-ray-super-clean-chain-lube", "label": "Chain lube"},
    ]),
    (["communication", "sena", "bluetooth", "intercom", "headset"], [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ]),
    (["backpack", "pack", "bag", "kriega", "ogio-no-drag"], [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ]),
    (["tire", "tyre"], [
        {"id": "bel-ray-super-clean-chain-lube", "label": "Chain lube"},
    ]),
    (["goggle", "goggles"], [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
    ]),
    (["heated", "heated-gear"], [
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
    ]),
]


def get_recommendations(product_id: str) -> list:
    """Get recommendations for a product. Checks explicit first, then category fallback."""
    pid_lower = product_id.lower()
    # 1. Explicit match
    if product_id in RECOMMENDATIONS:
        return RECOMMENDATIONS[product_id]
    # 2. Category fallback
    for keywords, recs in CATEGORY_RULES:
        if any(kw in pid_lower for kw in keywords):
            return recs
    # 3. Generic fallback for any product
    return [
        {"id": "pinlock-earplug-set-w-case", "label": "Earplugs"},
        {"id": "ogio-head-case-helmet-bag", "label": "Helmet bag"},
    ]
