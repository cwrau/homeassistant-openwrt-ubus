import aiohttp
import pytest

from custom_components.openwrt_ubus import ExtendedUbus

test_host = "router.lan.cwrau.de"
test_user = "homeassistant"
test_password = "WdFIGDDAx3cPlh5Yzz8sXirDHDeAai7nK3ho"


@pytest.mark.asyncio
async def test_file_read():
    async with aiohttp.ClientSession() as client:
        ubus = ExtendedUbus(
            test_host,
            test_user,
            test_password,
            client,
        )

        leases = await ubus.file_read("/tmp/dhcp.leases")
        conntrack_count = await ubus.get_conntrack_count()
        temps = await ubus.get_system_temperatures()
        assert True
