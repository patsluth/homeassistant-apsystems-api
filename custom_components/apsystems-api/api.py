import base64
import hashlib
import hmac
import json
import logging
import typing
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin
from uuid import uuid4
import argparse
import os

import requests
from logging import Logger, getLogger

class APSystemsApi:
    class ResponseException(Exception):
        pass

    @dataclass
    class SystemSummaryData:
        month: float
        year: float
        today: float
        lifetime: float

    @dataclass
    class ECUMinutelyEnergyData:
        today: float
        time: typing.List[str]
        power: typing.List[int]
        energy: typing.List[float]

        @property
        def latest_power(self) -> int:
            return self.power[-1]

        @property
        def latest_energy(self) -> float:
            return self.energy[-1]

    base_url: str = "https://api.apsystemsema.com:9282"
    api_app_id: str
    api_app_secret: str
    sid: str
    ecu_id: str
    logger: Logger

    def __init__(self, api_app_id: str, api_app_secret: str, sid: str, ecu_id: str, logger: Logger = None):
        self.api_app_id = api_app_id
        self.api_app_secret = api_app_secret
        self.sid = sid
        self.ecu_id = ecu_id
        self.logger = logger or getLogger(__name__)

    def _hmac_sha256(self, key: str, message: str) -> str:
        _hmac = hmac.new(key.encode(), message.encode(), hashlib.sha256)
        return base64.b64encode(_hmac.digest()).decode("utf-8")

    def _request_headers(self, request_method: str, requuest_path: str) -> str:
        X_CA_AppId = self.api_app_id
        X_CA_Timestamp = f"{int(round(datetime.now().timestamp()))}"
        X_CA_Nonce = uuid4().hex
        X_CA_Signature_Method = "HmacSHA256"
        X_CA_Signature = self._hmac_sha256(
            self.api_app_secret,
            "/".join(
                [
                    X_CA_Timestamp,
                    X_CA_Nonce,
                    X_CA_AppId,
                    requuest_path.split("/")[-1],
                    request_method.upper(),
                    X_CA_Signature_Method,
                ]
            ),
        )

        return {
            "content-type": "application/json",
            "x-ca-appid": X_CA_AppId,
            "x-ca-timestamp": X_CA_Timestamp,
            "x-ca-nonce": X_CA_Nonce,
            "x-ca-signature-method": X_CA_Signature_Method,
            "x-ca-signature": X_CA_Signature,
        }

    def system_summary(self) -> SystemSummaryData:
        request_path = "/user/api/v2/systems/summary/{sid}".format(sid=self.sid)
        self.logger.debug("request_path: %s", request_path)
        url = urljoin(self.base_url, request_path)
        headers = self._request_headers("GET", request_path)
        response = requests.get(url=url, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data["code"] != 0:
            raise APSystemsApi.ResponseException(
                "Non zero response code: {data}".format(data=json.dumps(data, indent=4))
            )
        return APSystemsApi.SystemSummaryData(**data["data"])

    # def system_energy(self) -> dict:
    #     request_path = "/user/api/v2/systems/energy/{sid}".format(sid=self.sid)
    #     url = urljoin(self.base_url, request_path)
    #     headers = self._request_headers("GET", request_path)
    #     response = requests.get(
    #         url=url,
    #         params=dict(
    #             energy_level="hourly",
    #             date_range=datetime.now().strftime("%Y-%m-%d")
    #         ),
    #         headers=headers
    #     )
    #     response.raise_for_status()
    #     print(response.headers)
    #     print(response.status_code)
    #     print(json.dumps(response.json(), indent=4))
    #     return response.json()

    # def system_devices_meter_period(self) -> dict:
    #     request_path = "/user/api/v2/systems/{sid}/devices/meter/period/{eid}".format(
    #         sid=self.sid,
    #         eid=self.ecu_id
    #     )
    #     url = urljoin(self.base_url, request_path)
    #     headers = self._request_headers("GET", request_path)
    #     response = requests.get(
    #         url=url,
    #         params=dict(
    #             energy_level="minutely",
    #             date_range=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    #         ),
    #         headers=headers
    #     )
    #     response.raise_for_status()
    #     print(response.headers)
    #     print(response.status_code)
    #     print(json.dumps(response.json(), indent=4))
    #     return response.json()

    # def ecu_summary(self) -> dict:
    #     request_path = "/user/api/v2/systems/{sid}/devices/ecu/summary/{eid}".format(
    #         sid=self.sid,
    #         eid=self.ecu_id
    #     )
    #     url = urljoin(self.base_url, request_path)
    #     headers = self._request_headers("GET", request_path)
    #     response = requests.get(
    #         url=url,
    #         headers=headers
    #     )
    #     response.raise_for_status()
    #     print(response.headers)
    #     print(response.status_code)
    #     print(json.dumps(response.json(), indent=4))
    #     return response.json()

    def ecu_minutely_energy(self) -> ECUMinutelyEnergyData:
        request_path = "/user/api/v2/systems/{sid}/devices/ecu/energy/{eid}".format(
            sid=self.sid, eid=self.ecu_id
        )
        url = urljoin(self.base_url, request_path)
        headers = self._request_headers("GET", request_path)
        response = requests.get(
            url=url,
            params=dict(
                energy_level="minutely",
                date_range=(datetime.now()).strftime("%Y-%m-%d"),
            ),
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        if data["code"] != 0:
            raise APSystemsApi.ResponseException(
                "Non zero response code: {data}".format(data=json.dumps(data, indent=4))
            )
        return APSystemsApi.ECUMinutelyEnergyData(**data["data"])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api_app_id", type=str, default=os.environ.get('APSYSTEMS_API_APP_ID'))
    parser.add_argument("--api_app_secret", type=str, default=os.environ.get('APSYSTEMS_API_APP_SECRET'))
    parser.add_argument("--sid", type=str, default=os.environ.get('APSYSTEMS_SID'))
    parser.add_argument("--ecu_id", type=str, default=os.environ.get('APSYSTEMS_ECU_ID'))
    args = parser.parse_args()

    api = APSystemsApi(
        api_app_id=args.api_app_id,
        api_app_secret=args.api_app_secret,
        sid=args.sid,
        ecu_id=args.ecu_id,
    )

    print("system_summary", api.system_summary())
    print("system_summary", api.ecu_minutely_energy())
    print("system_summary", api.ecu_minutely_energy().latest_power)
    print("system_summary", api.ecu_minutely_energy().latest_energy)
