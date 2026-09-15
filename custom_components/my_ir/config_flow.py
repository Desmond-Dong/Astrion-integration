from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryFlow
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import callback
import voluptuous as vol
from .const import DOMAIN, CONF_CONVERSATION_AGENT
from .cards import (
    CARD_TV,
    CARD_TYPES,
    OWNED_KEYS,
    SUBENTRY_TYPE_IR,
    SUBENTRY_TYPE_GATEWAY,
    category_label,
    merge_into_existing,
)
from homeassistant.helpers import selector
import logging
import json
import asyncio
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://astrion.lifex360.com/api/v1"
# 按键控制，喇叭播放，电量，屏幕唤醒集成到HA中，在


async def _get_preferred_agent_id(hass) -> str:
    """取当前 Assist 管线偏好的对话代理（assist_pipeline 未加载时返回空）"""
    try:
        from homeassistant.components.assist_pipeline.pipeline import async_get_pipeline

        pipeline = async_get_pipeline(hass)
        return pipeline.conversation_engine if isinstance(pipeline.conversation_engine, str) else ""
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Unable to resolve preferred assist pipeline: %r", err)
        return ""


def _agent_schema(hass, default_agent: str) -> vol.Schema:
    """对话代理选择表单（与 cn_im_hub 相同的交互）"""
    return vol.Schema(
        {
            vol.Required(
                CONF_CONVERSATION_AGENT, default=default_agent
            ): selector.ConversationAgentSelector(
                selector.ConversationAgentSelectorConfig(language=hass.config.language)
            )
        }
    )

class MyIRConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """配置流程 (首次添加集成网关时触发)"""
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """启用选项流，并在集成卡片上显示‘配置’按钮"""
        return MyIROptionsFlowHandler(config_entry)

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: config_entries.ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """集成页面「添加子条目」— 每种原 RosCard 卡片一个子条目类型"""
        return SUBENTRY_HANDLERS

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """添加集成：先选择一个对话代理（Conversation Agent），选完直接创建条目

        不强制先配对网关——创建的条目即可管理分类与设备；
        网关配对在需要时通过条目的「配置」按钮进行。
        """
        # 【关键】确保 WebSocket 处理器已注册（async_setup 可能未被调用）
        from homeassistant.components import websocket_api
        from . import websocket_submit_pair_data, websocket_get_device_codes, websocket_get_harmony_config
        websocket_api.async_register_command(self.hass, websocket_submit_pair_data)
        websocket_api.async_register_command(self.hass, websocket_get_device_codes)
        websocket_api.async_register_command(self.hass, websocket_get_harmony_config)
        _LOGGER.info("[config_flow] WebSocket handler registered during config flow")

        preferred_agent = await _get_preferred_agent_id(self.hass)
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=_agent_schema(self.hass, preferred_agent),
            )

        agent_id = str(user_input.get(CONF_CONVERSATION_AGENT, "")).strip()
        if not agent_id:
            return self.async_show_form(
                step_id="user",
                data_schema=_agent_schema(self.hass, preferred_agent),
                errors={"base": "agent_id_required"},
            )

        # 直接创建：不强制配对网关，记录所选对话代理
        _LOGGER.info("[config_flow] Standalone entry created (no gateway pairing), agent=%s", agent_id)
        return self.async_create_entry(
            title="Astrion Home",
            data={CONF_CONVERSATION_AGENT: agent_id},
        )

    async def async_step_discover(self, user_input: dict | None = None) -> FlowResult:
        """显示已发现的网关列表，或重试搜索"""
        discovered = self.hass.data.get(DOMAIN, {}).get("discovered_gateways", {})

        if user_input is not None:
            selected_serial = user_input.get("gateway")
            if selected_serial and selected_serial in discovered:
                gw_data = discovered[selected_serial]
                model = gw_data.get("model", "IR Gateway")
                # 创建条目，填入 App 信息；同时创建默认「红外」「网关」子条目，
                # 让所有设备从一开始就有归组分
                return self.async_create_entry(
                    title=f"Smart Remote:{model} SN:{selected_serial}",
                    data={
                        "app_serial": selected_serial,
                        "app_model": model
                    },
                    subentries=[
                        {
                            "subentry_type": SUBENTRY_TYPE_IR,
                            "data": {},
                            "title": category_label(self.hass, SUBENTRY_TYPE_IR),
                            "unique_id": None,
                        },
                        {
                            "subentry_type": SUBENTRY_TYPE_GATEWAY,
                            "data": {},
                            "title": category_label(self.hass, SUBENTRY_TYPE_GATEWAY),
                            "unique_id": None,
                        },
                    ],
                )

        _LOGGER.info("[discover] Final check — discovered_gateways=%s, len=%d", dict(discovered), len(discovered))
        
        # 检查是否有发现的网关
        if discovered:
            _LOGGER.info("[discover] Gateways found! Showing selection list, count=%d", len(discovered))
            options = [
                {"value": s, "label": f"Smart Remote:{d.get('model','IR Gateway')} SN:{s}"}
                for s, d in discovered.items()
            ]
            return self.async_show_form(
                step_id="discover",
                data_schema=vol.Schema({
                    vol.Required("gateway"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, mode="list")
                    )
                }),
                description_placeholders={
                    "count": str(len(discovered))
                }
            )
        else:
            _LOGGER.info("[discover] No gateways found, showing retry screen")
            # 无发现，显示重试界面
            return self.async_show_form(
                step_id="discover_retry",
                data_schema=vol.Schema({
                    vol.Optional("retry", default=False): selector.BooleanSelector(
                        selector.BooleanSelectorConfig()
                    )
                })
            )

    async def async_step_discover_retry(self, user_input: dict | None = None) -> FlowResult:
        """处理重试表单的提交——重新广播发现"""
        if user_input is None:
            return self.async_show_form(
                step_id="discover_retry",
                data_schema=vol.Schema({
                    vol.Optional("retry", default=False): selector.BooleanSelector(
                        selector.BooleanSelectorConfig()
                    )
                })
            )

        if user_input.get("retry"):
            self.hass.bus.async_fire(f"{DOMAIN}/pair_request", {
                "code": "DISCOVER_ALL",
                "mode": "discover_all",
                "timestamp": datetime.utcnow().isoformat(),
                "source": "config_flow"
            })
            _LOGGER.info("[Retry] User requested re-discovery, waiting 8s…")
            await asyncio.sleep(8)

            discovered = self.hass.data.get(DOMAIN, {}).get("discovered_gateways", {})
            _LOGGER.info("[Retry] Discovered %d gateways", len(discovered))

            if discovered:
                options = [
                    {"value": s, "label": f"Smart Remote:{d.get('model','IR Gateway')} SN:{s}"}
                    for s, d in discovered.items()
                ]
                return self.async_show_form(
                    step_id="discover",
                    data_schema=vol.Schema({
                        vol.Required("gateway"): selector.SelectSelector(
                            selector.SelectSelectorConfig(options=options, mode="list")
                        )
                    }),
                    description_placeholders={
                        "count": str(len(discovered))
                    }
                )

        # 仍然无发现，或用户未勾选重试——再次显示重试界面
        if not user_input.get("retry"):
            _LOGGER.info("[Retry] User did not check 'Retry', staying on retry screen")
        else:
            _LOGGER.warning("[Retry] No gateways found after retry, please check if App is online")

        return self.async_show_form(
            step_id="discover_retry",
            data_schema=vol.Schema({
                vol.Optional("retry", default=False): selector.BooleanSelector(
                    selector.BooleanSelectorConfig()
                )
            })
        )


# ====================== 选项流 (点击“配置”按钮后触发) ======================
class MyIROptionsFlowHandler(config_entries.OptionsFlow):
    """API驱动的新设备添加流程（不需要头认证）"""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._config_entry = config_entry
        # 步骤1: 库
        self._depot_id = None
        self._depot_name = None
        self._depot_id_map = {}
        # 步骤2: 设备分类
        self._category_id = None
        self._category_name = None
        self._cat_id_map = {}
        # 步骤3: 品牌
        self._brand_id = None
        self._brand_name = None
        self._brand_id_map = {}
        # 步骤4: 驱动列表（分页收集）
        self._all_drives = []
        self._drive_label_map = {}

    # ------------------------------------------------------------------
    #  API 请求工具（无认证头）
    # ------------------------------------------------------------------

    async def _api_get(self, path: str, params: dict = None) -> dict | list:
        """向API发送无认证的GET请求"""
        session = async_get_clientsession(self.hass)
        url = f"{API_BASE_URL}{path}"
        try:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                _LOGGER.error("API request failed [%s] %s: %s", resp.status, url, await resp.text()[:200])
        except Exception as e:
            _LOGGER.error("API request exception %s: %s", url, e)
        return {}

    @staticmethod
    def _extract_list(resp, default_key="rows"):
        """从API响应中提取列表数据，兼容多种返回格式"""
        if isinstance(resp, list):
            return resp
        if isinstance(resp, dict):
            # 尝试常见的包裹key
            for key in ("data", default_key, "list", "records", "result", "items"):
                val = resp.get(key)
                if isinstance(val, list):
                    return val
            # 如果code/msg包装，递归找第一个list值
            for v in resp.values():
                if isinstance(v, list):
                    return v
        return []

    # ------------------------------------------------------------------
    #  入口
    # ------------------------------------------------------------------

    async def async_step_init(self, user_input=None) -> FlowResult:
        """点击配置按钮后触发：未配对网关时先补配对，否则进入红外库"""
        if not self.config_entry.data.get("app_serial"):
            return await self.async_step_pair_gateway()
        return await self.async_step_depot()

    # ------------------------------------------------------------------
    #  补配网关：为「直接创建」的条目在需要红外功能时配对网关
    # ------------------------------------------------------------------

    async def async_step_pair_gateway(self, user_input=None) -> FlowResult:
        """广播发现网关 → 选择 → 写入 app_serial → 进入红外库"""
        if user_input is None:
            self.hass.data.setdefault(DOMAIN, {}).pop("discovered_gateways", None)
            self.hass.bus.async_fire(f"{DOMAIN}/pair_request", {
                "code": "DISCOVER_ALL",
                "mode": "discover_all",
                "timestamp": datetime.utcnow().isoformat(),
                "source": "options_flow"
            })
            _LOGGER.info("[Pair] Broadcast pair_request from options flow, waiting 8s…")
            await asyncio.sleep(8)
            discovered = self.hass.data.get(DOMAIN, {}).get("discovered_gateways", {})
            if not discovered:
                return self.async_abort(reason="no_gateway_found")
            self._pair_map = discovered
            options = [
                {"value": s, "label": f"Smart Remote:{d.get('model', 'IR Gateway')} SN:{s}"}
                for s, d in discovered.items()
            ]
            return self.async_show_form(
                step_id="pair_gateway",
                data_schema=vol.Schema({
                    vol.Required("gateway"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, mode="list")
                    )
                }),
            )

        selected = user_input.get("gateway")
        if not selected or selected not in self._pair_map:
            return await self.async_step_pair_gateway()

        gw = self._pair_map[selected]
        new_data = dict(self.config_entry.data)
        new_data["app_serial"] = selected
        new_data["app_model"] = gw.get("model", "IR Gateway")
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        _LOGGER.info("[Pair] Gateway %s paired to existing entry via options flow", selected)
        return await self.async_step_depot()

    # ------------------------------------------------------------------
    #  步骤1: 选择库
    # ------------------------------------------------------------------

    async def async_step_depot(self, user_input=None) -> FlowResult:
        """第一步：从API获取库列表，用户选择"""
        if user_input is not None:
            selected = user_input["depot_id"]
            if selected not in self._depot_id_map:
                return await self.async_step_depot()
            self._depot_id = self._depot_id_map[selected]
            self._depot_name = selected
            _LOGGER.info("Selected depot: %s (%s)", self._depot_name, self._depot_id)
            return await self.async_step_category()

        data = await self._api_get("/rc/app/depot/list")
        depots = self._extract_list(data)

        if not depots:
            return self.async_abort(reason="cloud_fetch_failed")

        self._depot_id_map = {}
        self._depot_opts = []
        for d in depots:
            did = str(d.get("depotId") or d.get("id"))
            dname = d.get("depotName") or d.get("name") or "Unknown"
            if did:
                value = dname
                label = dname
                if dname == "红外":
                    value = "IR"
                    label = "IR"
                self._depot_opts.append({"value": value, "label": label})
                self._depot_id_map[value] = did

        return self.async_show_form(
            step_id="depot",
            data_schema=vol.Schema({
                vol.Required("depot_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._depot_opts, mode="dropdown", custom_value=True)
                )
            }),
            description_placeholders={}
        )

    # ------------------------------------------------------------------
    #  步骤2: 选择设备分类
    # ------------------------------------------------------------------

    async def async_step_category(self, user_input=None) -> FlowResult:
        """第二步：从API获取设备分类列表，用户选择"""
        if user_input is not None:
            selected = user_input["category_id"]
            if selected not in self._cat_id_map:
                return await self.async_step_category()
            self._category_id = self._cat_id_map[selected]
            self._category_name = selected
            _LOGGER.info("Selected category: %s (%s)", self._category_name, self._category_id)
            return await self.async_step_brand()

        data = await self._api_get("/rc/app/category/list")
        categories = self._extract_list(data)

        if not categories:
            return self.async_abort(reason="cloud_fetch_failed")

        self._cat_id_map = {}
        self._cat_opts = []
        for c in categories:
            cid = str(c.get("categoryId") or c.get("id") or c.get("category_id"))
            cname = c.get("categoryName") or c.get("name") or "Unknown"
            if cid:
                self._cat_opts.append({"value": cname, "label": cname})
                self._cat_id_map[cname] = cid

        return self.async_show_form(
            step_id="category",
            data_schema=vol.Schema({
                vol.Required("category_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._cat_opts, mode="dropdown", custom_value=True)
                )
            }),
            description_placeholders={}
        )

    # ------------------------------------------------------------------
    #  步骤3: 选择品牌
    # ------------------------------------------------------------------

    async def async_step_brand(self, user_input=None) -> FlowResult:
        """第三步：从API获取品牌列表，用户选择"""
        if user_input is not None:
            selected = user_input["brand_id"]
            if selected not in self._brand_id_map:
                return await self.async_step_brand()
            self._brand_id = self._brand_id_map[selected]
            self._brand_name = selected
            _LOGGER.info("Selected brand: %s (%s)", self._brand_name, self._brand_id)
            return await self.async_step_drive_list()

        data = await self._api_get("/rc/app/brand/all")
        brands = self._extract_list(data)

        if not brands:
            return self.async_abort(reason="cloud_fetch_failed")

        self._brand_id_map = {}
        self._brand_opts = []
        for b in brands:
            bid = str(b.get("brandId") or b.get("id"))
            bname = b.get("brandName") or b.get("name") or "Unknown"
            if bid:
                self._brand_opts.append({"value": bname, "label": bname})
                self._brand_id_map[bname] = bid

        return self.async_show_form(
            step_id="brand",
            data_schema=vol.Schema({
                vol.Required("brand_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._brand_opts, mode="dropdown", custom_value=True)
                )
            }),
            description_placeholders={}
        )

    # ------------------------------------------------------------------
    #  步骤4: 分页查询所有驱动 → 用户选择
    # ------------------------------------------------------------------

    async def async_step_drive_list(self, user_input=None) -> FlowResult:
        """第四步：分页获取驱动列表，用户选择一条"""
        if user_input is not None:
            selected = user_input["drive_index"]
            if selected not in self._drive_label_map:
                return await self.async_step_drive_list()
            return await self._save_drive(self._drive_label_map[selected])

        # 首次进入：分页收集所有驱动，查到最后一页为止
        self._all_drives = []
        page_size = 200
        page_num = 1

        while True:
            resp = await self._api_get("/rc/app/drive/list", {
                "source": "0",
                "categoryId": self._category_id,
                "depotId": self._depot_id,
                "brandId": self._brand_id,
                "pageSize": str(page_size),
                "pageNum": str(page_num),
            })

            rows = resp.get("rows", [])
            if not rows:
                break

            self._all_drives.extend(rows)
            _LOGGER.info("Drive list page %d: got %d entries", page_num, len(rows))

            # 如果这一页返回少于 pageSize 条，说明已到最后一页，停止
            if len(rows) < page_size:
                break

            page_num += 1

        if not self._all_drives:
            _LOGGER.warning("No drives found: category=%s, depot=%s, brand=%s",
                            self._category_id, self._depot_id, self._brand_id)
            return self.async_abort(reason="no_drives_found")

        # 可搜索的下拉框（用 label 文本作为 value，combo box 才能显示名称）
        self._drive_opts = []
        self._drive_label_map = {}
        for i, d in enumerate(self._all_drives):
            brand_name = d.get("brand", {}).get("brandName", "")
            model = d.get("modelName", "Unknown Model")
            official = "Official" if d.get("isOfficial") == 1 else "Custom"
            label = f"{model}"
            if brand_name:
                label = f"{brand_name} {model}"
            label += f" [{official}]"
            # 如果标签重复，追加区别后缀
            key = label
            while key in self._drive_label_map:
                key = f"{label} #{i}"
            self._drive_opts.append({"value": key, "label": label})
            self._drive_label_map[key] = d

        return self.async_show_form(
            step_id="drive_list",
            data_schema=vol.Schema({
                vol.Required("drive_index"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self._drive_opts, mode="dropdown", custom_value=True)
                )
            }),
            description_placeholders={
                "count": str(len(self._all_drives))
            }
        )

    # ------------------------------------------------------------------
    #  保存：获取驱动详情 → 解析 data.commands → 写入库 → 重载
    # ------------------------------------------------------------------

    async def _save_drive(self, drive_data: dict) -> FlowResult:
        """获取驱动详情，解析data中的commands，保存为红外remote实体"""
        drive_id = drive_data.get("driveId")
        if not drive_id:
            _LOGGER.error("Drive data missing driveId")
            return self.async_abort(reason="cloud_fetch_failed")

        # 1. 获取驱动详情（可能包装在 {code, msg, data: {...}} 中）
        detail = await self._api_get(f"/rc/app/drive/{drive_id}")
        _LOGGER.debug("Drive %s detail raw response: %s", drive_id, str(detail)[:300])

        commands = {}

        if detail:
            # 尝试穿透常见 API 包装层找到实际的 drive 对象
            drive_obj = detail
            if "code" in detail and isinstance(detail.get("data"), dict):
                # 包装格式: { code, msg, data: { categoryId, ..., data: "<json>", ... } }
                drive_obj = detail["data"]

            # 从 drive 对象中提取 data 字段（JSON 字符串）
            data_field = drive_obj.get("data", "")

            if isinstance(data_field, str) and data_field.strip():
                try:
                    data_obj = json.loads(data_field)
                    commands = data_obj.get("commands", {})
                except json.JSONDecodeError:
                    _LOGGER.warning("Drive %s data field is not valid JSON: %s…", drive_id, data_field[:120])
            elif isinstance(data_field, dict):
                # data 字段本身已经是字典对象
                commands = data_field.get("commands", {})

        if not commands:
            _LOGGER.warning("Could not extract commands from drive %s, creating remote with empty keys", drive_id)

        # 3. 构建设备信息
        library = self.hass.data[DOMAIN].setdefault("library", {"devices": {}})
        parent_app_serial = self.config_entry.data.get("app_serial", "unknown")

        # 唯一序列号（融合父网关串号 + driveId）
        serial = f"IR_{parent_app_serial}_{drive_id}"

        model_name = drive_data.get("modelName", "Unknown Model")
        brand_name = drive_data.get("brand", {}).get("brandName", "")
        device_name = f"Sanytron {brand_name} {model_name}" if brand_name else f"Sanytron {model_name}"

        device_info = {
            "serial_number": serial,
            "device_key": f"sanytron_{drive_id}_{parent_app_serial}",
            "name": device_name,
            "buttons": commands,
            "source": "api_drive",
            "parent_app_serial": parent_app_serial,
        }

        # 4. 写入 HA store
        library["devices"][serial] = device_info
        await self.hass.data[DOMAIN]["store"].async_save(library)

        # 5. 更新 config_entry 数据
        new_data = dict(self.config_entry.data)
        new_data.setdefault("devices", {})
        new_data["devices"][serial] = device_info
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

        # 6. 重载配置条目以创建新的remote实体
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )

        _LOGGER.info("Successfully mounted IR device: %s (%d keys)", device_name, len(commands))
        return self.async_create_entry(title=f"Mounted: {device_name}", data={})


# ====================== 子条目流程（原 RosCard 卡片 → 集成页面单独添加） ======================

_TV_REQUIRED_FIELDS = ("devices", "remote_entities", "select_entities")


def _validate_card_data(subentry_type: str, role: str, data: dict) -> str | None:
    """表单无法表达的跨字段校验，返回错误 key 或 None"""
    if subentry_type == CARD_TV and role == "user":
        # TV 卡片至少要绑定一个控制来源
        if not any(data.get(f) for f in _TV_REQUIRED_FIELDS):
            return "no_entities"
    return None


class CardSubentryFlowHandler(ConfigSubentryFlow):
    """卡片子条目流程基类

    每个子条目 = 远端 UI 上的一张卡片。卡片类型在 cards.CARD_TYPES 中
    声明自己的步骤链（如 TV: user → controls → keys），本基类按链路
    逐步收集并合并数据，添加与重新配置共用同一套步骤。
    """

    _subentry_type: str

    @property
    def _spec(self):
        return CARD_TYPES[self._subentry_type]

    @staticmethod
    def _role(step_id: str) -> str:
        """步骤名 → 角色名（重新配置入口复用 user 角色的表单与校验）"""
        return "user" if step_id == "reconfigure" else step_id

    def _steps(self) -> list[str]:
        """当前流程的完整步骤链"""
        steps = self._spec.steps
        if getattr(self, "_editing", False):
            return ["reconfigure", *steps[1:]]
        return list(steps)

    async def _async_process_step(self, step_id: str, user_input: dict | None):
        """处理链中的一个步骤：校验 → 合并 → 下一步 / 收尾"""
        spec = self._spec
        steps = self._steps()
        role = self._role(step_id)
        errors = {}
        if user_input is not None:
            error = _validate_card_data(self._subentry_type, role, user_input)
            if error is None:
                # 先移除该步骤拥有的旧字段再写入，保证清空的字段被正确删除
                for key in OWNED_KEYS.get(role, ()):
                    self._data.pop(key, None)
                self._data.update(spec.merge_step(role, user_input, self._data))
                # 添加流程：同分类已有子条目时，第一步提交后直接把设备并入，
                # 不产生重复子条目（每个分类全局只有一个子条目）
                if role == "user" and not getattr(self, "_editing", False):
                    entry = self._get_entry()
                    existing = entry.get_subentries_of_type(self._subentry_type)
                    if existing:
                        merged = merge_into_existing(
                            dict(existing[0].data), self._data, self._subentry_type
                        )
                        self._async_update(entry, existing[0], data=merged)
                        return self.async_abort(reason="merged_into_existing")
                index = steps.index(step_id)
                if index + 1 < len(steps):
                    return await self._async_process_step(steps[index + 1], None)
                return self._async_finish()
            errors["base"] = error
        schema = spec.build_schema(role, self.hass, self._data)
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    def _async_finish(self):
        """步骤链走完：创建或更新子条目（标题自动取设备 Friendly Name）"""
        spec = self._spec
        title = spec.build_title(self.hass, self._data)
        if getattr(self, "_editing", False):
            self._async_update(
                self._get_entry(),
                self._subentry,
                data=self._data,
                title=title,
            )
            return self.async_abort(reason="reconfigure_successful")
        return self.async_create_entry(title=title, data=self._data)

    async def async_step_user(self, user_input: dict | None = None):
        """集成页面「添加子条目」— 步骤链入口"""
        self._data = {}
        return await self._async_process_step("user", user_input)

    async def async_step_controls(self, user_input: dict | None = None):
        """TV 卡片第二步：电源 / 音量 / 媒体按键 / select 选项绑定"""
        return await self._async_process_step("controls", user_input)

    async def async_step_keys(self, user_input: dict | None = None):
        """TV 卡片第三步：F4-F11 物理按键绑定"""
        return await self._async_process_step("keys", user_input)

    async def async_step_reconfigure(self, user_input: dict | None = None):
        """集成页面子条目上的「重新配置」— 复用步骤链，从已有数据回填"""
        self._editing = True
        self._subentry = self._get_reconfigure_subentry()
        self._data = dict(self._subentry.data)
        return await self._async_process_step("reconfigure", user_input)


def _make_card_subentry_class(subentry_type: str) -> type[CardSubentryFlowHandler]:
    """为每种卡片类型生成对应的子条目流程类"""
    return type(
        f"{subentry_type.capitalize()}CardSubentryFlowHandler",
        (CardSubentryFlowHandler,),
        {"_subentry_type": subentry_type},
    )


SUBENTRY_HANDLERS: dict[str, type[ConfigSubentryFlow]] = {
    subentry_type: _make_card_subentry_class(subentry_type)
    for subentry_type in CARD_TYPES
}
