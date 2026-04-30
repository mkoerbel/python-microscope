#!/usr/bin/env python3

## Copyright (C) 2021 David Miguel Susano Pinto <carandraug@gmail.com>
## Copyright (C) 2026 Markus Koerbel <markus.koerbel@embl.de>
##
## This file is part of Microscope.
##
## Microscope is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
##
## Microscope is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with Microscope.  If not, see <http://www.gnu.org/licenses/>.

"""Yokogawa CSU spinning disk confocal controllers."""

import threading
from typing import Dict, Mapping, Optional

import serial

import microscope
import microscope.abc


_DEFAULT_COMMANDS = {
	"set_spinning_disk_stop": "MS_STOP",
	"set_spinning_disk_run": "MS_RUN", 
	"get_spinning_disk_speed": "MS, ?",
	"set_spinning_disk_speed": "MS, {speed}", # int
	"set_spinning_disk_to_exposure": "MS_ADJUST, {exposure}", # float
	"get_spinning_disk_max_speed": "MS_MAX, ?",
	"get_filterwheel_position": "FW_POS, 2, ?", # needs to be set to FW channel, get with "SYSTEM, ?"
	"set_filterwheel_position": "FW_POS, 2, {position}", # int
	"get_filterwheel_info": "FW_INFO, 2, {position}, ?", # int
	"get_dichroic_position": "DM_POS, ?",
	"set_dichroic_position": "DM_POS, {position}", # int
	"get_shutter_state": "SH, ?",
	"set_shutter_open": "SHO",
	"set_shutter_close": "SHC",
	"get_spinning_disk_hardware_connections": "SYSTEM, ?",
	"set_spinning_disk_serial_number": "SERIAL_CSU, ?",
}


class _YokogawaCSUConnection:
	"""Low-level serial connection for Yokogawa CSU commands."""

	def __init__(
		self,
		port: str,
		baudrate: int,
		timeout: float,
		command_map: Optional[Mapping[str, str]] = None,
	) -> None:
		self._serial = serial.Serial(
			port=port,
			baudrate=baudrate,
			timeout=timeout,
			bytesize=serial.EIGHTBITS,
			stopbits=serial.STOPBITS_ONE,
			parity=serial.PARITY_NONE,
		)
		self._lock = threading.RLock()
		self._commands = dict(_DEFAULT_COMMANDS)
		if command_map is not None:
			self._commands.update(command_map)
		self.max_disk_speed = self.get_spinning_disk_max_speed()

	def _require_command(self, name: str) -> str:
		cmd = self._commands.get(name)
		if cmd is None or not cmd.strip():
			raise microscope.UnsupportedFeatureError(
				"No command configured for '%s'" % name
			)
		return cmd

	def _send(self, command: str) -> str:
		with self._lock:
			self._serial.write(command.encode("ascii") + b"\r")
			answer = self._serial.read_until(b"\r").decode("ascii").strip()
			for suffix in (":A", ":N"):
				if answer.endswith(suffix):
					return answer[: -len(suffix)].rstrip()
			return answer

	@staticmethod
	def _state_token(state: bool) -> str:
		return "ON" if state else "OFF"

	@staticmethod
	def _parse_bool(value: str) -> bool:
		token = value.strip().upper()
		if token in ("1", "ON", "OPEN", "TRUE"):
			return True
		if token in ("0", "OFF", "CLOSE", "CLOSED", "FALSE"):
			return False
		raise microscope.DeviceError("unexpected boolean answer '%s'" % value)

	@staticmethod
	def _parse_int(value: object, name: str) -> int:
		if isinstance(value, bool):
			raise ValueError("%s must be an integer, got bool" % name)
		if isinstance(value, int):
			if value < 0:
				raise ValueError("%s must be a positive integer" % name)
			return value
		if isinstance(value, str):
			token = value.strip()
			if token.isdigit():
				return int(token)
		raise ValueError("%s must be a positive integer" % name)

	def initialize(self) -> None:
		cmd = self._require_command("set_spinning_disk_stop")
		self._send(cmd)

	def get_spinning_disk_enabled(self) -> bool:
		return self.get_spinning_disk_speed() > 0

	def set_spinning_disk_enabled(self, enabled: bool) -> None:
		command_name = (
			"set_spinning_disk_run" if enabled else "set_spinning_disk_stop"
		)
		self._send(self._require_command(command_name))

	def get_spinning_disk_speed(self) -> int:
		cmd = self._require_command("get_spinning_disk_speed")
		answer = self._send(cmd)
		try:
			return self._parse_int(answer, "spinning disk speed")
		except ValueError:
			raise microscope.DeviceError(
				"unexpected speed answer '%s'" % answer
			)

	def set_spinning_disk_speed(self, speed: int) -> None:
		if speed > self.max_disk_speed:
			speed = self.max_disk_speed
		template = self._require_command("set_spinning_disk_speed")
		self._send(
			template.format(speed=self._parse_int(speed, "spinning disk speed"))
		)
	
	def set_spinning_disk_speed_to_exposure(self, exposure: float) -> None:
		template = self._require_command("set_spinning_disk_to_exposure")
		self._send(
			template.format(exposure=exposure)
		)

	def get_spinning_disk_max_speed(self) -> int:
		cmd = self._require_command("get_spinning_disk_max_speed")
		answer = self._send(cmd)
		try:
			return self._parse_int(answer, "spinning disk max speed")
		except ValueError:
			raise microscope.DeviceError(
				"unexpected max speed answer '%s'" % answer
			)

	def get_filterwheel_position(self) -> int:
		cmd = self._require_command("get_filterwheel_position")
		answer = self._send(cmd)
		try:
			return self._parse_int(answer, "filter wheel position")
		except ValueError:
			raise microscope.DeviceError(
				"unexpected filter wheel position answer '%s'" % answer
			)

	def set_filterwheel_position(self, position: int) -> None:
		template = self._require_command("set_filterwheel_position")
		self._send(
			template.format(
				position=self._parse_int(position, "filter wheel position")
			)
		)

	def get_filterwheel_info(self, position: int) -> str:
		template = self._require_command("get_filterwheel_info")
		return self._send(
			template.format(
				position=self._parse_int(position, "filter wheel position")
			)
		)

	def get_dichroic_position(self) -> int:
		cmd = self._require_command("get_dichroic_position")
		answer = self._send(cmd)
		try:
			return self._parse_int(answer, "dichroic mirror position")
		except ValueError:
			raise microscope.DeviceError(
				"unexpected dichroic mirror position answer '%s'" % answer
			)

	def set_dichroic_position(self, position: int) -> None:
		template = self._require_command("set_dichroic_position")
		self._send(
			template.format(
				position=self._parse_int(position, "dichroic mirror position")
			)
		)

	def get_shutter_open(self) -> bool:
		cmd = self._require_command("get_shutter_state")
		return self._parse_bool(self._send(cmd))

	def set_shutter_open(self, is_open: bool) -> None:
		command_name = "set_shutter_open" if is_open else "set_shutter_close"
		self._send(self._require_command(command_name))

class _YokogawaCSUSpinningDisk(microscope.abc.Device):
	"""Spinning disk controls."""

	def __init__(
		self, connection: _YokogawaCSUConnection
	) -> None:
		super().__init__()
		self._conn = connection
		self.add_setting(
			"enabled",
			"bool",
			self.get_enabled,
			self.set_enabled,
			None,
		)
		self.add_setting(
			"speed",
			"int",
			self.get_speed,
			self.set_speed,
			(0, self._conn.get_spinning_disk_max_speed()),
		)

	def get_enabled(self) -> bool:
		return self._conn.get_spinning_disk_enabled()

	def set_enabled(self, enabled: bool) -> None:
		self._conn.set_spinning_disk_enabled(enabled)

	def get_speed(self) -> int:
		return self._conn.get_spinning_disk_speed()

	def set_speed(self, speed: int) -> None:
		self._conn.set_spinning_disk_speed(speed)
		
	def set_speed_auto(self, exposure: float) -> None:
		"""Set the spinning disk speed automatically based on the exposure time."""
		self._conn.set_spinning_disk_speed_to_exposure(exposure)

	def _do_shutdown(self) -> None:
		pass


class _YokogawaCSUFilterWheel(microscope.abc.FilterWheel):
	"""Filter wheel controlled by a Yokogawa CSU."""

	def __init__(
		self, connection: _YokogawaCSUConnection, positions: int
	) -> None:
		super().__init__(positions=positions)
		self._conn = connection

	def _do_get_position(self) -> int:
		return self._conn.get_filterwheel_position()

	def _do_set_position(self, position: int) -> None:
		self._conn.set_filterwheel_position(position)

	def get_info(self, position: Optional[int] = None) -> str:
		if position is None:
			position = self._conn.get_filterwheel_position()
		return self._conn.get_filterwheel_info(position)

	def _do_shutdown(self) -> None:
		pass


class _YokogawaCSUDichroicMirror(microscope.abc.FilterWheel):
	"""Dichroic mirror turret controlled by a Yokogawa CSU."""

	def __init__(
		self, connection: _YokogawaCSUConnection, positions: int
	) -> None:
		super().__init__(positions=positions)
		self._conn = connection

	def _do_get_position(self) -> int:
		return self._conn.get_dichroic_position()

	def _do_set_position(self, position: int) -> None:
		self._conn.set_dichroic_position(position)

	def _do_shutdown(self) -> None:
		pass


class _YokogawaCSUShutter(microscope.abc.Device):
	"""Shutter controls."""

	def __init__(self, connection: _YokogawaCSUConnection) -> None:
		super().__init__()
		self._conn = connection
		self.add_setting(
			"open",
			"bool",
			self.is_open,
			self.set_open,
			None,
		)

	def is_open(self) -> bool:
		return self._conn.get_shutter_open()

	def set_open(self, is_open: bool) -> None:
		self._conn.set_shutter_open(is_open)

	def open(self) -> None:
		self.set_open(True)

	def close(self) -> None:
		self.set_open(False)

	def _do_shutdown(self) -> None:
		pass


class YokogawaCSU(microscope.abc.Controller):
	"""Controller for Yokogawa CSU systems."""

	def __init__(
		self,
		port: str,
		baudrate: int = 115200,
		timeout: float = 1.0,
		filterwheel_positions: int = 6,
		dichroic_positions: int = 3,
		command_map: Optional[Mapping[str, str]] = None,
		**kwargs,
	) -> None:
		super().__init__(**kwargs)
		self._conn = _YokogawaCSUConnection(
			port=port,
			baudrate=baudrate,
			timeout=timeout,
			command_map=command_map,
		)
		self._devices: Dict[str, microscope.abc.Device] = {
			"spinning_disk": _YokogawaCSUSpinningDisk(
				self._conn,
			),
			"filterwheel": _YokogawaCSUFilterWheel(
				self._conn, positions=filterwheel_positions
			),
			"dichroic_mirror": _YokogawaCSUDichroicMirror(
				self._conn, positions=dichroic_positions
			),
			"shutter": _YokogawaCSUShutter(self._conn),
		}

	@property
	def devices(self) -> Mapping[str, microscope.abc.Device]:
		return self._devices

	def initialize(self) -> None:
		self._conn.initialize()
