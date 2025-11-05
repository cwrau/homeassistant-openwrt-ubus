import aiohttp
import pytest

from custom_components.openwrt_ubus.Ubus import Ubus

test_host = "router.lan.cwrau.de"
test_user = "homeassistant"
test_password = "WdFIGDDAx3cPlh5Yzz8sXirDHDeAai7nK3ho"


@pytest.mark.asyncio
async def test_api_call():
    async with aiohttp.ClientSession() as client:
        ubus = Ubus(
            test_host,
            test_user,
            test_password,
            client,
        )

        await ubus.connect()
