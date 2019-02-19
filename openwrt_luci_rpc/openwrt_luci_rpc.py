# -*- coding: utf-8 -*-

"""
Support for OpenWRT (luci) routers.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/device_tracker.luci/
"""

import requests
import json
import logging
from .constants import OpenWrtConstants
from .exceptions import InvalidLuciTokenError, \
    LuciRpcMethodNotFoundError, InvalidLuciLoginError, \
    LuciRpcUnknownError

log = logging.getLogger(__name__)


class OpenWrtLuciRPC:

    def __init__(self, host_url, username, password):
        """
        Initiate an API request with all parameters
        :param host_url: string
        :param username: string
        :param password: string
        """
        self.host_api_url = host_url
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.token = None
        self._refresh_token()

    def _refresh_token(self):
        """Get a new token."""
        self.token = self._get_token()

    def _get_token(self):
        """Get authentication token for the given configuration."""

        url = '{}/cgi-bin/luci/rpc/auth'.format(self.host_api_url)
        return self._call_json_rpc(url, 'login', self.username, self.password)

    def get_all_connected_devices(self):
        """Get details of all connected devices"""
        log.info("Checking for connected devices")

        sys_url = '{}/cgi-bin/luci/rpc/sys'.format(self.origin)
        ip_url = '{}/cgi-bin/luci/rpc/ip'.format(self.origin)

        try:
            if self.use_ip_neighbors_table:
                try:
                    # Newer OpenWRT releases (18.06+)
                    result = _req_json_rpc(
                        ip_url, 'neighbors', {"family": 4},
                        params={'auth': self.token})
                except LuciRpcMethodNotFoundError:
                    # This is normal for older OpenWRT (pre-18.06)
                    log.warn('method neighbors not found. '
                                 'Will try older net.arptable instead')
                    self.use_ip_neighbors_table = False
                    return False
            else:
                try:
                    # Older OpenWRT releases (pre-18.06)
                    result = _req_json_rpc(
                        sys_url, 'net.arptable', params={
                            'auth': self.token})
                except LuciRpcMethodNotFoundError:
                    # This is normal for newer OpenWRT (18.06+)
                    log.warn('method net.arptable not found. '
                                 'Will try ip neighbors instead')
                    self.use_ip_neighbors_table = True
                    return False
        except InvalidLuciTokenError:
            log.info("Refreshing token")
            self.refresh_token()
            return False

        if result:
            for device_entry in result:
                log.info('device_entry. %s', device_entry)

                if "Flags" in device_entry:
                    # Older OpenWRT releases (pre-18.06)
                    #
                    # Check if the Flags for each device contain
                    # NUD_REACHABLE and if so, add it to last_results
                    if int(device_entry['Flags'], 16) & 0x2:
                        self.last_results.append(device_entry['HW address'])
                elif "reachable" in device_entry and "mac" in device_entry:
                    # Newer OpenWRT releases (18.06+)
                    #
                    # Do not use `reachable` or `stale` values
                    # as they flap constantly even
                    # when the device is inside the network.
                    # The very existence of the mac in the results
                    # is enough to determine the "device is home"
                    if device_entry['reachable']:
                        self.last_results.append(device_entry['mac'])

            return True

        return False

    def _call_json_rpc(self, url, method, *args, **kwargs):
        """Perform one JSON RPC operation."""
        data = json.dumps({'method': method, 'params': args})

        log.info("_call_json_rpc : %s" % url)
        res = self.session.post(url,
                                data=data,
                                timeout=OpenWrtConstants.DEFAULT_TIMEOUT,
                                **kwargs)

        if res.status_code == 200:
            result = res.json()
            try:
                token = result['result']

                if token is not None:
                    log.info("Luci RPC login was successful")
                    return token

                elif result['error'] is not None:
                    # On 18.06, we want to check for error 'Method not Found'
                    error_message = result['error']['message']
                    error_code = result['error']['code']
                    if error_code == -32601:
                        raise LuciRpcMethodNotFoundError(
                            "method: '%s' returned an "
                            "error '%s' (code: '%s).",
                            method, error_message, error_code)
                else:
                    log.debug("method: '%s' returned : %s" % (method, result))
                    # Authentication error
                    raise InvalidLuciLoginError("Failed to authenticate "
                                                "with Luci RPC, check your "
                                                "username and password.")

            except KeyError:
                raise LuciRpcUnknownError("No result in response from luci")

        elif res.status_code == 401:
            raise InvalidLuciLoginError("Failed to authenticate "
                                        "with Luci RPC, check your "
                                        "username and password.")
        elif res.status_code == 403:
            raise InvalidLuciTokenError("Luci responded "
                                        "with a 403 Invalid token")

        else:
            raise LuciRpcUnknownError("Invalid response from luci: %s", res)
