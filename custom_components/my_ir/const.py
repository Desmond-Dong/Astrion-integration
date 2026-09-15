DOMAIN = "astrion"
NAME = "Astrion Remote"

# 添加集成时选择的对话代理（Conversation Agent）
CONF_CONVERSATION_AGENT = "conversation_agent"

# Harmony Hub 配置文件搜索模式
HARMONY_CONF_PATTERN = "harmony_*.conf"

# Broadlink learned-code storage is owned by the Broadlink integration.  Astrion
# only reads the exact file derived from the entity registry unique_id.
BROADLINK_STORAGE_PREFIX = "broadlink_remote_"
BROADLINK_STORAGE_SUFFIX = "_codes"
