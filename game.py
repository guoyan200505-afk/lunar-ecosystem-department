import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import random

# Linux 推荐字体（云端 Linux 显示中文）
plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC',
                                    'Source Han Sans SC', 'SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ==========================================
# 航天物理与生物工程参数
# ==========================================
DENSITY_O2 = 1.429
DENSITY_CO2 = 1.977
VOL_HABITAT, VOL_PLANT, VOL_COMPOST = 50.0, 80.0, 20.0
WATER_PER_HABITAT, WATER_PER_PLANT, WATER_PER_COMPOST = 100.0, 150.0, 50.0
O2_TANK_CAPACITY_PER_UNIT = 10.0
MAX_CO2_TANK_CAPACITY = 100.0

MAINTENANCE_COST_PER_MODULE = 0.05

META = {"O2_CONS": 0.84, "CO2_PROD": 1.0, "WATER_USE": 14.5, "SOLID_WASTE": 0.2, "FOOD_CONS": 0.25}
BIO_PARAMS = {
    "ALGAE_CO2_ABS_KG": 0.25, "ALGAE_O2_PROD_KG": 0.20, "ALGAE_WATER_PUR_KG": 0.8,
    "COMPOST_MAX_SW_PER_UNIT": 3.0, "COMPOST_MAX_WW_PER_UNIT": 10.0,
    "PLANT_BASE_EVAPORATION": 15.0
}

# ============================================================
# 难度模式（v7 · 开局锁定的突发事件强度）
# ============================================================
DIFFICULTY_LEVELS = {
    "easy":   {"name": "简单模式", "emoji": "🌱", "chance": 0.04,
               "desc": "事件稀少 · 适合熟悉系统、欣赏闭环演进"},
    "hard":   {"name": "困难模式", "emoji": "⚔️", "chance": 0.10,
               "desc": "事件常态 · 需要应急储备与天赋协同"},
    "hell":   {"name": "地狱模式", "emoji": "🔥", "chance": 0.20,
               "desc": "事件频发 · 任何疏忽都可能导致生物圈崩溃"},
}
DEFAULT_DIFFICULTY = "hard"

# ============================================================
# 突发事件库（与 v5 相同）
# ============================================================
def _solar_particle_impact(s, ctx):
    shield = s.get("Regolith_Shield_m2", 0.0)
    exposure = max(0.0, 1.0 - shield * 0.004)
    rad_mood = s.get("research_multipliers", {}).get("radiation_mood", 1.0)
    ctx["mood_shock"](-25.0 * exposure * rad_mood)
    s["hull_integrity"] = max(0.0, s["hull_integrity"] - 3.0 * exposure)


def _apply_mood(s, ctx, delta):
    ctx["mood_shock"](delta)


EVENT_LIBRARY = {
    "micrometeoroid": {
        "name": "☄️ 微流星体撞击穿孔", "category": "instant", "weight": 1.0,
        "desc": "壳体被击穿，舱内大气向真空急速泄漏。",
        "impact": lambda s, ctx: s.update({
            "O2_kg": s["O2_kg"] * 0.85, "CO2_kg": s["CO2_kg"] * 0.85,
            "hull_integrity": max(0.0, s["hull_integrity"] - 12.0),
        }),
    },
    "solar_particle": {
        "name": "🌟 太阳高能粒子事件 (SPE)", "category": "instant", "weight": 1.2,
        "desc": "强辐射暴。月壤护甲薄则乘组士气暴跌，并损伤壳体。",
        "impact": lambda s, ctx: _solar_particle_impact(s, ctx),
    },
    "power_outage": {
        "name": "⚡ 主电源中断", "category": "instant", "weight": 0.9,
        "desc": "供电骤停，当日微藻与作物光合停摆，CDRA 气压调节失效一日。",
        "impact": lambda s, ctx: ctx["add_status"]("power_down", 1),
    },
    "coolant_loss": {
        "name": "🌡️ 热控回路泄漏", "category": "ongoing", "duration": 4, "weight": 1.0,
        "desc": "散热能力下降，舱内升温，乘组每日承受热应激。",
        "tick": lambda s, ctx: _apply_mood(s, ctx, -3.0),
    },
    "eclss_fault": {
        "name": "🔧 ECLSS 净化部件故障", "category": "ongoing", "duration": 5, "weight": 1.0,
        "desc": "CO2 洗涤效率下降，期间储碳罐无法吸收 CO2。",
        "tick": lambda s, ctx: ctx["disable_scrubber"](),
    },
    "dust_storm": {
        "name": "🌪️ 月面尘暴", "category": "ongoing", "duration": 7, "weight": 0.8,
        "desc": "遮蔽阳光，持续一周内光照效率大幅衰减。",
        "tick": lambda s, ctx: ctx["scale_light"](0.4),
    },
    "slow_leak": {
        "name": "🫧 密封件缓慢泄漏", "category": "creeping", "duration": 25, "weight": 0.9,
        "desc": "几乎察觉不到的微泄漏，每天悄悄损失少量大气。",
        "tick": lambda s, ctx: s.update({
            "O2_kg": s["O2_kg"] * 0.992, "CO2_kg": s["CO2_kg"] * 0.992,
        }),
    },
    "microbial_bloom": {
        "name": "🦠 杂菌生物膜暴发", "category": "creeping", "duration": 15, "weight": 0.8,
        "desc": "管路滋生杂菌，持续污染净水并与微藻争夺养分。",
        "tick": lambda s, ctx: s.update({
            "Clean_Water_kg": s["Clean_Water_kg"] - 3.0,
            "Waste_Water_kg": s["Waste_Water_kg"] + 3.0,
            "Algae_Biomass_kg": max(0.1, s["Algae_Biomass_kg"] * 0.98),
        }),
    },
    "embrittlement": {
        "name": "🧱 结构辐照脆化", "category": "creeping", "duration": 30, "weight": 0.7,
        "desc": "壳体材料缓慢脆化，结构完整性持续下滑。",
        "tick": lambda s, ctx: s.update({
            "hull_integrity": max(0.0, s["hull_integrity"] - 0.8),
        }),
    },
}

# ============================================================
# 🆕 v6 作物：去掉英文型号，新增药用植物（产药材）
# ============================================================
CROP_DATA = {
    "Wheat":     {"name": "矮秆小麦 🌾",  "cycle": 65, "daily_ww": 0.615, "daily_co2": 0.057, "daily_fert": 0.0038, "daily_cw": 0.600, "daily_o2": 0.046, "yield_food": 1.0, "yield_sw": 1.50, "yield_herb": 0.0},
    "Lettuce":   {"name": "气雾生菜 🥬",  "cycle": 33, "daily_ww": 1.818, "daily_co2": 0.054, "daily_fert": 0.0030, "daily_cw": 1.787, "daily_o2": 0.042, "yield_food": 1.0, "yield_sw": 0.25, "yield_herb": 0.0},
    "Potato":    {"name": "微型土豆 🥔",  "cycle": 80, "daily_ww": 0.562, "daily_co2": 0.026, "daily_fert": 0.0018, "daily_cw": 0.550, "daily_o2": 0.021, "yield_food": 1.0, "yield_sw": 0.40, "yield_herb": 0.0},
    "Medicinal": {"name": "药用植物 🌿",  "cycle": 70, "daily_ww": 0.700, "daily_co2": 0.030, "daily_fert": 0.0040, "daily_cw": 0.680, "daily_o2": 0.025, "yield_food": 0.0, "yield_sw": 0.35, "yield_herb": 1.0},
}
PLANT_CAPACITY_PER_UNIT = 80.0

# ==========================================
# 实验室 + 电力 + 科研常量
# ==========================================
VOL_LAB = 30.0
WATER_PER_LAB = 80.0
SOLAR_KWH_PER_M2_HOUR = 0.066
INCINERATOR_KWH_PER_KG = 0.4
BATTERY_CAP_DEFAULT = 200.0
SOLAR_PANEL_M2_DEFAULT = 100.0
POWER_PER_HABITAT = 8.0
POWER_PER_PLANT = 25.0
POWER_PER_COMPOST = 3.0
POWER_PER_LAB_IDLE = 5.0
POWER_PER_LAB_ACTIVE = 15.0

VOL_GREENHOUSE = 60.0
WATER_PER_GREENHOUSE = 120.0
POWER_PER_GREENHOUSE = 25.0
GH_FERT_PER_DAY = 1.5
GH_WW_PER_DAY = 12.0
GH_CO2_PER_DAY = 0.75
GH_O2_PER_DAY = 0.4
GH_WATER_RECLAIM_PER_DAY = 7.0
GH_MOOD_BONUS_PER_UNIT = 3.0

RESEARCH_BASE_RATE = 1.0
EFFECTIVE_CREW_TABLE = [0.0, 1.0, 1.7, 2.2, 2.5]


# ============================================================
# 课题库（保留 v5 全部 + 🆕 v6 制药课题：可重复进行）
# ============================================================
def _research_algae(m):       m["algae_o2"] = 1.20; m["algae_co2"] = 1.20
def _research_compost(m):     m["compost"] = 1.25
def _research_crops(m):       m["crop_yield"] = 1.20
def _research_isru(m):        m["hull_durability"] = 1.50
def _research_solar(m):       m["solar_efficiency"] = 1.30
def _research_water_loop(m):  m["water_recycle"] = 1.20; m["maintenance"] *= 0.7
def _research_radiation(m):   m["radiation_mood"] = 0.5
def _research_sabatier(m):    m["co2_to_water"] = True
def _research_automation(m):  m["maintenance"] *= 0.5
def _research_pharma(m):      m["pharma_ready"] = True


RESEARCH_LIBRARY = {
    "algae_strain":     {"name": "🦠 高效螺旋藻菌株筛选", "cycle": 30, "desc": "ISS 4 周批次培养。完成后微藻产氧/吸碳系数 +20%。", "on_complete": _research_algae,    "repeatable": False},
    "compost_microbes": {"name": "🧫 堆肥高效微生物选育", "cycle": 35, "desc": "MELiSSA 降解菌选育。堆肥处理上限/产肥率 +25%。", "on_complete": _research_compost, "repeatable": False},
    "crop_breeding":    {"name": "🌾 加速作物育种 (Speed Breeding)", "cycle": 80, "desc": "所有作物收获产量 +20%。",                       "on_complete": _research_crops,   "repeatable": False},
    "isru_wall":        {"name": "🧱 ISRU 月壤+水墙复合材料", "cycle": 50, "desc": "壳体抗冲击/抗辐射 +50%。",                                  "on_complete": _research_isru,    "repeatable": False},
    "solar_upgrade":    {"name": "☀️ 坑外太阳能阵列升级", "cycle": 45, "desc": "太阳能发电效率 +30%。",                                          "on_complete": _research_solar,   "repeatable": False},
    "water_loop":       {"name": "💧 闭环水回收升级",       "cycle": 40, "desc": "净水回收 +20%，模块维护水耗 -30%。",                          "on_complete": _research_water_loop, "repeatable": False},
    "radiation_med":    {"name": "💊 辐射医学/乘组健康协议", "cycle": 40, "desc": "SPE 等辐射事件心情冲击减半。",                              "on_complete": _research_radiation, "repeatable": False},
    "sabatier":         {"name": "⚗️ Sabatier CO₂ 再利用反应器", "cycle": 55, "desc": "每日把过量 CO₂ 转化为水。",                            "on_complete": _research_sabatier, "repeatable": False},
    "automation":       {"name": "🤖 自动化机器人维护",     "cycle": 60, "desc": "降低每模块维护水耗 50%。",                                  "on_complete": _research_automation, "repeatable": False},
    # 🆕 v6
    "pharma":           {"name": "💉 制药课题（药材→药物）", "cycle": 25, "desc": "消耗 10 单位药材产出 5 单位药物。可重复立项。",          "on_complete": _research_pharma,   "repeatable": True,
                         "herb_cost": 10.0, "medicine_yield": 5.0},
}


def _default_research_multipliers():
    return {
        "algae_o2": 1.0, "algae_co2": 1.0, "compost": 1.0, "crop_yield": 1.0,
        "hull_durability": 1.0, "solar_efficiency": 1.0, "water_recycle": 1.0,
        "radiation_mood": 1.0, "maintenance": 1.0,
        "co2_to_water": False, "pharma_ready": False,
    }


# ============================================================
# 🆕 v6 天赋系统（替代职业）
# 类型：科研 / 探索 / 修理 / 建造 / 娱乐
# ============================================================
TALENT_TYPES = {
    "research":  {"name": "🔬 科研",  "job": "research"},
    "explore":   {"name": "⛏️ 探索",  "job": "explore"},
    "repair":    {"name": "🔧 修理",  "job": "repair"},
    "build":     {"name": "🏗️ 建造",  "job": "build"},
    "entertain": {"name": "🎭 娱乐",  "job": None},          # 每天全员心情加成
}
TALENT_LEVEL_LABEL = {"low": "低级", "mid": "中级", "high": "高级", "top": "顶级"}

TALENT_NUM_PROB = [0.30, 0.50, 0.20]    # 0/1/2 个天赋
TALENT_LEVEL_PROB = {"low": 0.45, "mid": 0.35, "high": 0.20}   # 普通人不出顶级

TALENT_WORK_MULT = {
    "low":  (1.0, 1.4),
    "mid":  (1.5, 1.9),
    "high": (2.0, 2.9),
    "top":  (3.0, 3.0),
}
TALENT_ENTERTAIN_BONUS = {
    "low":  (1.0, 1.2),
    "mid":  (1.3, 1.5),
    "high": (1.7, 1.9),
    "top":  (2.0, 2.0),
}

MINISTERS = {
    "annie":  {"name": "Annie 部长", "talents": [("build",     "top")], "desc": "顶级建造（建造速度 ×3）"},
    "huang":  {"name": "黄部长",      "talents": [("research",  "top")], "desc": "顶级科研（科研速度 ×3）"},
    "luo":    {"name": "罗部长",      "talents": [("explore",   "top")], "desc": "顶级探索（探索收获 ×3）"},
    "guo":    {"name": "郭部长",      "talents": [("entertain", "top")], "desc": "顶级娱乐（每天全员 +2% 心情）"},
}
# ============================================================
# 🆕 【部长数据库：形象、教程协议、常驻百科与动态警告】
# ============================================================
MINISTER_DATA = {
    "Annie部长": {
        "init_img": "Annie initialize.png", "game_img": "Annie in game.png", "style": "Annie部长（温柔专业）",
        "intro": "指挥官您好，我是Annie。深空生存容不得一点差错，我会耐心协助您构建最稳固的月球居所。",
        "tutorial": {
            "T0": "欢迎指挥官！为了确保您的基地不在第 10 天就因为 CO₂ 中毒或断水崩溃，请完成以下模拟训练：\n\n- **协议-大气修复**：学会开启空气净化洗涤器。\n- **协议-闭环补给**：播种作物并观察废水消耗与物质循环。\n- **协议-能源调度**：扩展太阳能板，观察电池充电。\n- **协议-人才管理**：将“科研型”乘员指派到实验室。\n\n提示：模拟期间系统已下发 3 个补给医疗包。",
            "T1": "【阶段 1：呼吸】指挥官，深呼吸。现在舱内 CO₂ 浓度超标，大家开始咳嗽了。除了依赖被动过滤，我们需要主动出击！请去侧边栏找到【🦠 微藻光水调控】，尝试增加废水通量或拉满光照时长，然后点击【⏳ 闭环演进】利用光合作用吃掉 CO₂！",
            "T2": "【阶段 2：温饱】食物要见底了，系统发出了警报！请立刻去左侧边栏【批次农业播种中心】播种些小麦或土豆，注意观察水分流失。收获后残渣会被丢进【堆肥舱】。‘化肥-作物-废物’的闭环运作起来，我们才有长久的温饱。",
            "T3": "【阶段 3：生存】警报！电池电量仅剩5%！如果不采取行动，基地即将断电！请立即在侧边栏扩展【坑外光伏阵列】，或者在实验室研发‘自动化机器人维护’来降低基础水耗。活下去，能源是关键。",
            "T4": "【阶段 4：成长】基地规模达到瓶颈，我们需要更强的防护。系统已紧急为您空投并展开了一座【实验室】！请去侧边栏【🔬 科研课题立项】派人研发‘ISRU月壤复合材料’。",
            "T5": "【崩溃预演】指挥官，如果刚刚断电，您的基地会发生什么？\n\n🚨 **模拟推演日志**：\n> **Day X**: 主电源中断，水循环泵停止。\n> **Day X+1**: 温室失去补光，作物全部枯死，氧气停止产出。\n> **Day X+2**: 失去热控，温度骤降导致舱体(Hull)出现裂缝。\n> **Day X+3**: 大气向真空泄漏，全员缺氧阵亡。\n\n您看到的每一个指标都牵动着全员生死。天外家园的命运，交给你了！"
        },
        "help": {
            "居住舱": "居住舱是我们休息的港湾，每个舱能容纳 2 人。建得太少大家会觉得拥挤，但盲目扩建会增加基础维护水耗。",
            "温室舱": "生态引擎的核心！每个温室不仅能容纳 2 人，还能大幅提升全员心情，并成倍增加光合作用产出。",
            "种植舱": "口粮的来源。每增加一个种植舱，我们就能各种植 80kg 的作物，它是我们建立碳水闭环的起点。",
            "堆肥舱": "千万别嫌脏，这里是变废为宝的地方。它能把固体废物和废水降解成肥料，没有它，植物就会饿死。",
            "实验室": "科技是第一生产力。建成后，把有科研天赋的人派进去，无论是研究更厚的护甲还是更高效的微藻，全靠它了。",
            "微藻光水调控": "微藻是我们最高效的“生物滤水器”和“氧气发生器”。调节废水通量和光照，控制它的生长节奏是门艺术。",
            "电力系统": "太阳能是生命线。没电就没光，没光植物就死。遇到紧急情况可以烧垃圾发电，但小心 CO₂ 超标。",
            "招募系统": "人多力量大，但前提是你有足够的床位、口粮和水。随便招人只会让基地更快崩溃。",
            "灾难系统": "外面太危险了。月壤护甲能帮我们挡住微流星体和辐射。一旦舱体受损，必须立刻派人去修理。",
            "健康系统": "身体和心理同样重要。生病必须休息吃药，心情跌到底可是会引发叛逃的。"
        },
        "warnings": {
            "co2": "指挥官，CO₂ 浓度已达到毒性临界值！大家已经出现眩晕症状，请立刻检查 CDRA 供电或烧掉多余垃圾！",
            "o2": "氧气流失严重！监测到多名乘员出现窒息特征，请立刻调节微藻或播种作物！",
            "water": "净水储备跌破红线！没有水我们撑不过三天，请立刻派人出舱采集或检查微藻净化效率！",
            "food": "口粮即将断绝！饥荒正在基地蔓延，温室里还有什么能吃的吗？",
            "hull": "警告！壳体结构完整性严重受损！再不派人去修理，我们全都要暴露在真空里了！",
            "crew": "指挥官，请关注大家的状况，有人已经处于伤病或崩溃的边缘，我们需要他们活着！"
        }
    },
    "郭部长": {
        "init_img": "Guo initialize.png", "game_img": "Guo in game.png", "style": "郭部长（幽默轻松）",
        "intro": "哟，指挥官，我是郭部长。在这儿，活下去比什么都重要，当然，别忘了找点乐子。",
        "tutorial": {
            "T0": "欢迎上任！为了防止您在头十天就把我们团灭，先走个过场做下模拟训练吧：\n\n- **协议-大气修复**：别憋死自己，学会开空气洗涤器。\n- **协议-闭环补给**：种地、浇水、收菜、堆肥，搞懂这套流程。\n- **协议-能源调度**：搞点太阳能板，没电连游戏都没法打。\n- **协议-人才管理**：别让种地的去搞科研，学会分配天赋。\n\n提示：白送你 3 个医疗包，省着点用啊！",
            "T1": "【阶段 1：呼吸】咳咳...想大口呼吸新鲜空气？盯紧 CO₂ 浓度！光靠机器洗空气可不行，去侧边栏把【🦠 微藻光水调控】的光照拉满，让那帮绿油油的小东西赶紧干活！调好后点【⏳ 闭环演进】推演一天试试！",
            "T2": "【阶段 2：温饱】肚子饿了？系统警报都响了！赶紧去左边播种！种田会掉水，吃剩的丢进堆肥舱。‘化肥-作物-废物’的闭环不转起来，我们就只能吃土了。",
            "T3": "【阶段 3：生存】没电连游戏都没法打。电池就剩5%了大哥！去侧边栏多造点太阳能板，要是停电导致作物全枯死，整个基地就准备歇菜吧。",
            "T4": "【阶段 4：成长】不想被陨石砸成筛子，就赶紧搞‘ISRU科研’！我已经托关系给你空降了一座【实验室】，赶紧把那些戴眼镜的科研天才派进去立项干活！",
            "T5": "【崩溃预演】想知道乱来的下场吗？\n\n🚨 **死法展示**：\n> 一旦断电 ➡️ 没光照 ➡️ 植物死光 ➡️ 没吃没喝没氧气 ➡️ 温度降到绝对零度 ➡️ 舱体冻裂 ➡️ 大家一起变太空垃圾。\n\n所以，求求你盯紧资源表，别让我们集体扑街！拿上急救药，好自为之！"
        },
        "help": {
            "居住舱": "睡觉的地方。别把大家像沙丁鱼一样塞在一起，建多了又费水，抠搜点建。",
            "温室舱": "多造点这玩意儿！除了能种地，还能改善大家的心情，不然我们天天只能看石头解闷。",
            "种植舱": "我们的“太空菜园子”。记住，种菜是要消耗废水的，千万别干涸了。",
            "堆肥舱": "俗称“造粪机回收站”。虽然听着恶心，但没它生产化肥，咱们连土都没得吃。",
            "实验室": "学霸们的快乐老家。把那些戴眼镜的书呆子塞进去，我们的护甲和技术全指望他们了。",
            "微藻光水调控": "绿油油的救命稻草。把废水灌进去，光照拉满，氧气和净水就源源不断地来了。",
            "电力系统": "没电就没光，没光植物就死，植物死了我们就憋死。懂这连环逻辑了吧？",
            "招募系统": "想摇人？准备好水和电。人来了要是不干活，那可是纯纯的造粪机器。",
            "灾难系统": "外面辐射乱飞，石头乱砸。要是月壤护甲破了，咱们就都成太空垃圾了。",
            "健康系统": "别让人带病干活，咱们又不是黑心老板。心情差了还会造反，记得多关心大家。"
        },
        "warnings": {
            "co2": "咳咳咳！大哥，你想把我们熏死吗？CO₂ 爆表了，赶紧开洗涤器或者烧点垃圾！",
            "o2": "喘不上气了...氧气要没了！赶紧弄点微藻或者催熟植物，不然我们要憋死了！",
            "water": "水管里一滴水都没了！你这是打算让我们集体渴死变成木乃伊吗？赶紧去采水！",
            "food": "饭呢？锅里连颗土豆渣都没了！再不弄点吃的，大家就要开始生啃控制台了！",
            "hull": "天呐舱体要裂开了！外面可是真空！赶紧派人去修，我可不想不穿宇航服出门！",
            "crew": "喂！有人心态崩了或者快病死了，赶紧给他们放个假吃点药，造反了可别怪我没提醒你！"
        }
    },
    "黄部长": {
        "init_img": "Huang initialize.png", "game_img": "Huang in game.png", "style": "黄部长（严谨理性）",
        "intro": "指挥官，我是黄部长。一切运作都基于物理法则，请用数据说话，避免感性决策。",
        "tutorial": {
            "T0": "指挥官，演练协议已加载。为确保基地存续概率 >99%，请依次验证以下子系统：\n\n- **协议-大气修复**：验证 ECLSS 大气洗涤流转逻辑。\n- **协议-闭环补给**：初始化批次农业参数，观测水循环熵减。\n- **协议-能源调度**：校准光伏阵列输出与负荷的收支平衡。\n- **协议-人才管理**：基于效能倍率分配科研人员进入实验室。\n\n提示：初始医疗耗材已注入您的资源库。",
            "T1": "【阶段 1：呼吸】协议启动。CO₂ 偏离安全阈值。为了建立长效碳汇，请前往侧边栏【🦠 微藻光水调控】增加光照时长或废水输入，强化微藻的光合固碳效率。调整完毕后，执行【⏳ 闭环演进】观察参数回落。",
            "T2": "【阶段 2：温饱】口粮储量告急。建立碳水闭环协议。请执行播种指令。植物蒸腾作用是水分流转的核心，随后需建立堆肥舱处理固废，维持‘化肥-作物-废物’的高效闭环。",
            "T3": "【阶段 3：生存】能源缺口警告，电池余量5%。电池是生命保障系统的基石，断电即死。请立即在侧边栏增加坑外光伏阵列，或者通过研发自动化降低水耗，维持正向收支。",
            "T4": "【阶段 4：成长】系统物理防御到达瓶颈。工程部已为您极速部署了一座【实验室】。请评估乘组的科研天赋，分配最优人力进入实验室立项，加速 ISRU 护甲研发。",
            "T5": "【崩溃预演】建立错误决策推演模型：\n\n🚨 **级联故障链**：\n> 电力供给归零 ➡️ ECLSS与光照停机 ➡️ 光合作用中断 ➡️ 碳水闭环崩塌 ➡️ 热控失效致使结构脆化 ➡️ 最终结局：系统不可逆解体。\n\n请务必规避此崩溃路径。医疗物资已发放，训练结束。"
        },
        "help": {
            "居住舱": "基础拓扑单元。承载 2 个人口单位，扩展时请精确计算其带来的边际维护水耗，避免盲目扩张。",
            "温室舱": "复合型生态单元。除了提供居住容量，还能产出情绪价值（Mood加成）并优化碳水循环效率。",
            "种植舱": "生物量转化核心。将废水和化肥转化为食物和氧气。请时刻关注其负载上限。",
            "堆肥舱": "熵减处理器。将系统代谢的废料降解重组为有效肥料，是维持物质守恒的必需设备。",
            "实验室": "技术迭代平台。科研进度与分配人员的智力天赋呈正相关，请保持至少一个活跃课题以应对衰减。",
            "微藻光水调控": "高频生物反应器。调节参数以最优化净水回收率与固碳率，注意不要让其超过环境承载力(K值)。",
            "电力系统": "能量流的基石。严格遵循能量守恒，确保蓄电池余量足以支撑夜间周期的 ECLSS 运作。",
            "招募系统": "引入新变量。人口增加将同步提升代谢负荷与生产力，请提前规划冗余资源。",
            "灾难系统": "外部物理扰动。护甲厚度（Shield）将按比例抵消动能冲击与高能辐射，受损后必须指派维修。",
            "健康系统": "双轨监控机制。生理健康（Health）或心理韧性（Mood）降至零均会触发单位不可逆的丢失。"
        },
        "warnings": {
            "co2": "严重警告：CO₂ 分压已击穿致死阈值。乘组正在发生高碳酸血症，请立即执行降碳干预！",
            "o2": "危急：氧气浓度持续走低，当前环境不足以维持基础有氧代谢，系统崩溃倒计时已启动！",
            "water": "水循环即将断裂！净水池余量已无法支撑下一个系统周期的维护耗水，请紧急补充！",
            "food": "热量储备耗尽。生物单位即将进入饥饿性休克，请立即从温室收割任何可用碳水化合物！",
            "hull": "结构警告：壳体完整性逼近临界点。若发生减压爆炸，生还概率为 0%，立刻执行维修指令！",
            "crew": "监测到个别人事单位的生理/心理参数逼近崩溃边缘，为避免减员带来的生产力断层，请及时干预。"
        }
    },
    "罗部长": {
        "init_img": "Luo initialize.png", "game_img": "Luo in game.png", "style": "罗部长（果敢气质）",
        "intro": "指挥官，我是罗部长。月球是个难啃的骨头，准备好跟着我征服这片荒原了吗？",
        "tutorial": {
            "T0": "听着，指挥官！月球不相信眼泪，想活下去，先通过这项基础生存考验：\n\n- **协议-大气修复**：学会看仪表盘，把憋死人的二氧化碳处理掉。\n- **协议-闭环补给**：播种第一批粮食，搞懂废水和化肥是怎么循环的。\n- **协议-能源调度**：铺设太阳能，保证基地的电力心脏不跳停。\n- **协议-人才管理**：好钢用在刀刃上，把科研人才派进实验室。\n\n提示：拿好这 3 个医疗包，随时准备拼命！",
            "T1": "【阶段 1：呼吸】指挥官！兄弟们快憋坏了！别光指望排气扇，去侧边栏找到【🦠 微藻光水调控】，给那帮绿藻加足水和光照，让它们把 CO₂ 全吸干净！搞定后按【⏳ 闭环演进】！",
            "T2": "【阶段 2：温饱】食物见底了！想征服这片荒原，就得自己动手。去左边播种！种出来的植物不仅能吃，还能处理代谢废物。记得把残渣丢进堆肥舱，水和化肥循环起来才是底牌。",
            "T3": "【阶段 3：生存】警报！电池剩5%！外面辐射再强，没电我们也只能等死。去侧边栏多铺点太阳能板，把电池充满，手里有粮有电，心里才不慌。",
            "T4": "【阶段 4：成长】外面越来越危险，护甲不够看了！后勤刚给我们强行搭好了一座【实验室】，赶紧把科研好手派进去立项，把 ISRU 护甲搞出来，否则我们连门都不敢出！",
            "T5": "【崩溃预演】看看如果在战场上失误会有什么后果：\n\n🚨 **毁灭推演**：\n> 断电 ➡️ 供暖与制氧全停 ➡️ 农作物冻死 ➡️ 护甲在严寒中脆裂 ➡️ 基地全面解体。\n\n别让我们走到那一步！拿着这包急救药，准备好大干一场了吗？"
        },
        "help": {
            "居住舱": "我们的营房。让兄弟们有地方睡觉，但建得太多就是在浪费我们宝贵的水资源。",
            "温室舱": "基地的绿洲！在荒凉的月球上，能看到一片绿色，兄弟们的士气都会高涨不少！",
            "种植舱": "我们的军粮库。只要种子播下去，废水跟上，我们就有在这个地狱活下去的底气。",
            "堆肥舱": "垃圾场里的黄金！把废物扔进去，发酵出来的化肥能让我们的作物长得比野草还疯。",
            "实验室": "军械库！派脑子最灵光的人进去，把护甲和科技堆高，我们才敢跟月球的极端环境硬碰硬。",
            "微藻光水调控": "水和氧气的源泉。控好废水和光照，微藻就是我们在深空里最可靠的肺！",
            "电力系统": "去铺面板！坑外的阳光就是我们的黄金。要是遇到沙尘暴没电，就只能烧垃圾应急发电了！",
            "招募系统": "宇宙开拓需要新鲜血液！只要资源（水和电）够，就把兄弟们接过来，一起干！",
            "灾难系统": "月球不相信眼泪。流星体和太阳风暴随时会要我们的命，把护甲堆厚点，随时安排人去修复！",
            "健康系统": "出门采集难免挨辐射。受伤了就赶紧回来休息吃药，养精蓄锐才能走得更远。"
        },
        "warnings": {
            "co2": "指挥官！兄弟们快被 CO₂ 憋死了！立刻启动净化系统或者找点能烧的给植物施碳！",
            "o2": "氧气供不上了！大家都在大口喘气，立刻催熟温室里的东西，不然全军覆没！",
            "water": "水库要干了！没有水，兄弟们连汗都流不出来，立刻安排人出舱凿冰！",
            "food": "没吃的怎么打仗！口粮已经见底了，再不想办法，营地里就要起暴动了！",
            "hull": "基地外壳快被砸穿了！别管其他的了，立刻把所有人派去修墙，不然全得死！",
            "crew": "注意！有人撑不住了！无论是受伤还是心态炸裂，赶紧给他们治疗，别抛弃任何一个兄弟！"
        }
    }
}

# 普通人名池（中英混合，避开职业名与政治人物）
NAME_POOL = [
    "李明", "王芳", "陈思", "刘洋", "张涛", "周婷", "吴磊", "徐倩", "孙浩", "马琳",
    "Alex", "Mia", "Ryan", "Nora", "Leo", "Eva", "Sam", "Iris", "Owen", "Lily",
    "韩雪", "高远", "梁宇", "宋佳", "崔琳", "贾然", "苗壮", "唐宁", "蒋楠", "薛冬",
    "Kai", "Zoe", "Theo", "Maya", "Finn", "Cleo", "Jude", "Ines",
]


def _roll_talent_level():
    keys = list(TALENT_LEVEL_PROB.keys())
    probs = [TALENT_LEVEL_PROB[k] for k in keys]
    return random.choices(keys, weights=probs, k=1)[0]


def _roll_talent_mult(ttype, level):
    """工作类返回乘数；娱乐返回每人每天心情%加成。"""
    if ttype == "entertain":
        lo, hi = TALENT_ENTERTAIN_BONUS[level]
    else:
        lo, hi = TALENT_WORK_MULT[level]
    if lo == hi:
        return round(lo, 2)
    return round(random.uniform(lo, hi), 2)


def _gen_random_talents():
    """根据概率分布生成 0~2 个天赋。返回 [(type, level, mult), ...]。"""
    n = random.choices([0, 1, 2], weights=TALENT_NUM_PROB, k=1)[0]
    if n == 0:
        return []
    chosen_types = random.sample(list(TALENT_TYPES.keys()), n)
    out = []
    for t in chosen_types:
        lvl = _roll_talent_level()
        out.append((t, lvl, _roll_talent_mult(t, lvl)))
    return out


def _talents_from_minister(minister_key):
    out = []
    for t, lvl in MINISTERS[minister_key]["talents"]:
        out.append((t, lvl, _roll_talent_mult(t, lvl)))
    return out


def _format_talents(talents):
    if not talents:
        return "无天赋"
    parts = []
    for t, lvl, mult in talents:
        name = TALENT_TYPES[t]["name"]
        if t == "entertain":
            parts.append(f"{name}·{TALENT_LEVEL_LABEL[lvl]}(+{mult:.1f}%)")
        else:
            parts.append(f"{name}·{TALENT_LEVEL_LABEL[lvl]}(×{mult:.2f})")
    return " · ".join(parts)


def _make_random_crew(name=None):
    """生成一个普通乘员：随机名 + 0~2 天赋 + 体质 0.7~1.0。"""
    return {
        "name": name or random.choice(NAME_POOL),
        "mood": 100.0,
        "health": 100.0,
        "job": JOB_DEFAULT,
        "talents": _gen_random_talents(),
        "constitution": round(random.uniform(0.7, 1.0), 2),
        # 🆕 v6 医疗/受伤
        "sickness": None,        # None / "early" / "severe"
        "sickness_days": 0,
        "injury": None,          # None / "light" / "heavy"
        "injury_days": 0,
    }


def _make_minister_crew(minister_key):
    return {
        "name": MINISTERS[minister_key]["name"],
        "mood": 100.0,
        "health": 100.0,
        "job": JOB_DEFAULT,
        "talents": _talents_from_minister(minister_key),
        "constitution": 1.0,
        "sickness": None, "sickness_days": 0,
        "injury": None, "injury_days": 0,
    }


def _crew_talent_mult(member, job_key):
    """该乘员从事 job 时的天赋倍率（无对应天赋则 1.0）。"""
    for t, lvl, mult in member.get("talents", []):
        if TALENT_TYPES[t]["job"] == job_key:
            return mult
    return 1.0


def _team_talent_avg_mult(members, job_key):
    """团队平均天赋倍率，用于乘到团队工作产出上。"""
    if not members:
        return 1.0
    s = sum(_crew_talent_mult(m, job_key) for m in members)
    return s / len(members)


def _daily_entertain_bonus(crew):
    """每天全员获得的心情加成（%）：所有娱乐天赋叠加。"""
    total = 0.0
    for m in crew:
        for t, lvl, mult in m.get("talents", []):
            if t == "entertain":
                total += mult
    return total


# ============================================================
# 🆕 v6 工作系统：删除"职业"，新增"建造"工作
# ============================================================
JOBS = {
    "rest":     {"name": "😴 休息",  "desc": "回复心情与健康（唯一恢复手段）"},
    "research": {"name": "🔬 科研",  "desc": "推进所在实验室课题进度"},
    "repair":   {"name": "🔧 修理",  "desc": "消耗月壤护甲材料，恢复壳体完整性"},
    "explore":  {"name": "⛏️ 探索",  "desc": "出舱采净水/月壤；有 8% 几率受伤"},
    "build":    {"name": "🏗️ 建造",  "desc": "推进建造队列中的舱室工程"},
}
JOB_DEFAULT = "rest"
JOB_MOOD_DELTA = {"rest": +5.0, "research": -2.0, "repair": -1.5, "explore": -1.5, "build": -1.5}
JOB_HEALTH_DELTA = {"rest": +5.0, "research": 0.0, "repair": -0.5, "explore": 0.0, "build": -0.5}

REPAIR_SHIELD_COST_PER_EFF = 10.0
REPAIR_HULL_GAIN_PER_EFF = 5.0
EXPLORE_WATER_PER_EFF = 20.0
EXPLORE_REGOLITH_PER_EFF = 5.0
EXPLORE_POWER_PER_CREW = 5.0
EXPLORE_RAD_BASE = 8.0
EXPLORE_RAD_MIN = 1.5

# 🆕 v6 建造工作量（人·天）
BUILD_WORK = {"hab": 3.0, "plant": 4.0, "compost": 2.0, "lab": 5.0, "greenhouse": 6.0}
BUILD_LABEL = {"hab": "居住舱", "plant": "种植舱", "compost": "堆肥舱", "lab": "实验室", "greenhouse": "温室"}
BUILD_WATER = {
    "hab": WATER_PER_HABITAT, "plant": WATER_PER_PLANT, "compost": WATER_PER_COMPOST,
    "lab": WATER_PER_LAB, "greenhouse": WATER_PER_GREENHOUSE,
}

# 🆕 v6 居住容量（用于招募判定）
RESIDENTS_PER_HAB = 2
RESIDENTS_PER_GH = 2

# 🆕 v6 医疗/受伤参数
SICKNESS_BASE_DAILY = 0.03
SICKNESS_SELFHEAL_BASE = 0.35
SICKNESS_TO_SEVERE_DAYS = 3
SICKNESS_MEDICINE_RECOVER = 0.60
SICKNESS_NOMED_HEALTH_LOSS = 4.0
INJURY_DAILY_PER_EXPLORER = 0.08
INJURY_LIGHT_SELFHEAL = 0.40
INJURY_HEAVY_MED_RECOVER = 0.50
INJURY_NOMED_HEALTH_LOSS = 3.0
INJURY_HEALTH_PENALTY = {"light": 0.5, "heavy": 2.0}

st.set_page_config(page_title="天外家园：v6 天赋·医疗·建造", layout="wide")


# ==========================================
# 界面套皮（v7 · 方案一 · CSS 注入，不改任何游戏逻辑）
# ==========================================
def inject_style():
    st.markdown(
        """
        <style>
        :root {
          --bg-deep: #08161c;
          --bg-1: #0a1820;
          --bg-2: #0d2228;
          --glass: rgba(12, 20, 28, 0.55);
          --glass-strong: rgba(12, 20, 28, 0.78);
          --glass-border: rgba(120, 200, 210, 0.18);
          --glass-border-strong: rgba(120, 200, 210, 0.35);
          --glow: rgba(60, 200, 200, 0.30);
          --accent: #4fd1c5;
          --accent-soft: rgba(79, 209, 197, 0.55);
          --accent-warn: #f0b860;
          --text-main: #e8f4f4;
          --text-dim: rgba(200, 220, 220, 0.62);
          --blur: 14px;
        }

        /* 全屏深色科幻背景（渐变 + 暗角） */
        .stApp {
          background:
            radial-gradient(ellipse at 30% 20%, rgba(40, 90, 80, 0.35), transparent 50%),
            radial-gradient(ellipse at 70% 80%, rgba(20, 80, 95, 0.30), transparent 55%),
            linear-gradient(160deg, var(--bg-1), var(--bg-2) 40%, var(--bg-deep));
          color: var(--text-main);
        }

        /* 标题与正文文字 */
        .stApp h1, .stApp h2, .stApp h3, .stApp h4 {
          color: var(--text-main);
          text-shadow: 0 0 12px rgba(79, 209, 197, 0.20);
        }
        .stApp p, .stApp li, .stApp label, .stApp span { color: var(--text-main); }
        .stApp [data-testid="stCaptionContainer"],
        .stApp .stCaption, .stApp small { color: var(--text-dim) !important; }

        /* 分隔线 --- → 青绿渐隐 */
        .stApp hr {
          border: none;
          height: 1px;
          background: linear-gradient(90deg, transparent, var(--accent-soft) 50%, transparent);
          opacity: 0.6;
        }

        /* 侧边栏 */
        [data-testid="stSidebar"] {
          background: rgba(8, 18, 24, 0.85);
          backdrop-filter: blur(var(--blur));
          -webkit-backdrop-filter: blur(var(--blur));
          border-right: 1px solid var(--glass-border-strong);
          box-shadow: 4px 0 24px rgba(0, 0, 0, 0.35);
        }
        [data-testid="stSidebar"] * { color: var(--text-main); }

        /* metric → 毛玻璃胶囊 */
        [data-testid="stMetric"] {
          background: var(--glass);
          backdrop-filter: blur(var(--blur));
          -webkit-backdrop-filter: blur(var(--blur));
          border: 1px solid var(--glass-border);
          border-radius: 16px;
          padding: 12px 16px;
          box-shadow: 0 4px 24px rgba(0, 0, 0, 0.30);
          transition: border-color .25s, box-shadow .25s;
        }
        [data-testid="stMetric"]:hover {
          border-color: var(--accent-soft);
          box-shadow: 0 4px 28px var(--glow);
        }
        [data-testid="stMetricValue"] {
          color: var(--text-main);
          text-shadow: 0 0 8px rgba(79, 209, 197, 0.25);
        }
        [data-testid="stMetricLabel"] { color: var(--text-dim); }
        [data-testid="stMetricDelta"] svg { fill: var(--accent); }

        /* 按钮 */
        .stButton > button, .stDownloadButton > button {
          background: var(--glass);
          border: 1px solid var(--glass-border);
          border-radius: 14px;
          color: var(--text-main);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          transition: all .25s ease;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
          border-color: var(--accent);
          color: var(--accent);
          box-shadow: 0 4px 24px var(--glow);
          transform: translateY(-1px);
        }
        .stButton > button[kind="primary"] {
          background: linear-gradient(135deg, rgba(79, 209, 197, 0.25), rgba(40, 130, 130, 0.25));
          border-color: var(--accent-soft);
          color: var(--text-main);
          box-shadow: 0 4px 18px var(--glow);
        }
        .stButton > button[kind="primary"]:hover {
          background: linear-gradient(135deg, rgba(79, 209, 197, 0.40), rgba(40, 130, 130, 0.40));
          box-shadow: 0 6px 28px var(--glow);
        }

        /* expander 卡片 */
        [data-testid="stExpander"], [data-testid="stExpander"] > details {
          background: var(--glass) !important;
          backdrop-filter: blur(var(--blur)) !important;
          -webkit-backdrop-filter: blur(var(--blur)) !important;
          border: 1px solid var(--glass-border) !important;
          border-radius: 14px !important;
          box-shadow: 0 4px 24px rgba(0, 0, 0, 0.25) !important;
        }
        [data-testid="stExpander"] summary { 
          background: transparent !important; 
          color: var(--text-main) !important; 
        }
        [data-testid="stExpander"] summary:hover { 
          color: var(--accent) !important; 
        }
        /* 强制覆盖标题文字和下拉箭头的颜色 */
        [data-testid="stExpander"] summary p { 
          color: var(--text-main) !important; 
          font-weight: 600 !important;
        }
        [data-testid="stExpander"] summary svg { 
          color: var(--accent) !important; 
          fill: var(--accent) !important; 
        }

        /* 数字 / 文本输入框 */
        .stNumberInput input, .stTextInput input, .stTextArea textarea {
          background: rgba(8, 18, 24, 0.55) !important;
          color: var(--text-main) !important;
          border: 1px solid var(--glass-border) !important;
          border-radius: 8px !important;
        }
        .stNumberInput input:focus, .stTextInput input:focus, .stTextArea textarea:focus {
          border-color: var(--accent) !important;
          box-shadow: 0 0 0 1px var(--accent-soft) !important;
        }
        .stNumberInput button {
          background: rgba(8, 18, 24, 0.55) !important;
          border-color: var(--glass-border) !important;
          color: var(--accent) !important;
        }

        /* 下拉选择 */
        .stSelectbox [data-baseweb="select"] > div {
          background: rgba(8, 18, 24, 0.55) !important;
          border: 1px solid var(--glass-border) !important;
          border-radius: 8px !important;
          color: var(--text-main) !important;
        }

        /* 滑块 */
        .stSlider [data-baseweb="slider"] [role="slider"] {
          background: var(--accent) !important;
          box-shadow: 0 0 12px var(--glow) !important;
        }

        /* 进度条 */
        .stProgress > div > div > div {
          background-color: rgba(8, 18, 24, 0.55) !important;
          border: 1px solid var(--glass-border) !important;
          border-radius: 8px !important;
        }
        .stProgress > div > div > div > div {
          background-image: linear-gradient(90deg, var(--accent), #2e9d92) !important;
          box-shadow: 0 0 12px var(--glow);
        }

        /* 表格 */
        .stTable, [data-testid="stTable"], [data-testid="stDataFrame"] {
          background: var(--glass) !important;
          backdrop-filter: blur(var(--blur));
          -webkit-backdrop-filter: blur(var(--blur));
          border: 1px solid var(--glass-border) !important;
          border-radius: 12px !important;
          overflow: hidden;
        }
        .stTable table, [data-testid="stTable"] table, [data-testid="stDataFrame"] table {
          background: transparent !important;
          color: var(--text-main) !important;
        }
        .stTable thead th, [data-testid="stTable"] thead th, [data-testid="stDataFrame"] thead th {
          background: rgba(79, 209, 197, 0.10) !important;
          color: var(--accent) !important;
          border-bottom: 1px solid var(--accent-soft) !important;
          font-weight: 600;
        }
        .stTable tbody tr:nth-child(even),
        [data-testid="stTable"] tbody tr:nth-child(even),
        [data-testid="stDataFrame"] tbody tr:nth-child(even) {
          background: rgba(255, 255, 255, 0.02) !important;
        }
        .stTable tbody td, [data-testid="stTable"] tbody td, [data-testid="stDataFrame"] tbody td {
          color: var(--text-main) !important;
          border-color: rgba(120, 200, 210, 0.08) !important;
        }

        /* info / success / warning / error 提示框 */
        [data-testid="stAlert"] {
          background: var(--glass) !important;
          backdrop-filter: blur(var(--blur));
          -webkit-backdrop-filter: blur(var(--blur));
          border: 1px solid var(--glass-border);
          border-left: 3px solid var(--accent);
          border-radius: 10px;
          color: var(--text-main);
        }
        [data-testid="stAlert"] * { color: var(--text-main) !important; }

        /* radio / checkbox */
        .stRadio label, .stCheckbox label { color: var(--text-main) !important; }

        /* 滚动条 */
        ::-webkit-scrollbar { width: 10px; height: 10px; }
        ::-webkit-scrollbar-track { background: rgba(8, 18, 24, 0.4); }
        ::-webkit-scrollbar-thumb {
          background: rgba(79, 209, 197, 0.25);
          border-radius: 6px;
        }
        ::-webkit-scrollbar-thumb:hover { background: rgba(79, 209, 197, 0.45); }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_style()


# ==========================================
# 初始化
# ==========================================
def _initialize_game(o2_tanks, crew_size, hab, plant, compost,
                     minister_key="annie", difficulty=DEFAULT_DIFFICULTY):
    if difficulty not in DIFFICULTY_LEVELS:
        difficulty = DEFAULT_DIFFICULTY
    st.session_state.day = 0
    st.session_state.is_alive = True
    st.session_state.death_reason = ""
    st.session_state.last_hab = hab
    st.session_state.last_plant = plant
    st.session_state.last_compost = compost
    st.session_state.last_lab = 0
    st.session_state.last_greenhouse = 0
    st.session_state.init_tanks = o2_tanks
    st.session_state.locked_crew_size = crew_size
    st.session_state.difficulty = difficulty
    st.session_state.event_chance = DIFFICULTY_LEVELS[difficulty]["chance"]
    st.session_state.locked_initial = {
        "tanks": o2_tanks, "crew": crew_size,
        "hab": hab, "plant": plant, "compost": compost,
        "minister": minister_key,
        "difficulty": difficulty,
    }
    st.session_state.crew_list = [_make_minister_crew(minister_key)]
    used_names = {st.session_state.crew_list[0]["name"]}
    for _ in range(crew_size - 1):
        name = random.choice(NAME_POOL); tries = 0
        while name in used_names and tries < 30:
            name = random.choice(NAME_POOL); tries += 1
        used_names.add(name)
        st.session_state.crew_list.append(_make_random_crew(name=name))

    st.session_state.crop_batches = []
    st.session_state.active_events = []
    st.session_state.event_log = []
    st.session_state.lab_projects = []
    st.session_state.build_queue = []
    st.session_state.solar_panel_m2 = SOLAR_PANEL_M2_DEFAULT

    start_vol = hab * VOL_HABITAT + plant * VOL_PLANT + compost * VOL_COMPOST
    st.session_state.state = {
        "O2_kg": start_vol * 0.21 * DENSITY_O2,
        "CO2_kg": start_vol * 0.0020 * DENSITY_CO2,
        "O2_Tank_kg": o2_tanks * O2_TANK_CAPACITY_PER_UNIT,
        "CO2_Tank_kg": 50.0,
        "Clean_Water_kg": 800.0,
        "Structural_Water_kg": hab * WATER_PER_HABITAT + plant * WATER_PER_PLANT + compost * WATER_PER_COMPOST,
        "Waste_Water_kg": 60.0,
        "Solid_Waste_kg": 2.0,
        "Fertilizer_kg": 10.0,
        "Food_kg": 80.0,
        "Algae_Biomass_kg": 10.0,
        "Regolith_Shield_m2": 0.0,
        "hull_integrity": 100.0,
        "Power_Battery_kWh": BATTERY_CAP_DEFAULT,
        "Power_Battery_Cap_kWh": BATTERY_CAP_DEFAULT,
        "research_multipliers": _default_research_multipliers(),
        "completed_research": [],
        # 🆕 v6 药材 / 药物
        "Herbs_kg": 0.0,
        "Medicine_kg": 5.0,
    }
    st.session_state.history = pd.DataFrame()
    # === 🆕 新手教程参数初始化 ===
    st.session_state.current_minister = _minister_choice.split(" ")[0]
    st.session_state.tutorial_step = 1  # 设置初始步骤为 1
    st.session_state.state["Medicine_kg"] += 3  # 教程赠送 3 个医疗包
    # ==============================
    st.session_state.game_started = True


if "game_started" not in st.session_state:
    st.session_state.game_started = False

# ---------- 开局界面 ----------
if not st.session_state.game_started:
    st.title("🌙 月球生态部")
    st.markdown("---")
    st.header("🚀 任务初始化")
    st.caption("v6 引入天赋系统、医疗/受伤系统与排队建造工作。开局参数一旦确认将永久锁定。")

    col_l, col_r = st.columns(2)
    with col_l:
        init_tanks_in = st.number_input("初始高压氧气瓶 (10kg/瓶)", min_value=0, value=10, step=1)
        init_crew_in = st.number_input("初始乘组规模 (人)", min_value=1, max_value=10, value=4, step=1,
                                       help="1 号乘员为你选定的部长；其余成员姓名+天赋随机生成。")
    with col_r:
        init_hab_in = st.number_input("初始居住舱数量", min_value=1, value=2, step=1)
        init_plant_in = st.number_input("初始种植舱数量", min_value=0, value=1, step=1)
        init_compost_in = st.number_input("初始堆肥舱数量", min_value=0, value=1, step=1)

    st.markdown("---")
    st.subheader("👑 选择 1 号成员（部长）")
    st.caption("部长拥有顶级天赋。其余成员姓名与天赋全随机（0~2 个，概率 30%/50%/20%）。")
    _min_keys = list(MINISTERS.keys())
    _minister_choice = st.session_state.get("_init_minister", _min_keys[0])
    # === 🆕 渲染初始部长立绘 ===
    # 选人界面立绘
    # === 🆕 渲染初始部长立绘 ===
    # 选人界面立绘
    NAME_MAP = {"annie": "Annie部长", "guo": "郭部长", "huang": "黄部长", "luo": "罗部长"}
    m_key_init = NAME_MAP.get(_minister_choice, "Annie部长") # 通过翻译官转换 Key
    
    import os
    img_path = MINISTER_DATA[m_key_init]["init_img"]
    if os.path.exists(img_path):
        st.image(img_path, width=300, caption=MINISTER_DATA[m_key_init]["style"])
        st.info(MINISTER_DATA[m_key_init]["intro"])
    else:
        st.warning(f"找不到图片文件：{img_path}，请检查文件名或后缀（比如是不是多了一个 .jpg）")
    _mcols = st.columns(len(_min_keys))
    for _ci, _mk in enumerate(_min_keys):
        with _mcols[_ci]:
            if st.button(MINISTERS[_mk]["name"], use_container_width=True, key=f"minister_btn_{_mk}"):
                st.session_state._init_minister = _mk
                _minister_choice = _mk
            st.caption(MINISTERS[_mk]["desc"])
    st.info(f"当前选择：**{MINISTERS[_minister_choice]['name']}** — {MINISTERS[_minister_choice]['desc']}")
    st.session_state._init_minister = _minister_choice

    st.markdown("---")
    st.subheader("⚠️ 选择突发事件强度（难度模式）")
    st.caption("难度一旦确认将永久锁定，整局沿用此事件概率。")
    _diff_keys = list(DIFFICULTY_LEVELS.keys())
    _diff_choice = st.session_state.get("_init_difficulty", DEFAULT_DIFFICULTY)
    if _diff_choice not in DIFFICULTY_LEVELS:
        _diff_choice = DEFAULT_DIFFICULTY
    _dcols = st.columns(len(_diff_keys))
    for _di, _dk in enumerate(_diff_keys):
        _dspec = DIFFICULTY_LEVELS[_dk]
        with _dcols[_di]:
            _label = f"{_dspec['emoji']} {_dspec['name']}"
            if st.button(_label, use_container_width=True, key=f"diff_btn_{_dk}"):
                st.session_state._init_difficulty = _dk
                _diff_choice = _dk
            st.caption(f"事件概率 {_dspec['chance']*100:.0f}% / 天")
            st.caption(_dspec["desc"])
    _dspec_sel = DIFFICULTY_LEVELS[_diff_choice]
    st.info(
        f"当前难度：**{_dspec_sel['emoji']} {_dspec_sel['name']}** "
        f"— 每日触发概率 {_dspec_sel['chance']*100:.0f}% · {_dspec_sel['desc']}"
    )
    st.session_state._init_difficulty = _diff_choice

    if st.button("🚀 确认配置，开始任务", type="primary", use_container_width=True):
        _initialize_game(init_tanks_in, init_crew_in, init_hab_in, init_plant_in, init_compost_in,
                         minister_key=_minister_choice, difficulty=_diff_choice)
        st.rerun()
    st.stop()

# ---------- 运营中：旧存档兼容 ----------
for _k, _v in [
    ("last_lab", 0), ("lab_projects", []),
    ("solar_panel_m2", SOLAR_PANEL_M2_DEFAULT),
    ("last_greenhouse", 0),
    ("build_queue", []),
    ("locked_crew_size", len(st.session_state.get("crew_list", []))),
    ("difficulty", DEFAULT_DIFFICULTY),
    ("event_chance", DIFFICULTY_LEVELS[DEFAULT_DIFFICULTY]["chance"]),
    ("locked_initial", {
        "tanks": st.session_state.get("init_tanks", 10),
        "crew": len(st.session_state.get("crew_list", [])),
        "hab": st.session_state.get("last_hab", 2),
        "plant": st.session_state.get("last_plant", 1),
        "compost": st.session_state.get("last_compost", 1),
        "minister": "annie",
        "difficulty": DEFAULT_DIFFICULTY,
    }),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v
st.session_state.locked_initial.setdefault("difficulty", st.session_state.get("difficulty", DEFAULT_DIFFICULTY))

for _k, _v in [
    ("Power_Battery_kWh", BATTERY_CAP_DEFAULT),
    ("Power_Battery_Cap_kWh", BATTERY_CAP_DEFAULT),
    ("completed_research", []),
    ("Herbs_kg", 0.0),
    ("Medicine_kg", 5.0),
]:
    if _k not in st.session_state.state:
        st.session_state.state[_k] = _v
if "research_multipliers" not in st.session_state.state:
    st.session_state.state["research_multipliers"] = _default_research_multipliers()
else:
    st.session_state.state["research_multipliers"].setdefault("pharma_ready", False)

for _c in st.session_state.crew_list:
    _c.setdefault("health", 100.0)
    _c.setdefault("job", JOB_DEFAULT)
    if "talents" not in _c:
        _c["talents"] = _gen_random_talents()
    _c.setdefault("constitution", round(random.uniform(0.7, 1.0), 2))
    _c.setdefault("sickness", None)
    _c.setdefault("sickness_days", 0)
    _c.setdefault("injury", None)
    _c.setdefault("injury_days", 0)

for _p in st.session_state.lab_projects:
    _p.setdefault("assigned_crew", [])


# ==========================================
# 突发事件引擎
# ==========================================
def _process_events(s, day_index, hab, plant, compost, base_light, event_chance):
    ctx_flags = {"light_mult": 1.0, "scrubber_off": False, "mood_delta": 0.0}
    def add_status(key, days): st.session_state.active_events.append({"key": key, "days_left": days})
    def scale_light(m): ctx_flags["light_mult"] = min(ctx_flags["light_mult"], m)
    def disable_scrubber(): ctx_flags["scrubber_off"] = True
    def mood_shock(d): ctx_flags["mood_delta"] += d
    ctx = {"add_status": add_status, "scale_light": scale_light,
           "disable_scrubber": disable_scrubber, "mood_shock": mood_shock, "day": day_index}

    hull_dur = s.get("research_multipliers", {}).get("hull_durability", 1.0)
    def _run_with_hull_wrap(fn):
        pre = s["hull_integrity"]; fn(s, ctx); post = s["hull_integrity"]
        dmg = pre - post
        if dmg > 0 and hull_dur > 1.0:
            s["hull_integrity"] = pre - dmg / hull_dur

    still_active = []
    for ev in st.session_state.active_events:
        if ev["key"] == "power_down":
            scale_light(0.0); disable_scrubber()
        else:
            spec = EVENT_LIBRARY.get(ev["key"])
            if spec and "tick" in spec:
                _run_with_hull_wrap(spec["tick"])
        ev["days_left"] -= 1
        if ev["days_left"] > 0:
            still_active.append(ev)
    st.session_state.active_events = still_active

    if event_chance > 0 and np.random.random() < event_chance:
        keys = list(EVENT_LIBRARY.keys())
        weights = np.array([EVENT_LIBRARY[k]["weight"] for k in keys], dtype=float)
        weights /= weights.sum()
        chosen = np.random.choice(keys, p=weights)
        spec = EVENT_LIBRARY[chosen]
        if spec["category"] == "instant":
            _run_with_hull_wrap(spec["impact"])
        else:
            add_status(chosen, spec["duration"])
            if "tick" in spec:
                _run_with_hull_wrap(spec["tick"])
        st.session_state.event_log.append(
            {"day": day_index + 1, "name": spec["name"], "desc": spec["desc"]})

    return ctx_flags


def sync_lab_count(target_count):
    cur = len(st.session_state.lab_projects)
    if target_count > cur:
        for _ in range(target_count - cur):
            st.session_state.lab_projects.append({"project": None, "progress": 0.0, "crew": 0, "assigned_crew": []})
    elif target_count < cur:
        for _removed in st.session_state.lab_projects[target_count:]:
            for _ci in _removed.get("assigned_crew", []):
                if 0 <= _ci < len(st.session_state.crew_list):
                    st.session_state.crew_list[_ci]["job"] = JOB_DEFAULT
        st.session_state.lab_projects = st.session_state.lab_projects[:target_count]


# ==========================================
# 🆕 v6 医疗与受伤日处理
# ==========================================
def _process_medical_and_injury(s, day_index):
    log = []
    for member in st.session_state.crew_list:
        mood = member["mood"]
        constitution = member.get("constitution", 0.85)
        mood_factor = (mood / 100.0)

        # 受伤（探索触发）
        if member.get("injury") is None and member.get("job") == "explore":
            if random.random() < INJURY_DAILY_PER_EXPLORER:
                kind = "light" if random.random() < 0.6 else "heavy"
                member["injury"] = kind
                member["injury_days"] = 0
                log.append({"day": day_index + 1,
                            "name": f"🩹 {member['name']} {'轻伤' if kind=='light' else '重伤'}",
                            "desc": "外出探索时受伤。" + ("可能自愈。" if kind == "light" else "需吃药治疗。")})

        if member.get("injury"):
            member["injury_days"] += 1
            kind = member["injury"]
            member["health"] = max(0.0, member["health"] - INJURY_HEALTH_PENALTY[kind])
            if kind == "light":
                p = INJURY_LIGHT_SELFHEAL + 0.3 * (mood_factor - 0.5) + 0.2 * (constitution - 0.85)
                if random.random() < max(0.05, min(0.9, p)):
                    member["injury"] = None
                    member["injury_days"] = 0
                    log.append({"day": day_index + 1, "name": f"💪 {member['name']} 轻伤自愈", "desc": "心情/体质支撑下顺利康复。"})
            else:  # heavy
                if s["Medicine_kg"] >= 1.0:
                    s["Medicine_kg"] -= 1.0
                    if random.random() < INJURY_HEAVY_MED_RECOVER + 0.2 * (mood_factor - 0.5):
                        member["injury"] = "light"
                        member["injury_days"] = 0
                        log.append({"day": day_index + 1, "name": f"💊 {member['name']} 重伤好转", "desc": "用药后转为轻伤，进入恢复期。"})
                else:
                    member["health"] = max(0.0, member["health"] - INJURY_NOMED_HEALTH_LOSS)

        # 疾病
        if member.get("sickness") is None:
            p = SICKNESS_BASE_DAILY * (1.15 - constitution) * (1.5 - mood_factor)
            if random.random() < max(0.0, p):
                member["sickness"] = "early"
                member["sickness_days"] = 0
                log.append({"day": day_index + 1, "name": f"🤒 {member['name']} 发病",
                            "desc": "进入病程初期，有概率自愈，否则 3 天后转为加重。"})

        if member.get("sickness"):
            member["sickness_days"] += 1
            stage = member["sickness"]
            if stage == "early":
                p = SICKNESS_SELFHEAL_BASE + 0.3 * (constitution - 0.85) + 0.2 * (mood_factor - 0.5)
                if random.random() < max(0.05, min(0.9, p)):
                    member["sickness"] = None
                    member["sickness_days"] = 0
                    log.append({"day": day_index + 1, "name": f"🌿 {member['name']} 自愈", "desc": "初期病症自行康复。"})
                elif member["sickness_days"] >= SICKNESS_TO_SEVERE_DAYS:
                    member["sickness"] = "severe"
                    member["sickness_days"] = 0
                    log.append({"day": day_index + 1, "name": f"⚠️ {member['name']} 病情加重",
                                "desc": "3 天未愈，需每日服药治疗。"})
                member["health"] = max(0.0, member["health"] - 1.0)
            else:  # severe
                if s["Medicine_kg"] >= 1.0:
                    s["Medicine_kg"] -= 1.0
                    if random.random() < SICKNESS_MEDICINE_RECOVER + 0.15 * (mood_factor - 0.5):
                        member["sickness"] = "early"
                        member["sickness_days"] = 0
                        log.append({"day": day_index + 1, "name": f"💊 {member['name']} 药效见效", "desc": "病情转回初期，继续观察。"})
                    member["health"] = max(0.0, member["health"] - 1.0)
                else:
                    member["health"] = max(0.0, member["health"] - SICKNESS_NOMED_HEALTH_LOSS)
    if log:
        st.session_state.event_log.extend(log)


def _purge_lost_crew(day_index):
    """🆕 v6 永久移除：health=0 死亡 / mood=0 叛逃。"""
    survivors = []
    removed = []
    for m in st.session_state.crew_list:
        if m["health"] <= 0:
            removed.append((m["name"], "💀 死亡（健康衰竭）"))
        elif m["mood"] <= 0:
            removed.append((m["name"], "🏃 叛逃（心情崩溃）"))
        else:
            survivors.append(m)
    if removed:
        # 按 name 重映射 lab 派遣的索引
        name_to_new_idx = {m["name"]: i for i, m in enumerate(survivors)}
        for proj in st.session_state.lab_projects:
            old = proj.get("assigned_crew", [])
            new_assigned = []
            for ci in old:
                if 0 <= ci < len(st.session_state.crew_list):
                    nm = st.session_state.crew_list[ci]["name"]
                    if nm in name_to_new_idx:
                        new_assigned.append(name_to_new_idx[nm])
            proj["assigned_crew"] = new_assigned
            proj["crew"] = len(new_assigned)
        st.session_state.crew_list = survivors
        for nm, reason in removed:
            st.session_state.event_log.append({
                "day": day_index + 1, "name": f"❌ {nm} {reason}", "desc": "成员已永久从基地名册中移除。"
            })


# ==========================================
# 🆕 v6 建造队列推进
# ==========================================
def _process_build_queue(s, day_index):
    if not st.session_state.build_queue:
        return
    builders = [c for c in st.session_state.crew_list if c.get("job") == "build"]
    if not builders:
        return
    n = len(builders)
    eff = EFFECTIVE_CREW_TABLE[min(n, len(EFFECTIVE_CREW_TABLE) - 1)]
    talent_mult = _team_talent_avg_mult(builders, "build")
    health_factor = float(np.mean([min(1.0, m["health"] / 100.0) for m in builders]))
    work_today = eff * talent_mult * health_factor

    remaining = work_today
    new_queue = []
    completed_names = []
    for item in st.session_state.build_queue:
        if remaining <= 0:
            new_queue.append(item); continue
        spend = min(remaining, item["work_remaining"])
        item["work_remaining"] -= spend
        remaining -= spend
        if item["work_remaining"] <= 0:
            t = item["type"]
            if t == "hab":         st.session_state.last_hab += 1
            elif t == "plant":     st.session_state.last_plant += 1
            elif t == "compost":   st.session_state.last_compost += 1
            elif t == "lab":       st.session_state.last_lab += 1; sync_lab_count(st.session_state.last_lab)
            elif t == "greenhouse":st.session_state.last_greenhouse += 1
            s["Structural_Water_kg"] += BUILD_WATER[t]
            completed_names.append(BUILD_LABEL[t])
        else:
            new_queue.append(item)
    st.session_state.build_queue = new_queue
    if completed_names:
        st.session_state.event_log.append({
            "day": day_index + 1, "name": "🏗️ 建造完工",
            "desc": "新建成：" + "、".join(completed_names)
        })


def queue_build(s, btype):
    """玩家点击排队建造：立即扣净水。"""
    water_need = BUILD_WATER[btype]
    if s["Clean_Water_kg"] < water_need:
        return False, f"净水不足，需要 {water_need:.0f} kg。"
    s["Clean_Water_kg"] -= water_need
    st.session_state.build_queue.append({
        "type": btype,
        "work_remaining": BUILD_WORK[btype],
        "total_work": BUILD_WORK[btype],
        "water_paid": water_need,
    })
    return True, f"已排队建造 {BUILD_LABEL[btype]}（工作量 {BUILD_WORK[btype]:.0f} 人·天，已扣净水 {water_need:.0f} kg）。"


def recruit_member():
    """🆕 v6 招募新成员。"""
    s = st.session_state.state
    cur = len(st.session_state.crew_list)
    cap = st.session_state.last_hab * RESIDENTS_PER_HAB + st.session_state.last_greenhouse * RESIDENTS_PER_GH
    if cur >= cap:
        return False, "居住容量已满，无法招募。请先扩建居住舱或温室。"
    if s["Food_kg"] <= 5.0 or s["Clean_Water_kg"] <= 10.0:
        return False, "食物或净水储备不足，无法迎接新成员。"
    used = {m["name"] for m in st.session_state.crew_list}
    name = random.choice(NAME_POOL); tries = 0
    while name in used and tries < 30:
        name = random.choice(NAME_POOL); tries += 1
    new = _make_random_crew(name=name)
    st.session_state.crew_list.append(new)
    return True, f"新成员 **{new['name']}** 已加入！天赋：{_format_talents(new['talents'])}；体质 {new['constitution']:.2f}。"


# ==========================================
# 核心演算引擎
# ==========================================
def step_system(alg_ww, alg_fert, light_h, incinerator_rate, solar_panel_m2,
                days_step, event_chance):
    if not st.session_state.is_alive:
        return
    s = st.session_state.state
    sync_lab_count(st.session_state.last_lab)
    m = s["research_multipliers"]

    for _ in range(days_step):
        hab = st.session_state.last_hab
        plant = st.session_state.last_plant
        compost = st.session_state.last_compost
        lab = st.session_state.last_lab
        greenhouse = st.session_state.last_greenhouse

        ev_ctx = _process_events(s, st.session_state.day, hab, plant, compost, light_h, event_chance)
        day_light = light_h * ev_ctx["light_mult"]

        vol = (hab * VOL_HABITAT + plant * VOL_PLANT + compost * VOL_COMPOST
               + lab * VOL_LAB + greenhouse * VOL_GREENHOUSE)
        max_ww = plant * 150.0 + compost * 50.0 + 50.0
        max_sw = compost * 30.0 + 10.0

        daily_water_reclaimed = 0.0
        daily_water_consumed = 0.0

        O2_pct_current = (s["O2_kg"] / DENSITY_O2) / vol * 100 if vol > 0 else 0
        CO2_pct_current = (s["CO2_kg"] / DENSITY_CO2) / vol * 100 if vol > 0 else 0

        total_crew = len(st.session_state.crew_list)
        if total_crew == 0:
            st.session_state.is_alive = False
            st.session_state.death_reason = "全员阵亡或叛逃，基地无人留守。"
            break
        living_rooms = hab + greenhouse
        people_per_room = total_crew / living_rooms if living_rooms > 0 else total_crew

        # 电力
        gen_solar = solar_panel_m2 * SOLAR_KWH_PER_M2_HOUR * day_light * m.get("solar_efficiency", 1.0)
        active_labs = sum(1 for proj in st.session_state.lab_projects if proj.get("project"))
        cons_total = (hab * POWER_PER_HABITAT + plant * POWER_PER_PLANT
                      + compost * POWER_PER_COMPOST + lab * POWER_PER_LAB_IDLE
                      + active_labs * (POWER_PER_LAB_ACTIVE - POWER_PER_LAB_IDLE)
                      + greenhouse * POWER_PER_GREENHOUSE)
        net_power = gen_solar - cons_total
        s["Power_Battery_kWh"] = min(s["Power_Battery_kWh"] + net_power, s["Power_Battery_Cap_kWh"])
        power_shortage = s["Power_Battery_kWh"] < 0
        if power_shortage:
            s["Power_Battery_kWh"] = 0.0
            s["hull_integrity"] = max(0.0, s["hull_integrity"] - 0.5)

        repairer_list = [c for c in st.session_state.crew_list if c.get("job") == "repair"]
        explorer_list = [c for c in st.session_state.crew_list if c.get("job") == "explore"]
        repairers = len(repairer_list); explorers = len(explorer_list)

        # 科研推进
        for lab_proj in st.session_state.lab_projects:
            proj_key = lab_proj.get("project")
            if proj_key and proj_key in RESEARCH_LIBRARY:
                spec = RESEARCH_LIBRARY[proj_key]
                valid_crew_idx = [ci for ci in lab_proj.get("assigned_crew", [])
                                  if 0 <= ci < len(st.session_state.crew_list)]
                valid_members = [st.session_state.crew_list[ci] for ci in valid_crew_idx]
                actual = len(valid_members)
                if not power_shortage and actual > 0:
                    eff = EFFECTIVE_CREW_TABLE[min(actual, len(EFFECTIVE_CREW_TABLE) - 1)]
                    talent_mult = _team_talent_avg_mult(valid_members, "research")
                    health_factor = float(np.mean([min(1.0, mm["health"] / 100.0) for mm in valid_members]))
                    lab_proj["progress"] += RESEARCH_BASE_RATE * eff * talent_mult * health_factor
                    if lab_proj["progress"] >= spec["cycle"]:
                        # 🆕 v6 制药：消耗药材产药物（不重复占用 completed_research）
                        if proj_key == "pharma":
                            cost = spec.get("herb_cost", 10.0)
                            if s["Herbs_kg"] >= cost:
                                s["Herbs_kg"] -= cost
                                s["Medicine_kg"] += spec.get("medicine_yield", 5.0)
                                spec["on_complete"](m)
                                st.session_state.event_log.append({
                                    "day": st.session_state.day + 1,
                                    "name": f"💉 制药完成: 产 {spec.get('medicine_yield', 5.0):.0f} 单位药物",
                                    "desc": "可重复立项；继续提交将再次消耗药材。",
                                })
                            else:
                                lab_proj["progress"] = spec["cycle"]
                                continue
                        else:
                            spec["on_complete"](m)
                            s["completed_research"].append(proj_key)
                            st.session_state.event_log.append({
                                "day": st.session_state.day + 1,
                                "name": f"🏆 课题完成: {spec['name']}",
                                "desc": spec["desc"],
                            })
                        for ci in valid_crew_idx:
                            if 0 <= ci < len(st.session_state.crew_list):
                                st.session_state.crew_list[ci]["job"] = JOB_DEFAULT
                        lab_proj["project"] = None
                        lab_proj["progress"] = 0.0
                        lab_proj["crew"] = 0
                        lab_proj["assigned_crew"] = []

        # 🆕 v6 建造队列推进
        _process_build_queue(s, st.session_state.day)

        # 修理
        if repairers > 0 and s["Regolith_Shield_m2"] > 0:
            eff = EFFECTIVE_CREW_TABLE[min(repairers, len(EFFECTIVE_CREW_TABLE) - 1)]
            talent_mult = _team_talent_avg_mult(repairer_list, "repair")
            health_factor = float(np.mean([min(1.0, mm["health"] / 100.0) for mm in repairer_list]))
            shield_cost = min(s["Regolith_Shield_m2"], REPAIR_SHIELD_COST_PER_EFF * eff)
            hull_gain = (shield_cost / REPAIR_SHIELD_COST_PER_EFF) * REPAIR_HULL_GAIN_PER_EFF * talent_mult * health_factor
            s["Regolith_Shield_m2"] -= shield_cost
            s["hull_integrity"] = min(100.0, s["hull_integrity"] + hull_gain)

        # 探索
        if explorers > 0:
            eff = EFFECTIVE_CREW_TABLE[min(explorers, len(EFFECTIVE_CREW_TABLE) - 1)]
            talent_mult = _team_talent_avg_mult(explorer_list, "explore")
            health_factor = float(np.mean([min(1.0, mm["health"] / 100.0) for mm in explorer_list]))
            pow_need = explorers * EXPLORE_POWER_PER_CREW
            pow_have = min(pow_need, s["Power_Battery_kWh"])
            s["Power_Battery_kWh"] -= pow_have
            pow_factor = (pow_have / pow_need) if pow_need > 0 else 1.0
            explore_water = EXPLORE_WATER_PER_EFF * eff * pow_factor * talent_mult * health_factor
            explore_regolith = EXPLORE_REGOLITH_PER_EFF * eff * pow_factor * talent_mult * health_factor
            s["Clean_Water_kg"] += explore_water
            s["Regolith_Shield_m2"] += explore_regolith
            daily_water_reclaimed += explore_water

        # 维护
        total_modules = hab + plant + compost + lab + greenhouse
        maint_water = total_modules * MAINTENANCE_COST_PER_MODULE * m.get("maintenance", 1.0)
        s["Clean_Water_kg"] -= maint_water
        daily_water_consumed += maint_water

        # 资源压力
        resource_stress = 0
        if s["Food_kg"] <= 10.0: resource_stress += 10.0
        if O2_pct_current < 19.5: resource_stress += 8.0
        if CO2_pct_current > 0.5: resource_stress += 6.0
        if CO2_pct_current < 0.04: resource_stress += 5.0
        if s["Waste_Water_kg"] > max_ww: resource_stress += 5.0
        if s["Solid_Waste_kg"] > max_sw: resource_stress += 7.0

        # 心情/健康（含娱乐天赋每日加成）
        shield = s["Regolith_Shield_m2"]
        explore_rad_per_person = max(EXPLORE_RAD_MIN, EXPLORE_RAD_BASE - shield * 0.02)
        anoxia = O2_pct_current < 19.5
        co2_toxic = CO2_pct_current > 0.5
        entertain_bonus = _daily_entertain_bonus(st.session_state.crew_list)

        for member in st.session_state.crew_list:
            job = member.get("job", JOB_DEFAULT)

            base_decay = -np.random.uniform(0.1, 0.5)
            greenhouse_bonus = plant * 0.6
            green_room_bonus = greenhouse * GH_MOOD_BONUS_PER_UNIT
            crew_support_bonus = total_crew * 0.20
            crowding_penalty = -people_per_room * 0.7
            shield_safety_bonus = min(5.0, shield * 0.02)
            resource_penalty = -resource_stress
            event_shock = ev_ctx["mood_delta"]
            job_mood = JOB_MOOD_DELTA.get(job, 0.0)
            sick_mood = (-2.0 if member.get("sickness") == "early"
                         else (-5.0 if member.get("sickness") == "severe" else 0.0))
            inj_mood = (-1.0 if member.get("injury") == "light"
                        else (-4.0 if member.get("injury") == "heavy" else 0.0))

            delta_m = (base_decay + greenhouse_bonus + green_room_bonus + crew_support_bonus
                       + crowding_penalty + shield_safety_bonus + resource_penalty
                       + event_shock + job_mood + entertain_bonus + sick_mood + inj_mood)
            member["mood"] = max(0.0, min(100.0, member["mood"] + delta_m))

            health_d = JOB_HEALTH_DELTA.get(job, 0.0)
            if job == "explore":
                health_d -= explore_rad_per_person
            if anoxia: health_d -= 1.0
            if co2_toxic: health_d -= 1.0
            member["health"] = max(0.0, min(100.0, member["health"] + health_d))

        # 🆕 v6 医疗/受伤
        _process_medical_and_injury(s, st.session_state.day)

        avg_mood = float(np.mean([mm["mood"] for mm in st.session_state.crew_list]))
        avg_health = float(np.mean([mm["health"] for mm in st.session_state.crew_list]))

        # 代谢 / 堆肥
        s["O2_kg"] -= META["O2_CONS"] * total_crew
        s["CO2_kg"] += META["CO2_PROD"] * total_crew
        metab_water = META["WATER_USE"] * total_crew
        s["Clean_Water_kg"] -= metab_water
        s["Waste_Water_kg"] += metab_water
        daily_water_consumed += metab_water
        s["Solid_Waste_kg"] += META["SOLID_WASTE"] * total_crew
        s["Food_kg"] -= META["FOOD_CONS"] * total_crew

        comp_mult = m.get("compost", 1.0)
        proc_sw = min(s["Solid_Waste_kg"], BIO_PARAMS["COMPOST_MAX_SW_PER_UNIT"] * compost * comp_mult)
        proc_ww = min(s["Waste_Water_kg"], BIO_PARAMS["COMPOST_MAX_WW_PER_UNIT"] * compost * comp_mult)
        s["Solid_Waste_kg"] -= proc_sw
        s["Waste_Water_kg"] -= proc_ww
        s["Fertilizer_kg"] += (proc_sw * 0.8 + proc_ww * 0.9) * comp_mult
        s["CO2_kg"] += (proc_sw * 0.2 + proc_ww * 0.1)

        # 焚化
        act_inc = min(s["Solid_Waste_kg"], incinerator_rate)
        act_inc = min(act_inc, s["O2_kg"] / 1.5)
        if act_inc > 0:
            s["Solid_Waste_kg"] -= act_inc
            s["O2_kg"] -= act_inc * 1.1
            s["CO2_kg"] += act_inc * 1.5
            s["Waste_Water_kg"] += act_inc * 0.6
            s["Power_Battery_kWh"] = min(s["Power_Battery_kWh"] + act_inc * INCINERATOR_KWH_PER_KG,
                                         s["Power_Battery_Cap_kWh"])

        # 🚫 v6：删除"排向月壤"（不再有 MICP 倾倒处理）

        # 微藻
        K_cap = max(1.0, total_modules) * 20.0
        act_alg_fert = min(s["Fertilizer_kg"], alg_fert)
        s["Fertilizer_kg"] -= act_alg_fert
        nut_factor = (alg_ww + act_alg_fert * 10) / (s["Waste_Water_kg"] + 1) if (s["Waste_Water_kg"] + act_alg_fert) > 0 else 0
        l_fac = day_light / 24.0
        g_rate = 0.3 * l_fac * min(1.0, nut_factor * 5) if l_fac > 0 else -0.1
        s["Algae_Biomass_kg"] = max(0.1, s["Algae_Biomass_kg"] + g_rate * s["Algae_Biomass_kg"] * (1 - s["Algae_Biomass_kg"] / K_cap))
        alg_pur = min(min(s["Waste_Water_kg"], alg_ww), BIO_PARAMS["ALGAE_WATER_PUR_KG"] * s["Algae_Biomass_kg"])
        s["Waste_Water_kg"] -= alg_pur
        alg_pur_clean = alg_pur * m.get("water_recycle", 1.0)
        s["Clean_Water_kg"] += alg_pur_clean
        daily_water_reclaimed += alg_pur_clean
        alg_co2_abs = min(s["CO2_kg"], BIO_PARAMS["ALGAE_CO2_ABS_KG"] * m.get("algae_co2", 1.0) * s["Algae_Biomass_kg"] * l_fac)
        s["CO2_kg"] -= alg_co2_abs
        s["O2_kg"] += alg_co2_abs * 0.8 * m.get("algae_o2", 1.0)

        # 农作物
        base_evap = min(s["Waste_Water_kg"], plant * BIO_PARAMS["PLANT_BASE_EVAPORATION"])
        s["Waste_Water_kg"] -= base_evap
        base_evap_clean = base_evap * m.get("water_recycle", 1.0)
        s["Clean_Water_kg"] += base_evap_clean
        daily_water_reclaimed += base_evap_clean

        tot_req_ww = tot_req_co2 = tot_req_fert = 0.0
        for batch in st.session_state.crop_batches:
            cinfo = CROP_DATA[batch['type']]
            tot_req_ww += cinfo['daily_ww'] * batch['amount']
            tot_req_co2 += cinfo['daily_co2'] * batch['amount']
            tot_req_fert += cinfo['daily_fert'] * batch['amount']

        total_water_pool = s["Waste_Water_kg"] + s["Clean_Water_kg"]
        r_ww = min(1.0, total_water_pool / tot_req_ww) if tot_req_ww > 0 else 1.0
        r_co2 = min(1.0, s["CO2_kg"] / tot_req_co2) if tot_req_co2 > 0 else 1.0
        r_fert = min(1.0, s["Fertilizer_kg"] / tot_req_fert) if tot_req_fert > 0 else 1.0

        light_crop_factor = (day_light / light_h) if light_h > 0 else 0.0
        if power_shortage:
            light_crop_factor *= 0.5

        surviving_batches = []
        for batch in st.session_state.crop_batches:
            cinfo = CROP_DATA[batch['type']]
            amt = batch['amount']

            need_irrig = r_ww * cinfo['daily_ww'] * amt
            take_ww = min(need_irrig, s["Waste_Water_kg"])
            take_cw_irrig = min(need_irrig - take_ww, s["Clean_Water_kg"])
            s["Waste_Water_kg"] -= take_ww
            s["Clean_Water_kg"] -= take_cw_irrig
            daily_water_consumed += take_cw_irrig

            act_cw = r_ww * cinfo['daily_cw'] * amt * m.get("water_recycle", 1.0)
            s["Clean_Water_kg"] += act_cw
            daily_water_reclaimed += act_cw

            act_co2_ratio = min(r_ww, r_co2) * light_crop_factor
            act_co2 = act_co2_ratio * cinfo['daily_co2'] * amt
            act_o2 = act_co2_ratio * cinfo['daily_o2'] * amt
            s["CO2_kg"] -= act_co2
            s["O2_kg"] += act_o2

            act_fert = r_fert * cinfo['daily_fert'] * amt
            s["Fertilizer_kg"] -= act_fert

            supply_min = min(r_ww, r_co2, r_fert)
            if supply_min < 0.5:
                batch['health'] -= 5.0 * (1.0 - supply_min)
            elif supply_min >= 0.8:
                batch['health'] = min(100.0, batch['health'] + 5.0)

            if batch['health'] <= 0:
                s["Solid_Waste_kg"] += amt * cinfo['yield_sw'] * 0.5
            else:
                batch['age'] += 1
                if batch['age'] >= cinfo['cycle']:
                    hp = batch['health'] / 100.0
                    s["Food_kg"] += amt * cinfo['yield_food'] * hp * m.get("crop_yield", 1.0)
                    s["Herbs_kg"] += amt * cinfo.get("yield_herb", 0.0) * hp * m.get("crop_yield", 1.0)
                    s["Solid_Waste_kg"] += amt * cinfo['yield_sw']
                else:
                    surviving_batches.append(batch)

        st.session_state.crop_batches = surviving_batches

        # 温室
        if greenhouse > 0:
            gh_light = light_crop_factor if light_h > 0 else 0.0
            req_ww = greenhouse * GH_WW_PER_DAY
            req_co2 = greenhouse * GH_CO2_PER_DAY
            req_fert = greenhouse * GH_FERT_PER_DAY
            gh_water_pool = s["Waste_Water_kg"] + s["Clean_Water_kg"]
            r_gh_ww = min(1.0, gh_water_pool / req_ww) if req_ww > 0 else 1.0
            r_gh_co2 = min(1.0, s["CO2_kg"] / req_co2) if req_co2 > 0 else 1.0
            r_gh_fert = min(1.0, s["Fertilizer_kg"] / req_fert) if req_fert > 0 else 1.0
            gh_factor = min(r_gh_ww, r_gh_co2, r_gh_fert) * gh_light * m.get("crop_yield", 1.0)

            need_gh_irrig = req_ww * r_gh_ww
            take_gh_ww = min(need_gh_irrig, s["Waste_Water_kg"])
            take_gh_cw = min(need_gh_irrig - take_gh_ww, s["Clean_Water_kg"])
            s["Waste_Water_kg"] -= take_gh_ww
            s["Clean_Water_kg"] -= take_gh_cw
            daily_water_consumed += take_gh_cw

            s["CO2_kg"] -= req_co2 * r_gh_co2
            s["Fertilizer_kg"] -= req_fert * r_gh_fert
            s["O2_kg"] += greenhouse * GH_O2_PER_DAY * gh_factor

            gh_water = greenhouse * GH_WATER_RECLAIM_PER_DAY * gh_factor * m.get("water_recycle", 1.0)
            s["Clean_Water_kg"] += gh_water
            daily_water_reclaimed += gh_water

        # Sabatier
        if m.get("co2_to_water", False):
            co2_threshold = 0.3 / 100 * vol * DENSITY_CO2
            if s["CO2_kg"] > co2_threshold:
                conv_co2 = min(s["CO2_kg"] - co2_threshold, 2.0)
                s["CO2_kg"] -= conv_co2
                sabatier_water = conv_co2 * 0.5
                s["Clean_Water_kg"] += sabatier_water
                daily_water_reclaimed += sabatier_water

        # CDRA
        temp_o2_pct = (s["O2_kg"] / DENSITY_O2) / vol * 100 if vol > 0 else 0
        if temp_o2_pct > 24.0 and s["O2_Tank_kg"] < (st.session_state.init_tanks * O2_TANK_CAPACITY_PER_UNIT):
            mass_to_pull = min(s["O2_kg"] - (24.0 / 100 * vol * DENSITY_O2),
                               (st.session_state.init_tanks * O2_TANK_CAPACITY_PER_UNIT) - s["O2_Tank_kg"])
            s["O2_kg"] -= max(0, mass_to_pull); s["O2_Tank_kg"] += max(0, mass_to_pull)
        elif temp_o2_pct < 19.5 and s["O2_Tank_kg"] > 0:
            mass_to_push = min((19.5 / 100 * vol * DENSITY_O2) - s["O2_kg"], s["O2_Tank_kg"])
            s["O2_kg"] += max(0, mass_to_push); s["O2_Tank_kg"] -= max(0, mass_to_push)

        temp_co2_pct = (s["CO2_kg"] / DENSITY_CO2) / vol * 100 if vol > 0 else 0
        if (temp_co2_pct > 0.3 and s["CO2_Tank_kg"] < MAX_CO2_TANK_CAPACITY
                and not ev_ctx["scrubber_off"]):
            mass_to_pull = min(s["CO2_kg"] - (0.3 / 100 * vol * DENSITY_CO2),
                               MAX_CO2_TANK_CAPACITY - s["CO2_Tank_kg"])
            s["CO2_kg"] -= max(0, mass_to_pull); s["CO2_Tank_kg"] += max(0, mass_to_pull)
        elif temp_co2_pct < 0.05 and s["CO2_Tank_kg"] > 0:
            mass_to_push = min((0.05 / 100 * vol * DENSITY_CO2) - s["CO2_kg"], s["CO2_Tank_kg"])
            s["CO2_kg"] += max(0, mass_to_push); s["CO2_Tank_kg"] -= max(0, mass_to_push)

        # 🆕 v6 永久移除
        _purge_lost_crew(st.session_state.day)

        final_O2_pct = (s["O2_kg"] / DENSITY_O2) / vol * 100 if vol > 0 else 0
        final_CO2_pct = (s["CO2_kg"] / DENSITY_CO2) / vol * 100 if vol > 0 else 0

        st.session_state.day += 1
        st.session_state.history = pd.concat([st.session_state.history, pd.DataFrame([{
            "Day": st.session_state.day, "O2_percent": final_O2_pct, "CO2_percent": final_CO2_pct,
            "Clean_Water": s["Clean_Water_kg"], "Waste_Water": s["Waste_Water_kg"], "Max_WW": max_ww,
            "Solid_Waste": s["Solid_Waste_kg"], "Max_SW": max_sw,
            "Algae_Biomass": s["Algae_Biomass_kg"], "Food": s["Food_kg"], "Fertilizer": s["Fertilizer_kg"],
            "Mood": avg_mood, "O2_Tank": s["O2_Tank_kg"], "CO2_Tank": s["CO2_Tank_kg"],
            "Regolith_Shield": s["Regolith_Shield_m2"], "Hull": s["hull_integrity"],
            "Battery": s["Power_Battery_kWh"], "Battery_Cap": s["Power_Battery_Cap_kWh"],
            "Power_Net": net_power,
            "Water_Reclaimed": daily_water_reclaimed,
            "Water_Consumed": daily_water_consumed,
            "Water_Net": daily_water_reclaimed - daily_water_consumed,
            "Health": avg_health,
            "Herbs": s["Herbs_kg"], "Medicine": s["Medicine_kg"],
            "Crew": len(st.session_state.crew_list),
        }])], ignore_index=True)

        if len(st.session_state.crew_list) == 0:
            st.session_state.is_alive = False
            st.session_state.death_reason = "全员死亡或叛逃，基地荒废。"
            break
        if final_CO2_pct > 3.0:
            st.session_state.is_alive = False; st.session_state.death_reason = "CO2 毒性崩溃"; break
        if final_O2_pct < 18.0:
            st.session_state.is_alive = False; st.session_state.death_reason = "缺氧崩溃"; break
        if s["Clean_Water_kg"] < 0:
            st.session_state.is_alive = False; st.session_state.death_reason = "饮用水枯竭"; break
        if s["Food_kg"] < 0:
            st.session_state.is_alive = False; st.session_state.death_reason = "口粮断绝"; break
        if s["hull_integrity"] <= 0:
            st.session_state.is_alive = False; st.session_state.death_reason = "壳体结构失效"; break
        # ... 上面是已有的结算和存入 history 的代码 ...
        if len(st.session_state.crew_list) == 0:
            st.session_state.is_alive = False
            st.session_state.death_reason = "全员死亡或叛逃，基地荒废。"
            break
        if final_CO2_pct > 3.0:
            st.session_state.is_alive = False; st.session_state.death_reason = "CO2 毒性崩溃"; break
        if final_O2_pct < 18.0:
            st.session_state.is_alive = False; st.session_state.death_reason = "缺氧崩溃"; break
        if s["Clean_Water_kg"] < 0:
            st.session_state.is_alive = False; st.session_state.death_reason = "饮用水枯竭"; break
        if s["Food_kg"] < 0:
            st.session_state.is_alive = False; st.session_state.death_reason = "口粮断绝"; break
        if s["hull_integrity"] <= 0:
            st.session_state.is_alive = False; st.session_state.death_reason = "壳体结构失效"; break

        # === 🆕 加入多日推演·智能刹车机制 ===
        # 如果玩家选择了一次性跳过多天，且当前不是跳跃的最后一天
        if days_step > 1 and _ < days_step - 1:
            crit_warn = False
            if final_CO2_pct > 2.0: crit_warn = True
            if final_O2_pct < 18.5: crit_warn = True
            if s["Clean_Water_kg"] < 50.0: crit_warn = True
            if s["Food_kg"] < 15.0: crit_warn = True
            if s["hull_integrity"] < 30.0: crit_warn = True
            for m in st.session_state.crew_list:
                if m["mood"] < 30 or m["health"] < 30:
                    crit_warn = True
            
            # 只要触发任何一项致命预警，强行终止后续的跳跃演进
            if crit_warn:
                st.session_state.event_log.append({
                    "day": st.session_state.day, 
                    "name": "🛑 系统强制暂停", 
                    "desc": f"检测到基地处于高危状态，已自动为您打断剩余的 {days_step - 1 - _} 天推演！请立即处理危机。"
                })
                # 👇 终极修复：重置天数为1，并且升级滑块版本号，强制前端刷新！
                st.session_state._step_n = 1
                st.session_state.slider_version = st.session_state.get("slider_version", 0) + 1
                # 👆 
                break
        # ========================================

# ==========================================
# 前端
# ==========================================
# 🆕 v6 把"天数"放到左栏最上方
with st.sidebar:
    st.markdown(f"## 📅 第 **{st.session_state.day}** 天")
    st.caption(f"在岗 {len(st.session_state.crew_list)} 人 · "
               f"舱 居{st.session_state.last_hab}/植{st.session_state.last_plant}/堆{st.session_state.last_compost}/"
               f"实{st.session_state.last_lab}/温{st.session_state.last_greenhouse}")
    st.markdown("---")

st.header("🌙 月球生态部")
if not st.session_state.is_alive:
    st.error(f"## 💀 生物圈已彻底崩溃！\n**终结原委：** {st.session_state.death_reason}")
    if st.button("🔄 重新开始 (初始化新基地)", type="primary", use_container_width=True, key="restart_top_btn"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
    st.markdown("---")
#st.caption("天赋系统 · 医疗/受伤 · 排队建造 · 药物生产链")
# ============================================================
# 🆕 领航员通讯频道与全站危机侦测 (互动式新手教程 / 预警)
# ============================================================
m_key_internal = st.session_state.current_minister
NAME_MAP = {"annie": "Annie部长", "guo": "郭部长", "huang": "黄部长", "luo": "罗部长"}
m_key_cn = NAME_MAP.get(m_key_internal, "Annie部长")

# 1. 提前侦测全局危险（用于置顶报警和全站特效）
mood_danger = [c["name"] for c in st.session_state.crew_list if c["mood"] < 40]
health_danger = [c["name"] for c in st.session_state.crew_list if c["health"] < 40]

warning_box = []
if st.session_state.is_alive and not st.session_state.history.empty:
    cur_chk = st.session_state.history.iloc[-1]
    hull_chk = st.session_state.state.get("hull_integrity", 100.0)
    if cur_chk['CO2_percent'] > 2.0:   warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["co2"])
    if cur_chk['O2_percent'] < 18.5:   warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["o2"])
    if cur_chk['Clean_Water'] < 50.0:  warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["water"])
    if cur_chk['Food'] < 15.0:         warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["food"])
    if hull_chk < 30.0:                warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["hull"])
    if mood_danger or health_danger:   warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["crew"])

# 🆕 全站红光警报特效 (除了部长，环境本身给出压迫感)
if warning_box and st.session_state.is_alive:
    st.markdown("""<style>.stApp { box-shadow: inset 0 0 120px rgba(220, 38, 38, 0.25); }</style>""", unsafe_allow_html=True)

# 2. 判断部长存活
minister_alive = True
minister_real_name = MINISTERS[m_key_internal]["name"].split(" ")[0]
for c in st.session_state.crew_list:
    if c["name"].startswith(minister_real_name) and c["health"] <= 0:
        minister_alive = False

if not minister_alive and st.session_state.is_alive:
    with st.expander("📡 领航员通讯频道：[无响应]", expanded=True):
        col_img, col_txt = st.columns([1, 5])
        col_img.caption("⬛ [信号已丢失]")
        col_txt.error(f"### ⚠️ 严重错误：连接中断\n\n系统已丢失与 {m_key_cn} 的生物特征连接。其已阵亡或离队，通讯通道永久冻结。")
else:
    is_tutorial_active = st.session_state.get("tutorial_step", 0) <= 5
    force_expand = is_tutorial_active or len(warning_box) > 0
    
    with st.expander(f"💬 领航员通讯频道：{m_key_cn}", expanded=force_expand):
        col_img, col_txt = st.columns([1, 5])
        try:
            col_img.image(MINISTER_DATA[m_key_cn]["game_img"], use_container_width=True)
        except:
            col_img.caption("[图片未找到]")

        tabs_names = ["🎯 模拟训练协议", "📚 基地系统百科"]
        if warning_box: tabs_names.insert(0, "🚨 紧急事态拦截")
            
        active_tabs = col_txt.tabs(tabs_names)
        
        if warning_box:
            tab_warn, tab_tut, tab_enc = active_tabs[0], active_tabs[1], active_tabs[2]
            with tab_warn:
                st.error("### 🔴 全站最高级别警报")
                for w in warning_box:
                    st.warning(f"**{m_key_cn}**：{w}")
        else:
            tab_tut, tab_enc = active_tabs[0], active_tabs[1]

        with tab_tut:
            if is_tutorial_active:
                step = st.session_state.tutorial_step
                dialogue = MINISTER_DATA[m_key_cn]["tutorial"].get(f"T{step}", "")
                
                if step == 0: st.markdown("### 📋 入职模拟训练协议")
                elif step == 5: st.markdown("### 💥 严重操作失误崩溃预演")
                else: st.markdown(f"### 🎯 训练阶段 {step} / 4")
                st.success(f"**{m_key_cn}**: \"{dialogue}\"")
                
                condition_met = False
                if step == 0: condition_met = True
                elif step == 1:
                    changed_algae = st.session_state.get("tutorial_light_h", 16) > 16 or st.session_state.get("tutorial_alg_ww", 20.0) > 20.0
                    clicked_evolve = st.session_state.get("evolve_top", False)
                    condition_met = changed_algae and (st.session_state.day > 0 or clicked_evolve)
                    st.info("👉 **行动引导**：CO₂ 已经超标爆红。请前往侧边栏【🦠 微藻光水调控】，将光照时长调大（>16），然后回到页面上方点击【⏳ 闭环演进】让微藻发挥作用。")
                elif step == 2:
                    condition_met = len(st.session_state.crop_batches) > 0
                    st.info("👉 **行动引导**：食物库存见底了！去左侧边栏【🌱 批次农业播种中心】，选一种作物并点击【🚜 下达播种指令】。")
                elif step == 3:
                    current_solar = float(st.session_state.get("solar_panel_m2_input", st.session_state.solar_panel_m2))
                    condition_met = current_solar > 100.0
                    st.info("👉 **行动引导**：电池快没电了！去左侧边栏【⚡ 电力系统】把【☀️ 坑外光伏面积】加大。")
                elif step == 4:
                    condition_met = any(p.get("project") for p in st.session_state.lab_projects)
                    st.info("👉 **行动引导**：系统已空投实验室！请向下滑动到【乘组工作分配】，把一名成员工作设为“🔬 科研”；接着去左侧边栏【🔬 科研课题立项】派他去研究！")
                elif step == 5: condition_met = True

                def advance_tutorial():
                    st.session_state.tutorial_step += 1
                    new_step = st.session_state.tutorial_step
                    s = st.session_state.state
                    vol = (st.session_state.last_hab * VOL_HABITAT + st.session_state.last_plant * VOL_PLANT + 
                           st.session_state.last_compost * VOL_COMPOST + st.session_state.last_lab * VOL_LAB + 
                           st.session_state.last_greenhouse * VOL_GREENHOUSE)
                    if new_step == 1: s["CO2_kg"] = 2.8 / 100 * vol * DENSITY_CO2
                    elif new_step == 2:
                        s["CO2_kg"] = 0.1 / 100 * vol * DENSITY_CO2; s["Food_kg"] = 2.0
                    elif new_step == 3:
                        s["Food_kg"] = 80.0; s["Power_Battery_kWh"] = s["Power_Battery_Cap_kWh"] * 0.05
                    elif new_step == 4:
                        s["Power_Battery_kWh"] = s["Power_Battery_Cap_kWh"]; s["hull_integrity"] = 55.0
                        if st.session_state.last_lab == 0: st.session_state.last_lab = 1; sync_lab_count(1)
                    elif new_step > 4: s["hull_integrity"] = 100.0

                btn_col1, btn_col2 = st.columns(2)
                if step < 5:
                    if condition_met:
                        if btn_col1.button("✅ 目标达成，进入下一阶段", type="primary", use_container_width=True):
                            advance_tutorial(); st.rerun()
                    else:
                        btn_col1.button("⚠️ 请先完成上方指示的行动", disabled=True, use_container_width=True)
                    if btn_col2.button("⏭️ 跳过新手教程", use_container_width=True):
                        st.session_state.tutorial_step = 6
                        s = st.session_state.state
                        vol = (st.session_state.last_hab * VOL_HABITAT + st.session_state.last_plant * VOL_PLANT + st.session_state.last_compost * VOL_COMPOST + st.session_state.last_lab * VOL_LAB + st.session_state.last_greenhouse * VOL_GREENHOUSE)
                        s["CO2_kg"] = 0.15 / 100 * vol * DENSITY_CO2; s["Food_kg"] = 80.0; s["Power_Battery_kWh"] = s["Power_Battery_Cap_kWh"]; s["hull_integrity"] = 100.0
                        st.rerun()
                else:
                    if btn_col1.button("🚀 结束预演，正式接管基地！", type="primary", use_container_width=True):
                        advance_tutorial(); st.rerun()
            else:
                st.info("🎯 新手模拟训练协议已完成。干得漂亮，指挥官！")
                if st.button("🔄 重新进行新手预演"): st.session_state.tutorial_step = 0; st.rerun()

        with tab_enc:
            st.markdown("### 📚 基地系统资料库")
            help_topic = st.selectbox("需要查阅哪部分资料？", ["居住舱", "温室舱", "种植舱", "堆肥舱", "实验室", "微藻光水调控", "电力系统", "招募系统", "灾难系统", "健康系统"])
            st.info(f"**{m_key_cn}**: \"{MINISTER_DATA[m_key_cn]['help'][help_topic]}\"")
# ============================================================

# ---------- 页面最上方：一键推进时间 ----------
_run_c1, _run_c2, _run_c3, _run_c4 = st.columns([1.5, 1, 1, 1.5])
with _run_c1:
    st.markdown(f"### 📅 运行天数：**第 {st.session_state.day} 天**")
    st.caption(f"在岗 {len(st.session_state.crew_list)} 人 | 居住舱: {st.session_state.last_hab} | 温室: {st.session_state.last_greenhouse}")
with _run_c2:
    if st.button("⏳ 闭环演进", type="primary",
                 use_container_width=True, key="evolve_top",
                 disabled=not st.session_state.is_alive):
        st.session_state._do_step = True
with _run_c3:
    if st.button("🚨 重置基地",type="primary", use_container_width=True, help="放弃当前存档，返回初始配置界面"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
with _run_c4:
    # 👇 获取当前滑块的版本号（默认是0）
    s_ver = st.session_state.get("slider_version", 0)
    
    _step_top = st.slider("推演时间跨度 (天)", 1, 30,
                          int(st.session_state.get("_step_n", 5)),
                          key=f"step_slider_top_{s_ver}") # 👈 动态生成 Key
    st.session_state._step_n = _step_top
st.markdown("---")


# 👇👇👇 新增：基地核心态势感知看板 (最高优先级置顶) 👇👇👇
if not st.session_state.history.empty:
    # 1. 进行中的异常事件
    if st.session_state.active_events:
        active_names = [EVENT_LIBRARY[e["key"]]["name"] + f"(剩{e['days_left']}天)" for e in st.session_state.active_events if e["key"] in EVENT_LIBRARY]
        if active_names:
            st.warning("🔴 **进行中的异常事件**：" + " ｜ ".join(active_names))
    
    # 2. 壳体结构完整性血条
    hull_top = st.session_state.state.get("hull_integrity", 100.0)
    st.progress(max(0.0, min(1.0, hull_top / 100.0)), text=f"🛡️ 壳体结构完整性 σ：{hull_top:.1f} / 100")
    
    # 3. 人员崩溃边缘警告
    mood_danger = [c["name"] for c in st.session_state.crew_list if c["mood"] < 40]
    health_danger = [c["name"] for c in st.session_state.crew_list if c["health"] < 40]
    if mood_danger:
        st.error(f"🚨 **心情崩溃边缘**：{', '.join(mood_danger)} —— 心情降至 0 将永久叛逃！")
    if health_danger:
        st.error(f"🚨 **健康崩溃边缘**：{', '.join(health_danger)} —— 健康=0 将永久死亡，请立即安排休息或就医！")
    
    # 4. 基地历史日志 (展开显示)
    if st.session_state.event_log:
        with st.expander("📜 日志 (最近 15 条)",expanded=True):
            for e in reversed(st.session_state.event_log[-15:]):
                st.markdown(f"**第 {e['day']} 天 — {e['name']}** \n　{e['desc']}")
st.markdown("---")
# 👆👆👆 置顶结束 👆👆👆

def _mood_health_tier(v):
    if v > 70:  return "✅"
    if v >= 40: return "⚠️"
    return "🚨"

def _sick_badge(m):
    s = m.get("sickness"); i = m.get("injury")
    out = []
    if s == "early": out.append("🤒 初期")
    elif s == "severe": out.append("🤢 加重")
    if i == "light": out.append("🩹 轻伤")
    elif i == "heavy": out.append("🚑 重伤")
    return " · ".join(out) if out else "—"

st.markdown("---")

# 接着才是原来的乘组分配
st.subheader("👥 乘组工作分配")
st.caption("每位乘员每天选 1 项工作；产出按边际递减并叠加天赋倍率。带伤病可工作，但效率随健康下降，且健康会继续掉。"
           "「🔬科研」必须通过侧边栏「科研课题立项」派遣。")
_crew_n = len(st.session_state.crew_list)
_locked_to_lab = {}
for _li, _proj in enumerate(st.session_state.lab_projects):
    if _proj.get("project"):
        for _ci in _proj.get("assigned_crew", []):
            _locked_to_lab[_ci] = _li
_free_job_keys = [k for k in JOBS if k != "research"]
_per_row = 4
for _row_start in range(0, _crew_n, _per_row):
    _row_members = st.session_state.crew_list[_row_start:_row_start + _per_row]
    _cols = st.columns(_per_row)
    for _i, _member in enumerate(_row_members):
        _abs_idx = _row_start + _i
        with _cols[_i]:
            _mt = _mood_health_tier(_member["mood"])
            _ht = _mood_health_tier(_member["health"])
            st.markdown(
                f"**{_member['name']}**  \n"
                f"心情 {_mt} **{_member['mood']:.0f}** · 健康 {_ht} **{_member['health']:.0f}**"
            )
            st.caption(f"天赋：{_format_talents(_member.get('talents', []))}")
            st.caption(f"体质 {_member.get('constitution', 1.0):.2f} · 伤病：{_sick_badge(_member)}")
            if _abs_idx in _locked_to_lab:
                _lab_n = _locked_to_lab[_abs_idx] + 1
                _proj_key = st.session_state.lab_projects[_locked_to_lab[_abs_idx]].get("project")
                _proj_name = RESEARCH_LIBRARY[_proj_key]["name"] if _proj_key in RESEARCH_LIBRARY else "?"
                st.markdown(f"🔒 **科研中** · 实验室 #{_lab_n}")
                st.caption(f"课题：{_proj_name}")
            else:
                _cur_job = _member.get("job", JOB_DEFAULT)
                if _cur_job not in _free_job_keys:
                    _cur_job = JOB_DEFAULT
                _new_job = st.selectbox(
                    "今日工作", _free_job_keys,
                    index=_free_job_keys.index(_cur_job),
                    format_func=lambda k: JOBS[k]["name"],
                    key=f"job_select_{_abs_idx}",
                )
                _member["job"] = _new_job
                _tm = _crew_talent_mult(_member, _new_job)
                if _tm > 1.0:
                    st.caption(f"✨ 天赋倍率 ×{_tm:.2f} — {JOBS[_new_job]['desc']}")
                else:
                    st.caption(JOBS[_new_job]["desc"])
st.markdown("---")

# 🆕 把科研课题状态移到这里
completed_top = st.session_state.state.get("completed_research", [])
with st.expander(f"🔬 科研课题状态 (进行中 {sum(1 for p in st.session_state.lab_projects if p.get('project'))} · 已完成 {len(completed_top)})", expanded=True):
    if st.session_state.lab_projects:
        for idx, proj in enumerate(st.session_state.lab_projects):
            key = proj.get("project")
            if key and key in RESEARCH_LIBRARY:
                spec = RESEARCH_LIBRARY[key]
                pct = min(1.0, proj["progress"] / spec["cycle"])
                _names = [st.session_state.crew_list[ci]["name"] for ci in proj.get("assigned_crew", []) if 0 <= ci < len(st.session_state.crew_list)]
                _team = "、".join(_names) if _names else "无人在岗"
                st.progress(pct, text=f"实验室 #{idx + 1} · {spec['name']} · {proj['progress']:.1f}/{spec['cycle']} · {_team}")
            else:
                st.caption(f"实验室 #{idx + 1} · 空闲")
    if completed_top:
        st.markdown("**🏆 已完成课题：**")
        st.markdown("  \n".join(f"- {RESEARCH_LIBRARY[k]['name']}" for k in completed_top if k in RESEARCH_LIBRARY))

st.markdown("---")

# ============================================================

with st.sidebar:
    st.header("🔒 任务约束 (开局已锁定)")
    _lk = st.session_state.locked_initial
    _min_name = MINISTERS.get(_lk.get("minister", "annie"), MINISTERS["annie"])["name"]
    _dk = _lk.get("difficulty", DEFAULT_DIFFICULTY)
    _dspec_lk = DIFFICULTY_LEVELS.get(_dk, DIFFICULTY_LEVELS[DEFAULT_DIFFICULTY])
    st.markdown(
        f"- 着陆携带 **{_lk['tanks']}** 瓶储氧罐\n"
        f"- 初始乘组 **{_lk['crew']}** 人\n"
        f"- 初始舱室 居 **{_lk['hab']}** / 植 **{_lk['plant']}** / 堆 **{_lk['compost']}**\n"
        f"- 部长：**{_min_name}**\n"
        f"- 难度：**{_dspec_lk['emoji']} {_dspec_lk['name']}**（事件 {_dspec_lk['chance']*100:.0f}%/天）"
    )

    st.markdown("---")
    st.header("🏗️ 建造队列")
    st.caption("排队即扣净水构造水；由「🏗️ 建造」工作推进，建造天赋者更快。")
    s = st.session_state.state
    _bq_cols = st.columns(5)
    _btypes = list(BUILD_WORK.keys())
    for _bi, _bt in enumerate(_btypes):
        with _bq_cols[_bi]:
            st.caption(f"{BUILD_LABEL[_bt]}\n{BUILD_WATER[_bt]:.0f}水·{BUILD_WORK[_bt]:.0f}人天")
            if st.button(f"➕{BUILD_LABEL[_bt]}", key=f"queue_{_bt}", use_container_width=True):
                ok, msg = queue_build(s, _bt)
                (st.success if ok else st.error)(msg)
    if st.session_state.build_queue:
        st.markdown("**队列中：**")
        for _bi, item in enumerate(st.session_state.build_queue):
            pct = 1.0 - (item["work_remaining"] / item["total_work"])
            st.progress(max(0.0, min(1.0, pct)),
                        text=f"#{_bi+1} {BUILD_LABEL[item['type']]} — 剩 {item['work_remaining']:.1f}/{item['total_work']:.0f} 人·天")
    else:
        st.caption("（无在建项目）")

    st.markdown("---")
    st.header("🧑‍🚀 招募新成员")
    _cap = st.session_state.last_hab * RESIDENTS_PER_HAB + st.session_state.last_greenhouse * RESIDENTS_PER_GH
    st.caption(f"居住容量：{len(st.session_state.crew_list)} / {_cap} 人")
    if st.button("🤝 招募一名新成员", use_container_width=True):
        ok, msg = recruit_member()
        (st.success if ok else st.error)(msg)

    st.markdown("---")
    st.header("⚡ 电力系统")
    solar_panel_m2 = st.number_input("☀️ 坑外光伏面积 (m²)", min_value=0.0,
                                     value=float(st.session_state.solar_panel_m2), step=20.0,
                                     key="solar_panel_m2_input",  # 👈 必须加上这行 key
                                     help=f"{SOLAR_KWH_PER_M2_HOUR:.3f} kWh/m²/h × 日照时长 × 效率倍率。")
    st.session_state.solar_panel_m2 = solar_panel_m2

    st.markdown("---")
    st.header("🌱 批次农业播种中心")
    current_load = sum(b['amount'] for b in st.session_state.crop_batches)
    max_load = st.session_state.last_plant * PLANT_CAPACITY_PER_UNIT
    st.caption(f"当前温室承载量: {current_load:.1f} / {max_load:.1f} kg")

    col_a, col_b = st.columns([3, 2])
    sel_crop = col_a.selectbox("播种作物", ["Lettuce", "Potato", "Wheat", "Medicinal"],
                               format_func=lambda x: CROP_DATA[x]['name'])
    sel_amt = col_b.number_input("预期产出 (kg)", min_value=1.0, value=15.0, step=5.0)

    if st.button("🚜 下达播种指令", use_container_width=True):
        if st.session_state.last_plant == 0:
            st.error("没有种植舱，无法播种！")
        elif current_load + sel_amt > max_load:
            st.error("温室容量不足！")
        else:
            st.session_state.crop_batches.append({"type": sel_crop, "amount": sel_amt, "age": 0, "health": 100.0})
            st.success(f"成功播种！预期 {CROP_DATA[sel_crop]['cycle']} 天后收获 {sel_amt}kg {CROP_DATA[sel_crop]['name']}。")
            st.rerun()

    st.markdown("---")
    st.header("🛡️ 应急脱困")
    incinerator_rate = st.number_input("🔥 固废高温催化炉 (kg/天)", min_value=0.0, value=0.0, step=2.0,
                                       help="燃烧垃圾和氧气，释放 CO2 挽救植物碳饥饿；并补充少量电力。")

    st.markdown("---")
    st.header("🦠 微藻光水调控")
    # 🆕 加上了 key="tutorial_alg_ww" 等属性，方便教程系统读取玩家的操作
    alg_ww = st.number_input("微藻废水通量 (kg/天)", min_value=0.0, value=20.0, step=10.0, key="tutorial_alg_ww")
    alg_fert = st.number_input("微藻施肥量 (kg/天)", min_value=0.0, value=0.5, step=0.5, key="tutorial_alg_fert")
    light_h = st.slider("光照时长 (h/day)", 0, 24, 16, key="tutorial_light_h")

    st.markdown("---")
    st.header("🔬 科研课题立项")
    sync_lab_count(st.session_state.last_lab)
    lab = st.session_state.last_lab
    if lab == 0:
        st.caption("尚未建造实验室舱。完工后可在此处为每个实验室立项与派人。")
    else:
        completed = set(st.session_state.state.get("completed_research", []))
        in_progress = {p["project"] for p in st.session_state.lab_projects if p.get("project")}
        for idx, proj in enumerate(st.session_state.lab_projects):
            st.markdown(f"**实验室 #{idx + 1}**")
            cur_key = proj.get("project")
            # 可重复课题（制药）即使已完成仍可立项；不重复课题完成后从可选中移除
            available = []
            for k, spec in RESEARCH_LIBRARY.items():
                if spec.get("repeatable") or k not in completed:
                    if k == cur_key or k not in in_progress:
                        available.append(k)
            options = ["(空闲)"] + available
            cur_label = cur_key if cur_key in available else "(空闲)"
            choice = st.selectbox(
                f"课题 #{idx + 1}", options, index=options.index(cur_label),
                format_func=lambda k: "(空闲)" if k == "(空闲)" else f"{RESEARCH_LIBRARY[k]['name']} · {RESEARCH_LIBRARY[k]['cycle']}天",
                key=f"lab_proj_{idx}",
            )
            new_key = None if choice == "(空闲)" else choice
            if new_key != cur_key:
                for _ci in proj.get("assigned_crew", []):
                    if 0 <= _ci < len(st.session_state.crew_list):
                        st.session_state.crew_list[_ci]["job"] = JOB_DEFAULT
                proj["assigned_crew"] = []
                proj["project"] = new_key
                proj["progress"] = 0.0

            if new_key:
                _crew_n = len(st.session_state.crew_list)
                _in_other_labs = set()
                for _j, _other in enumerate(st.session_state.lab_projects):
                    if _j != idx:
                        _in_other_labs.update(_other.get("assigned_crew", []))
                _crew_options = [i for i in range(_crew_n) if i not in _in_other_labs]
                _cur_assigned = [i for i in proj.get("assigned_crew", []) if i in _crew_options]
                _max = len(EFFECTIVE_CREW_TABLE) - 1
                def _fmt_crew(i):
                    _c = st.session_state.crew_list[i]
                    _tm = _crew_talent_mult(_c, "research")
                    _badge = f" ✨×{_tm:.2f}" if _tm > 1.0 else ""
                    return f"{_c['name']}{_badge} (心情{_c['mood']:.0f}/健康{_c['health']:.0f})"
                _selected = st.multiselect(
                    f"派遣乘员 (上限 {_max} 人，边际递减)",
                    options=_crew_options,
                    default=_cur_assigned,
                    format_func=_fmt_crew,
                    max_selections=_max,
                    key=f"lab_assigned_{idx}",
                    help="选中即把该乘员的工作锁定为「🔬科研」。"
                )
                _old_set, _new_set = set(proj.get("assigned_crew", [])), set(_selected)
                for _ci in _old_set - _new_set:
                    if 0 <= _ci < _crew_n:
                        st.session_state.crew_list[_ci]["job"] = JOB_DEFAULT
                for _ci in _new_set - _old_set:
                    if 0 <= _ci < _crew_n:
                        st.session_state.crew_list[_ci]["job"] = "research"
                proj["assigned_crew"] = list(_selected)
                proj["crew"] = len(_selected)

                spec = RESEARCH_LIBRARY[new_key]
                pct = min(1.0, proj["progress"] / spec["cycle"])
                st.progress(pct, text=f"进度 {proj['progress']:.1f} / {spec['cycle']} 天")
                st.caption(spec["desc"])
                if new_key == "pharma":
                    st.caption(f"💉 需要药材 {spec.get('herb_cost', 10):.0f} 单位 · 当前药材 {st.session_state.state['Herbs_kg']:.1f}")
            else:
                proj["crew"] = 0
            st.markdown("")

if st.session_state.pop("_do_step", False):
    step_system(alg_ww, alg_fert, light_h, incinerator_rate, solar_panel_m2,
                int(st.session_state.get("_step_n", 5)),
                st.session_state.event_chance)
    st.rerun()  # 👈 新增这一行！强制系统刷新，让上面的部长瞬间拿到最新情报！


if not st.session_state.history.empty:
    cur = st.session_state.history.iloc[-1]
    cur_max_ww = st.session_state.last_plant * 150.0 + st.session_state.last_compost * 50.0 + 50.0
    cur_max_sw = st.session_state.last_compost * 30.0 + 10.0

    with st.expander("🌾 农作物实时生长监控大屏", expanded=True):
        if len(st.session_state.crop_batches) == 0:
            st.info("目前温室处于闲置状态。")
        else:
            display_data = []
            for i, b in enumerate(st.session_state.crop_batches):
                cname = CROP_DATA[b['type']]['name']
                cycle = CROP_DATA[b['type']]['cycle']
                status = "✅ 生长中" if b['health'] > 50 else "⚠️ 濒临枯死"
                display_data.append({
                    "批次": f"#{i+1}", "作物": cname,
                    "预期产量 (kg)": f"{b['amount']:.1f}",
                    "生长进度": f"第 {b['age']} 天 / {cycle} 天",
                    "健康度": f"{b['health']:.1f} %",
                    "状态": status,
                })
            st.table(pd.DataFrame(display_data))

    st.subheader("📊 实时生态雷达")
    
    # # === 🆕 强力危机动态拦截预警 ===
    # if st.session_state.is_alive and not st.session_state.history.empty:
    #     warning_box = []
    #     if cur['CO2_percent'] > 2.0:
    #         warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["co2"])
    #     if cur['O2_percent'] < 18.5:
    #         warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["o2"])
    #     if cur['Clean_Water'] < 50.0:
    #         warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["water"])
    #     if cur['Food'] < 15.0:
    #         warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["food"])
    #     if hull < 30.0:
    #         warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["hull"])
            
    #     crew_danger = [c for c in st.session_state.crew_list if c["mood"] < 30 or c["health"] < 30]
    #     if crew_danger:
    #         warning_box.append(MINISTER_DATA[m_key_cn]["warnings"]["crew"])
            
    #     if warning_box:
    #         st.error("### 🚨 基地高危警报！")
    #         for w_msg in warning_box:
    #             st.warning(f"**{m_key_cn}**：{w_msg}")
    # # ============================
    avg_m = cur['Mood']
    mood_status = "✅ 士气高昂" if avg_m > 70 else ("⚠️ 幽闭焦虑" if avg_m > 40 else "🚨 叛乱边缘")
    co2_val = cur['CO2_percent']
    if co2_val > 0.5:   co2_status = "⚠️ 毒性堆积"
    elif co2_val < 0.04: co2_status = "⚠️ 碳饥饿"
    else:                co2_status = "✅ 正常"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("氧气 O₂", f"{cur['O2_percent']:.2f} %", "✅ 正常" if cur['O2_percent'] > 19.5 else "⚠️ 濒临缺氧")
    c2.metric("二氧化碳 CO₂", f"{co2_val:.2f} %", co2_status, delta_color="normal" if co2_status == "✅ 正常" else "inverse")
    c3.metric("备用高压氧罐", f"{cur['O2_Tank']:.1f} kg")
    c4.metric("备用高压碳源", f"{cur['CO2_Tank']:.1f} kg")
    c5.metric("团队心理韧性 (均值)", f"{cur['Mood']:.1f} / 100", mood_status)

    # def _tier_label(v):
    #     if v > 70: return "✅ 良好"
    #     if v >= 40: return "⚠️ 警戒"
    #     return "🚨 崩溃边缘"

    # mood_danger = [c["name"] for c in st.session_state.crew_list if c["mood"] < 40]
    # health_danger = [c["name"] for c in st.session_state.crew_list if c["health"] < 40]
    # if mood_danger:
    #     st.error(f"🚨 心情崩溃边缘：{', '.join(mood_danger)} —— 心情=0 将永久叛逃！")
    # if health_danger:
    #     st.error(f"🚨 健康崩溃边缘：{', '.join(health_danger)} —— 健康=0 将永久死亡，让他们休息或就医！")

    
    st.markdown("<br>", unsafe_allow_html=True)
    # 🆕 v6 资源面板：含药材/药物
    c6, c7, c8, c9, c10, c11 = st.columns(6)
    c6.metric("食物", f"{cur['Food']:.1f} kg")
    c7.metric("肥料", f"{cur['Fertilizer']:.1f} kg")
    c8.metric("废水", f"{cur['Waste_Water']:.1f} kg", f"上限 {cur_max_ww:.0f}", delta_color="off")
    c9.metric("固废", f"{cur['Solid_Waste']:.1f} kg", f"上限 {cur_max_sw:.0f}", delta_color="off")
    c10.metric("🌿 药材", f"{st.session_state.state['Herbs_kg']:.1f} 单位")
    c11.metric("💊 药物", f"{st.session_state.state['Medicine_kg']:.1f} 单位")

    st.markdown("---")
    st.subheader("⚡ 电力与 🔬 科研")
    bat = cur.get("Battery", 0.0)
    bat_cap = cur.get("Battery_Cap", st.session_state.state.get("Power_Battery_Cap_kWh", BATTERY_CAP_DEFAULT))
    net = cur.get("Power_Net", 0.0)
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("蓄电池余量", f"{bat:.1f} / {bat_cap:.0f} kWh",
              "⚠️ 见底" if bat < 1.0 else ("⚠️ 紧张" if bat < bat_cap * 0.2 else "✅ 充裕"),
              delta_color="inverse" if bat < bat_cap * 0.2 else "normal")
    p2.metric("昨日净电量", f"{net:+.1f} kWh", "盈余" if net >= 0 else "赤字",
              delta_color="normal" if net >= 0 else "inverse")
    p3.metric("光伏面积", f"{st.session_state.solar_panel_m2:.0f} m²")
    p4.metric("实验室 / 温室", f"{st.session_state.last_lab} / {st.session_state.last_greenhouse} 个")
    st.progress(max(0.0, min(1.0, bat / bat_cap)) if bat_cap > 0 else 0.0,
                text=f"🔋 电池 {bat:.1f} / {bat_cap:.0f} kWh")

    w_rec = cur.get("Water_Reclaimed", 0.0)
    w_con = cur.get("Water_Consumed", 0.0)
    w_net = cur.get("Water_Net", w_rec - w_con)
    w1, w2, w3, w4 = st.columns(4)
    w1.metric("💧 今日净水产量", f"{w_rec:.2f} kg", "微藻+作物+温室+探索", delta_color="off")
    w2.metric("今日净水消耗", f"{w_con:.2f} kg", "生活+维护+灌溉", delta_color="off")
    w3.metric("净水净流量", f"{w_net:+.2f} kg", "盈余" if w_net >= 0 else "亏空",
              delta_color="normal" if w_net >= 0 else "inverse")
    w4.metric("净水存量", f"{cur['Clean_Water']:.1f} kg")

    completed = st.session_state.state.get("completed_research", [])
    with st.expander(f"🔬 科研课题状态 (进行中 {sum(1 for p in st.session_state.lab_projects if p.get('project'))} · 已完成 {len(completed)})", expanded=False):
        if st.session_state.lab_projects:
            for idx, proj in enumerate(st.session_state.lab_projects):
                key = proj.get("project")
                if key and key in RESEARCH_LIBRARY:
                    spec = RESEARCH_LIBRARY[key]
                    pct = min(1.0, proj["progress"] / spec["cycle"])
                    _names = [st.session_state.crew_list[ci]["name"]
                              for ci in proj.get("assigned_crew", [])
                              if 0 <= ci < len(st.session_state.crew_list)]
                    _team = "、".join(_names) if _names else "无人在岗"
                    st.progress(pct, text=f"实验室 #{idx + 1} · {spec['name']} · {proj['progress']:.1f}/{spec['cycle']} · {_team}")
                else:
                    st.caption(f"实验室 #{idx + 1} · 空闲")
        if completed:
            st.markdown("**🏆 已完成课题：**")
            st.markdown("  \n".join(f"- {RESEARCH_LIBRARY[k]['name']}" for k in completed if k in RESEARCH_LIBRARY))


    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(20, 5))
    days_axis = st.session_state.history["Day"]

    ax1.plot(days_axis, st.session_state.history["O2_percent"], label="O2 (%)", color='#2ca02c', lw=2.5)
    ax1.plot(days_axis, st.session_state.history["CO2_percent"], label="CO2 (%)", color='#d62728', lw=2)
    ax1.axhline(18, color='darkgreen', linestyle=':', label='缺氧线(18%)')
    ax1.axhline(3, color='darkred', linestyle=':', label='CO2毒性线(3%)')
    ax1.set_title("大气动力学")
    ax1.legend()

    ax2.plot(days_axis, st.session_state.history["Waste_Water"], label="废水(kg)", color='brown')
    ax2.plot(days_axis, st.session_state.history["Max_WW"], label="废水上限", color='brown', linestyle=':', alpha=0.5)
    ax2.plot(days_axis, st.session_state.history["Solid_Waste"], label="固废(kg)", color='orange')
    ax2.plot(days_axis, st.session_state.history["Max_SW"], label="固废上限", color='orange', linestyle=':', alpha=0.5)
    ax2.plot(days_axis, st.session_state.history["Mood"], label="平均心情", color='purple', lw=2)
    if "Health" in st.session_state.history.columns:
        ax2.plot(days_axis, st.session_state.history["Health"].fillna(100.0),
                 label="平均健康", color='deeppink', lw=2, linestyle='--')
    if "Water_Reclaimed" in st.session_state.history.columns:
        ax2_r = ax2.twinx()
        ax2_r.plot(days_axis, st.session_state.history["Water_Reclaimed"].fillna(0),
                   label="净水产量(kg/天)", color='dodgerblue', lw=1.8)
        ax2_r.plot(days_axis, st.session_state.history["Water_Consumed"].fillna(0),
                   label="净水消耗(kg/天)", color='dodgerblue', lw=1.5, linestyle='--', alpha=0.7)
        ax2_r.set_ylabel("净水流量 kg/天", color='dodgerblue')
        ax2_r.tick_params(axis='y', labelcolor='dodgerblue')
        ax2_r.legend(loc='upper right')
    ax2.set_title("污染 · 心理 · 净水")
    ax2.legend(loc='upper left')

    ax3.plot(days_axis, st.session_state.history["Food"], label="粮食(kg)", color='gold')
    ax3.plot(days_axis, st.session_state.history["Regolith_Shield"], label="月壤护甲(m²)", color='silver', lw=2.5)
    ax3.plot(days_axis, st.session_state.history["Hull"], label="壳体σ", color='black', lw=2)
    ax3.plot(days_axis, st.session_state.history["O2_Tank"], label="备用氧气罐(kg)", color='teal', linestyle=':')
    ax3.plot(days_axis, st.session_state.history["CO2_Tank"], label="高压碳源罐(kg)", color='grey', linestyle='-.')
    if "Medicine" in st.session_state.history.columns:
        ax3.plot(days_axis, st.session_state.history["Medicine"].fillna(0), label="药物(单位)", color='crimson', lw=1.5)
        ax3.plot(days_axis, st.session_state.history["Herbs"].fillna(0), label="药材(单位)", color='seagreen', lw=1.2, linestyle='--')
    ax3.set_title("战略物资演进")
    ax3.legend()

    st.pyplot(fig)
