"""Config flow for openwrt ubus integration."""

from __future__ import annotations

import logging
from abc import ABC
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, ConfigFlow, OptionsFlowWithReload
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from voluptuous import Schema

from .Ubus import Ubus
from .Ubus.const import API_RPC_CALL
from .Ubus.interface import Authentication
from .const import (
    CONF_DHCP_SOFTWARE,
    CONF_WIRELESS_SOFTWARE,
    CONF_ENABLE_QMODEM_SENSORS,
    CONF_ENABLE_STATION_SENSORS,
    CONF_ENABLE_SYSTEM_SENSORS,
    CONF_ENABLE_ACCESS_POINT_SENSORS,
    CONF_ENABLE_SERVICE_CONTROLS,
    CONF_ENABLE_DEVICE_KICK_BUTTONS,
    CONF_SELECTED_SERVICES,
    CONF_SYSTEM_SENSOR_INTERVAL,
    CONF_QMODEM_SENSOR_INTERVAL,
    CONF_STATION_SENSOR_INTERVAL,
    CONF_ACCESS_POINT_SENSOR_INTERVAL,
    CONF_SERVICE_INTERVAL,
    DEFAULT_DHCP_SOFTWARE,
    DEFAULT_WIRELESS_SOFTWARE,
    DEFAULT_ENABLE_QMODEM_SENSORS,
    DEFAULT_ENABLE_STA_SENSORS,
    DEFAULT_ENABLE_SYSTEM_SENSORS,
    DEFAULT_ENABLE_AP_SENSORS,
    DEFAULT_ENABLE_SERVICE_CONTROLS,
    DEFAULT_ENABLE_DEVICE_KICK_BUTTONS,
    DEFAULT_SYSTEM_SENSOR_INTERVAL,
    DEFAULT_QMODEM_SENSOR_INTERVAL,
    DEFAULT_STATISTIC_SENSOR_INTERVAL,
    DEFAULT_ACCESS_POINT_SENSOR_INTERVAL,
    DEFAULT_SERVICE_INTERVAL,
    DHCP_SOFTWARES,
    DOMAIN,
    WIRELESS_SOFTWARES,
    API_SUBSYS_RC,
    API_METHOD_LIST, CONF_SECTION_KEY,
)
from .extended_ubus import RCListServicesResponse

_LOGGER = logging.getLogger(__name__)


class UpdateIntervals:
    def __init__(
            self,
            system: timedelta,
            qmodem: timedelta,
            statistic: timedelta,
            access_points: timedelta,
            services: timedelta
    ):
        self.system = system
        self.qmodem = qmodem
        self.statistic = statistic
        self.access_points = access_points
        self.services = services


class ServiceConfig:
    def __init__(self, selected_services: list[str]):
        self.selected_services = selected_services


class SensorConfig:
    def __init__(
            self,
            wireless_software: str,
            dhcp_software: str,
            enable_system_sensors: bool,
            enable_qmodem_sensors: bool,
            enable_sta_sensors: bool,
            enable_ap_sensors: bool,
            enable_service_controls: bool,
            enable_device_kick_buttons: bool,
    ):
        self.wireless_software = wireless_software
        self.dhcp_software = dhcp_software
        self.enable_system_sensors = enable_system_sensors
        self.enable_qmodem_sensors = enable_qmodem_sensors
        self.enable_sta_sensors = enable_sta_sensors
        self.enable_ap_sensors = enable_ap_sensors
        self.enable_service_controls = enable_service_controls
        self.enable_device_kick_buttons = enable_device_kick_buttons


class EntryConfiguration:
    def __init__(
            self,
            authentication: Authentication, sensor_config: SensorConfig,
            service_config: ServiceConfig, update_intervals: UpdateIntervals
    ):
        self.authentication = authentication
        self.sensor_config = sensor_config
        self.service_config = service_config
        self.update_intervals = update_intervals


# Step 1: Connection configuration
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


# Step 2: Sensor configuration
def step_sensors_data_schema(
        sensor_config: SensorConfig | None = None,
) -> Schema:
    if sensor_config:
        default_wireless = sensor_config.wireless_software
        default_dhcp = sensor_config.dhcp_software
        default_enable_system = sensor_config.enable_system_sensors
        default_enable_qmodem = sensor_config.enable_qmodem_sensors
        default_enable_sta = sensor_config.enable_sta_sensors
        default_enable_ap = sensor_config.enable_ap_sensors
        default_enable_service_controls = sensor_config.enable_service_controls
        default_enable_device_kick_buttons = sensor_config.enable_device_kick_buttons
    else:
        default_wireless = DEFAULT_WIRELESS_SOFTWARE
        default_dhcp = DEFAULT_DHCP_SOFTWARE
        default_enable_system = DEFAULT_ENABLE_SYSTEM_SENSORS
        default_enable_qmodem = DEFAULT_ENABLE_QMODEM_SENSORS
        default_enable_sta = DEFAULT_ENABLE_STA_SENSORS
        default_enable_ap = DEFAULT_ENABLE_AP_SENSORS
        default_enable_service_controls = DEFAULT_ENABLE_SERVICE_CONTROLS
        default_enable_device_kick_buttons = DEFAULT_ENABLE_DEVICE_KICK_BUTTONS

    return vol.Schema(
        {
            vol.Optional(CONF_WIRELESS_SOFTWARE, default=default_wireless): vol.In(WIRELESS_SOFTWARES),
            vol.Optional(CONF_DHCP_SOFTWARE, default=default_dhcp): vol.In(DHCP_SOFTWARES),
            vol.Optional(CONF_ENABLE_SYSTEM_SENSORS, default=default_enable_system): bool,
            vol.Optional(CONF_ENABLE_QMODEM_SENSORS, default=default_enable_qmodem): bool,
            vol.Optional(CONF_ENABLE_STATION_SENSORS, default=default_enable_sta): bool,
            vol.Optional(CONF_ENABLE_ACCESS_POINT_SENSORS, default=default_enable_ap): bool,
            vol.Optional(CONF_ENABLE_SERVICE_CONTROLS, default=default_enable_service_controls): bool,
            vol.Optional(CONF_ENABLE_DEVICE_KICK_BUTTONS, default=default_enable_device_kick_buttons): bool,
        }
    )


# Step 4: Intervals configuration
def step_intervals_data_schema(
        update_intervals: UpdateIntervals | None = None,
) -> Schema:
    if update_intervals:
        default_system_interval = int(update_intervals.system.total_seconds())
        default_qmodem_interval = int(update_intervals.qmodem.total_seconds())
        default_statistic_interval = int(update_intervals.statistic.total_seconds())
        default_ap_interval = int(update_intervals.access_points.total_seconds())
        default_service_interval = int(update_intervals.services.total_seconds())
    else:
        default_system_interval = DEFAULT_SYSTEM_SENSOR_INTERVAL
        default_qmodem_interval = DEFAULT_QMODEM_SENSOR_INTERVAL
        default_statistic_interval = DEFAULT_STATISTIC_SENSOR_INTERVAL
        default_ap_interval = DEFAULT_ACCESS_POINT_SENSOR_INTERVAL
        default_service_interval = DEFAULT_SERVICE_INTERVAL

    return vol.Schema(
        {
            vol.Optional(CONF_SYSTEM_SENSOR_INTERVAL, default=default_system_interval): vol.All(
                vol.Coerce(int), vol.Range(min=10, max=300)
            ),
            vol.Optional(CONF_QMODEM_SENSOR_INTERVAL, default=default_qmodem_interval): vol.All(
                vol.Coerce(int), vol.Range(min=30, max=600)
            ),
            vol.Optional(CONF_STATION_SENSOR_INTERVAL, default=default_statistic_interval): vol.All(
                vol.Coerce(int), vol.Range(min=10, max=300)
            ),
            vol.Optional(CONF_ACCESS_POINT_SENSOR_INTERVAL, default=default_ap_interval): vol.All(
                vol.Coerce(int), vol.Range(min=30, max=600)
            ),
            vol.Optional(CONF_SERVICE_INTERVAL, default=default_service_interval): vol.All(
                vol.Coerce(int), vol.Range(min=10, max=300)
            ),
        }
    )


class UbusFlow(ABC):
    hass: HomeAssistant
    _authentication: Authentication

    async def get_services_list(self) -> list[str]:
        """Get list of available services from OpenWrt."""
        session = async_get_clientsession(self.hass)
        ubus = Ubus(self._authentication, client=session)

        try:
            if response := await ubus.api_call(RCListServicesResponse, API_RPC_CALL, API_SUBSYS_RC, API_METHOD_LIST):
                return response.services

        except Exception as exc:
            _LOGGER.warning("Failed to get services list: %s", exc)

        return []


class OpenwrtUbusConfigFlow(UbusFlow, ConfigFlow, domain=DOMAIN):
    """Handle a config flow for openwrt ubus."""
    _service_config: ServiceConfig
    _sensor_config: SensorConfig
    _update_intervals: UpdateIntervals

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Create the options flow."""
        return OpenwrtUbusOptionsFlow()

    async def _validate_input(self) -> str | None:
        """Validate the user input allows us to connect."""
        error: str | None = None
        try:
            session = async_get_clientsession(self.hass)

            ubus = Ubus(self._authentication, client=session)

            try:
                # Test connection
                if await ubus.connect() is None:
                    raise CannotConnect("Failed to connect to OpenWrt device")

            except Exception as exc:
                _LOGGER.exception("Unexpected exception during connection test")
                raise CannotConnect("Failed to connect to OpenWrt device") from exc
        except CannotConnect:
            error = "cannot_connect"
        except PermissionError:
            error = "invalid_auth"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            error = "unknown"

        return error

    async def async_step_reauth(
            self, entry_data: dict[str, Any]
    ):
        """Show the reauth form to the user."""
        entry_configuration: EntryConfiguration = entry_data[CONF_SECTION_KEY]
        self._authentication = entry_configuration.authentication

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
            self, user_input: dict[str, Any] | None = None
    ):
        """Dialog that informs the user that reauth is required."""
        if user_input is None:
            return await self._show_form_reauth_confirm()

        self._authentication = Authentication(
            host=self._authentication.host,
            username=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
        )

        if error := await self._validate_input():
            return self._show_form_reauth_confirm({"base": error})

        reauth_entry = self._get_reauth_entry()
        entry_configuration: EntryConfiguration = reauth_entry.data[CONF_SECTION_KEY]
        return self.async_update_reload_and_abort(
            reauth_entry,
            data={
                CONF_SECTION_KEY: EntryConfiguration(
                    authentication=self._authentication,
                    sensor_config=entry_configuration.sensor_config,
                    service_config=entry_configuration.service_config,
                    update_intervals=entry_configuration.update_intervals,
                )
            }
        )

    async def _show_form_reauth_confirm(self, errors: dict[str, str] | None = None):
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=self._authentication.username): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            description_placeholders={
                "host": self._authentication.host
            },
            errors=errors or {},
        )

    async def async_step_user(
            self, user_input: dict[str, Any] | None = None
    ):
        """Handle the initial step."""

        if user_input is None:
            return self._show_login_form()

        self._authentication = Authentication(
            host=user_input[CONF_HOST],
            username=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
        )

        if error := await self._validate_input():
            return self._show_login_form({"base": error})

        # Check if already configured
        await self.async_set_unique_id(user_input[CONF_HOST])
        self._abort_if_unique_id_configured()

        if user_input[CONF_ENABLE_SERVICE_CONTROLS]:
            return await self.async_step_services()

        return self.async_step_sensors()

    def _show_login_form(self, errors: dict[str, str] | None = None):
        return self.async_show_form(
            step_id="user",
            last_step=False,
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors or {},
        )

    async def async_step_sensors(
            self, user_input: dict[str, Any] | None = None
    ):
        """Handle the sensors configuration step."""

        if user_input is None:
            return self.async_show_form(
                step_id="sensors",
                last_step=False,
                data_schema=step_sensors_data_schema(),
                description_placeholders={
                    "host": self._authentication.host
                }
            )

        self._sensor_config = SensorConfig(
            wireless_software=user_input[CONF_WIRELESS_SOFTWARE],
            dhcp_software=user_input[CONF_DHCP_SOFTWARE],
            enable_system_sensors=user_input[CONF_ENABLE_SYSTEM_SENSORS],
            enable_qmodem_sensors=user_input[CONF_ENABLE_QMODEM_SENSORS],
            enable_sta_sensors=user_input[CONF_ENABLE_STATION_SENSORS],
            enable_ap_sensors=user_input[CONF_ENABLE_ACCESS_POINT_SENSORS],
            enable_service_controls=user_input[CONF_ENABLE_SERVICE_CONTROLS],
            enable_device_kick_buttons=user_input[CONF_ENABLE_DEVICE_KICK_BUTTONS],
        )

        return self.async_step_intervals()

    async def async_step_services(
            self, user_input: dict[str, Any] | None = None
    ):
        """Handle the services selection step."""

        if user_input is None:
            return self._show_services_form()

        self._service_config = ServiceConfig(user_input[CONF_SELECTED_SERVICES])

        return self.async_step_sensors()

    async def _show_services_form(self):
        errors: dict[str, str] = {}
        available_services: list[str] = []
        try:
            available_services = await self.get_services_list()
        except Exception as exc:
            _LOGGER.warning("Failed to get services list: %s", exc)
            errors["base"] = "cannot_get_services"
        else:
            if len(available_services) == 0:
                errors["base"] = "no_services_found"
        return self.async_show_form(
            step_id="services",
            last_step=False,
            data_schema=vol.Schema({
                vol.Optional(CONF_SELECTED_SERVICES, default=[]): cv.multi_select(
                    {service: service for service in available_services}
                ),
            }),
            errors=errors,
            description_placeholders={
                "host": self._authentication.host,
                "services_count": len(available_services)
            }
        )

    async def async_step_intervals(
            self, user_input: dict[str, Any] | None = None
    ):
        """Handle the interval configuration step."""

        if user_input is None:
            return self.async_show_form(
                step_id="intervals",
                last_step=True,
                data_schema=step_intervals_data_schema(),
                description_placeholders={
                    "host": self._authentication.host
                }
            )

        return self.async_create_entry(
            title=f"OpenWrt ubus {self._authentication.host}",
            data={
                CONF_SECTION_KEY: EntryConfiguration(
                    authentication=self._authentication,
                    sensor_config=self._sensor_config,
                    service_config=self._service_config,
                    update_intervals=UpdateIntervals(
                        system=timedelta(seconds=user_input[CONF_SYSTEM_SENSOR_INTERVAL]),
                        qmodem=timedelta(seconds=user_input[CONF_QMODEM_SENSOR_INTERVAL]),
                        statistic=timedelta(seconds=user_input[CONF_STATION_SENSOR_INTERVAL]),
                        access_points=timedelta(seconds=user_input[CONF_ACCESS_POINT_SENSOR_INTERVAL]),
                        services=timedelta(seconds=user_input[CONF_SERVICE_INTERVAL]),
                    )
                )
            }
        )


class OpenwrtUbusOptionsFlow(UbusFlow, OptionsFlowWithReload):
    """Handle options flow for OpenWrt ubus."""

    def __init__(self) -> None:
        """Initialize options flow."""
        super().__init__()
        self._available_services: list[str] = []

    async def async_step_init(
            self, user_input: dict[str, Any] | None = None
    ):
        """Manage the options."""
        if user_input is not None:
            # Check if we need to refresh services
            if user_input.get("refresh_services", False):
                return await self.async_step_services()

            return await self.create_entry_from_user_input(user_input)

        # Create form with all configurable options
        current_data: EntryConfiguration = self.config_entry.data[CONF_SECTION_KEY]
        (
            step_sensors_data_schema(current_data.sensor_config).
            extend(
                vol.Schema(

                ).
                extend(step_intervals_data_schema(current_data.update_intervals))
            )
            options_schema = vol.Schema(
            {
            vol.Optional(
            CONF_SYSTEM_SENSOR_INTERVAL,
            default=current_data.get(CONF_SYSTEM_SENSOR_INTERVAL, DEFAULT_SYSTEM_SENSOR_INTERVAL)
        ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
        vol.Optional(
            CONF_QMODEM_SENSOR_INTERVAL,
            default=current_data.get(CONF_QMODEM_SENSOR_INTERVAL, DEFAULT_QMODEM_SENSOR_INTERVAL)
        ): vol.All(vol.Coerce(int), vol.Range(min=30, max=600)),
        vol.Optional(
            CONF_STATION_SENSOR_INTERVAL,
            default=current_data.get(CONF_STATION_SENSOR_INTERVAL, DEFAULT_STATISTIC_SENSOR_INTERVAL)
        ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
        vol.Optional(
            CONF_ACCESS_POINT_SENSOR_INTERVAL,
            default=current_data.get(CONF_ACCESS_POINT_SENSOR_INTERVAL, DEFAULT_ACCESS_POINT_SENSOR_INTERVAL)
        ): vol.All(vol.Coerce(int), vol.Range(min=30, max=600)),
        vol.Optional("refresh_services", default=False): bool,
        }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            description_placeholders={
                "host": self.config_entry.data[CONF_HOST]
            }
        )

    async def async_step_services(
            self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle services configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            return await self.create_entry_from_user_input(user_input)

        # Get available services
        if not self._available_services:
            try:
                self._available_services = await self.get_services_list()
            except Exception as exc:
                _LOGGER.warning("Failed to get services list: %s", exc)
                errors["base"] = "cannot_get_services"

        if not self._available_services and not errors:
            errors["base"] = "no_services_found"

        # Create multi-select schema for services
        current_services = self.config_entry.data.get(CONF_SELECTED_SERVICES, [])
        services_schema = vol.Schema({})
        if self._available_services:
            services_schema = vol.Schema({
                vol.Optional(CONF_SELECTED_SERVICES, default=current_services): cv.multi_select(
                    {service: service for service in self._available_services}
                ),
            })

        return self.async_show_form(
            step_id="services",
            data_schema=services_schema,
            errors=errors,
            description_placeholders={
                "host": self.config_entry.data[CONF_HOST],
                "services_count": str(len(self._available_services)) if self._available_services else "0"
            }
        )

    async def create_entry_from_user_input(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        # Update config with selected services
        new_data = dict(self.config_entry.data)
        new_data.update(user_input)

        # Update the config entry
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=new_data
        )

        # Reload the integration
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)

        return self.async_create_entry(title="", data={})


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
