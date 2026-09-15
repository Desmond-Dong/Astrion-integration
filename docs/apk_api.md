# Astrion 集成分类/设备 UI — APK 对接文档

> 适用版本：Astrion Home integration **v2.0.0+**（`replace_roscard` 分支）
> 本文档描述 APK 如何获取用户在「设置 → 设备与服务 → Astrion Home」里
> 以**子条目（subentry）**形式添加的分类与设备，替代旧的 RosCard 仪表盘卡片方案。

---

## 1. 架构变化（先读这个）

**旧方案（已淘汰）**：用户在 Lovelace 仪表盘手写 `aiks-*` 卡片，APK 通过 WebView
加载仪表盘渲染，卡片数据分散在仪表盘 YAML 里。

**新方案**：每个 subentry = 遥控器上的一个**分类**（TV、灯光、窗帘……），
一个分类下可以添加**多个 HA 设备**。每种分类在每台网关上**只有一个子条目**：
重复添加同一分类时，新选的设备会自动并入已有子条目；
子条目标题就是分类名（如「灯光」/ "Light"）。分类数据保存在 HA 原生 config entry
subentries 中（`core.config_entries` 存储，随集成自动持久化、备份）。

```text
用户在集成页面添加分类（选分类 → 选设备，名称自动取 Friendly Name）
        │
        ▼
Astrion Home 集成（subentry 持久化）
        │  WebSocket: astrion/get_cards
        ▼
APK 拉取分类列表（含解析好的实体列表）→ 本地渲染 UI
        │
        │  变更时集成广播 astrion/cards_updated 事件，APK 重新拉取
        ▼
用户操作 → APK 通过 WebSocket 调用 HA 服务（call_service）
```

**APK 不再需要**：解析 Lovelace 配置、加载 RosCard JS、WebView 渲染卡片。
所有 UI 数据来自本文档的一个 WebSocket 接口 + 一个事件。

---

## 2. 前置条件（与现有配对流程一致，无新要求）

- APK 通过 HA WebSocket API 连接：`ws://<host>:8123/api/websocket`
- 认证：Long-Lived Access Token（`auth` 消息，管理员账号创建）
- 这套连接 APK 已经在用（配对用的 `astrion/submit_pair_data` 就是同一条连接），
  分类拉取直接复用，无需新连接。

---

## 3. 获取分类列表：`astrion/get_cards`

### 请求

```json
{
  "id": 1,
  "type": "astrion/get_cards"
}
```

可选参数 `entry_id`（string）：只返回某个 Astrion 网关条目下的分类。
不传则返回**所有**网关条目下的全部分类（多遥控器场景一次拉全量）。

### 响应

```json
{
  "id": 1,
  "type": "result",
  "success": true,
  "result": {
    "api_version": 1,
    "cards": [
      {
        "entry_id": "01J...",
        "subentry_id": "01K...",
        "card_type": "light",
        "title": "Light 1, 卧室灯…",
        "config": {
          "devices": ["01L...", "01M..."]
        },
        "entities": ["light.a", "light.b"]
      },
      {
        "entry_id": "01J...",
        "subentry_id": "01N...",
        "card_type": "tv",
        "title": "客厅电视",
        "config": { "devices": ["01O..."], "tv_type": "android_tv", "...": "见 §5" },
        "entities": ["media_player.tv"]
      },
      {
        "entry_id": "01J...",
        "subentry_id": "01P...",
        "card_type": "scene",
        "title": "电影模式, 离家",
        "config": { "entities": ["scene.movie", "script.leave"], "mode": "immediate" }
      }
    ]
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `api_version` | int | 接口版本，当前固定 `1` |
| `cards[].entry_id` | string | 所属 Astrion 网关条目 ID（多网关区分用） |
| `cards[].subentry_id` | string | 分类子条目 ID（重新配置/删除定位用，APK 一般不用） |
| `cards[].card_type` | string | 分类类型，见下表 |
| `cards[].title` | string | **分类显示名**。集成自动生成：单设备 = 设备 Friendly Name（用户改名优先）；多设备 = 前 3 个名称拼接 + `…`。直接显示，不要再拼"卡片"等后缀 |
| `cards[].config` | object | 分类原始配置，结构按 card_type 见 §4 / §5 |
| `cards[].entities` | string[] | **仅当分类绑定了设备时出现**：集成已把设备解析为该分类对应域的实体 ID 列表，APK 直接拿来渲染和调用服务。场景/天气/主机分类没有此字段（实体直接在 `config.entities` 里） |

### `card_type` 与 `entities` 解析规则

| card_type | 绑定方式 | `entities` 解析域 | 说明 |
| --- | --- | --- | --- |
| `tv` | 设备 | `media_player` | 电视设备（媒体播放器）；每个设备可含多实体，全部返回 |
| `media_player` | 设备 | `media_player` | |
| `light` | 设备 | `light` | |
| `fan` | 设备 | `fan` | |
| `climate` | 设备 | `climate` | |
| `cover` | 设备 | `cover` | |
| `switch` | 设备 | `switch` | |
| `switch_monitor` | 设备 | `switch` | |
| `scene` | 实体 | —（无此字段） | 场景/脚本没有设备，实体在 `config.entities` |
| `weather` | 实体 | —（无此字段） | |
| `host` | 实体 | —（无此字段） | |

> 实现细节：解析用 HA 设备注册表（device → 其名下实体，按上表域过滤）。
> 同一设备名下的其它域实体（如电视设备挂着的 `remote.*`）不会混进来。
>
> 另外：分类绑定的每个设备同时会在 HA 侧创建一个真正的设备条目
> （挂在网关设备下、归属到对应子条目），用户在 HA 设备页面删除它时
> 集成会自动把它从分类里移除——这只影响 HA 侧展示，`get_cards`
> 的数据以分类配置为准，APK 逻辑不受影响。
>
> 红外设备（通过网关配对/红外库添加的那些）不经过 `get_cards` 下发，
> 仍走网关自有协议；HA 侧它们自动归属到默认的「红外」子条目下。
> 网关设备本身则归属到默认的「网关」子条目。这两个子条目仅用于
> HA 侧设备归组，都不会出现在 `get_cards` 的返回里。

---

## 4. 各分类 `config` 结构

所有字段**都可能缺省**（表单里没填就不存在），APK 一律按可选处理。

### 设备类分类（light / fan / climate / switch / media_player）

```json
{ "devices": ["<device_id>", "..."] }
```

### `cover`（窗帘）

```json
{ "devices": ["..."], "curtain_type": "curtain" }
```

`curtain_type`：`curtain`（普通窗帘）| `blind`（百叶窗）

### `switch_monitor`（开关监控）

```json
{ "devices": ["..."], "device_types": ["switch", "light"] }
```

`device_types` 取值：`switch` `light` `fan` `climate` `cover` `media_player` `humidifier`

### `scene`（场景/脚本）

```json
{
  "entities": ["scene.movie", "script.leave"],
  "mode": "immediate",
  "text_color": "#ffffff",
  "image_path": "..."
}
```

`mode`：`immediate`（立即执行）| `delayed`（延迟执行）| `popup`（弹窗询问）
`text_color` / `image_path` 可选，行样式。

### `weather` / `host`

```json
{ "entities": ["weather.home"] }
```

`host` 的实体不限域。

### `tv`（电视，三步配置的完整结构）

```json
{
  "devices": ["<media_player 设备 id>"],
  "tv_type": "android_tv",
  "remote_version": "ha100a",
  "remote_entities": ["remote.ir1"],
  "select_entities": ["select.inputs"],
  "background_path": "...",

  "power_entity": "remote.ir1",
  "power_command": "",

  "volume_mode": "updown",
  "volume_entity": "media_player.x",
  "volume_up_entity": "script.vol_up",
  "volume_down_entity": "script.vol_down",

  "media_commands": ["turn_on", "media_play", "volume_up"],
  "select_options": { "select.inputs": ["HDMI1", "TV"] },

  "key_bindings": {
    "F4": { "entity_id": "remote.ir1", "command": "" },
    "F5": { "entity_id": "remote.bl1", "command": "客厅设备/电源" },
    "F8": { "entity_id": "remote.harmony", "command": "Watch TV" }
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `devices` | 电视设备（media_player），`entities` 字段已解析 |
| `tv_type` | `android_tv` \| `harmony` \| `broadlink`（决定 UI 风格与指令默认语义） |
| `remote_version` | 遥控器硬件版本：`x9` \| `ha100a` \| `ha100b`（决定 F4–F11 键面含义） |
| `remote_entities` | 控制来源：红外遥控器实体（可多个） |
| `select_entities` | 控制来源：选择器实体（信号源切换等） |
| `background_path` | 背景图地址（可选） |
| `power_entity` + `power_command` | 电源键绑定；`command` 留空 = 按码库解析 |
| `volume_mode` | `none` \| `single`（单媒体实体，用 `volume_entity`）\| `updown`（音量加/减分开，用 `volume_up_entity` / `volume_down_entity`） |
| `media_commands` | 要在 UI 上显示的媒体按键，取值见 §6 映射表 |
| `select_options` | 按键→选项绑定：`{实体 ID: [选项...]}`，每个选项渲染一个按键 |
| `key_bindings` | 物理按键绑定，键名固定 `F4`–`F11`；`command` 语义见 §6.3 |

F 键含义按 `remote_version`：

| 键 | HA100A | HA100B |
| --- | --- | --- |
| F4 | 灯 | 快退 |
| F5 | 窗帘 | 播放/暂停 |
| F6 | 音乐 | 停止 |
| F7 | 空调 | 快进 |
| F8–F11 | 自定义 1–4 | 自定义 1–4 |

---

## 5. 变更通知：`astrion/cards_updated` 事件

用户在集成页面**添加 / 重新配置 / 删除分类**、或修改网关条目配置时，集成会广播：

```json
{
  "id": "...",
  "type": "event",
  "event": {
    "event_type": "astrion/cards_updated",
    "data": { "entry_id": "01J..." }
  }
}
```

APK 处理：WebSocket `subscribe_events` 订阅 `astrion/cards_updated`
（`{ "id": 9, "type": "subscribe_events", "event_type": "astrion/cards_updated" }`），
收到后**重新调用 `astrion/get_cards`** 全量刷新即可（数据量小，无需做增量）。

---

## 6. 控制绑定实体（用户按下按键后 APK 做什么）

分类里解析出的 `entities` 都是标准 HA 实体，APK 通过 WebSocket `call_service`
调用对应域的标准服务即可（与 RosCard 时代 `hass.callService` 等价）。

### 6.1 标准实体服务

| 域 | 常用服务 |
| --- | --- |
| `light` | `light.turn_on`（支持 `brightness_pct` / `rgb_color` / `color_temp_kelvin`）、`light.turn_off` |
| `fan` | `fan.turn_on`（`percentage` / `preset_mode`）、`fan.turn_off` |
| `climate` | `climate.set_temperature`、`climate.set_hvac_mode`、`climate.set_fan_mode`、`climate.set_preset_mode` |
| `cover` | `cover.open_cover` / `close_cover` / `stop_cover`、`cover.set_cover_position` |
| `switch` | `switch.turn_on` / `turn_off` |
| `media_player` | 见下方媒体按键映射 |
| `scene` | `scene.turn_on` |
| `script` | `script.turn_on` |
| `weather` | 只读，`get_states` 取状态渲染 |

### 6.2 媒体按键映射（TV 分类的 `media_commands`）

| media_command 值 | 对应服务调用 |
| --- | --- |
| `turn_on` | `media_player.turn_on` |
| `turn_off` | `media_player.turn_off` |
| `media_play` | `media_player.media_play` |
| `media_pause` | `media_player.media_pause` |
| `volume_up` | `media_player.volume_up` |
| `volume_down` | `media_player.volume_down` |
| `volume_mute_true` | `media_player.volume_mute` + `{"is_volume_muted": true}` |
| `volume_mute_false` | `media_player.volume_mute` + `{"is_volume_muted": false}` |

目标实体：TV 分类的 `entities`（电视设备下的 media_player 实体）。

### 6.3 红外指令：`remote_entities` / `key_bindings` / `power_entity` 的 command 语义

Astrion 红外遥控实体是标准 `remote` 实体，发送用：

```json
{ "id": 20, "type": "call_service",
  "domain": "remote", "service": "send_command",
  "target": { "entity_id": "remote.ir1" },
  "service_data": { "command": "电源" } }
```

`command`（也就是 subentry 里存的 `key_bindings.*.command` / `power_command`）
按绑定实体的类型有三种语义：

| 绑定实体类型 | command 语义 | 码库查询接口 |
| --- | --- | --- |
| Astrion 红外遥控器 | **按键名**（如 `电源`、`音量+`）或原生红外长码；**留空 = 用按键名本身**（F4 等）去码库解析 | WebSocket `astrion/get_device_codes` |
| 博联 Broadlink | `"设备名/按键名"`（斜杠分隔） | WebSocket `astrion/get_broadlink_codes` |
| Harmony hub | 活动/设备名 | WebSocket `astrion/get_harmony_config` |

三个码库接口都是**集成现有接口，格式不变**，APK 按 `entity_id` 查询：

```json
{ "id": 21, "type": "astrion/get_device_codes", "entity_id": "remote.ir1" }
```

```json
{ "id": 22, "type": "astrion/get_broadlink_codes", "entity_id": "remote.bl1" }
```

```json
{ "id": 23, "type": "astrion/get_harmony_config", "entity_id": "remote.harmony" }
```

博联 RF 按键注意：HA100 只有红外，遇到 RF 按键应提示不可用
（判断方式与旧 RosCard 相同）。

### 6.4 select 按键（信号源）

`select_options` 里每个选项一个按键，按下即：

```json
{ "id": 24, "type": "call_service",
  "domain": "select", "service": "select_option",
  "target": { "entity_id": "select.inputs" },
  "service_data": { "option": "HDMI1" } }
```

---

## 7. APK 端推荐实现流程（伪代码）

```text
连接 WebSocket → auth(token) 成功后：

1. subscribe_events("astrion/cards_updated")
2. cards = call "astrion/get_cards"
3. 渲染：
   for card in cards:
     category_name = card.title
     实体列表 = card.entities （设备类分类）
              或 card.config.entities（scene/weather/host）
     按 card_type 渲染分类入口；TV 分类额外读 config 里的
     power/volume/media_commands/select_options/key_bindings 渲染按键面板

4. 收到 "astrion/cards_updated" 事件 → 重新执行步骤 2
5. 用户操作 → 按 §6 调用服务；红外指令先按 §6.3 查码库
```

---

## 8. 与旧 RosCard 字段对照（便于迁移逻辑复用）

| RosCard 卡片字段 | 新位置 |
| --- | --- |
| 卡片 type（aiks-light-card 等） | `card_type`（`light` 等，去掉 `aiks-`/`-card`） |
| 卡片 `entities[].entity_id` | 设备类分类 → `entities`（集成按设备解析）；scene/weather/host → `config.entities` |
| TV 卡 `tv_name` | 不再需要，`title` 自动生成 |
| TV 卡 `tv_type` | `config.tv_type`（值不变） |
| TV 卡 `icon_path` | 已移除（APK 自带分类图标） |
| TV 卡 `entities[].commands`（红外） | `config.key_bindings` + `config.power_entity/power_command`，command 语义不变 |
| 场景卡 `mode` / `text_color` | `config.mode` / `config.text_color`（值不变） |
| 窗帘卡窗帘类型 | `config.curtain_type`（值不变） |
| 统计卡 `monitor_name` / `device_types` | `monitor_name` 已移除；`config.device_types` 不变 |

---

## 9. 注意事项

1. **字段容错**：`config` 里所有键都可能缺失（用户没配置就是没有），APK 按
   optional 处理，不要假设键存在。
2. **`entities` 只在绑定设备的分类上出现**；scene/weather/host 用 `config.entities`。
3. **多网关**：`get_cards` 默认返回所有 Astrion 条目的分类；如需按遥控器区分，
   用 `entry_id` 过滤（每台遥控器知道自己配对的 entry_id）。
4. **旧接口不变**：`astrion/submit_pair_data`、`astrion/navigate_list_upload`、
   `astrion/page_visited`、`astrion/navigate_to`、`astrion/refresh_request`、
   `astrion/control_command` 等网关相关接口与事件全部保持原样。
5. **不要缓存 entity_id 到本地**：实体由集成在 `get_cards` 响应里实时解析，
   每次以响应为准（用户重配分类后设备实体会变）。
