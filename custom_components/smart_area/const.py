"""Constantes de l'intégration Smart Area."""

DOMAIN = "smart_area"

# Types d'entrées de configuration
ENTRY_TYPE_LIGHT = "light"
ENTRY_TYPE_COVER = "cover"
ENTRY_TYPE_SWITCH = "switch"
ENTRY_TYPE_SENSOR = "sensor"

PLATFORMS_BY_TYPE = {
    ENTRY_TYPE_LIGHT: ["light"],
    ENTRY_TYPE_COVER: ["cover"],
    ENTRY_TYPE_SWITCH: ["switch"],
    ENTRY_TYPE_SENSOR: ["sensor"],
}
