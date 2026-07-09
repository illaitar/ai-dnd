"""Session config — tunables for the play layer.

Key functions
-------------
PLAYER : str : Player entity id used across session/state/store keys.
PB : dict : UNIFIED balance table (thresholds/coefficients/times) for the play layer.
_GT0 : int : Starting game-time in minutes (derived from PB["start_gt"]).
"""

from __future__ import annotations

PLAYER = "pc"

# UNIFIED balance table for play layer (after mind.value.BAL pattern): all thresholds/coefficients/times
# NAMED and live here — not scattered across code.
PB = {
    "start_gt": 19 * 60 + 40,
    "start_coins": 12,
    "step_min": 1,
    "talk_min": 2,
    "loot_min": 2,
    "trade_min": 3,
    "act_min": 2,
    "live_tick_min": 3,
    "live_gap_s": 6.0,
    "give_min": 1,
    # prices: sell to trader / buy from them (from THEIR vision of worth)
    "sell_base": 0.55,
    "sell_aff": 0.15,
    "sell_greed": -0.2,
    "buy_base": 1.35,
    "buy_greed": 0.25,
    "buy_aff": -0.15,
    # crime gates
    "steal_dc_base": 9,
    "steal_dc_att": 8,
    "rob_dc_base": 10,
    "rob_dc_brav": 8,
    "purse_cut": 2,  # theft takes 1/N of purse
    "rob_cut_num": 2,
    "rob_cut_den": 3,  # robbery takes num/den
    # ask for key: bar = base + greed·k + honesty·k
    "askkey_base": 0.5,
    "askkey_greed": 0.4,
    "askkey_honesty": -0.2,
    # contracts
    "contract_enemy_aff": -0.1,
    "contract_poor_purse": 5,
    "contract_reward_min": 2,
    "complete_trust": 0.3,
    "complete_aff": 0.2,
    "befriend_aff": 0.25,
    "merchant_float": 30,
    "hostile_aff": -0.2,
    # NPC schedule — from NEEDS (aidnd.society), not from role probabilities (see society/*)
    "plan_cap": 3,  # chain links from one phrase: plan longer — truncate
    # PLAYER DEALS (deal-gate): base DC/prices by type, weight of temperament/bet adequacy
    "deal_dc_dead": 15,
    "deal_dc_bring": 11,
    "deal_dc_visit": 9,
    "deal_dc_befriend": 10,
    "deal_price_dead": 30,
    "deal_price_bring": 8,
    "deal_price_visit": 4,
    "deal_price_befriend": 6,
    "deal_honesty_k": 7,
    "deal_honesty_dead_k": 12,
    "deal_malice_dead_k": 8,
    "deal_adq_k": 5,
    "deal_adq_clamp": 6,  # bet adequacy moves DC maximum by ±6
    "deal_aff_k": 6,
    "deal_fear_k": 4,
    "deal_flat_honesty": 0.75,
    "deal_flat_malice": 0.35,  # honest and harmless won't take blood WITHOUT roll
    "deal_kin_aff": 0.3,  # warm relations with target — "won't touch own"
    "deal_due_min": 1440,  # one day to fulfill agreement
    "deal_night_min": 300,  # blood not before 5 hours (at night)
    "crime_solicit": 3,  # solicitation of murder on refusal — wanted
    # EAVESDROP (perceptual link): DC = base + zone noise; success holds N ticks
    "listen_dc_base": 8,
    "listen_noise_k": 8,
    "listen_ticks": 3,
    # SOUND (docs/sound-attention.md): heard = loudness − sound_k · euclid(centroids); tier by thresholds
    "sound_k": 0.045,          # falloff per cell of centroid distance
    "sound_t1": 0.6,           # heard ≥ t1 → L1 (verbatim)
    "sound_t2": 0.35,          # heard ≥ t2 → L2 (cutout)
    "sound_t3": 0.12,          # heard ≥ t3 → L3 (presence only); below → inaudible
    "sound_voice": 0.8,        # loudness of ordinary conversation
    "sound_cutout_keep": 0.4,  # fraction of words kept at L2
    "sound_mem_l1": 0.18,      # overheard-memory weight at L1 (matches today's same-zone weight)
    "sound_mem_l2": 0.12,
    "sound_mem_l3": 0.06,
    "sound_murmur_k": 0.5,     # crowd-murmur loudness = occupancy_frac × zone.noise × this
    # LEISURE (tavern playtest): a leisure venue lifts converse toward ACQUAINTANCES only (aff>0),
    # so regulars talk instead of idly eating; strangers get no lift. Set on present states in _live_build.
    "leisure_social_lift": 3.0,
    # gift: affinity gain = min(cap, base + worth/div)
    "gift_aff_base": 0.05,
    "gift_aff_div": 100,
    "gift_aff_cap": 0.25,
    # hero and lairs
    "pc_max_hp": 18,
    "lairs": 5,
    "lair_cr_near": 0.8,
    "lair_cr_far": 3.0,
    "lair_travel_min": 25,
    "defeat_coin_cut": 2,
    "loot_coin_per_cr": 6,
    "loot_item_chance": 0.6,
    "combat_round_s": 5,  # 1 combat round = 5 seconds game time
    "dungeon_waves": 2,  # lair = this many enemy waves
    "dungeon_step_min": 4,  # transition between dungeon rooms
    "dungeon_loot_min": 3,  # search room
    "dungeon_wander_n": 2,  # wanderers: 1-in-6 check every N transitions
    "incident_p": 0.6,  # chance of new city incident in morning (if active < 2)
    "incident_gang_malice": 0.55,  # threshold for criminals: townspeople form gangs
    "caravan_chance": 0.35,  # chance of caravan with goods in morning
    "path_event_dc": 0.7,  # NPC emotion threshold that breaks path
    # GUARD / WANTED: crime weight (points), arrest threshold, decay/day, fine, escape
    "crime_pickpocket": 1,
    "crime_rob": 3,
    "crime_assault": 4,
    "crime_murder": 8,
    "wanted_confront": 5,
    "wanted_decay": 2,
    "watch_fine_per_pt": 3,
    "watch_flee_dc": 12,
    "watch_jail_h": 7,  # didn't pay — "lockup" until morning
    # MAGIC (mana-candle): start/cap/regen/growth/fatigue/cast difficulty
    "mana_start": 12.0,
    "mana_cap_start": 14.0,
    "mana_hardcap_per_int": 8,  # cap ≤ Int×8
    "mana_regen_base": 1.0,
    "mana_grow_frac": 0.1,
    "mana_sleep_mult": 3,  # sleep fills candle faster
    "fatigue_div": 8,
    "fatigue_min_per_pt": 24,  # fatigue: 1+burned/8 to stats, fades over time
    # DRAWING (M-5.2): candle drains ~drain/sec (softer from Int+Wis) + glyph weight when inscribed;
    # known circle from grimoire — instant for fraction of complexity; burnout (mana 0) → misfire+fatigue×mult
    "draw_drain_per_s": 1.5,
    "draw_intwis_k": 0.12,
    "known_cost_k": 0.6,
    "burnout_fat_mult": 2,
    # glyph teaching from mage/scribe: price = base + weight·k; below affinity — won't teach; high → free
    "learn_base": 6,
    "learn_per_weight": 5,
    "learn_aff_min": -0.15,
    "learn_aff_free": 0.5,
    "taboo_witness": 2,  # attack magic with witnesses → wanted
    "craft_skill_dc": 12,
    "craft_fail_min": 15,  # unfamiliar craft: Int roll / failure cost
    "guild_float": 120,
    "guild_reward_per_cr": 8,
    "guild_mark_fine": 15,
    # NPC delves: chance of brave pair morning expedition
    "npc_delve_chance": 0.6,
    "npc_brave_min": 0.55,
    "fighter_roles": ("стражник", "охотник", "головорез", "бродяга", "наёмник"),
    "board_max_ads": 4,
    "board_npc_fulfill": 0.4,  # board: cap ads, NPC fulfillment chance
    "rest_cost": 2,
    "rest_until_h": 7,
    "tone_friendly_aff": 0.04,
    "tone_rude_aff": 0.08,
    "tone_threat_aff": 0.15,
    "tone_threat_fear": 0.2,
    "look_dc": 8,
    "look_good": 15,
}
_GT0 = PB["start_gt"]
