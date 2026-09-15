from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.helpers import storage, config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.components import websocket_api
import voluptuous as vol
import asyncio
from datetime import datetime
import json
import glob
import os
import logging
from .const import (
    DOMAIN,
    HARMONY_CONF_PATTERN,
    BROADLINK_STORAGE_PREFIX,
    BROADLINK_STORAGE_SUFFIX,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.library"
PLATFORMS = ["remote", "select", "button"]
MAX_BROADLINK_DEVICES = 100
MAX_BROADLINK_KEYS_PER_DEVICE = 200
MAX_BROADLINK_CODE_LENGTH = 16_384
BROADLINK_BROADCAST_SERIAL = "broadlink_broadcast"

# ====================== 1. 核心初始化 ======================
async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    _LOGGER.info("[Startup] async_setup called! config=%s", config)
    
    # 延迟导入，避免模块加载时的依赖问题
    from homeassistant.components.http import HomeAssistantView
    from homeassistant.components import websocket_api

    class HarmonyConfigView(HomeAssistantView):
        """提供 Harmony Hub 配置文件的 HTTP API 端点

        在 HA 配置目录中查找 harmony_*.conf 文件并返回其 JSON 内容。
        供 Lovelace 卡片获取 Harmony Hub 的活动、设备和命令列表。
        """
        url = "/api/astrion/harmony_config"
        name = "api:astrion:harmony_config"
        requires_auth = True

        def __init__(self, hass):
            self.hass = hass

        def _find_all_harmony_confs(self):
            """在配置目录中寻找所有 harmony_*.conf 文件"""
            config_dir = self.hass.config.config_dir
            pattern = os.path.join(config_dir, HARMONY_CONF_PATTERN)
            files = sorted(glob.glob(pattern))
            return files

        async def get(self, request):
            """处理 GET 请求 — 返回所有 Harmony Hub 的配置文件内容"""
            conf_files = await self.hass.async_add_executor_job(self._find_all_harmony_confs)

            if not conf_files:
                return self.json(
                    {"error": "No harmony_*.conf files found in config directory"},
                    status_code=404
                )

            try:
                def read_all_files():
                    hubs = []
                    for path in conf_files:
                        _LOGGER.info("Reading Harmony config file: %s", path)
                        with open(path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        basename = os.path.basename(path)
                        hub_name = basename.replace("harmony_", "").replace(".conf", "")
                        hubs.append({
                            "hub_name": hub_name,
                            "source_file": basename,
                            "config": data
                        })
                    return hubs

                hubs = await self.hass.async_add_executor_job(read_all_files)
                return self.json({"hubs": hubs})

            except Exception as e:
                _LOGGER.error("Failed to read Harmony config file: %s", e)
                return self.json({"error": str(e)}, status_code=500)

    hass.http.register_view(HarmonyConfigView(hass))
    
    # 【关键】注册 WebSocket 处理器（必须在 config_entry 存在之前就注册，否则首次添加集成时 App 消息无处理器）
    _LOGGER.info("[Startup] Registering WebSocket handlers…")
    websocket_api.async_register_command(hass, websocket_submit_pair_data)
    websocket_api.async_register_command(hass, websocket_get_device_codes)
    websocket_api.async_register_command(hass, websocket_get_harmony_config)
    websocket_api.async_register_command(hass, websocket_get_broadlink_codes)
    websocket_api.async_register_command(hass, websocket_get_cards)
    _LOGGER.info("[Startup] WebSocket handlers registered successfully!")

    # 监听 APK 通过 fire_event 上报的导航列表
    async def _handle_navigate_list_upload(event):
        """APK 上报导航列表 → 更新 store → 通知 select 实体"""
        data = event.data
        serial = data.get("serial_number")
        pages = data.get("pages", [])
        if not serial or not pages:
            return
        library = hass.data.setdefault(DOMAIN, {}).setdefault("library", {"devices": {}})
        gateways = library.setdefault("gateways", {})
        gateways.setdefault(serial, {})["pages"] = pages
        await hass.data[DOMAIN]["store"].async_save(library)
        _LOGGER.info("Gateway %s navigate list uploaded: %s", serial, pages)
        hass.bus.async_fire(f"{DOMAIN}/navigate_list_updated", {
            "serial_number": serial,
            "pages": pages,
        })

    hass.bus.async_listen(f"{DOMAIN}/navigate_list_upload", _handle_navigate_list_upload)

    # 监听 APK 上报的页面访问（反向触发自动化）
    async def _handle_page_visited(event):
        """APK 页面访问上报

        - source="user": 用户主动切换 → A-Select 触发自动化
        - source="auto": HA 命令的回包 → A-Select 静默等待复位
        """
        data = event.data
        serial = data.get("serial_number")
        page = data.get("page")
        source = data.get("source", "user")
        if not serial or not page:
            return
        # 存储当前页
        library = hass.data.setdefault(DOMAIN, {}).setdefault("library", {"devices": {}})
        gateways = library.setdefault("gateways", {})
        known_pages = gateways.get(serial, {}).get("pages", [])
        if page not in known_pages:
            _LOGGER.warning(
                "Gateway %s ignored page_visited value not in uploaded list: %s",
                serial,
                page,
            )
            return
        gateways.setdefault(serial, {})["current_page"] = page
        await hass.data[DOMAIN]["store"].async_save(library)
        _LOGGER.info("Gateway %s page visited: %s (source=%s)", serial, page, source)
        # A-Select: 是否触发自动化取决于 source  |  B-Select: 同步当前值
        refs = hass.data.get(DOMAIN, {}).get("_selects", {}).get(serial, {})
        nav = refs.get("navigate")
        sc  = refs.get("scene")
        if nav:
            await nav.trigger_from_apk(page, source)
        if sc:
            sc.sync_from_apk(page)

    hass.bus.async_listen(f"{DOMAIN}/page_visited", _handle_page_visited)
    
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """初始化配置条目"""
    store = storage.Store(hass, STORAGE_VERSION, STORAGE_KEY)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["store"] = store
    hass.data[DOMAIN]["library"] = await store.async_load() or {"devices": {}}

    # 冗余注册 WebSocket 处理器（如果 async_setup 已注册，这是无操作）
    websocket_api.async_register_command(hass, websocket_submit_pair_data)
    websocket_api.async_register_command(hass, websocket_get_device_codes)
    websocket_api.async_register_command(hass, websocket_get_harmony_config)
    websocket_api.async_register_command(hass, websocket_get_broadlink_codes)
    websocket_api.async_register_command(hass, websocket_get_cards)

    # 加载遥控器实体平台 + 网关场景选择器
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 注册红外服务
    hass.services.async_register(DOMAIN, "discover_all", handle_discover_all)
    hass.services.async_register(
        DOMAIN, "send_command", handle_send_command,
        schema=vol.Schema({
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("button"): cv.string,
        })
    )

    # 卡片子条目（原 RosCard 卡片）变更时同步设备并通知 App 重新拉取
    # 注意：update listener 必须是协程函数，HA 会把其返回值调度为任务
    async def _notify_cards_updated(hass_: HomeAssistant, entry_: ConfigEntry) -> None:
        _async_sync_category_devices(hass_, entry_)
        ir_subentry_id = _async_ensure_ir_subentry(hass_, entry_)
        if ir_subentry_id:
            _async_sync_ir_devices(hass_, entry_, ir_subentry_id)
        gateway_subentry_id = _async_ensure_gateway_subentry(hass_, entry_)
        if gateway_subentry_id:
            _async_attach_gateway_device(hass_, entry_, gateway_subentry_id)
        hass_.bus.async_fire(f"{DOMAIN}/cards_updated", {"entry_id": entry_.entry_id})

    entry.async_on_unload(entry.add_update_listener(_notify_cards_updated))

    # 首次加载时同步一次分类设备
    _async_sync_category_devices(hass, entry)

    # 默认「红外」子条目：确保存在，并把红外设备归属到它下面
    ir_subentry_id = _async_ensure_ir_subentry(hass, entry)
    if ir_subentry_id:
        _async_sync_ir_devices(hass, entry, ir_subentry_id)

    # 默认「网关」子条目：网关设备本身也归组
    gateway_subentry_id = _async_ensure_gateway_subentry(hass, entry)
    if gateway_subentry_id:
        _async_attach_gateway_device(hass, entry, gateway_subentry_id)
    return True

# ====================== 2. 卸载与设备删除 ======================
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and len(hass.config_entries.async_entries(DOMAIN)) == 1:
        hass.services.async_remove(DOMAIN, "discover_all")
        hass.services.async_remove(DOMAIN, "send_command")
    return unload_ok

async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """允许在设备页面通过 UI 删除红外设备 / 分类联动设备"""
    # 分类联动设备（cat:<subentry_id>:<device_id>）：从 UI 删除 = 从分类中移除该设备
    for ident_domain, ident_value in device_entry.identifiers:
        if ident_domain == DOMAIN and ident_value.startswith(CATEGORY_DEVICE_PREFIX):
            _, subentry_id, device_id = ident_value.split(":", 2)
            subentry = config_entry.subentries.get(subentry_id)
            bound = (subentry.data.get("devices") or []) if subentry else []
            if subentry is not None and device_id in bound:
                new_data = dict(subentry.data)
                new_data["devices"] = [d for d in bound if d != device_id]
                hass.config_entries.async_update_subentry(
                    entry=config_entry, subentry=subentry, data=new_data
                )
                _LOGGER.info(
                    "Category device %s removed from subentry %s via integration page",
                    device_id,
                    subentry_id,
                )
            # 设备已不在分类里时也允许删除（残留联动设备清理）
            return True

    if DOMAIN not in hass.data or "library" not in hass.data[DOMAIN]:
        return False
    library = hass.data[DOMAIN]["library"]
    devices = library.setdefault("devices", {})
    serial = None

    for ident in device_entry.identifiers:
        if ident[0] == DOMAIN:
            serial = ident[1]
            break

    if serial and serial in devices:
        # 只允许删除属于当前网关条目的设备，避免跨网关误删
        if devices[serial].get("parent_app_serial") != config_entry.data.get("app_serial"):
            return False
        devices.pop(serial, None)
        await hass.data[DOMAIN]["store"].async_save(library)
        
        new_data = dict(config_entry.data)
        if "devices" in new_data and serial in new_data["devices"]:
            new_data["devices"].pop(serial, None)
            hass.config_entries.async_update_entry(config_entry, data=new_data)
            
        _LOGGER.info("Successfully removed device via integration page: %s", serial)
        return True
    return False

# ====================== 3. 服务触发逻辑 ======================
@callback
def handle_discover_all(call: ServiceCall) -> None:
    call.hass.bus.async_fire(f"{DOMAIN}/pair_request", {
        "code": "DISCOVER_ALL",
        "mode": "discover_all",
        "timestamp": datetime.utcnow().isoformat(),
        "source": "service_call"
    })

@callback
def handle_send_command(call: ServiceCall) -> None:
    """红外实体直接使用父网关串号发送控制命令"""
    hass = call.hass
    entity_id = call.data["entity_id"]
    ir_code = call.data["button"]

    # 获取实体状态对象
    state = hass.states.get(entity_id)
    if not state:
        _LOGGER.warning("Entity does not exist: %s", entity_id)
        return

    # 检查是否是自定义红外实体
    domain, _ = entity_id.split(".", 1)
    if domain != "remote":
        _LOGGER.debug("Not an IR entity: %s", entity_id)
        return

    # 从实体属性获取父级网关串号
    parent_serial = state.attributes.get("parent_app_serial")
    packet_format = None
    if not parent_serial:
        # Broadlink remotes are not bound to an HA100.  The App protocol still
        # requires a non-empty serial_number, so use a stable broadcast marker;
        # Android deliberately does not route Broadlink commands by this value.
        from homeassistant.helpers import entity_registry as er
        entry = er.async_get(hass).async_get(entity_id)
        if entry and entry.platform == "broadlink":
            parent_serial = BROADLINK_BROADCAST_SERIAL
            packet_format = "broadlink"
        else:
            _LOGGER.warning("IR entity %s has no parent gateway serial", entity_id)
            return

    # 获取按键 IR 码
    buttons = state.attributes.get("supported_keys", {})
    # 按键 IR 码直接用传入的 button 名称
    actual_ir_code = ir_code  # 或根据你的 IR 映射字典转换

    # 直接发送控制命令，不再判断网关是否存在
    event_data = {
        "serial_number": parent_serial,
        "button": actual_ir_code,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if packet_format:
        event_data["format"] = packet_format
    hass.bus.async_fire(f"{DOMAIN}/control_command", event_data)
    _LOGGER.info("IR control command sent: %s -> parent gateway %s -> button %s",
                 entity_id, parent_serial, actual_ir_code)

# ====================== 4. WebSocket 接口定义 ======================
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/submit_pair_data",
    vol.Required("code"): cv.string,
    vol.Required("data"): dict,
})
@websocket_api.async_response
async def websocket_submit_pair_data(hass: HomeAssistant, connection, msg):
    """App 上报配对数据的接口（存入发现列表，等待用户在配置流程中选择）"""
    _LOGGER.info("[Pair] Message received! Raw message: %s", str(msg)[:500])
    
    data = msg["data"]
    app_serial = data.get("serial_number")
    _LOGGER.info("[Pair] serial_number=%s, model=%s, full data=%s", app_serial, data.get("model"), str(data)[:300])
    
    if not app_serial:
        _LOGGER.warning(
            "[Pair Error] App reported data missing serial_number, cannot store in discovery list. "
            "Full message: %s", str(msg)[:500]
        )
        connection.send_error(msg["id"], "missing_serial", "Missing serial_number")
        return

    entries = hass.config_entries.async_entries(DOMAIN)
    
    # 查重：App 已存在则无需再次发现
    for entry in entries:
        if entry.data.get("app_serial") == app_serial:
            _LOGGER.info("[Pair] App serial %s already has a config entry, skipping duplicate pairing", app_serial)
            connection.send_result(msg["id"], {"success": True, "message": "App already exists, no need to pair again"})
            return

    # 存入发现列表，等待用户在配置流程中选择
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("discovered_gateways", {})
    
    model = data.get("model") or "IR Gateway"
    hass.data[DOMAIN]["discovered_gateways"][app_serial] = {
        "serial_number": app_serial,
        "model": model,
        "name": data.get("name", ""),
    }
    
    # 触发 bus 事件，方便外部监听（如配置流程自动刷新）
    hass.bus.async_fire(f"{DOMAIN}/gateway_discovered", {
        "serial": app_serial,
        "model": model,
    })
    
    _LOGGER.info("Discovered new gateway: Smart Remote:%s SN:%s (saved to pending list)", model, app_serial)
    connection.send_result(msg["id"], {
        "success": True,
        "serial": app_serial,
        "message": "Gateway added to pending list, please confirm in HA configuration"
    })

@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/get_device_codes",
    vol.Required("entity_id"): cv.entity_id,
})
@websocket_api.async_response
async def websocket_get_device_codes(hass: HomeAssistant, connection, msg):
    """供 App 按需拉取完整红外码本的接口（增强版）"""
    entity_id = msg["entity_id"]
    library = hass.data[DOMAIN].get("library", {})
    devices = library.get("devices", {})
    
    # 获取搜索用的 key（转为小写）
    search_key = entity_id.replace("remote.", "").lower()
    target_data = None

    # 第一步：尝试直接通过小写化的 key 匹配
    for s, d in devices.items():
        stored_key = d.get("device_key", "").lower()
        if stored_key == search_key or s.lower() in search_key:
            target_data = d
            break

    # 第二步：如果第一步失败，通过实体注册表找 unique_id (即 serial)
    if not target_data:
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(hass)
        entry = registry.async_get(entity_id)
        # 只要找到了 unique_id，就一定能从 library 里拿出来
        if entry and entry.unique_id in devices:
            target_data = devices[entry.unique_id]

    if not target_data:
        connection.send_error(msg["id"], "not_found", f"Entity not found: {entity_id}")
        return
        
    connection.send_result(msg["id"], {
        "entity_id": entity_id,
        "serial_number": target_data.get("serial_number"),
        "parent_app_serial": target_data.get("parent_app_serial"),
        "ir_codes": target_data.get("buttons", {})
    })


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/get_harmony_config",
    vol.Optional("entity_id"): cv.string,
})
@websocket_api.async_response
async def websocket_get_harmony_config(hass: HomeAssistant, connection, msg):
    """通过 WebSocket 获取 Harmony Hub 的配置文件内容

    如果传入 entity_id，根据实体的 unique_id 精确匹配对应的配置文件；
    如果不传，返回所有配置文件（兼容旧版）。
    """
    try:
        config_dir = hass.config.config_dir
        pattern = os.path.join(config_dir, HARMONY_CONF_PATTERN)
        all_files = sorted(glob.glob(pattern))

        # 如果传了 entity_id，通过实体注册表查 unique_id 来匹配
        target_unique_id = None
        entity_id = msg.get("entity_id")
        if entity_id:
            from homeassistant.helpers import entity_registry as er
            registry = er.async_get(hass)
            entry = registry.async_get(entity_id)
            if entry:
                target_unique_id = entry.unique_id
                _LOGGER.debug("Harmony entity %s → unique_id: %s", entity_id, target_unique_id)

        hubs = []
        for path in all_files:
            basename = os.path.basename(path)
            file_id = basename.replace("harmony_", "").replace(".conf", "")

            # 如果指定了 unique_id，只匹配对应文件
            if target_unique_id and file_id != target_unique_id:
                continue

            _LOGGER.info("Reading Harmony config file: %s", path)
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            hubs.append({
                "hub_name": file_id,
                "source_file": basename,
                "config": data
            })

        connection.send_result(msg["id"], {"hubs": hubs})

    except Exception as e:
        _LOGGER.error("Failed to read Harmony config file: %s", e)
        connection.send_error(msg["id"], "read_error", str(e))


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/get_broadlink_codes",
    vol.Required("entity_id"): cv.entity_id,
})
@websocket_api.async_response
async def websocket_get_broadlink_codes(hass: HomeAssistant, connection, msg):
    """Return normalized Broadlink learned IR/RF codes for one remote entity.

    The caller can only supply an entity_id.  The exact storage file is derived
    from its registry unique_id, so no caller-controlled path is ever read.
    """
    entity_id = msg["entity_id"]
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if not entry:
        connection.send_error(msg["id"], "entity_not_found", "Entity was not found")
        return

    if entity_id.split(".", 1)[0] != "remote" or entry.platform != "broadlink" or not entry.unique_id:
        connection.send_error(msg["id"], "invalid_entity", "Entity is not a Broadlink remote")
        return

    unique_id = entry.unique_id
    storage_dir = os.path.realpath(os.path.join(hass.config.config_dir, ".storage"))
    source_file = f"{BROADLINK_STORAGE_PREFIX}{unique_id}{BROADLINK_STORAGE_SUFFIX}"
    source_path = os.path.realpath(os.path.join(storage_dir, source_file))

    # A malformed unique_id must not turn into a path traversal.  commonpath is
    # used instead of a string prefix to handle similarly named sibling paths.
    try:
        safe_path = os.path.commonpath([storage_dir, source_path]) == storage_dir
    except ValueError:
        safe_path = False
    if not safe_path:
        _LOGGER.warning("Rejected unsafe Broadlink storage path for entity %s", entity_id)
        connection.send_error(msg["id"], "invalid_entity", "Invalid entity unique_id")
        return

    def _read_and_normalize():
        if not os.path.isfile(source_path):
            raise FileNotFoundError(source_file)
        with open(source_path, "r", encoding="utf-8") as storage_file:
            payload = json.load(storage_file)

        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise ValueError("data is not an object")

        normalized = {}
        for device_name, device_codes in payload["data"].items():
            if len(normalized) >= MAX_BROADLINK_DEVICES:
                raise ValueError("too many devices")
            if not isinstance(device_name, str) or not isinstance(device_codes, dict):
                raise ValueError("invalid device entry")

            keys = {}
            for key_name, code in device_codes.items():
                if len(keys) >= MAX_BROADLINK_KEYS_PER_DEVICE:
                    raise ValueError("too many keys")
                if not isinstance(key_name, str) or not isinstance(code, str):
                    raise ValueError("invalid key entry")
                if len(code) > MAX_BROADLINK_CODE_LENGTH:
                    raise ValueError("code exceeds maximum length")
                keys[key_name] = code
            normalized[device_name] = keys
        return normalized

    try:
        devices = await hass.async_add_executor_job(_read_and_normalize)
    except FileNotFoundError:
        _LOGGER.info("Broadlink code file not found for entity %s: %s", entity_id, source_file)
        connection.send_error(msg["id"], "file_not_found", "Broadlink code file was not found")
    except (json.JSONDecodeError, ValueError) as err:
        _LOGGER.warning("Invalid Broadlink storage for entity %s (%s)", entity_id, type(err).__name__)
        connection.send_error(msg["id"], "invalid_storage", "Broadlink storage is invalid")
    except OSError as err:
        _LOGGER.warning("Unable to read Broadlink storage for entity %s (%s)", entity_id, type(err).__name__)
        connection.send_error(msg["id"], "read_error", "Unable to read Broadlink storage")
    else:
        connection.send_result(msg["id"], {
            "entity_id": entity_id,
            "unique_id": unique_id,
            "source_file": source_file,
            "devices": devices,
        })


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/get_cards",
    vol.Optional("entry_id"): cv.string,
})
@websocket_api.async_response
async def websocket_get_cards(hass: HomeAssistant, connection, msg):
    """App 拉取分类列表（原 RosCard 卡片配置，现在来自集成子条目）

    每个 subentry = 遥控器上的一个分类，data.devices 为该分类下的 HA 设备。
    本接口会把设备解析为分类对应域的实体列表（entities 字段）一并返回，
    App 收到 astrion/cards_updated 事件后应重新调用本接口刷新 UI。
    """
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from .cards import CARD_DOMAINS, SUBENTRY_TYPE_IR, SUBENTRY_TYPE_GATEWAY

    # 仅用于 HA 侧设备归组、不作为分类卡片下发的子条目类型
    hidden_subentry_types = {SUBENTRY_TYPE_IR, SUBENTRY_TYPE_GATEWAY}

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    cards = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if msg.get("entry_id") and entry.entry_id != msg["entry_id"]:
            continue
        for subentry in entry.subentries.values():
            if subentry.subentry_type in hidden_subentry_types:
                # 红外子条目：红外设备走网关自有协议；
                # 网关子条目：归属网关设备本身。均不作为分类卡片下发给 App
                continue
            config = dict(subentry.data)
            card = {
                "entry_id": entry.entry_id,
                "subentry_id": subentry.subentry_id,
                "card_type": subentry.subentry_type,
                "title": subentry.title,
                "config": config,
            }
            # 分类下的设备 → 解析为该分类域的实体，App 可直接渲染
            device_ids = config.get("devices") or []
            if device_ids:
                domain = CARD_DOMAINS.get(subentry.subentry_type)
                entity_ids = []
                for device_id in device_ids:
                    for ent in er.async_entries_for_device(ent_reg, device_id):
                        if domain is not None and ent.domain == domain:
                            entity_ids.append(ent.entity_id)
                card["entities"] = entity_ids
            cards.append(card)
    connection.send_result(msg["id"], {"api_version": 1, "cards": cards})


# ====================== 6. 分类设备同步（与红外设备相同的设备注册表机制） ======================

# 分类联动设备标识前缀：cat:<subentry_id>:<device_id>
CATEGORY_DEVICE_PREFIX = "cat:"


@callback
def _async_sync_category_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """把分类子条目绑定的设备同步为真正的 HA 设备

    与红外设备一样进设备注册表：挂在网关设备下（via_device），
    并通过 config_subentry_id 归属到对应子条目，集成页面按分类分组展示。
    用户在分类里增删设备 / 删除子条目后重新同步。
    """
    from .cards import CARD_TYPES, CARD_MODELS

    dev_reg = dr.async_get(hass)
    serial = entry.data.get("app_serial")

    # 期望的设备集合：{(subentry_id, device_id): (显示名, 型号)}
    wanted: dict[tuple[str, str], tuple[str, str]] = {}
    for subentry in entry.subentries.values():
        if subentry.subentry_type not in CARD_TYPES:
            continue
        model = CARD_MODELS.get(subentry.subentry_type, subentry.subentry_type)
        for device_id in subentry.data.get("devices") or []:
            source = dev_reg.async_get(device_id)
            name = (source.name_by_user or source.name) if source else None
            wanted[(subentry.subentry_id, device_id)] = (name or device_id, model)

    # 现有的分类联动设备：{identifier: DeviceEntry}
    existing: dict[str, DeviceEntry] = {}
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        for domain, value in device.identifiers:
            if domain == DOMAIN and value.startswith(CATEGORY_DEVICE_PREFIX):
                existing[value] = device

    # 创建缺失的，并刷新名称/型号（用户手动改名过的设备 HA 会保留 name_by_user）
    for (subentry_id, device_id), (name, model) in wanted.items():
        identifier = f"{CATEGORY_DEVICE_PREFIX}{subentry_id}:{device_id}"
        if identifier in existing:
            continue
        kwargs: dict = {
            "config_entry_id": entry.entry_id,
            "config_subentry_id": subentry_id,
            "identifiers": {(DOMAIN, identifier)},
            "name": name,
            "manufacturer": "Astrion",
            "model": model,
        }
        if serial:
            kwargs["via_device"] = (DOMAIN, serial)
        dev_reg.async_get_or_create(**kwargs)
        _LOGGER.info("Category device created: %s (%s) in subentry %s", name, model, subentry_id)

    # 名称变化同步到已存在的设备
    for (subentry_id, device_id), (name, model) in wanted.items():
        identifier = f"{CATEGORY_DEVICE_PREFIX}{subentry_id}:{device_id}"
        device = existing.get(identifier)
        if device is None:
            continue
        updates: dict = {}
        if not device.name_by_user and device.name != name:
            updates["name"] = name
        if device.model != model:
            updates["model"] = model
        if updates:
            dev_reg.async_update_device(device.id, **updates)

    # 清理已不在任何分类里的联动设备
    valid_identifiers = {
        f"{CATEGORY_DEVICE_PREFIX}{subentry_id}:{device_id}"
        for subentry_id, device_id in wanted
    }
    for identifier, device in existing.items():
        if identifier not in valid_identifiers:
            dev_reg.async_remove_device(device.id)
            _LOGGER.info("Category device removed: %s", identifier)


# ====================== 7. 默认「红外」子条目（红外设备的归组分） ======================


@callback
def _async_ensure_ir_subentry(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """确保网关条目下存在默认「红外」子条目，返回其 subentry_id

    配对流程会随条目一起创建；老用户升级后首次加载时在这里补建，
    保证红外设备始终有归组分，不会"不属于任何分组"。
    """
    from .cards import SUBENTRY_TYPE_IR, category_label

    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_IR:
            return subentry.subentry_id

    subentry = ConfigSubentry(
        data={},
        subentry_type=SUBENTRY_TYPE_IR,
        title=category_label(hass, SUBENTRY_TYPE_IR),
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    _LOGGER.info(
        "Default IR subentry created for gateway %s", entry.data.get("app_serial")
    )
    return subentry.subentry_id


@callback
def _async_sync_ir_devices(hass: HomeAssistant, entry: ConfigEntry, ir_subentry_id: str) -> None:
    """把本网关的红外设备挂到默认「红外」子条目下

    只处理尚未归属任何子条目的设备，用户手动调整过分组的不动。
    """
    library = (hass.data.get(DOMAIN, {}).get("library") or {})
    devices = library.get("devices") or {}
    serial = entry.data.get("app_serial")
    if not serial:
        return
    dev_reg = dr.async_get(hass)
    for device_serial, info in devices.items():
        if info.get("parent_app_serial") != serial:
            continue
        # 红外设备的注册表 device_id 是 ULID，需按 identifiers（DOMAIN, 序列号）查找
        device = dev_reg.async_get_device(identifiers={(DOMAIN, device_serial)})
        if device is None or device.config_subentry_id:
            continue
        dev_reg.async_update_device(device.id, add_config_subentry_id=ir_subentry_id)
        _LOGGER.info("IR device %s attached to default IR subentry", device_serial)


@callback
def _async_ensure_gateway_subentry(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """确保网关条目下存在默认「网关」子条目，返回其 subentry_id

    网关设备上挂着导航事件/导航动作/数据同步等功能实体，
    归组后用户能在集成页面直接找到它们。
    """
    from .cards import SUBENTRY_TYPE_GATEWAY, category_label

    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TYPE_GATEWAY:
            return subentry.subentry_id

    subentry = ConfigSubentry(
        data={},
        subentry_type=SUBENTRY_TYPE_GATEWAY,
        title=category_label(hass, SUBENTRY_TYPE_GATEWAY),
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    return subentry.subentry_id


@callback
def _async_attach_gateway_device(hass: HomeAssistant, entry: ConfigEntry, gateway_subentry_id: str) -> None:
    """把网关设备本身挂到默认「网关」子条目下（已归属的不动）"""
    serial = entry.data.get("app_serial")
    if not serial:
        return
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, serial)})
    if device is None or device.config_subentry_id:
        return
    dev_reg.async_update_device(device.id, add_config_subentry_id=gateway_subentry_id)

