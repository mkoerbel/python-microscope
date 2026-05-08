#!/usr/bin/env python3

## Copyright (C) 2020 David Miguel Susano Pinto <carandraug@gmail.com>
## Copyright (C) 2020 Ian Dobbie <ian.dobbie@bioch.ox.ac.uk>
## Copyright (C) 2020 Mick Phillips <mick.phillips@gmail.com>
## Copyright (C) 2020 Tiago Susano Pinto <tiagosusanopinto@gmail.com>
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

import logging
import time

import serial

import microscope._utils
import microscope.abc

_logger = logging.getLogger(__name__)


class OmicronLaser(
    microscope._utils.OnlyTriggersBulbOnSoftwareMixin,
    microscope.abc.SerialDeviceMixin,
    microscope.abc.LightSource,
):
    """Omicron laser.

    Suite of Omicron lasers (LuxX, Led HUB, etc.)

    """

    laser_status = {
        0: "Error state: 1",
        1: "Laser ON",
        2: "Preheating",
        4: "Attention",
        6: "Laser enabled",
        7: "Key switch state: 1",
        8: "Toggle key switch!",
        9: "System powered",
        13: "External sensor connected",
    }

    def __init__(self, com=None, baud=500000, timeout=0.5, **kwargs):
        # laser controller must run at 500000 baud for USB connection, 8+1 bits,
        # no parity. no handshake
        # timeout shoudl be over 0.1 s, 0.5 s is safe
        super().__init__(**kwargs)
        self.connection = self._connect(com, baud, timeout)
        time.sleep(1)
        self.connection.reset_input_buffer()

        # Read Firmware
        self.model, self.device_id, self.firmware = self.ask_firmware()
        self.max_power_mW = float(self.ask("GMP"))
        self.power_mW = self.ask_power()
        self.operating_mode = self.ask("GOM")
        self.status = self.ask_actual_status()
        self.wavelength, self.spec_power = self.ask_specs()

    @staticmethod
    def _connect(com: str, baud: int, timeout: float,
                 max_attempts: int = 5, retry_delay: float = 2.0) -> serial.Serial:
        """Open *com* with up to *max_attempts* retries.

        Before each retry, the port is briefly opened and closed again to
        release any OS-level lock left by a previous connection.
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                conn = serial.Serial(
                    port=com,
                    baudrate=baud,
                    timeout=timeout,
                    stopbits=serial.STOPBITS_ONE,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                )
                _logger.info("Omicron: connected on %s (attempt %d/%d).", com, attempt, max_attempts)
                return conn
            except serial.SerialException as exc:
                last_exc = exc
                _logger.warning(
                    "Omicron: connection attempt %d/%d on %s failed: %s",
                    attempt, max_attempts, com, exc,
                )
                # Try to release any lingering OS lock on the port before retrying
                try:
                    stale = serial.Serial(port=com)
                    stale.close()
                except Exception:
                    pass
                if attempt < max_attempts:
                    time.sleep(retry_delay)
        raise serial.SerialException(
            f"Omicron: could not open {com} after {max_attempts} attempts."
        ) from last_exc

    def write(self, command: str) -> None:
        self.connection.write(("?" + command + "\r").encode('ascii'))
        time.sleep(0.5)

    def read(self) -> str:
        response = self.connection.read_all().decode('latin-1').strip()
        if "!UK" in response:
            return 'UK'
        else:
            return response

    def ask(self, command: str) -> str:
        """Send command and retrieve response."""
        #self.connection.reset_input_buffer()
        self.write(command)
        response = self.read()
        if response == 'UK':
            _logger.warning("Omicron: Laser responded with 'Unknown command' to command '%s'", command)
        response = response[4:]
        return response

    def ask_firmware(self) -> tuple:
        """Get the model, device ID and firmware version of the laser, returns a tuple (model, device_id, firmware)"""
        response = self.ask("GFw")
        response = response.split('§') # Remove the command echo
        model = response[0]
        device_id = int(response[1])
        firmware = float(response[2])
        return model, device_id, firmware

    def ask_actual_status(self) -> str:
        """Get the actual status of the laser. Return the binary status string."""
        response = self.ask("GAS")
        binary_status = format(int(response, 16), "b")[::-1]
        _logger.info("Omicron laser status:")
        for i in range(len(binary_status)):
            if binary_status[i] == '1':
                _logger.info("  %s", self.laser_status.get(i, "Undefined Status"))
        if binary_status[0] == '1':
            _logger.error("Omicron: Error state on laser!")
            # TODO: do follow up investigation
            failure_byte = self.ask("GFB")
            _logger.error("Omicron: Failure byte: %s", failure_byte)
        return binary_status

    def ask_specs(self) -> tuple:
        """Get the wavelength and the specified power in mW, returns a tuple (wavelength, spec_power)"""
        response = self.ask("GSI")
        response = response.split('§')
        wavelength = float(response[0])
        spec_power = float(response[1])
        return wavelength, spec_power

    def ask_power(self) -> float:
        """Get the current power value in mW"""
        power_hex = self.ask("GLP")
        power = int(power_hex, 16) * self.max_power_mW / 4095
        return power

    def set_power_mw(self, power) -> None:
        """Set the desired power in mW"""
        # Calculate the corresponding HEX code and transmit it
        if power > self.max_power_mW:
            _logger.warning(
                "Omicron: Requested power %.1f mW exceeds maximum %.1f mW; setting to maximum.",
                power, self.max_power_mW,
            )
            power = self.max_power_mW

        code = hex(int(4095*power/self.max_power_mW))[2:].upper().zfill(3)
        response = self.ask("SLP%s" % code)
        if response == '>':
            _logger.info("Omicron: Power set to %.1f mW.", power)
        elif response == 'x':
            _logger.error("Omicron: Failed to set power. Check if the laser is ON.")
        return power

    def laser_on(self) -> None:
        """Turn the laser ON. Return True if we succeeded, False otherwise."""
        response = self.ask("LOn")
        if response == '>':
            _logger.info("Omicron: Laser turned ON.")
        elif response == 'x':
            _logger.error("Omicron: Failed to turn ON. Check if the laser is ready.")
        #self.status = self.ask_actual_status()

    def laser_off(self) -> None:
        """Turn the laser OFF."""
        response = self.ask("LOf")
        if response == '>':
            _logger.info("Omicron: Laser turned OFF.")
        elif response == 'x':
            _logger.error("Omicron: Failed to turn OFF. Check if the laser is ready.")
        #self.status = self.ask_actual_status()

    def get_laser_status(self) -> bool:
        """Get the laser status, True if on."""
        if (self.status[1] == '1') & (self.status[6] == '1'):
            return True
        else:            
            return False

    def _do_shutdown(self) -> None:
        # Disable laser.
        self.laser_off()
        self.connection.close()

    def _do_get_power(self):
        return self.ask_power()
    
    def _do_set_power(self, power):
        return self.set_power_mw(power)
    
    def get_is_on(self):
        return self.get_laser_status()
    
    def get_status(self):
        return self.ask_actual_status()
    
    def _do_enable(self):
        return self.laser_on()
    
    def _do_disable(self):
        return self.laser_off()