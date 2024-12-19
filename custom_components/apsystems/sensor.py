from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, NamedTuple, Optional

import homeassistant.helpers.config_validation as cv
import requests
import voluptuous as vol  # type: ignore
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.const import (
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_OK,
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util.dt import as_local
from homeassistant.util.dt import utcnow as dt_utcnow
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from .api import APSystemsApi

CONF_AUTH_ID = "authId"
CONF_ECU_ID = "ecuId"
CONF_SUNSET = "sunset"
CONF_SYSTEM_ID = "systemId"

EXTRA_TIMESTAMP = "timestamp"
SENSOR_ENERGY_TODAY = "energy_today"
SENSOR_ENERGY_LATEST = "energy_latest"
SENSOR_ENERGY_TOTAL = "energy_total"
SENSOR_POWER_LATEST = "power_latest"
SENSOR_POWER_MAX = "power_max_day"
SENSOR_TIME = "date"

# to move apsystems timestamp to UTC
OFFSET_MS = (
    timedelta(hours=7).total_seconds() / timedelta(milliseconds=1).total_seconds()
)

CUSTOM_CONF_API_APP_ID = "api_app_id"
CUSTOM_CONF_API_APP_SECRET = "api_app_secret"
CUSTOM_CONF_SID = "sid"
CUSTOM_CONF_ECU_ID = "ecu_id"
CUSTOM_CONF_SUNSET = "sunset"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CUSTOM_CONF_API_APP_ID): cv.string,
        vol.Required(CUSTOM_CONF_API_APP_SECRET): cv.string,
        vol.Required(CUSTOM_CONF_SID): cv.string,
        vol.Required(CUSTOM_CONF_ECU_ID): cv.string,
        vol.Optional(CUSTOM_CONF_SUNSET, default="off"): cv.string,
    }
)


class ApsMetadata(NamedTuple):
    json_key: str
    icon: str
    unit: str = ""
    state_class: Optional[str] = None


SENSORS = {
    SENSOR_ENERGY_TODAY: ApsMetadata(
        json_key="total",
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        state_class="total_increasing",
    ),
    SENSOR_ENERGY_LATEST: ApsMetadata(
        json_key="energy",
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
    ),
    SENSOR_POWER_LATEST: ApsMetadata(
        json_key="power",
        unit=UnitOfPower.WATT,
        icon="mdi:solar-power",
    ),
}

SCAN_INTERVAL = timedelta(minutes=1)
_LOGGER = logging.getLogger(__name__)

offset_hours = (8 * 60 * 60 * 1000) - (time.localtime().tm_gmtoff * 1000)
_LOGGER.debug("Offset set to : " + str(offset_hours / (60 * 60 * 1000)) + " hours")


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    api_app_id = config[CUSTOM_CONF_API_APP_ID]
    api_app_secret = config.get(CUSTOM_CONF_API_APP_SECRET)
    sid = config.get(CUSTOM_CONF_SID)
    ecu_id = config.get(CUSTOM_CONF_ECU_ID)
    sunset = config.get(CUSTOM_CONF_SUNSET)

    api = APSystemsApi(
        api_app_id=api_app_id,
        api_app_secret=api_app_secret,
        sid=sid,
        ecu_id=ecu_id
    )

    # await self._hass.async_add_executor_job(
    #     s.request,
    #     "POST",
    #     self.url_data,
    #     None,
    #     post_data,
    #     self.headers,
    #     browser.cookies.get_dict(),
    # )

    sensors = []
    for type, metadata in SENSORS.items():
        sensor_name = config.get(CONF_NAME).lower() + "_" + type
        sensor = APSystemsSensor(
            sensor_name=sensor_name, sunset=sunset, api=api, metadata=metadata
        )
        sensors.append(sensor)

    add_entities(sensors, True)


class APSystemsSensor(SensorEntity):
    """Representation of a Sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY

    def __init__(
        self,
        sensor_name: str,
        # system_id: str,
        sunset: str,
        api: APSystemsApi,
        metadata: ApsMetadata,
    ):
        """Initialize the sensor."""
        self._state = None
        self._name = sensor_name
        # self._system_id = system_id
        self._sunset = sunset
        self._api= api
        self._metadata = metadata
        self._attributes: Dict[str, Any] = {}

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state_class(self):
        """Return the state_class of the sensor."""
        return self._metadata.state_class

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def state_attributes(self):
        """Return the device state attributes."""
        return self._attributes

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._metadata.unit

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return self._metadata.icon

    @property
    def available(self, utc_now=None):
        _LOGGER.debug(f"Sunset variable: {self._sunset=}")

        if self._sunset == "False":
            _LOGGER.debug("Sensor is running. Sunset is disabled")
            return True

        if utc_now is None:
            utc_now = dt_utcnow()
        now = as_local(utc_now)

        start_time = self.find_start_time(now)
        stop_time = self.find_stop_time(now)

        if as_local(start_time) <= now <= as_local(stop_time):
            _LOGGER.debug(
                "Sensor is running. Start/Stop time: "
                f"{as_local(start_time)}, {as_local(stop_time)}"
            )
            return True
        else:
            _LOGGER.debug(
                "Sensor is not running. Start/Stop time: "
                f"{as_local(start_time)}, {as_local(stop_time)}"
            )
            return False
        
    def update(self) -> None:
        try:
            _LOGGER.debug(f"Updating sensor: {self._name}")
            system_summary = self._api.system_summary()
            _LOGGER.debug(f"Updated sensor: {self._name} {system_summary}")
            self._state = "TEST"
            # self._state = STATE_OK
        except Exception as e:
            _LOGGER.error(f"Error updating sensor: {e}")
            self._state = STATE_UNAVAILABLE
    # async def async_update(self):
    #     """Fetch new state data for the sensor.
    #     This is the only method that should fetch new data for Home Assistant.
    #     """
    #     if not self.available:
    #         self._state = STATE_UNAVAILABLE
    #         return

    #     ap_data = await self._fetcher.data()

    #     # state is not available
    #     if ap_data is None:
    #         self._state = STATE_UNAVAILABLE
    #         return
    #     index = self._metadata[0]
    #     value = ap_data[index]
    #     if isinstance(value, list):
    #         value = value[-1]

    #     # get timestamp
    #     index_time = SENSORS[SENSOR_TIME][0]
    #     timestamp = ap_data[index_time][-1]

    #     if value == timestamp:  # current attribute is the timestamp, so fix it
    #         value = int(value) + offset_hours
    #         value = datetime.fromtimestamp(value / 1000)
    #     timestamp = int(timestamp) + offset_hours

    #     self._attributes[EXTRA_TIMESTAMP] = timestamp

    #     _LOGGER.debug(self._name + ":" + str(value))
    #     self._state = value

    def find_start_time(self, now):
        """Return sunrise or start_time if given."""
        sunrise = get_astral_event_date(self.hass, SUN_EVENT_SUNRISE, now.date())
        return sunrise

    def find_stop_time(self, now):
        """Return sunset or stop_time if given."""
        sunset = get_astral_event_date(self.hass, SUN_EVENT_SUNSET, now.date())
        return sunset