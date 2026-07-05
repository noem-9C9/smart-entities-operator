"""Capteurs "opérateurs" : agrégat, différence, dérivée et moyenne glissante.

Quatre sous-types (``sensor_kind``) :
  - ``aggregate``       : combine plusieurs capteurs (moyenne, médiane, min, max…)
                          découverts par mots-clés/label et/ou choisis explicitement.
  - ``difference``      : A − B entre deux entités précises.
  - ``derivative``      : dérivée temporelle d'une entité (par s/min/h/jour).
  - ``moving_average``  : moyenne glissante temporelle d'une entité.

Tous excluent les membres indisponibles et peuvent ignorer les valeurs aberrantes.
"""
import logging
from collections import Counter, deque
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorStateClass
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import (
    async_track_state_change_event, async_track_time_interval
)
from homeassistant.util import dt as dt_util

from .const import (
    AGGREGATE_OPERATIONS, DOMAIN, KIND_AGGREGATE, KIND_DERIVATIVE,
    KIND_DIFFERENCE, KIND_MOVING_AVERAGE, OP_MEAN, TIME_SENSOR_INTERVAL_SECONDS,
    TIME_UNITS,
)
from .helpers import (
    apply_operation, in_bounds, normalize, parse_offsets, to_float
)

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE_STATES = ("unknown", "unavailable")

OP_LABELS = {
    "mean": "Moyenne", "median": "Médiane", "min": "Min", "max": "Max",
    "sum": "Somme", "range": "Amplitude", "stdev": "Écart-type", "count": "Nombre",
}


def _slugify(text):
    """Slug technique : minuscules sans accents, uniquement [a-z0-9_]."""
    base = normalize(text).replace(" ", "_")
    return "".join(c for c in base if c.isalnum() or c == "_").strip("_") or "operateur"


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Crée les capteurs opérateurs selon le sous-type choisi dans l'UI."""
    conf = {**config_entry.data, **config_entry.options}
    kind = conf.get("sensor_kind", KIND_AGGREGATE)

    entities = []
    if kind == KIND_AGGREGATE:
        keywords = [k.strip() for k in str(conf.get("keywords", "")).split(",") if k.strip()]
        if keywords:
            entities = [AggregateSensor(hass, config_entry, keyword=kw) for kw in keywords]
        else:
            # Mode "entités précises" : un seul capteur à partir de la liste explicite
            entities = [AggregateSensor(hass, config_entry, keyword=None)]
    elif kind == KIND_DIFFERENCE:
        entities = [DifferenceSensor(hass, config_entry)]
    elif kind == KIND_DERIVATIVE:
        entities = [DerivativeSensor(hass, config_entry)]
    elif kind == KIND_MOVING_AVERAGE:
        entities = [MovingAverageSensor(hass, config_entry)]

    async_add_entities(entities)


class OperatorSensorBase(SensorEntity):
    """Base commune : suivi des sources, exclusion des indisponibles, attributs 'liées'."""

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    # Les sous-classes découvrant leurs sources dynamiquement mettent True.
    _uses_registry = False
    # Les sous-classes dépendant du temps (fenêtre glissante, dérivée) mettent True.
    _uses_time = False

    def __init__(self, hass, config_entry):
        self.hass = hass
        self.config_entry = config_entry
        self._tracked_entities = []
        self._unavailable_entities = []
        self._excluded_entities = []
        self._unsub_track_state = None
        self._attr_native_value = None
        self._attr_native_unit_of_measurement = None
        self._attr_device_class = None

    @property
    def _conf(self):
        return {**self.config_entry.data, **self.config_entry.options}

    @property
    def extra_state_attributes(self):
        attrs = {
            # Convention HA : la liste des sources est lisible par les cartes et l'UI.
            "entity_id": self._tracked_entities,
            "total_sources": len(self._tracked_entities),
            "unavailable_members": self._unavailable_entities,
            "excluded_members": self._excluded_entities,
        }
        attrs.update(self._extra_attributes())
        return attrs

    def _extra_attributes(self):
        return {}

    async def async_added_to_hass(self):
        self._update()

        if self._uses_registry:
            self.async_on_remove(
                self.hass.bus.async_listen("entity_registry_updated", self._async_recompute)
            )
            self.async_on_remove(
                self.hass.bus.async_listen("device_registry_updated", self._async_recompute)
            )

        if self._uses_time:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass, self._async_recompute,
                    timedelta(seconds=TIME_SENSOR_INTERVAL_SECONDS),
                )
            )

        if not self.hass.is_running:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._async_recompute)

    async def async_will_remove_from_hass(self):
        if self._unsub_track_state:
            self._unsub_track_state()

    def _setup_listeners(self):
        if self._unsub_track_state:
            self._unsub_track_state()
            self._unsub_track_state = None
        if self._tracked_entities:
            self._unsub_track_state = async_track_state_change_event(
                self.hass, self._tracked_entities, self._async_recompute
            )

    @callback
    def _async_recompute(self, _event=None):
        self._update()
        self.async_write_ha_state()

    def _update(self):
        try:
            new_tracked = self._resolve_tracked()
            if set(new_tracked) != set(self._tracked_entities):
                self._tracked_entities = new_tracked
                self._setup_listeners()

            self._unavailable_entities = [
                entity_id for entity_id in self._tracked_entities
                if (state := self.hass.states.get(entity_id)) is None
                or state.state in UNAVAILABLE_STATES
            ]
            self._recalc()
        except Exception as err:
            _LOGGER.exception("Erreur lors de la mise à jour de %s : %s", self.name, err)

    def _valid_value(self, entity_id):
        """Retourne la valeur numérique de l'entité, ou None si indisponible/non numérique."""
        state = self.hass.states.get(entity_id)
        if not state or state.state in UNAVAILABLE_STATES:
            return None
        return to_float(state.state)

    def _copy_unit_and_class(self, entity_id, unit_suffix=None):
        """Reprend l'unité et la device_class de la source (pour un affichage cohérent)."""
        state = self.hass.states.get(entity_id)
        unit = state.attributes.get("unit_of_measurement") if state else None
        if unit and unit_suffix:
            unit = f"{unit}{unit_suffix}"
        self._attr_native_unit_of_measurement = unit
        dc = state.attributes.get("device_class") if state else None
        try:
            self._attr_device_class = SensorDeviceClass(dc) if dc else None
        except ValueError:
            self._attr_device_class = None

    def _resolve_tracked(self):
        raise NotImplementedError

    def _recalc(self):
        raise NotImplementedError


class AggregateSensor(OperatorSensorBase):
    """Combine plusieurs capteurs via une opération (moyenne, médiane, min, max…).

    Les sources viennent d'un mot-clé (id/nom/classe) filtré par label, et/ou
    d'une liste d'entités choisies explicitement.
    """

    _uses_registry = True

    def __init__(self, hass, config_entry, keyword):
        super().__init__(hass, config_entry)
        conf = self._conf
        operation = conf.get("operation", OP_MEAN)
        if operation not in AGGREGATE_OPERATIONS:
            operation = OP_MEAN
        self._operation = operation
        self._keyword = normalize(keyword) if keyword else None

        op_label = OP_LABELS.get(operation, "Agrégat")
        if self._keyword:
            slug = _slugify(self._keyword)
            self._attr_name = f"{op_label} {keyword} maison"
            # Compat : la moyenne par mot-clé garde l'id historique global_avg_*
            base = f"global_avg_{slug}" if operation == OP_MEAN else f"global_{operation}_{slug}"
        else:
            label = conf.get("name") or f"Agrégat {op_label}"
            slug = _slugify(label)
            self._attr_name = label
            base = f"op_{operation}_{slug}"

        self._attr_unique_id = base
        self.entity_id = f"sensor.{base}"

        self._valid_count = 0
        self._min_value = None
        self._max_value = None
        self._applied_offsets = {}

    def _extra_attributes(self):
        conf = self._conf
        label_id = conf.get("label_filter")
        return {
            "operation": self._operation,
            "keyword": self._keyword,
            "label_filter": label_id if label_id and label_id != "none" else "Aucun (toutes les entités)",
            "valid_values": self._valid_count,
            "min": self._min_value,
            "max": self._max_value,
            "offsets": self._applied_offsets,
        }

    def _matches_keyword(self, entity_id, entry):
        """Vrai si l'entité correspond au mot-clé (id, nom ou device_class)."""
        if self._keyword in normalize(entity_id):
            return True
        name = entry.name or entry.original_name
        if name and self._keyword in normalize(name):
            return True
        device_class = entry.device_class or entry.original_device_class
        if device_class and self._keyword in normalize(device_class):
            return True
        return False

    def _resolve_tracked(self):
        conf = self._conf
        label_filter = conf.get("label_filter")
        if label_filter == "none":
            label_filter = None

        # Entités choisies explicitement (toujours incluses, sans filtre)
        result = list(conf.get("entities") or [])

        if self._keyword:
            entity_reg = er.async_get(self.hass)
            device_reg = dr.async_get(self.hass)
            for entity_id, entry in entity_reg.entities.items():
                if entry.platform == DOMAIN or entry.disabled_by:
                    continue
                if not entity_id.startswith("sensor."):
                    continue
                if not self._matches_keyword(entity_id, entry):
                    continue

                ent_labels = entry.labels or set()
                if entry.device_id:
                    device = device_reg.async_get(entry.device_id)
                    if device and device.labels:
                        ent_labels = ent_labels.union(device.labels)
                if label_filter and label_filter not in ent_labels:
                    continue
                result.append(entity_id)

        # Dédoublonne en gardant l'ordre
        seen = set()
        return [e for e in result if not (e in seen or seen.add(e))]

    def _recalc(self):
        conf = self._conf
        offsets = parse_offsets(conf.get("offsets"))
        precision = int(to_float(conf.get("precision")) or 2)
        min_valid = to_float(conf.get("min_valid"))
        max_valid = to_float(conf.get("max_valid"))
        mad_threshold = to_float(conf.get("outlier_mad")) or 0.0

        # Regroupe par unité pour ne pas mélanger des °C avec des % (moyenne du groupe majoritaire)
        pairs_by_unit = {}
        device_classes = Counter()
        excluded = []

        for entity_id in self._tracked_entities:
            value = self._valid_value(entity_id)
            if value is None:
                continue
            value += offsets.get(entity_id, 0.0)
            if not in_bounds(value, min_valid, max_valid):
                excluded.append(entity_id)
                continue
            state = self.hass.states.get(entity_id)
            unit = state.attributes.get("unit_of_measurement")
            pairs_by_unit.setdefault(unit, []).append((entity_id, value))
            dc = state.attributes.get("device_class")
            if dc:
                device_classes[dc] += 1

        if not pairs_by_unit:
            self._attr_native_value = None
            self._valid_count = 0
            self._min_value = self._max_value = None
            self._excluded_entities = excluded
            self._attr_device_class = None
            return

        unit, pairs = max(pairs_by_unit.items(), key=lambda item: len(item[1]))

        # Rejet des valeurs aberrantes ponctuelles (écart absolu médian)
        pairs, rejected = _reject_outlier_pairs(pairs, mad_threshold)
        excluded.extend(entity_id for entity_id, _ in rejected)

        values = [v for _, v in pairs]
        result = apply_operation(self._operation, values)
        self._attr_native_value = round(result, precision) if result is not None else None
        self._attr_native_unit_of_measurement = unit
        self._valid_count = len(values)
        self._min_value = min(values)
        self._max_value = max(values)
        self._excluded_entities = excluded
        self._applied_offsets = {
            entity_id: off for entity_id, off in offsets.items()
            if entity_id in self._tracked_entities
        }

        if device_classes:
            try:
                self._attr_device_class = SensorDeviceClass(device_classes.most_common(1)[0][0])
            except ValueError:
                self._attr_device_class = None
        else:
            self._attr_device_class = None


def _reject_outlier_pairs(pairs, threshold):
    """Filtre des (entity_id, valeur) via l'écart absolu médian. Retourne (gardés, rejetés)."""
    import statistics
    if not threshold or len(pairs) < 3:
        return pairs, []
    values = [v for _, v in pairs]
    median = statistics.median(values)
    mad = statistics.median([abs(v - median) for v in values])
    if mad == 0:
        return pairs, []
    limit = threshold * 1.4826 * mad
    kept = [(e, v) for e, v in pairs if abs(v - median) <= limit]
    rejected = [(e, v) for e, v in pairs if abs(v - median) > limit]
    if not kept:
        return pairs, []
    return kept, rejected


class DifferenceSensor(OperatorSensorBase):
    """Différence entre deux entités précises : A − B (ou |A − B|)."""

    def __init__(self, hass, config_entry):
        super().__init__(hass, config_entry)
        conf = self._conf
        self._entity_a = conf.get("entity_a")
        self._entity_b = conf.get("entity_b")
        self._abs = bool(conf.get("abs_value", False))

        label = conf.get("name") or "Différence"
        base = f"op_diff_{_slugify(label)}"
        self._attr_name = label
        self._attr_unique_id = base
        self.entity_id = f"sensor.{base}"

    def _extra_attributes(self):
        return {
            "entity_a": self._entity_a,
            "entity_b": self._entity_b,
            "absolute": self._abs,
        }

    def _resolve_tracked(self):
        return [e for e in (self._entity_a, self._entity_b) if e]

    def _recalc(self):
        va = self._valid_value(self._entity_a) if self._entity_a else None
        vb = self._valid_value(self._entity_b) if self._entity_b else None
        conf = self._conf
        precision = int(to_float(conf.get("precision")) or 2)

        if va is None or vb is None:
            self._attr_native_value = None
            return

        diff = va - vb
        if self._abs:
            diff = abs(diff)
        self._attr_native_value = round(diff, precision)
        self._copy_unit_and_class(self._entity_a)


class DerivativeSensor(OperatorSensorBase):
    """Dérivée temporelle d'une entité (variation par unité de temps)."""

    _uses_time = True

    def __init__(self, hass, config_entry):
        super().__init__(hass, config_entry)
        conf = self._conf
        self._source = conf.get("source")
        self._unit_time = conf.get("unit_time", "h")
        if self._unit_time not in TIME_UNITS:
            self._unit_time = "h"
        self._window = int(to_float(conf.get("time_window")) or 0)
        self._buffer = deque()

        label = conf.get("name") or "Dérivée"
        base = f"op_derivative_{_slugify(label)}"
        self._attr_name = label
        self._attr_unique_id = base
        self.entity_id = f"sensor.{base}"

    def _extra_attributes(self):
        return {
            "source": self._source,
            "unit_time": self._unit_time,
            "time_window_s": self._window,
            "samples": len(self._buffer),
        }

    def _resolve_tracked(self):
        return [self._source] if self._source else []

    def _recalc(self):
        now = dt_util.utcnow().timestamp()
        value = self._valid_value(self._source) if self._source else None

        # On n'ajoute un point que lorsqu'une vraie valeur arrive (les ticks horaires
        # servent seulement à purger la fenêtre et à réémettre l'état).
        if value is not None and (not self._buffer or self._buffer[-1][1] != value):
            self._buffer.append((now, value))

        if self._window > 0:
            cutoff = now - self._window
            while len(self._buffer) > 2 and self._buffer[0][0] < cutoff:
                self._buffer.popleft()
        else:
            while len(self._buffer) > 2:
                self._buffer.popleft()

        if len(self._buffer) < 2:
            self._attr_native_value = None
            self._copy_unit_and_class(self._source, unit_suffix=f"/{self._unit_time}")
            return

        (t0, v0), (t1, v1) = self._buffer[0], self._buffer[-1]
        dt_seconds = t1 - t0
        if dt_seconds <= 0:
            self._attr_native_value = None
            return
        conf = self._conf
        precision = int(to_float(conf.get("precision")) or 3)
        rate_per_second = (v1 - v0) / dt_seconds
        self._attr_native_value = round(rate_per_second * TIME_UNITS[self._unit_time], precision)
        self._copy_unit_and_class(self._source, unit_suffix=f"/{self._unit_time}")


class MovingAverageSensor(OperatorSensorBase):
    """Moyenne glissante temporelle d'une entité (pondérée par la durée)."""

    _uses_time = True

    def __init__(self, hass, config_entry):
        super().__init__(hass, config_entry)
        conf = self._conf
        self._source = conf.get("source")
        self._window = int(to_float(conf.get("window")) or 300)
        self._buffer = deque()
        self._last_accepted = None

        label = conf.get("name") or "Moyenne glissante"
        base = f"op_movavg_{_slugify(label)}"
        self._attr_name = label
        self._attr_unique_id = base
        self.entity_id = f"sensor.{base}"

    def _extra_attributes(self):
        return {
            "source": self._source,
            "window_s": self._window,
            "samples": len(self._buffer),
        }

    def _resolve_tracked(self):
        return [self._source] if self._source else []

    def _recalc(self):
        now = dt_util.utcnow().timestamp()
        conf = self._conf
        precision = int(to_float(conf.get("precision")) or 2)
        min_valid = to_float(conf.get("min_valid"))
        max_valid = to_float(conf.get("max_valid"))
        max_step = to_float(conf.get("max_step"))

        self._excluded_entities = []
        value = self._valid_value(self._source) if self._source else None
        if value is not None and in_bounds(value, min_valid, max_valid):
            # Filtre anti-pic : ignore un saut trop brutal par rapport à la dernière valeur retenue
            if max_step is None or self._last_accepted is None or abs(value - self._last_accepted) <= max_step:
                if not self._buffer or self._buffer[-1][1] != value:
                    self._buffer.append((now, value))
                self._last_accepted = value
            else:
                self._excluded_entities = [self._source]
        elif value is not None and not in_bounds(value, min_valid, max_valid):
            self._excluded_entities = [self._source]

        cutoff = now - self._window
        while len(self._buffer) > 1 and self._buffer[0][0] < cutoff:
            self._buffer.popleft()

        if not self._buffer:
            self._attr_native_value = None
            self._copy_unit_and_class(self._source)
            return

        self._attr_native_value = round(self._time_weighted_average(now), precision)
        self._copy_unit_and_class(self._source)

    def _time_weighted_average(self, now):
        """Moyenne pondérée par la durée de chaque palier sur la fenêtre."""
        points = list(self._buffer)
        if len(points) == 1:
            return points[0][1]
        total_weight = 0.0
        weighted_sum = 0.0
        for (t_i, v_i), (t_next, _) in zip(points, points[1:]):
            weight = t_next - t_i
            weighted_sum += v_i * weight
            total_weight += weight
        # Dernier palier : de la dernière mesure jusqu'à maintenant
        last_t, last_v = points[-1]
        weight = max(now - last_t, 0.0)
        weighted_sum += last_v * weight
        total_weight += weight
        if total_weight <= 0:
            return points[-1][1]
        return weighted_sum / total_weight
