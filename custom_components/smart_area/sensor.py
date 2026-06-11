"""Capteurs globaux : moyenne de tous les capteurs de la maison d'un même type."""
import logging
import unicodedata
from collections import Counter

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass
)
from homeassistant.core import callback
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers import entity_registry as er, device_registry as dr
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _normalize(text):
    """Minuscules et sans accents, pour comparer les mots-clés ('humidité' == 'humidite')."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def _parse_offsets(raw):
    """Parse les offsets par capteur, une ligne par capteur : 'sensor.temp_salon = -0.5'."""
    offsets = {}
    for line in str(raw or "").replace(";", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        sep = "=" if "=" in line else ":"
        entity_id, found, value = line.partition(sep)
        if not found:
            _LOGGER.warning("Ligne d'offset ignorée (séparateur '=' ou ':' attendu) : %s", line)
            continue
        try:
            offsets[entity_id.strip().lower()] = float(value.strip().replace(",", "."))
        except ValueError:
            _LOGGER.warning("Ligne d'offset ignorée (valeur non numérique) : %s", line)
    return offsets


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Crée un capteur global (moyenne) par mot-clé saisi dans l'UI."""
    conf = {**config_entry.data, **config_entry.options}
    keywords = [k.strip() for k in conf.get("keywords", "").split(",") if k.strip()]

    entities = [SmartGlobalSensor(hass, keyword, config_entry) for keyword in keywords]
    async_add_entities(entities)


class SmartGlobalSensor(SensorEntity):
    """Moyenne de tous les capteurs dont l'id, le nom ou la classe contient le mot-clé."""

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass, keyword, config_entry):
        self.hass = hass
        self.config_entry = config_entry
        self._keyword = _normalize(keyword)

        slug = self._keyword.replace(" ", "_")
        self._attr_name = f"Moyenne {keyword} maison"
        self._attr_unique_id = f"global_avg_{slug}"
        # Force l'ID d'entité technique
        self.entity_id = f"sensor.global_avg_{slug}"

        self._attr_native_value = None
        self._attr_native_unit_of_measurement = None
        self._attr_device_class = None

        self._tracked_entities = []
        self._valid_values = 0
        self._min_value = None
        self._max_value = None
        self._applied_offsets = {}
        self._unsub_track_state = None

    @property
    def extra_state_attributes(self):
        """Attributs supplémentaires pour l'entité."""
        conf = {**self.config_entry.data, **self.config_entry.options}
        label_id = conf.get("label_filter")
        return {
            "keyword": self._keyword,
            "label_filter": label_id if label_id and label_id != "none" else "Aucun (Tous les capteurs)",
            "total_sensors": len(self._tracked_entities),
            "valid_values": self._valid_values,
            "min": self._min_value,
            "max": self._max_value,
            "offsets": self._applied_offsets,
            "tracked_entities": self._tracked_entities,
        }

    async def async_added_to_hass(self):
        """Appelé quand l'entité est ajoutée à Home Assistant."""
        self._update_internal_state()

        # Écouter l'ajout ou la modification d'appareils (pour MQTT/Zigbee Discovery)
        self.async_on_remove(
            self.hass.bus.async_listen("entity_registry_updated", self._async_registry_updated)
        )
        self.async_on_remove(
            self.hass.bus.async_listen("device_registry_updated", self._async_registry_updated)
        )

        # Si HA n'a pas encore fini de démarrer, on attend le signal pour recalculer l'état final
        if not self.hass.is_running:
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._async_ha_started
            )

    async def async_will_remove_from_hass(self):
        """Appelé quand l'entité est supprimée."""
        if self._unsub_track_state:
            self._unsub_track_state()

    def _setup_listeners(self):
        if self._unsub_track_state:
            self._unsub_track_state()
            self._unsub_track_state = None

        if self._tracked_entities:
            self._unsub_track_state = async_track_state_change_event(
                self.hass, self._tracked_entities, self._async_state_changed
            )

    @callback
    def _async_ha_started(self, _event):
        """Recalculer l'état quand Home Assistant a fini de démarrer."""
        self._update_internal_state()
        self.async_write_ha_state()

    @callback
    def _async_state_changed(self, event):
        self._update_internal_state()
        self.async_write_ha_state()

    @callback
    def _async_registry_updated(self, event):
        """Recalculer si une entité est ajoutée ou modifiée dans le registre."""
        self._update_internal_state()
        self.async_write_ha_state()

    def _matches_keyword(self, entity_id, entry):
        """Vérifie si l'entité correspond au mot-clé (id, nom ou device_class)."""
        if self._keyword in _normalize(entity_id):
            return True
        name = entry.name or entry.original_name
        if name and self._keyword in _normalize(name):
            return True
        device_class = entry.device_class or entry.original_device_class
        if device_class and self._keyword in _normalize(device_class):
            return True
        return False

    def _update_internal_state(self):
        """Met à jour la liste des capteurs suivis et la moyenne globale."""
        try:
            conf = {**self.config_entry.data, **self.config_entry.options}
            label_id_filter = conf.get("label_filter")
            if label_id_filter == "none":
                label_id_filter = None
            offsets = _parse_offsets(conf.get("offsets"))

            entity_reg = er.async_get(self.hass)
            device_reg = dr.async_get(self.hass)

            new_tracked = []
            for entity_id, entry in entity_reg.entities.items():
                # Ignorer nos propres entités globales et les entités désactivées
                if entry.platform == DOMAIN or entry.disabled_by:
                    continue
                if not entity_id.startswith("sensor."):
                    continue
                if not self._matches_keyword(entity_id, entry):
                    continue

                ent_labels = entry.labels or set()

                # Vérifier si l'appareil a le label
                if entry.device_id:
                    device = device_reg.async_get(entry.device_id)
                    if device and device.labels:
                        ent_labels = ent_labels.union(device.labels)

                if label_id_filter and label_id_filter not in ent_labels:
                    continue
                new_tracked.append(entity_id)

            if set(new_tracked) != set(self._tracked_entities):
                self._tracked_entities = new_tracked
                self._setup_listeners()

            # Regrouper les valeurs numériques par unité, puis moyenner le groupe majoritaire
            # (évite de mélanger des °C avec des % si un capteur matche par erreur)
            values_by_unit = {}
            device_classes = Counter()

            for entity_id in self._tracked_entities:
                state_obj = self.hass.states.get(entity_id)
                if not state_obj or state_obj.state in ("unknown", "unavailable"):
                    continue
                try:
                    value = float(state_obj.state)
                except (ValueError, TypeError):
                    continue

                # Offset de correction éventuel, défini par capteur dans les options
                value += offsets.get(entity_id, 0.0)

                unit = state_obj.attributes.get("unit_of_measurement")
                values_by_unit.setdefault(unit, []).append(value)

                dc = state_obj.attributes.get("device_class")
                if dc:
                    device_classes[dc] += 1

            if values_by_unit:
                unit, values = max(values_by_unit.items(), key=lambda item: len(item[1]))
                self._attr_native_value = round(sum(values) / len(values), 2)
                self._attr_native_unit_of_measurement = unit
                self._valid_values = len(values)
                self._min_value = min(values)
                self._max_value = max(values)
            self._applied_offsets = {
                entity_id: offset for entity_id, offset in offsets.items()
                if entity_id in self._tracked_entities
            }
            if not values_by_unit:
                self._attr_native_value = None
                self._valid_values = 0
                self._min_value = None
                self._max_value = None

            # Hériter de la classe d'appareil majoritaire (icône/affichage cohérents)
            if device_classes:
                try:
                    self._attr_device_class = SensorDeviceClass(device_classes.most_common(1)[0][0])
                except ValueError:
                    self._attr_device_class = None
            else:
                self._attr_device_class = None

        except Exception as err:
            _LOGGER.exception("Erreur critique lors de la mise à jour de %s : %s", self.name, err)
