# Astrion Home Assistant Integration

[![HACS Default](https://img.shields.io/badge/HACS-Default-blue.svg)](https://www.hacs.xyz/)
[![GitHub Release](https://img.shields.io/github/v/release/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/releases)
[![GitHub License](https://img.shields.io/github/license/yyqclhy/Astrion-integration)](LICENSE)
[![HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=yyqclhy&repository=Astrion-integration&category=integration)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-Yes-green.svg)](https://github.com/yyqclhy/Astrion-integration/commits/main)
[![GitHub Issues](https://img.shields.io/github/issues/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/issues)
[![GitHub Stars](https://img.shields.io/github/stars/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/stargazers)

# Astrion Home Assistant Integration

**Home Assistant integration for Sanytron Astrion local infrared control and IR device capabilities.**

Astrion Home connects an **Astrion Remote Gateway** to Home Assistant and exposes Astrion's infrared capabilities for use in Home Assistant workflows and Astrion interfaces.

Astrion Home is one component of the broader Astrion software ecosystem.

> **Since v2.0.0, Astrion Home no longer depends on RosCard.**
> The remote-facing UI cards formerly provided by RosCard are now built into Astrion Home as **configuration subentries**, added directly from the Home Assistant integrations page.
> RosCard is deprecated and no longer required.

---

## 🧠 Architecture

Astrion is built around a simple principle:

> **Home Assistant = Brain**
> **Astrion = Physical Interface**
> **Astrion Home = IR Integration + Remote UI Cards**

Home Assistant remains the source of truth for device states, services, scenes, scripts, and automations.

Astrion Home provides the Home Assistant-side connection for Astrion's IR capabilities and manages the remote UI cards as configuration subentries. The Astrion remote pulls the card list from Astrion Home and renders its purpose-built interface.

```text
                         HOME ASSISTANT
                  ┌──────────────────────────┐
                  │                          │
                  │   Entities               │
                  │   States                 │
                  │   Services               │
                  │   Automations / Scenes   │
                  │                          │
                  │          🧠 BRAIN         │
                  └────────────┬─────────────┘
                               │
                               ▼
                  ┌───────────────────────┐
                  │     Astrion Home      │
                  │ IR Gateway            │
                  │ IR Integration        │
                  │ IR Capabilities       │
                  │ Remote UI Cards       │
                  │  (config subentries)  │
                  └────────┬──────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   ASTRION    │
                    │              │
                    │ Touchscreen  │
                    │ Buttons      │
                    │ Local IR     │
                    └──────────────┘
```

### Astrion Home

**Astrion Home** is the Home Assistant integration associated with Astrion's local infrared capabilities.

It provides the Astrion Remote Gateway connection, exposes IR-related capabilities that can be used inside Home Assistant, and manages the cards shown on the Astrion remote as integration subentries.

### Remote UI Cards

The cards displayed on the Astrion remote (TV, media player, lights, climate, scenes, and more) are configured in Home Assistant as **subentries** of the Astrion Home integration.

Each card is added individually from the integration page, and the configuration is delivered to the Astrion remote over the local API. No Lovelace dashboard and no external card package is required.

---

## 📡 What Astrion Home Provides

Astrion Home was introduced alongside **Astrion firmware V1.2.0**, when local infrared control was added.

### Astrion Remote Gateway

The integration connects an Astrion Remote Gateway to Home Assistant.

During configuration, Home Assistant searches for available Astrion Remote Gateways connected to the Home Assistant environment.

Each gateway is identified by the Astrion Remote's **serial number (SN)**.

The SN can be found on Astrion under:

**Settings → About**

### 📺 Local Infrared Control

Astrion includes built-in infrared hardware for controlling compatible traditional equipment such as:

* TVs
* AV receivers
* Media players
* Air conditioners
* Other compatible IR-controlled devices

Astrion Home exposes the relevant IR capability to Home Assistant so it can be used by supported interfaces and Home Assistant workflows.

### 🗃️ IR Device and Code Library

Astrion Home provides access to Sanytron's supported IR device and code library.

Available devices and commands depend on the current library and supported device types.

### 🎛️ Home Assistant Workflows

Astrion IR entities can be used with standard Home Assistant functionality, including:

* Automations
* Scripts
* Scenes
* Helpers
* Other supported actions and workflows

For example:

```text
Movie Night
     │
     ├── TV → Power ON
     ├── AVR → Power ON
     ├── AVR → Select HDMI
     ├── Media Player → Start
     ├── Lights → 20%
     └── Curtains → Closed
```

The automation and orchestration logic remains in Home Assistant.

---

## 🎛️ Remote UI Categories (Subentries)

The remote UI is organized as categories (TV, lights, climate, scenes, …), managed as subentries of the Astrion Home integration.

To add a category:

```text
Home Assistant
      │
      ▼
Settings
      │
      ▼
Devices & services
      │
      ▼
Astrion Home
      │
      ▼
Add subentry
      │
      ▼
Select category
      │
      ▼
Select devices
```

The add flow first asks you to select a **conversation agent** (defaulting to your Assist pipeline's preferred agent) and creates the entry immediately — no gateway pairing is required up front. Gateway pairing remains available anytime via the entry's **Configure** button when you want to use IR devices.

Each category has exactly **one** subentry per gateway. Adding the same category again simply merges the newly selected devices into the existing one — devices can also be added or removed anytime via the subentry's *Reconfigure* option. The subentry is named after the category (e.g. *Light*, *TV*), and every device added to it is registered as a real Home Assistant device under the Astrion integration — linked to the gateway and grouped under its category subentry, so the whole remote configuration is visible and manageable from the devices & services page.

When the gateway is paired, two default subentries are created automatically: **Infrared** (all IR devices from the code library are grouped under it) and **Gateway** (the gateway device itself, which hosts the navigation controls and the data-sync button) — no device is ever left ungrouped.

The following categories are available:

| Category         | Purpose                                                        |
| ---------------- | -------------------------------------------------------------- |
| **TV**           | Bind TV devices to their IR remote control sources, bind power/volume controls, and bind each physical key (F4–F11) to a remote, Broadlink device/key, or Harmony activity |
| **Media player** | Playback control for media players (Apple TV, Android TV, …)   |
| **Light**        | On/off, brightness, color, and color temperature               |
| **Fan**          | Fan speed and state control                                    |
| **Climate**      | Target temperature, HVAC modes, fan modes, and presets         |
| **Cover**        | Curtains and blinds, including the curtain interface type      |
| **Switch**       | Switch state control                                           |
| **Scene & script** | Trigger scenes and scripts with immediate/delayed/popup mode |
| **Weather**      | Weather display                                                |
| **Host**         | General information display                                    |
| **Switch monitor** | Monitor switch states grouped by device type                 |

Categories can be reconfigured or removed at any time from the same integration page. When the configuration changes, Astrion Home notifies the Astrion remote, which refreshes its interface automatically.

> **APK integration:** the Astrion remote fetches categories and devices over WebSocket via `astrion/get_cards` and listens for `astrion/cards_updated`. See [docs/apk_api.md](docs/apk_api.md) for the full API contract.

### Migrating from RosCard

RosCard is deprecated. Its functionality is now built into Astrion Home.

If you previously configured RosCard cards on a Lovelace dashboard:

1. Update Astrion Home to v2.0.0 or newer.
2. Re-create each RosCard card as a subentry (see above) — the available card types and options mirror the former RosCard cards.
3. Remove the RosCard resource and the RosCard dashboard cards when done.

The configuration uses the same fields as the former RosCard cards (entities, TV type, execution mode, text color, curtain type, …), so it carries over directly. Devices are bound instead of individual entities, and names are taken automatically from the friendly names.

### TV Category Bindings

The TV category is configured in three steps:

1. **Devices** — select the TV devices (media players) and bind IR remote entities and select entities as control sources.
2. **Power & volume** — bind the power control (remote entity + command), choose the volume control mode (single media entity, or separate volume up/down bound to scripts or scenes), bind media buttons (play, pause, volume, mute, …), and bind select entity buttons to options (e.g. HDMI inputs).
3. **Physical keys** — bind each physical key (F4–F11) to a remote entity and command. Key meanings follow the remote hardware version (X9 / HA100A / HA100B), and commands support Astrion IR remotes (button name or IR code, resolved from the code library when left empty), Broadlink devices (`device/key`), and Harmony activities.

All bindings are stored with the category and delivered to the Astrion remote, replacing the equivalent RosCard TV card configuration.

---

## 🎬 Harmony, Activities, and Intent-Oriented Control

One of the ideas behind Astrion is the **Activity** concept popularized by Logitech Harmony.

Traditional remote control asks the user to think in terms of individual devices:

```text
TV
AV Receiver
Media Player
Input
Volume
```

Harmony introduced a higher-level interaction model:

```text
Watch TV
```

The system then translated that intention into the required device actions.

Home Assistant makes this concept significantly more powerful because an activity can involve an entire environment:

```text
                 WATCH A MOVIE
                       │
                       ▼
                HOME ASSISTANT
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
    Projector          AVR          Player
        │              │              │
        └──────────────┼──────────────┘
                       │
              ┌────────┼────────┐
              ▼        ▼        ▼
           Lights   Curtains  Climate
                       │
                       ▼
                    ASTRION
```

Astrion is therefore not intended simply to expose more device buttons.

The broader goal is to provide a physical interface through which users can interact with the larger Home Assistant system while allowing Home Assistant to handle the complexity underneath.

---

## 🔐 Requirements

Before configuring Astrion Home, make sure:

* Astrion is connected to the local network.
* Home Assistant is running and accessible.
* Astrion and Home Assistant can communicate on the same local network/subnet where required.
* The Home Assistant account used for authentication has **Administrator permissions**.
* The Long-Lived Access Token is created from that Administrator account.

### ⚠️ Administrator Permissions Matter

The Astrion Home configuration flow may fail to discover the Astrion Remote Gateway when the Home Assistant account used to create the Long-Lived Access Token does not have Administrator permissions.

If the gateway is not found during configuration:

1. Verify that the token was created by an **Administrator** account.
2. Create a new Long-Lived Access Token using an Administrator account if necessary.
3. Reconnect Astrion using the new token.
4. Try adding **Astrion Home** again from Home Assistant.

This is one of the first things to check before troubleshooting network connectivity.

---

## 📦 Installation

### HACS — Recommended

Astrion Home is available through HACS.

1. Open **HACS** in Home Assistant.
2. Search for **Astrion**.
3. Install **Astrion Home**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add Integration**.
6. Search for **Astrion Home**.

After the integration is added, Home Assistant will search for the available Astrion Remote Gateway.

Select the gateway corresponding to your Astrion Remote.

The gateway is identified by its **serial number (SN)**.

### Manual Installation

If you prefer manual installation:

1. Copy the integration folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add Integration**.
4. Search for **Astrion Home**.

---

## ⚙️ Configuration

After installing Astrion Home:

```text
Home Assistant
      │
      ▼
Settings
      │
      ▼
Devices & services
      │
      ▼
Add Integration
      │
      ▼
Astrion Home
      │
      ▼
Discover Astrion Gateway
      │
      ▼
Select Remote
      │
      ▼
Configure IR
```

The Astrion Gateway is identified by its **serial number (SN)**.

You can find the SN on Astrion under:

**Settings → About**

### If the Gateway Is Not Found

Check the following in order:

1. Astrion is powered on and connected to the network.
2. Astrion and Home Assistant are reachable from the same local network/subnet where required.
3. The Home Assistant account used for the Long-Lived Access Token has **Administrator** permissions.
4. The token was created using that Administrator account.
5. Create a new Long-Lived Access Token and reconnect Astrion if necessary.
6. Restart Home Assistant after installing or updating the integration.
7. Confirm that Astrion is running a compatible firmware version.

Troubleshooting:

https://hub.sanytron.com/support/astrion/no-connection

Getting Started:

https://hub.sanytron.com/support/astrion/getting-started

---

## 📡 Local Infrared Control

Local IR control was introduced in **Astrion V1.2.0**.

Astrion can transmit IR commands directly through its built-in infrared hardware.

This allows Astrion to control traditional IR equipment even when the target device is not itself a network-connected Home Assistant device.

The Astrion IR entity can then be used in supported Astrion interfaces such as the TV Card and in Home Assistant workflows.

Detailed IR documentation:

https://hub.sanytron.com/support/astrion/infrared

---

## 📺 TV Card and Multiple Control Sources

The Astrion TV Card can combine different control sources into a single physical interface.

For example:

```text
                         TV CARD
                            │
             ┌──────────────┼──────────────┐
             │              │              │
             ▼              ▼              ▼
         Astrion IR     Harmony HUB    Media Player
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                         ASTRION
                    Touch + Buttons
```

This allows different technologies to coexist within the same control experience.

Examples include:

* Local Astrion IR
* Existing Harmony HUB infrastructure
* Home Assistant `media_player` entities
* Home Assistant scenes, scripts, and automations

This approach allows users to transition from legacy universal-remote systems while gradually integrating more of their home into Home Assistant.

---

## 🧩 Design Principles

### Home Assistant Remains the Source of Truth

Device states, services, scenes, scripts, and automation logic remain in Home Assistant.

Astrion does not attempt to replace Home Assistant as the automation engine.

### Physical Interface Instead of Dashboard Mirroring

Astrion card subentries do not simply reproduce the entire Home Assistant dashboard on Astrion.

Instead, they selectively present the functions and information that make sense for a physical remote interface.

### Physical + Digital Control

Astrion combines:

* Touchscreen interaction
* Physical buttons
* Home Assistant entities
* Local infrared
* Automation workflows

This allows modern smart-home devices and traditional AV equipment to coexist within one physical control layer.

### State-Aware Interaction

When supported by the relevant Home Assistant entities and Astrion interfaces, Astrion can react to device states instead of relying only on static commands.

---

## 🧪 Development

Astrion Home is developed as part of the broader Astrion ecosystem and evolves through real-world usage, engineering iteration, and community feedback.

Bug reports, feature requests, documentation improvements, testing, and pull requests are welcome.

When reporting an issue, please include:

* Astrion firmware version
* Astrion Home integration version
* Home Assistant version
* Relevant logs
* Configuration details
* Steps to reproduce the issue

Open an issue:

https://github.com/yyqclhy/Astrion-integration/issues

For broader technical discussion:

https://forum.sanytron.com/

---

## 🌱 Community-Driven Development

Astrion was designed with the Home Assistant community in mind.

We have seen users experiment with:

* Custom launchers
* APK modifications
* UI changes
* Button mappings
* Card configurations
* Custom integrations
* Automation workflows
* Alternative interaction models

We do not regard these experiments as separate from the product.

They are part of the way the Astrion ecosystem evolves.

Real-world experimentation often reveals use cases that are difficult to predict during initial development, and community feedback has directly influenced subsequent improvements.

Astrion is therefore developed not only **for** the Home Assistant community, but also **with** the community.

---

## 🌐 Sanytron Ecosystem

Astrion Home is part of the broader **Sanytron interface ecosystem**.

Sanytron provides the product, documentation, software, community, and support environment around Astrion and related physical interfaces.

### Sanytron Official Resources

* 🌐 **Sanytron** — Product information, news, and ecosystem overview
  https://www.sanytron.com/

* 🌐 **Sanytron Hub** — Documentation, firmware, downloads, technical guides, and support
  https://hub.sanytron.com/

* 💬 **Sanytron Forum** — Technical discussions, troubleshooting, feature requests, and community development
  https://forum.sanytron.com/

* 🔴 **Reddit** — Community discussion and user experimentation
  https://www.reddit.com/r/Sanytron/

* 💬 **Discord** — Community support and development discussion
  https://discord.gg/z629RRgHBJ

---

## 🧭 Qinkunex

**Qinkunex** is the broader research and engineering initiative associated with **Human–Object Interaction and Interface Engineering**.

While **Sanytron** focuses on products, interfaces, and their surrounding user ecosystem, **Qinkunex** represents the broader engineering and conceptual direction behind this work.

The relationship can be viewed as:

```text
                       QINKUNEX
          Human–Object Interaction &
             Interface Engineering
                       │
                       ▼
                    SANYTRON
           Products & Interface Ecosystem
                       │
             ┌─────────┼─────────┐
             │         │         │
             ▼         ▼         ▼
          Astrion    Community
             │
             ▼
       Physical Interface
```

Qinkunex is not a runtime dependency of Astrion Home and is not required to install or use this integration.

Learn more:

https://github.com/Qinkunex

---

## 🔗 Related Projects

### RosCard (Deprecated)

**RosCard** was the former interaction layer for Astrion and Home Assistant.

It is deprecated as of Astrion Home v2.0.0 — its functionality is now built into Astrion Home as card subentries. See [Migrating from RosCard](#migrating-from-roscard).

https://github.com/yyqclhy/RosCard

### Astrion Support Center

Complete Astrion documentation:

https://hub.sanytron.com/support/astrion

### Astrion Getting Started

https://hub.sanytron.com/support/astrion/getting-started

### Astrion Infrared Documentation

https://hub.sanytron.com/support/astrion/infrared

### Astrion Troubleshooting

https://hub.sanytron.com/support/astrion/no-connection

---

## 🤝 Contributing

Contributions and experimentation are welcome.

You can help by:

* Reporting bugs
* Suggesting features
* Improving documentation
* Sharing configurations
* Testing releases
* Submitting pull requests

Please open an issue before submitting large changes.

Before submitting a pull request, please make sure your changes are focused and documented where appropriate.

Astrion is built together with its community.

---

## 📄 License

Astrion Home is released under the **MIT License**.

See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

Astrion Home builds on the work of the Home Assistant community and the many users who continue to experiment with new ways of interacting with smart homes.

Thank you to everyone who tests releases, reports issues, shares configurations, contributes ideas, and helps shape the Astrion ecosystem.

---

<p align="center">
  <strong>Astrion Home</strong><br>
  Home Assistant integration for Astrion IR capabilities<br>
  <em>Part of the Sanytron / Qinkunex ecosystem.</em>
</p>
