"""Client for the OpenWrt ubus API."""

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, TypeVar, Generic

from aiohttp import ClientSession

from .const import (
    API_DEF_SESSION,
    API_ERROR,
    API_MESSAGE,
    API_METHOD_LOGIN,
    API_PARAM_PASSWORD,
    API_PARAM_USERNAME,
    API_RESULT,
    API_RPC_CALL,
    API_RPC_VERSION,
    API_SUBSYS_SESSION,
    API_UBUS_RPC_SESSION,
    HTTP_STATUS_OK, API_UBUS_STATUS_PERMISSION_DENIED, API_ERROR_CODE, API_ID, API_UBUS_RPC_SESSION_EXPIRES,
)

_LOGGER = logging.getLogger(__name__)


class RPCResponseResult(ABC):
    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> "RPCResponseResult":
        pass


RPCResponseT = TypeVar("RPCResponseT", bound=RPCResponseResult)


class RPCResponse(Generic[RPCResponseT]):
    code: int

    def __init__(self, json_response: dict[str, Any], t_cls: type[RPCResponseT]):
        self.id: int | None = json_response[API_ID]
        self.result: RPCResponseT | None = None
        self.error: str | None = None

        if API_RESULT in json_response:
            result: list[Any] | dict[str, Any] = json_response[API_RESULT]
            if isinstance(result, list):
                self.code = result[0]
                self.result = t_cls.from_dict(result[1])
            elif isinstance(result, dict):
                self.code = 0
                self.result = t_cls.from_dict(result)
            else:
                self.code = -1
                self.error = "Invalid result format"
        elif API_ERROR in json_response:
            error: dict = json_response[API_ERROR]
            self.code = error[API_ERROR_CODE]
            self.error = error[API_MESSAGE]
        else:
            self.code = -1
            self.error = "No result or error in response"


class RPC(Generic[RPCResponseT]):
    def __init__(self,
                 r_cls: type[RPCResponseT],
                 rpc_method: str,
                 subsystem: str,
                 method: str | None = None,
                 params: dict | None = None,
                 ):
        self.r_cls = r_cls
        _params: list[Any] = [subsystem]
        if rpc_method == API_RPC_CALL:
            if method:
                _params.append(method)

            if params:
                _params.append(params)
            else:
                _params.append({})
        self._method = rpc_method
        self._params = _params

    def parse_response_from_dict(self, json_response: dict[str, Any]) -> RPCResponse[RPCResponseT]:
        return RPCResponse(json_response, self.r_cls)

    def to_json(self, session: str, rpc_id: int | None = None) -> str:
        data: dict[str, Any] = {
            "jsonrpc": API_RPC_VERSION,
            "method": self._method,
            "params": [session] + self._params,
        }

        if rpc_id is not None:
            data["id"] = rpc_id

        return json.dumps(data)


class LoginResponse(RPCResponseResult):
    def __init__(self, session: str, session_expires: float):
        self.session = session
        self.session_expires = session_expires

    @classmethod
    def from_dict(cls, data: dict) -> "LoginResponse":
        return LoginResponse(
            session=data.get(API_UBUS_RPC_SESSION, ""),
            session_expires=time.time() + int(data.get(API_UBUS_RPC_SESSION_EXPIRES, 0)),
        )


class Authentication:
    def __init__(self, host: str, username: str, password: str):
        self.host = host
        self.username = username
        self.password = password


class Ubus:
    """Interacts with the OpenWrt ubus API."""

    def __init__(
            self,
            authentication: Authentication,
            client: ClientSession | None = None,
    ):
        """Init OpenWrt ubus API."""
        self._authentication = authentication
        self._client = client  # Session will be provided externally

        self._session = None
        self._session_expires: float = 0

    async def _ensure_session_is_valid(self):
        """Ensure session is still valid"""
        if self._session_expires <= (time.time() - 15):
            await self.connect()

    async def api_call(
            self,
            r_cls: type[RPCResponseT],
            rpc_method: str,
            subsystem: str,
            method: str | None = None,
            params: dict | None = None,
    ) -> RPCResponseT | None:
        await self._ensure_session_is_valid()
        return await self._api_call(r_cls, rpc_method, subsystem, method, params)

    async def _api_call(
            self,
            r_cls: type[RPCResponseT],
            rpc_method: str,
            subsystem: str,
            method: str | None = None,
            params: dict | None = None,
    ) -> RPCResponseT | None:
        return await self._api_call_rpc(RPC(r_cls, rpc_method, subsystem, method, params))

    async def _api_call_rpc(self, rpc: RPC[RPCResponseT]) -> RPCResponseT | None:
        response = await self._client.post(
            f"https://{self._authentication.host}/ubus", data=rpc.to_json(self._session)
        )

        if response.status != HTTP_STATUS_OK:
            return None

        json_response = await response.json()

        rpc_response = rpc.parse_response_from_dict(json_response)

        if rpc_response.code == API_UBUS_STATUS_PERMISSION_DENIED:
            raise PermissionError("Permission denied")

        if rpc_response.error is not None:
            if rpc_response.error == "Access denied":
                raise PermissionError(rpc_response.error)
            raise ConnectionError(rpc_response.error)

        return rpc_response.result

    async def connect(self):
        """Connect to OpenWrt ubus API."""
        self._session = API_DEF_SESSION
        self._session_expires = 0

        login = await self._api_call(
            LoginResponse,
            API_RPC_CALL,
            API_SUBSYS_SESSION,
            API_METHOD_LOGIN,
            {
                API_PARAM_USERNAME: self._authentication.username,
                API_PARAM_PASSWORD: self._authentication.password,
            },
        )
        if login:
            self._session = login.session
            self._session_expires = login.session_expires
        else:
            self._session = None

        return self._session
