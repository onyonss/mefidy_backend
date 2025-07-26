import serial
import time
from django.conf import settings

class FingerprintReader:
    def __init__(self, port='COM6', baudrate=115200):
        print(f"Initializing FingerprintReader on {port} at {baudrate} baud")
        self.ser = serial.Serial(port, baudrate, timeout=1)
        self.ser.flushInput()  # Clear input buffer
        self.ser.flushOutput()  # Clear output buffer
        time.sleep(2)  # Wait for ESP8266 to initialize

    def read_enroll(self):
        print("Waiting for enroll data...")
        start_time = time.time()
        while time.time() - start_time < 30:  # 30-second timeout
            if self.ser.in_waiting:
                try:
                    line = self.ser.readline()
                    if line:
                        try:
                            decoded_line = line.decode('utf-8').strip()
                            print(f"Received: {decoded_line}")
                            if decoded_line.startswith("ENROLL_SUCCESS:"):
                                parts = decoded_line.split(":")
                                if len(parts) == 3:
                                    id, status = parts[1], parts[2]
                                    return id, status
                            elif decoded_line == "ENROLL_FAILED":
                                return None, "FAILED"
                        except UnicodeDecodeError:
                            print(f"Decode error in enroll, Raw bytes: {line}")
                except serial.SerialException as e:
                    raise serial.SerialException(f"Serial error: {str(e)}")
            time.sleep(0.1)
        print("Timeout: No enrollment response")
        return None, "TIMEOUT"

    def read_verify(self):
        print("Waiting for verify data...")
        start_time = time.time()
        while time.time() - start_time < 15:  # 15-second timeout
            if self.ser.in_waiting:
                try:
                    line = self.ser.readline()
                    if line:
                        try:
                            decoded_line = line.decode('utf-8').strip()
                            print(f"Received: {decoded_line}")
                            if decoded_line.startswith("VERIFY_SUCCESS:"):
                                parts = decoded_line.split(":")
                                if len(parts) == 3:
                                    id, status = parts[1], parts[2]
                                    return id, status
                            elif decoded_line == "VERIFY_FAILED":
                                return None, "FAILED"
                        except UnicodeDecodeError:
                            print(f"Decode error in verify, Raw bytes: {line}")
                except serial.SerialException as e:
                    raise serial.SerialException(f"Serial error: {str(e)}")
            time.sleep(0.1)
        print("Timeout: No verification response")
        return None, "TIMEOUT"

    def send_command(self, command):
        print(f"Sending command: {command.strip()}")
        self.ser.write((command + '\n').encode('utf-8'))
        self.ser.flush()

    def close(self):
        print("Closing serial connection")
        if self.ser.is_open:
            self.ser.close()

def get_fingerprint_from_sensor(mode='enroll', user_id=None):
    reader = FingerprintReader()
    try:
        if mode == 'enroll' and user_id:
            reader.send_command(f"ENROLL:{user_id}")
            id, status = reader.read_enroll()
            return id if status == "OK" else None
        elif mode == 'verify':
            reader.send_command("VERIFY")
            id, status = reader.read_verify()
            return id if status == "OK" else None
        return None
    finally:
        reader.close()