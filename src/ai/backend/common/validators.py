'''
An extension module to Trafaret which provides additional type checkers.
'''

import datetime
import ipaddress
import os
from pathlib import Path as _Path
import re
from typing import Any, Mapping, Optional, Sequence, Tuple
import uuid
import pwd

import dateutil.tz
import multidict
import trafaret as t
from trafaret.base import TrafaretMeta
from trafaret.lib import _empty

from .types import (
    BinarySize as _BinarySize,
    HostPortPair as _HostPortPair,
)

__all__ = (
    'BinarySize',
    'HostPortPair',
    'Path',
    'PortRange',
    'UserID',
    'GroupID',
    'Slug',
)


class StringLengthMeta(TrafaretMeta):
    '''
    A metaclass that makes string-like trafarets to have sliced min/max length indicator.
    '''

    def __getitem__(cls, slice_):
        return cls(min_length=slice_.start, max_length=slice_.stop)


class AliasedKey(t.Key):
    '''
    An extension to trafaret.Key which accepts multiple aliases of a single key.
    When successfully matched, the returned key name is the first one of the given aliases
    or the renamed key set via ``to_name()`` method or the ``>>`` operator.
    '''

    def __init__(self, names: Sequence[str], **kwargs):
        super().__init__(names[0], **kwargs)
        self.names = names

    def __call__(self, data, context=None):
        for name in self.names:
            if name in data:
                key = name
                break
        else:
            key = None

        if key is None:  # not specified
            if self.default is not _empty:
                default = self.default() if callable(self.default) else self.default
                try:
                    result = self.trafaret(default, context=context)
                except t.DataError as inner_error:
                    yield self.get_name(), inner_error, self.names
                else:
                    yield self.get_name(), result, self.names
                return
            if not self.optional:
                yield self.get_name(), t.DataError(error='is required'), self.names
            # if optional, just bypass
        else:
            try:
                result = self.trafaret(data[key], context=context)
            except t.DataError as inner_error:
                yield key, inner_error, self.names
            else:
                yield self.get_name(), result, self.names


class MultiKey(t.Key):

    def get_data(self, data, default):
        if isinstance(data, (multidict.MultiDict, multidict.MultiDictProxy)):
            return data.getall(self.name, default)
        # fallback for plain dicts
        raw_value = data.get(self.name, default)
        if isinstance(raw_value, Sequence):
            # if plain dict already contains list of values, just return it.
            return raw_value
        # otherwise, wrap the value in a list.
        return [raw_value]


class BinarySize(t.Trafaret):

    def check_and_return(self, value: Any) -> _BinarySize:
        try:
            return _BinarySize.from_str(value)
        except ValueError:
            self._failure('value is not a valid binary size', value=value)


class Path(t.Trafaret):

    def __init__(self, *, type: str,
                 base_path: _Path = None,
                 auto_create: bool = False,
                 allow_nonexisting: bool = False,
                 allow_devnull: bool = False):
        super().__init__()
        self._type = type
        if auto_create and type != 'dir':
            raise TypeError('Only directory paths can be set auto-created.')
        self._base_path = base_path
        self._auto_create = auto_create
        self._allow_nonexisting = allow_nonexisting
        self._allow_devnull = allow_devnull

    def check_and_return(self, value: Any) -> _Path:
        try:
            p = _Path(value).resolve()
        except (TypeError, ValueError):
            self._failure('cannot parse value as a path', value=value)
        if self._base_path is not None:
            try:
                p.relative_to(self._base_path.resolve())
            except ValueError:
                self._failure('value is not in the base path', value=value)
        if self._type == 'dir':
            if self._auto_create:
                p.mkdir(parents=True, exist_ok=True)
            if not self._allow_nonexisting and not p.is_dir():
                self._failure('value is not a directory', value=value)
        elif self._type == 'file':
            if not self._allow_devnull and str(p) == os.devnull:
                # it may be not a regular file but a char-device.
                return p
            if not self._allow_nonexisting and not p.is_file():
                self._failure('value is not a regular file', value=value)
        return p


class IPNetwork(t.Trafaret):

    def check_and_return(self, value: Any) -> ipaddress._BaseNetwork:
        try:
            return ipaddress.ip_network(value)
        except ValueError:
            self._failure('Invalid IP network format', value=value)


class IPAddress(t.Trafaret):

    def check_and_return(self, value: Any) -> ipaddress._BaseAddress:
        try:
            return ipaddress.ip_address(value)
        except ValueError:
            self._failure('Invalid IP address format', value=value)


class HostPortPair(t.Trafaret):

    def __init__(self, *, allow_blank_host: bool = False):
        super().__init__()
        self._allow_blank_host = allow_blank_host

    def check_and_return(self, value: Any) -> Tuple[ipaddress._BaseAddress, int]:
        if isinstance(value, str):
            pair = value.rsplit(':', maxsplit=1)
            if len(pair) == 1:
                self._failure('value as string must contain both address and number', value=value)
            host, port = pair[0], pair[1]
        elif isinstance(value, Sequence):
            if len(value) != 2:
                self._failure('value as array must contain only two values for address and number', value=value)
            host, port = value[0], value[1]
        elif isinstance(value, Mapping):
            try:
                host, port = value['host'], value['port']
            except KeyError:
                self._failure('value as map must contain "host" and "port" keys', value=value)
        else:
            self._failure('urecognized value type', value=value)
        try:
            host = ipaddress.ip_address(host.strip('[]'))
        except ValueError:
            pass  # just treat as a string hostname
        if not self._allow_blank_host and not host:
            self._failure('value has empty host', value=value)
        try:
            port = t.Int[1:65535].check(port)
        except t.DataError:
            self._failure('port number must be between 1 and 65535', value=value)
        return _HostPortPair(host, port)


class PortRange(t.Trafaret):

    def check_and_return(self, value: Any) -> Tuple[int, int]:
        if isinstance(value, str):
            try:
                value = tuple(map(int, value.split('-')))
            except (TypeError, ValueError):
                self._failure('value as string should be a hyphen-separated pair of integers', value=value)
        elif isinstance(value, Sequence):
            if len(value) != 2:
                self._failure('value as array must contain only two values', value=value)
        else:
            self._failure('urecognized value type', value=value)
        try:
            min_port = t.Int[1:65535].check(value[0])
            max_port = t.Int[1:65535].check(value[1])
        except t.DataError:
            self._failure('each value must be a valid port number')
        if not (min_port < max_port):
            self._failure('first value must be less than second value', value=value)
        return min_port, max_port


class UserID(t.Trafaret):

    def __init__(self, *, default_uid: int = None):
        super().__init__()
        self._default_uid = default_uid

    def check_and_return(self, value: Any) -> int:
        if value is None:
            if self._default_uid is not None:
                return self._default_uid
            else:
                return os.getuid()
        elif isinstance(value, int):
            if value == -1:
                return os.getuid()
        elif isinstance(value, str):
            if not value:
                if self._default_uid is not None:
                    return self._default_uid
                else:
                    return os.getuid()
            try:
                value = int(value)
            except ValueError:
                try:
                    return pwd.getpwnam(value).pw_uid
                except KeyError:
                    self._failure('no such user in system', value=value)
            else:
                return self.check_and_return(value)
        else:
            self._failure('value must be either int or str', value=value)
        return value


class GroupID(t.Trafaret):

    def __init__(self, *, default_gid: int = None):
        super().__init__()
        self._default_gid = default_gid

    def check_and_return(self, value: Any) -> int:
        if value is None:
            if self._default_gid is not None:
                return self._default_gid
            else:
                return os.getgid()
        elif isinstance(value, int):
            if value == -1:
                return os.getgid()
        elif isinstance(value, str):
            if not value:
                if self._default_gid is not None:
                    return self._default_gid
                else:
                    return os.getgid()
            try:
                value = int(value)
            except ValueError:
                try:
                    return pwd.getpwnam(value).pw_gid
                except KeyError:
                    self._failure('no such group in system', value=value)
            else:
                return self.check_and_return(value)
        else:
            self._failure('value must be either int or str', value=value)
        return value


class UUID(t.Trafaret):

    def check_and_return(self, value: Any) -> uuid.UUID:
        try:
            if isinstance(value, str):
                return uuid.UUID(value)
            elif isinstance(value, bytes):
                return uuid.UUID(bytes=value)
            else:
                self._failure('value must be string or bytes', value=value)
        except ValueError:
            self._failure('cannot convert value to UUID', value=value)


class TimeZone(t.Trafaret):

    def check_and_return(self, value: Any) -> datetime.tzinfo:
        if not isinstance(value, str):
            self._failure('value must be string', value=value)
        tz = dateutil.tz.gettz(value)
        if tz is None:
            self._failure('value is not a known timezone', value=value)
        return tz


class Slug(t.Trafaret, metaclass=StringLengthMeta):

    _rx_slug = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?$')

    def __init__(self, *, min_length: Optional[int] = None, max_length: Optional[int] = None,
                 allow_dot: bool = False):
        super().__init__()
        self._allow_dot = allow_dot
        if min_length is not None and min_length < 0:
            raise TypeError('min_length must be larger than or equal to zero.')
        if max_length is not None and max_length < 0:
            raise TypeError('max_length must be larger than or equal to zero.')
        if max_length is not None and min_length is not None and min_length > max_length:
            raise TypeError('min_length must be less than or equal to max_length when both set.')
        self._min_length = min_length
        self._max_length = max_length

    def check_and_return(self, value: Any) -> str:
        if isinstance(value, str):
            if self._min_length is not None and len(value) < self._min_length:
                self._failure(f'value is too short (min length {self._min_length})', value=value)
            if self._max_length is not None and len(value) > self._max_length:
                self._failure(f'value is too long (max length {self._max_length})', value=value)
            if self._allow_dot and value.startswith('.'):
                checked_value = value[1:]
            else:
                checked_value = value
            m = type(self)._rx_slug.search(checked_value)
            if not m:
                self._failure('value must be a valid slug.', value=value)
        else:
            self._failure('value must be a string', value=value)
        return value