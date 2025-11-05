"""Shared data manager for OpenWrt ubus API calls to reduce router load."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from enum import auto, IntFlag

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .Ubus.interface import Authentication
from .config_flow import UpdateIntervals
from .const import (
    CONF_DHCP_SOFTWARE,
    CONF_WIRELESS_SOFTWARE,
)
from .extended_ubus import ExtendedUbus, SystemInfo, BoardInfo, QModemInfo, DeviceStatistics, AccessPointsInfo, \
    ServiceStatus, SystemTemperatures

_LOGGER = logging.getLogger(__name__)


class UbusDataType(IntFlag):
    SYSTEM_INFO = auto()
    SYSTEM_BOARD = auto()
    QMODEM_INFO = auto()
    DEVICE_STATISTICS = auto()
    ACCESS_POINTS_INFO = auto()
    SERVICE_STATUS = auto()
    HOSTAPD_CLIENTS = auto()
    HOSTAPD_AVAILABLE = auto()
    CONNTRACK_COUNT = auto()
    SYSTEM_TEMPERATURES = auto()
    DHCP_CLIENTS_COUNT = auto()


SYSTEM_INFO = UbusDataType.SYSTEM_INFO
SYSTEM_BOARD = UbusDataType.SYSTEM_BOARD
QMODEM_INFO = UbusDataType.QMODEM_INFO
DEVICE_STATISTICS = UbusDataType.DEVICE_STATISTICS
ACCESS_POINTS_INFO = UbusDataType.ACCESS_POINTS_INFO
SERVICE_STATUS = UbusDataType.SERVICE_STATUS
HOSTAPD_CLIENTS = UbusDataType.HOSTAPD_CLIENTS
HOSTAPD_AVAILABLE = UbusDataType.HOSTAPD_AVAILABLE
CONNTRACK_COUNT = UbusDataType.CONNTRACK_COUNT
SYSTEM_TEMPERATURES = UbusDataType.SYSTEM_TEMPERATURES
DHCP_CLIENTS_COUNT = UbusDataType.DHCP_CLIENTS_COUNT


class SharedUbusDataManager:
    """Shared data manager for ubus API calls to reduce router load."""

    class DataCache:
        system_info: SystemInfo | None = None
        board_info: BoardInfo | None = None
        qmodem_info: QModemInfo | None = None
        device_statistics: DeviceStatistics | None = None
        acesspoint_info: AccessPointsInfo | None = None
        service_status: ServiceStatus | None = None
        hostapd_available: bool | None = None
        conntrack_count: int | None = None
        system_temperatures: SystemTemperatures | None = None
        dhcp_clients_count: int | None = None

    def __init__(
            self, hass: HomeAssistant,
            authentication: Authentication, update_intervals: UpdateIntervals,
            wireless_software: str = CONF_WIRELESS_SOFTWARE,
            dhcp_software: str = CONF_DHCP_SOFTWARE,
    ) -> None:
        """Initialize the shared data manager."""
        self._authentication = authentication
        self._wireless_software = wireless_software
        self._dhcp_software = dhcp_software
        self._data_cache: SharedUbusDataManager.DataCache = self.DataCache()
        self._last_update: dict[UbusDataType, float] = {
            key: 0 for key in UbusDataType
        }

        self._update_intervals: dict[UbusDataType, timedelta] = {
            SYSTEM_INFO: update_intervals.system,
            # Board info changes less frequently
            SYSTEM_BOARD: update_intervals.system * 2,
            QMODEM_INFO: update_intervals.qmodem,
            DEVICE_STATISTICS: update_intervals.statistic,
            HOSTAPD_CLIENTS: update_intervals.statistic,
            ACCESS_POINTS_INFO: update_intervals.access_points,
            SERVICE_STATUS: update_intervals.services,
            # Very long cache - hostapd availability rarely changes
            HOSTAPD_AVAILABLE: timedelta(minutes=30),
            CONNTRACK_COUNT: update_intervals.system,
            SYSTEM_TEMPERATURES: update_intervals.system,
            DHCP_CLIENTS_COUNT: update_intervals.statistic,
        }
        self._update_locks: dict[UbusDataType, asyncio.Lock] = {
            key: asyncio.Lock() for key in self._update_intervals
        }

        # Initialize ubus clients
        self._ubus_clients: dict[str, ExtendedUbus] = {}
        self._session = async_get_clientsession(hass)

    async def _get_ubus_client(self, client_type: str) -> ExtendedUbus:
        """Get or create ubus client instance."""
        if client_type not in self._ubus_clients:
            client = ExtendedUbus(self._authentication, client=self._session)

            # Connect to the client
            try:
                if await client.connect() is None:
                    raise UpdateFailed(f"Failed to connect to OpenWrt device")
                self._ubus_clients[client_type] = client
            except Exception as exc:
                _LOGGER.error("Failed to connect ubus client %s: %s", client_type, exc)
                raise UpdateFailed(f"Failed to connect ubus client {client_type}") from exc

        return self._ubus_clients[client_type]

    def _should_update(self, data_type: UbusDataType) -> bool:
        """Check if data should be updated based on interval."""
        return time.time() - self._last_update[data_type] > self._update_intervals[data_type].total_seconds()

    async def _fetch_system_data_batch(self) -> tuple[SystemInfo, BoardInfo]:
        """Fetch system data in batch with auto-reconnect protection."""
        client = await self._get_ubus_client("system")

        if self._should_update(SYSTEM_INFO):
            async with self._update_locks[SYSTEM_INFO]:
                self._data_cache.system_info = await client.system_info()  # Store raw data
                self._last_update[SYSTEM_INFO] = time.time()
        if self._should_update(SYSTEM_BOARD):
            async with self._update_locks[SYSTEM_BOARD]:
                self._data_cache.board_info = await client.system_board()  # Store raw data
                self._last_update[SYSTEM_BOARD] = time.time()

        return self._data_cache.system_info, self._data_cache.board_info

    async def update_data(self, data_type: UbusDataType) -> SharedData:
        """Get multiple data types in a single call to optimize API usage."""
        data = SharedData()

        # Fetch system data together if needed
        if SYSTEM_INFO in data_type or SYSTEM_BOARD in data_type:
            data_type &= ~SYSTEM_INFO
            data_type &= ~SYSTEM_BOARD
            system_data = await self._fetch_system_data_batch()
            data.system_info = system_data[0]
            data.board_info = system_data[1]

        # Fetch other data types individually
        for data_type in data_type:
            try:
                data = await self.get_data(data_type)
                data.update(data)
            except Exception as exc:
                _LOGGER.error("Error fetching %s: %s", data_type, exc)

        return data

    async def close(self):
        """Close all ubus client connections."""
        for client in self._ubus_clients.values():
            try:
                await client.close()
            except Exception as exc:
                _LOGGER.debug("Error closing ubus client: %s", exc)
        self._ubus_clients.clear()

    def invalidate_cache(self, data_type: str = None):
        """Invalidate cache for specific data type or all data."""
        if data_type:
            self._data_cache.pop(data_type, None)
            self._last_update.pop(data_type, None)
        else:
            self._data_cache.clear()
            self._last_update.clear()


class SharedData:
    system_info: SystemInfo | None = None
    board_info: BoardInfo | None = None


class SharedDataUpdateCoordinator(DataUpdateCoordinator[SharedData]):
    """Coordinator that uses shared data manager."""

    def __init__(
            self,
            hass: HomeAssistant,
            data_manager: SharedUbusDataManager,
            data_type: UbusDataType,
            name: str,
            update_interval: timedelta,
    ):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=update_interval,
        )
        self.data_manager = data_manager
        self.data_type = data_type

    async def _async_update_data(self) -> SharedData:
        """Fetch data using shared manager."""
        try:
            return await self.data_manager.update_data(self.data_type)
        except Exception as exc:
            raise UpdateFailed("Error communicating with API") from exc

    async def async_shutdown(self):
        """Shutdown the coordinator."""
        # Note: Don't close the data manager here as it might be shared
        # The data manager will be closed when the integration is unloaded
        pass
