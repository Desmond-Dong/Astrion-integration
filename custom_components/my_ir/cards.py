"""Astrion UI 分类卡片定义（原 RosCard 卡片 → 集成子条目 / subentry）

RosCard 时代的做法：用户在 Lovelace 仪表盘里手写 aiks-* 卡片 YAML，
Astrion APK 通过 WebView 加载仪表盘渲染。

淘汰 RosCard 后：每个 subentry 是遥控器上的一个「分类」（如 TV、灯光），
同一分类下可添加多个 HA 设备。用户在
「设置 → 设备与服务 → Astrion Home → 添加子条目」里先选分类，
再在表单中选择该分类下的设备（多选）。

- **每种分类全局只有一个子条目**：重复添加同一分类时，
  新选的设备会自动并入已有子条目（保序去重），不会产生重复子条目。
- 不提供名称/图标字段：子条目标题直接用分类名（如「灯光」/ "Light"），
  按分类归类一目了然；绑定的设备会以 Friendly Name 创建为真正的
  HA 设备（挂在网关下、归属到分类子条目）。
- APK 通过 WebSocket 接口 astrion/get_cards 拉取分类列表自行渲染，
  接口会把分类下的设备解析为对应域的实体列表一并返回。

绑定设备的分类 subentry data 结构：

    {
        "devices": ["<device_id>", ...],      # 该分类下的 HA 设备（多选）
        ...分类选项（如窗帘接口类型）
    }

TV 分类为三步流程（设备 → 电源音量 → 物理按键），data 结构：

    {
        "devices": ["<device_id>", ...],      # 电视设备（media_player）
        "tv_type": "android_tv" | "harmony" | "broadlink",
        "remote_version": "x9" | "ha100a" | "ha100b",
        "remote_entities": ["remote.a", ...],   # 红外遥控实体（可选）
        "select_entities": ["select.b", ...],   # 选择器实体（可选）
        "background_path": "...",               # 背景图（可选）
        "power_entity": "remote.a",             # 电源控制绑定（可选）
        "power_command": "...",                 # 电源指令（可选，留空按码库解析）
        "volume_mode": "none" | "single" | "updown",
        "volume_entity": "media_player.x",      # volume_mode=single 时
        "volume_up_entity": "script.x",         # volume_mode=updown 时
        "volume_down_entity": "script.y",       # volume_mode=updown 时
        "media_commands": ["media_play", ...],  # 媒体按键绑定
        "select_options": {"select.b": ["HDMI1"]},  # 按键→选项绑定
        "key_bindings": {                       # 物理按键 F4-F11 绑定
            "F4": {"entity_id": "remote.a", "command": "..."},
        },
    }

key_bindings 中 command 的语义由实体决定：
    - Astrion 普通遥控器: 按键名（码库解析）或原生红外长码，留空 = 按键名解析
    - 博联 Broadlink:     "设备名/按键名"（来自 astrion/get_broadlink_codes）
    - Harmony hub:        活动/设备名（来自 astrion/get_harmony_config）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

SUBENTRY_TYPE_IR = "ir"  # 默认红外子条目：仅用于 HA 侧设备归组，不在添加菜单中
SUBENTRY_TYPE_GATEWAY = "gateway"  # 默认网关子条目：归属网关设备本身，不在添加菜单中
CARD_TV = "tv"
CARD_MEDIA_PLAYER = "media_player"
CARD_LIGHT = "light"
CARD_FAN = "fan"
CARD_CLIMATE = "climate"
CARD_COVER = "cover"
CARD_SWITCH = "switch"
CARD_SCENE = "scene"
CARD_WEATHER = "weather"
CARD_HOST = "host"
CARD_SWITCH_MONITOR = "switch_monitor"

# 场景分类的执行方式（与 RosCard 一致）
SCENE_MODE_IMMEDIATE = "immediate"
SCENE_MODE_DELAYED = "delayed"
SCENE_MODE_POPUP = "popup"
SCENE_MODES = [SCENE_MODE_IMMEDIATE, SCENE_MODE_DELAYED, SCENE_MODE_POPUP]

# 电视分类的遥控类型（与 RosCard 一致）
TV_TYPE_ANDROID_TV = "android_tv"
TV_TYPE_HARMONY = "harmony"
TV_TYPE_BROADLINK = "broadlink"
TV_TYPES = [TV_TYPE_ANDROID_TV, TV_TYPE_HARMONY, TV_TYPE_BROADLINK]

# 遥控器硬件版本（决定 F4-F11 物理按键的含义）
REMOTE_VERSION_X9 = "x9"
REMOTE_VERSION_HA100A = "ha100a"
REMOTE_VERSION_HA100B = "ha100b"
REMOTE_VERSIONS = [REMOTE_VERSION_X9, REMOTE_VERSION_HA100A, REMOTE_VERSION_HA100B]

# 可绑定的物理按键（含义随 remote_version 不同，见 translations 说明）
FKEYS = ["F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11"]

# 音量控制模式（与 RosCard 一致：单媒体实体 / 音量加和减）
VOLUME_MODE_NONE = "none"
VOLUME_MODE_SINGLE = "single"
VOLUME_MODE_UPDOWN = "updown"
VOLUME_MODES = [VOLUME_MODE_NONE, VOLUME_MODE_SINGLE, VOLUME_MODE_UPDOWN]

# 媒体按键绑定（与 RosCard 一致）
MEDIA_COMMANDS = [
    "turn_on",
    "turn_off",
    "media_play",
    "media_pause",
    "volume_up",
    "volume_down",
    "volume_mute_true",
    "volume_mute_false",
]

# 窗帘分类的接口类型（与 RosCard 一致）
CURTAIN_TYPE_CURTAIN = "curtain"
CURTAIN_TYPE_BLIND = "blind"
CURTAIN_TYPES = [CURTAIN_TYPE_CURTAIN, CURTAIN_TYPE_BLIND]

# 开关监控分类可监控的设备类型
MONITOR_DEVICE_TYPES = [
    "switch",
    "light",
    "fan",
    "climate",
    "cover",
    "media_player",
    "humidifier",
]

# select 实体的按键→选项绑定在表单里的字段前缀
SELECT_OPTIONS_PREFIX = "select_options::"

# 每个分类对应的实体域：astrion/get_cards 把分类下的设备
# 解析为该域的实体列表返回给 App；None 表示配置里自带实体
CARD_DOMAINS: dict[str, str | None] = {
    CARD_TV: "media_player",
    CARD_MEDIA_PLAYER: "media_player",
    CARD_LIGHT: "light",
    CARD_FAN: "fan",
    CARD_CLIMATE: "climate",
    CARD_COVER: "cover",
    CARD_SWITCH: "switch",
    CARD_SCENE: None,
    CARD_WEATHER: None,
    CARD_HOST: None,
    CARD_SWITCH_MONITOR: "switch",
}

# 分类联动设备在设备注册表里显示的型号（与红外设备的 model 字段同用途）
CARD_MODELS: dict[str, str] = {
    SUBENTRY_TYPE_IR: "Infrared",
    SUBENTRY_TYPE_GATEWAY: "Gateway",
    CARD_TV: "TV",
    CARD_MEDIA_PLAYER: "Media Player",
    CARD_LIGHT: "Light",
    CARD_FAN: "Fan",
    CARD_CLIMATE: "Climate",
    CARD_COVER: "Cover",
    CARD_SWITCH: "Switch",
    CARD_SCENE: "Scene & Script",
    CARD_WEATHER: "Weather",
    CARD_HOST: "Host",
    CARD_SWITCH_MONITOR: "Switch Monitor",
}

# 分类显示名（子条目标题）：每种分类全局只有一个子条目，标题直接用分类名
CARD_LABELS_ZH: dict[str, str] = {
    SUBENTRY_TYPE_IR: "红外",
    SUBENTRY_TYPE_GATEWAY: "网关",
    CARD_TV: "TV",
    CARD_MEDIA_PLAYER: "媒体播放器",
    CARD_LIGHT: "灯光",
    CARD_FAN: "风扇",
    CARD_CLIMATE: "温控",
    CARD_COVER: "窗帘",
    CARD_SWITCH: "开关",
    CARD_SCENE: "场景/脚本",
    CARD_WEATHER: "天气",
    CARD_HOST: "主机",
    CARD_SWITCH_MONITOR: "开关监控",
}

# 添加流程重复添加同一分类时，需要并入已有子条目的列表字段
UNION_KEYS: dict[str, tuple[str, ...]] = {
    CARD_TV: ("devices", "remote_entities", "select_entities"),
    CARD_MEDIA_PLAYER: ("devices",),
    CARD_LIGHT: ("devices",),
    CARD_FAN: ("devices",),
    CARD_CLIMATE: ("devices",),
    CARD_COVER: ("devices",),
    CARD_SWITCH: ("devices",),
    CARD_SCENE: ("entities",),
    CARD_WEATHER: ("entities",),
    CARD_HOST: ("entities",),
    CARD_SWITCH_MONITOR: ("devices",),
}


def category_label(hass: HomeAssistant | None, subentry_type: str) -> str:
    """分类显示名：按 HA 语言取中文/英文"""
    language = str(getattr(getattr(hass, "config", None), "language", "") or "")
    if language.lower().startswith("zh"):
        return CARD_LABELS_ZH.get(subentry_type, subentry_type)
    return CARD_MODELS.get(subentry_type, subentry_type)


def merge_into_existing(
    existing_data: dict[str, Any], new_data: dict[str, Any], subentry_type: str
) -> dict[str, Any]:
    """重复添加同一分类时，把新选的设备/实体并入已有子条目数据（保序去重）"""
    merged = dict(existing_data)
    for key in UNION_KEYS.get(subentry_type, ()):
        combined = list(existing_data.get(key) or [])
        for item in new_data.get(key) or []:
            if item not in combined:
                combined.append(item)
        if combined:
            merged[key] = combined
    return merged

# 每个步骤角色拥有的 subentry data 字段：重新配置合并时先移除再写入，
# 保证用户清空的字段会被正确删除而不是残留旧值
OWNED_KEYS: dict[str, frozenset[str]] = {
    "user": frozenset(
        {
            "devices",
            "entities",
            "tv_type",
            "remote_version",
            "remote_entities",
            "select_entities",
            "background_path",
            "curtain_type",
            "mode",
            "text_color",
            "image_path",
            "device_types",
        }
    ),
    "controls": frozenset(
        {
            "power_entity",
            "power_command",
            "volume_mode",
            "volume_entity",
            "volume_up_entity",
            "volume_down_entity",
            "media_commands",
            "select_options",
        }
    ),
    "keys": frozenset({"key_bindings"}),
}


def _suggested(value: Any) -> dict[str, Any]:
    """表单字段回填已有值"""
    return {"description": {"suggested_value": value}}


def _devices_selector(domain: str) -> selector.DeviceSelector:
    """构造设备选择器：多选，限定设备下含指定域的实体"""
    return selector.DeviceSelector(
        selector.DeviceSelectorConfig(
            entity=[{"domain": domain}],
            multiple=True,
        )
    )


def _entities_selector(domains: list[str] | None, multiple: bool = True):
    """构造实体选择器；domains 为空表示不限实体域"""
    cfg_kwargs: dict[str, Any] = {"multiple": multiple}
    if domains:
        cfg_kwargs["domain"] = domains
    return selector.EntitySelector(selector.EntitySelectorConfig(**cfg_kwargs))


def _select_entity_options(hass: HomeAssistant | None, entity_id: str) -> list[str]:
    """读取 select 实体的可选选项，用于按键→选项绑定"""
    if hass is None:
        return []
    state = hass.states.get(entity_id)
    if not state:
        return []
    options = state.attributes.get("options")
    return [str(o) for o in options] if isinstance(options, list) else []


@dataclass(frozen=True)
class CardTypeSpec:
    """一个分类的 subentry 定义

    steps         添加流程的步骤名列表（重新配置流程为 ["reconfigure"] + steps[1:]）
    build_schema  构建某一步的表单，role 为步骤角色名
    merge_step    把某一步的提交结果合并进 subentry data
    build_title   子条目标题 = 分类显示名（每种分类全局只有一个子条目）
    """

    subentry_type: str
    steps: list[str]
    build_schema: Callable[[str, HomeAssistant | None, dict[str, Any]], vol.Schema]
    merge_step: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]
    build_title: Callable[[HomeAssistant | None, dict[str, Any]], str]


def _merge_identity(role: str, user_input: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """默认合并：原样写入"""
    return dict(user_input)


# ====================== TV 分类（三步：设备 → 电源音量 → 物理按键） ======================


def _tv_schema_user(role: str, hass, data: dict[str, Any]) -> vol.Schema:
    """第一步：选择电视设备并绑定控制来源"""
    return vol.Schema(
        {
            vol.Required("devices", **_suggested(data.get("devices"))): _devices_selector(
                "media_player"
            ),
            vol.Required(
                "tv_type", default=TV_TYPE_ANDROID_TV, **_suggested(data.get("tv_type"))
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=TV_TYPES,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="tv_type",
                )
            ),
            vol.Required(
                "remote_version",
                default=REMOTE_VERSION_HA100A,
                **_suggested(data.get("remote_version")),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=REMOTE_VERSIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="remote_version",
                )
            ),
            vol.Optional(
                "remote_entities", **_suggested(data.get("remote_entities"))
            ): _entities_selector(["remote"]),
            vol.Optional(
                "select_entities", **_suggested(data.get("select_entities"))
            ): _entities_selector(["select"]),
            vol.Optional(
                "background_path", **_suggested(data.get("background_path"))
            ): selector.TextSelector(),
        }
    )


def _tv_schema_controls(role: str, hass, data: dict[str, Any]) -> vol.Schema:
    """第二步：电源控制、音量控制、媒体按键、select 按键→选项绑定"""
    fields: dict[Any, Any] = {
        vol.Optional("power_entity", **_suggested(data.get("power_entity"))): _entities_selector(
            ["remote"], multiple=False
        ),
        vol.Optional(
            "power_command",
            **_suggested(data.get("power_command")),
        ): selector.TextSelector(),
        vol.Required(
            "volume_mode", default=VOLUME_MODE_NONE, **_suggested(data.get("volume_mode"))
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=VOLUME_MODES,
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="volume_mode",
            )
        ),
        vol.Optional("volume_entity", **_suggested(data.get("volume_entity"))): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="media_player")
        ),
        vol.Optional(
            "volume_up_entity", **_suggested(data.get("volume_up_entity"))
        ): _entities_selector(["script", "scene"], multiple=False),
        vol.Optional(
            "volume_down_entity", **_suggested(data.get("volume_down_entity"))
        ): _entities_selector(["script", "scene"], multiple=False),
    }

    # 媒体按键绑定（分类下有电视设备才出现）
    if data.get("devices"):
        fields[
            vol.Optional("media_commands", **_suggested(data.get("media_commands")))
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=MEDIA_COMMANDS,
                multiple=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="media_command",
            )
        )

    # select 实体的按键→选项绑定（绑定了 select 实体才出现；
    # 实体状态暂时不可用时回退用已存的选项，避免绑定被静默清掉）
    stored_select_options = data.get("select_options") or {}
    for entity_id in data.get("select_entities") or []:
        stored = stored_select_options.get(entity_id)
        options = _select_entity_options(hass, entity_id)
        if not options and stored:
            options = [str(o) for o in stored]
        if not options:
            continue
        fields[
            vol.Optional(f"{SELECT_OPTIONS_PREFIX}{entity_id}", **_suggested(stored))
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options,
                multiple=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

    return vol.Schema(fields)


def _tv_schema_keys(role: str, hass, data: dict[str, Any]) -> vol.Schema:
    """第三步：F4-F11 物理按键绑定（每键 = 遥控实体 + 指令）"""
    bindings = data.get("key_bindings") or {}
    fields: dict[Any, Any] = {}
    for key in FKEYS:
        binding = bindings.get(key) or {}
        fields[
            vol.Optional(f"{key}_entity", **_suggested(binding.get("entity_id")))
        ] = _entities_selector(["remote"], multiple=False)
        fields[
            vol.Optional(f"{key}_command", **_suggested(binding.get("command")))
        ] = selector.TextSelector()
    return vol.Schema(fields)


def _tv_merge_controls(user_input: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """controls 提交合并：select_options:: 字段组装为 select_options 字典"""
    merged = {k: v for k, v in user_input.items() if not k.startswith(SELECT_OPTIONS_PREFIX)}
    select_options = dict(data.get("select_options") or {})
    for key, value in user_input.items():
        if key.startswith(SELECT_OPTIONS_PREFIX):
            entity_id = key.split("::", 1)[1]
            if value:
                select_options[entity_id] = value
            else:
                select_options.pop(entity_id, None)
    if select_options:
        merged["select_options"] = select_options
    return merged


def _tv_merge_keys(user_input: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """keys 提交合并：F 键字段组装为 key_bindings 字典"""
    merged: dict[str, Any] = {}
    bindings = dict(data.get("key_bindings") or {})
    for key in FKEYS:
        entity_id = user_input.get(f"{key}_entity")
        command = user_input.get(f"{key}_command") or ""
        if entity_id or command:
            bindings[key] = {"entity_id": entity_id, "command": command}
        else:
            bindings.pop(key, None)
    if bindings:
        merged["key_bindings"] = bindings
    return merged


def _tv_merge_step(role: str, user_input: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """TV 分类按步骤角色分发合并逻辑"""
    if role == "controls":
        return _tv_merge_controls(user_input, data)
    if role == "keys":
        return _tv_merge_keys(user_input, data)
    return dict(user_input)


def _tv_build_schema(role: str, hass, data: dict[str, Any]) -> vol.Schema:
    """TV 分类按步骤角色分发表单"""
    if role == "controls":
        return _tv_schema_controls(role, hass, data)
    if role == "keys":
        return _tv_schema_keys(role, hass, data)
    return _tv_schema_user(role, hass, data)


# ====================== 通用分类 ======================


def _schema_devices(domain: str) -> Callable[[str, Any, dict], vol.Schema]:
    """设备类分类：media_player / light / fan / climate / switch"""

    def _build(role: str, hass, data: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("devices", **_suggested(data.get("devices"))): _devices_selector(
                    domain
                ),
            }
        )

    return _build


def _schema_cover() -> Callable[[str, Any, dict], vol.Schema]:
    """窗帘分类（含窗帘接口类型）"""

    def _build(role: str, hass, data: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("devices", **_suggested(data.get("devices"))): _devices_selector(
                    "cover"
                ),
                vol.Required(
                    "curtain_type", default=CURTAIN_TYPE_CURTAIN, **_suggested(data.get("curtain_type"))
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=CURTAIN_TYPES,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="curtain_type",
                    )
                ),
            }
        )

    return _build


def _schema_switch_monitor() -> Callable[[str, Any, dict], vol.Schema]:
    """开关监控分类"""

    def _build(role: str, hass, data: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("devices", **_suggested(data.get("devices"))): _devices_selector(
                    "switch"
                ),
                vol.Required("device_types", **_suggested(data.get("device_types"))): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=MONITOR_DEVICE_TYPES,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

    return _build


def _schema_scene() -> Callable[[str, Any, dict], vol.Schema]:
    """场景/脚本分类：场景和脚本没有设备，直接绑实体"""

    def _build(role: str, hass, data: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("entities", **_suggested(data.get("entities"))): _entities_selector(
                    ["scene", "script"]
                ),
                vol.Required(
                    "mode", default=SCENE_MODE_IMMEDIATE, **_suggested(data.get("mode"))
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=SCENE_MODES,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="scene_mode",
                    )
                ),
                vol.Optional("text_color", **_suggested(data.get("text_color"))): selector.TextSelector(),
                vol.Optional("image_path", **_suggested(data.get("image_path"))): selector.TextSelector(),
            }
        )

    return _build


def _schema_entities(domains: list[str] | None) -> Callable[[str, Any, dict], vol.Schema]:
    """实体类分类：weather / host（通常无设备，直接绑实体）"""

    def _build(role: str, hass, data: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("entities", **_suggested(data.get("entities"))): _entities_selector(
                    domains
                ),
            }
        )

    return _build


CARD_TYPES: dict[str, CardTypeSpec] = {
    CARD_TV: CardTypeSpec(
        subentry_type=CARD_TV,
        steps=["user", "controls", "keys"],
        build_schema=_tv_build_schema,
        merge_step=_tv_merge_step,
        build_title=lambda hass, d: category_label(hass, CARD_TV),
    ),
    CARD_MEDIA_PLAYER: CardTypeSpec(
        subentry_type=CARD_MEDIA_PLAYER,
        steps=["user"],
        build_schema=_schema_devices("media_player"),
        merge_step=_merge_identity,
        build_title=lambda hass, d: category_label(hass, CARD_MEDIA_PLAYER),
    ),
    CARD_LIGHT: CardTypeSpec(
        subentry_type=CARD_LIGHT,
        steps=["user"],
        build_schema=_schema_devices("light"),
        merge_step=_merge_identity,
        build_title=lambda hass, d: category_label(hass, CARD_LIGHT),
    ),
    CARD_FAN: CardTypeSpec(
        subentry_type=CARD_FAN,
        steps=["user"],
        build_schema=_schema_devices("fan"),
        merge_step=_merge_identity,
        build_title=lambda hass, d: category_label(hass, CARD_FAN),
    ),
    CARD_CLIMATE: CardTypeSpec(
        subentry_type=CARD_CLIMATE,
        steps=["user"],
        build_schema=_schema_devices("climate"),
        merge_step=_merge_identity,
        build_title=lambda hass, d: category_label(hass, CARD_CLIMATE),
    ),
    CARD_COVER: CardTypeSpec(
        subentry_type=CARD_COVER,
        steps=["user"],
        build_schema=_schema_cover(),
        merge_step=_merge_identity,
        build_title=lambda hass, d: category_label(hass, CARD_COVER),
    ),
    CARD_SWITCH: CardTypeSpec(
        subentry_type=CARD_SWITCH,
        steps=["user"],
        build_schema=_schema_devices("switch"),
        merge_step=_merge_identity,
        build_title=lambda hass, d: category_label(hass, CARD_SWITCH),
    ),
    CARD_SCENE: CardTypeSpec(
        subentry_type=CARD_SCENE,
        steps=["user"],
        build_schema=_schema_scene(),
        merge_step=_merge_identity,
        build_title=lambda hass, d: category_label(hass, CARD_SCENE),
    ),
    CARD_WEATHER: CardTypeSpec(
        subentry_type=CARD_WEATHER,
        steps=["user"],
        build_schema=_schema_entities(["weather"]),
        merge_step=_merge_identity,
        build_title=lambda hass, d: category_label(hass, CARD_WEATHER),
    ),
    CARD_HOST: CardTypeSpec(
        subentry_type=CARD_HOST,
        steps=["user"],
        # host 分类在 RosCard 中接受任意实体（信息展示类）
        build_schema=_schema_entities(None),
        merge_step=_merge_identity,
        build_title=lambda hass, d: category_label(hass, CARD_HOST),
    ),
    CARD_SWITCH_MONITOR: CardTypeSpec(
        subentry_type=CARD_SWITCH_MONITOR,
        steps=["user"],
        build_schema=_schema_switch_monitor(),
        merge_step=_merge_identity,
        build_title=lambda hass, d: category_label(hass, CARD_SWITCH_MONITOR),
    ),
}
