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
    # sim-stitching (docs/superpowers/plans/2026-07-14-sim-stitching.md)
    "churn_named_max": 2,       # max NAMED join/leave feed items per direction per tick; rest → summary
    "overflow_max_hops": 2,     # full venue → try this many next same-kind candidates before street
    # geo (NPC geographic knowledge) — geometric/social tunables, NOT willingness
    "geo_neighbor_hops": 2,     # a home within this many graph hops of yours = "сосед"
    "geo_friend_aff": 0.3,      # affinity above this = friend (reuses seeds.py:203 literal)
    "talk_min": 2,
    "loot_min": 2,
    "trade_min": 3,
    "act_min": 2,
    "live_tick_min": 3,
    "live_gap_s": 6.0,
    # LOD layers: not everyone thinks (LLM) each tick — crowds rotate (docs/sound-attention.md).
    # This is level-of-detail, not a behavior cap: NPCs with a concrete REASON to act (impulse
    # label in world._MUST_WHY — event/owed-answer/promise/foreshadow/emotion/overheard-player)
    # always think; the reasonless background crowd is staggered round-robin so nobody starves.
    "live_full_upto": 3,        # ≤ this many present → EVERYONE thinks this tick
    "live_active_ratio": 0.5,   # else ~this fraction of the crowd thinks per tick
    "live_active_cap": 6,       # hard ceiling on LLM actors per tick (latency)
    "pc_said_impulse": 2.8,   # near hearer pull when the player speaks aloud (L1; tier-scaled). tuned up so L2 hearers also engage
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
    # emergent quests (Inc 2) — salience weights + surfacing windows (docs/superpowers/specs/2026-07-12-emergent-quests-design.md §11)
    "quest_topk": 4,          # seeds sent to the judge
    "quest_offer_days": 2,    # days an unaccepted offer lives before compost
    "quest_w_rare": 1.0,      # salience weight — pattern rarity
    "quest_w_peak": 1.0,      # salience weight — cast affinity/deed peak
    "quest_w_near": 0.6,      # salience weight — giver↔player proximity
    "quest_w_fresh": 0.8,     # salience weight — evidence freshness
    "quest_plan_n": 3,        # NPCs given a life-goal each morning so the sifter has material
    "quest_active_max": 1,        # emergent quests in the surfacing window at once (director)
    "quest_interrupt_k": 2.0,     # a new seed must score ≥ k× queued to jump the window
    "quest_foreshadow_ticks": 2,  # ticks of mind-impulse foreshadow before the offer
    "quest_twist_p": 0.7,         # probability a qualifying twist candidate is planted
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
    "workplace_purpose_lift": 0.6,   # on-shift worker's purpose lift (additive to purpose goal; tune in playtest)
    # RUMOR SATURATION (docs/.../npc-topic-diversity-design.md): a room tires of a chewed subject
    "rumor_rot_min": 90,     # rotate a location rumor every ~this many game-minutes (was: whole day)
    "rumor_warm": 0.34,      # heat added each time a subject is offered
    "rumor_hot": 1.0,        # heat ≥ this → subject drops out of offered topics (~3 offers)
    "rumor_cool": 0.15,      # heat decay per tick (cools back over ~7 ticks)
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
    # LUCK & INSPIRATION: earned karma → luck; a fleeting inspiration spark (feeds the craft roll)
    "karma_ceil": 100,
    "karma_floor": 100,          # symmetric bound (±)
    "karma_per_luck": 20,        # karma ÷ this = luck
    "luck_cap": 4.0,             # luck bounded ±
    "karma_crime": 4,            # a witnessed crime lowers karma
    "karma_gift": 3,
    "karma_quest": 6,
    "karma_mercy": 5,
    "insp_spark": 5.0,           # inspiration set on an unusual sighting
    "insp_minutes": 90,          # decays linearly to 0 over this many game-minutes
    "mana_start": 12.0,
    "mana_cap_start": 14.0,
    "mana_hardcap_per_int": 8,  # cap ≤ Int×8
    "mana_regen_base": 1.0,
    "mana_grow_frac": 0.1,
    "mana_sleep_mult": 3,  # sleep fills candle faster
    "mana_per_band": 3.0,  # a mana draught restores (special:mana band) × this to the pool
    "enchant_chara_k": 10.0,  # item holds a bound law up to (чара ÷ this) power budget
    "enchant_charges": 3,     # a bound enchant fires this many times before it's spent
    # NPC↔NPC trade & haggle (emergent): value corridor + multi-tick negotiation, settled in the store
    "haggle_patience": 4,     # negotiation rounds before the parties walk away
    "haggle_gap_eps": 1.0,    # offers within this many coins → strike the deal at their mean
    "haggle_s_base": 0.55,    # seller concession base per round (toward the midpoint)
    "haggle_b_base": 0.35,    # buyer concession base per round
    "haggle_wants_chosen": 0.8,  # a buyer who CHOSE (LLM buy) wants it strongly → raises what he'll pay
    "haggle_wants": 0.6,      # background trickle: a commercially-minded buyer's moderate want for a good
    "haggle_bg_p": 0.14,      # background trickle: chance such a buyer opens a deal this tick (a low hum)
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
    # CRAFT SPARK LADDER: spark = base + mastery + material + luck + inspiration + d20 → band
    "craft_base": 2,
    "craft_material_k": 0.15,   # material-quality contribution (mean input attr × this)
    "craft_waste": 12,          # spark < this → inputs wasted, nothing made
    "craft_flaw": 18,           # < this → item with a HIDDEN crack (low true прочность)
    "craft_clean": 26,          # < this → clean plain item
    "craft_fine": 34,           # < this → fine (modified); ≥ this → exquisite masterwork
    "craft_flaw_mul": 0.35,     # flawed item: true прочность × this
    "craft_masterwork_bonus": 12,  # masterwork: strongest attribute +this
    "craft_time": 30,           # minutes spent per craft
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
    # PLAYER JOURNAL «Хроника»: rows kept per world; prune oldest on insert (docs/.../player-journal-design.md)
    "journal_cap": 2000,
}
_GT0 = PB["start_gt"]
