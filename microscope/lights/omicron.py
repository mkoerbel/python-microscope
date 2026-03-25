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
        0: "Error state",
        1: "Laser ON",
        2: "Preheating",
        4: "Attention",
        6: "Laser enabled",
        7: "Key switch state",
        8: "Toggle key switch",
        9: "System power",
        13: "External sensor connected",
    }

    def __init__(self, com=None, baud=500000, timeout=0.5, **kwargs):
        # laser controller must run at 500000 baud for USB connection, 8+1 bits,
        # no parity. no handshake
        # timeout shoudl be over 0.1 s, 0.5 s is safe
        super().__init__(**kwargs)
        self.connection = serial.Serial(
            port=com,
            baudrate=baud,
            timeout=timeout,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
        )
        time.sleep(timeout)
        self.connection.reset_input_buffer()

        # Read Firmware
        self.model, self.device_id, self.firmware = self.ask_firmware()
        self.max_power_mW = float(self.ask("GMP"))
        self.power_mW = float(self.ask("GLP"))
        self.operating_mode = self.ask("GOM")
        self.status = self.ask_actual_status()
        self.wavelength, self.spec_power = self.ask_specs()

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
        self.connection.reset_input_buffer()
        self.write(command)
        response = self.read()
        if response == 'UK':
            print("Laser responded with 'Unknown command' to command '%s'" % command)
        response = response[len(command)+1:]
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
        for i in range(len(binary_status)):
            if binary_status[i] == '1':
                print(self.laser_status.get(i, "Undefined Status"))
        if binary_status[0] == '1':
            print("Error state on laser!")
            # TODO: do follow up investigation
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

    def set_power(self, power) -> None:
        """Set the desired power in mW"""
        # Calculate the corresponding HEX code and transmit it
        if power > self.max_power_mW:
            print("Laser provides %imW only. The maximum power is set" % self.max_power_mW)
            self.write("SLPFFF")
        else:
            code = hex(int(4095*power/self.max_power_mW))[2:].upper().zfill(3)
            response = self.ask("SLP%s" % code)
            if response == '>':
                print("Power set to %imW" % power)
            elif response == 'x':
                print("Failed to set power. Check if the laser is ON.")
        self.status = self.ask_actual_status()

    def laser_on(self) -> None:
        """Turn the laser ON. Return True if we succeeded, False otherwise."""
        response = self.ask("LOn")
        if response == '>':
            print("Laser turned ON.")
        elif response == 'x':
            print("Failed to turn on. Check if the laser is ready.")
        self.status = self.ask_actual_status()

    def laser_off(self) -> None:
        """Turn the laser OFF."""
        response = self.ask("LOf")
        if response == '>':
            print("Laser turned OFF.")
        elif response == 'x':
            print("Failed to turn off. Check if the laser is ready.")
        self.status = self.ask_actual_status()

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
        return self.set_power(power)
    
    def get_is_on(self):
        return self.get_laser_status()
    
    def get_status(self):
        return self.ask_actual_status()
    