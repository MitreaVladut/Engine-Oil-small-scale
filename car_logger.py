import obd
import csv
import time
from datetime import datetime

PORT_NAME = "COM5"
CSV_FILENAME = "car_telemetry_log.csv"

# Global dictionary to track the last valid reading for each parameter
last_valid_values = {
    "RPM": 0.0,
    "Speed": 0.0,
    "Coolant_Temp": 0.0,
    "Engine_Load": 0.0
}

def connect_to_car():
    print(f"[*] Connecting to AUTOSKY on {PORT_NAME}...")
    
    connection = obd.OBD(
        portstr=PORT_NAME,
        baudrate=38400,
        protocol="3",     # ISO 9141-2
        fast=False,       # Keeps polling timing stable on legacy K-Line
        timeout=30
    )
        
    if connection.is_connected():
        print(f"[+] Connected successfully over protocol: {connection.protocol_name()}")
        return connection
    else:
        print("[!] Protocol 3 failed. Trying Protocol 5 (ISO 14230-4 KWP)...")
        connection = obd.OBD(
            portstr=PORT_NAME,
            baudrate=38400,
            protocol="5",
            fast=False,
            timeout=30
        )
        if connection.is_connected():
            print(f"[+] Connected successfully over protocol: {connection.protocol_name()}")
            return connection
            
        print("[-] Connection failed!")
        return None

def query_pid_safely(connection, command, key_name):
    """Query a PID and hold the previous valid value if the ECU drops a frame."""
    response = connection.query(command)
    
    if not response.is_null() and response.value is not None:
        val = response.value.magnitude
        last_valid_values[key_name] = val
        return val
    else:
        # ECU failed to answer this specific cycle; return the last known good value
        return last_valid_values[key_name]

def main():
    connection = connect_to_car()
    if not connection:
        return

    # Check/Create CSV file
    file_exists = False
    try:
        with open(CSV_FILENAME, 'r'):
            file_exists = True
    except FileNotFoundError:
        pass

    csv_file = open(CSV_FILENAME, mode='a', newline='')
    csv_writer = csv.writer(csv_file)

    if not file_exists:
        csv_writer.writerow(["Timestamp", "RPM", "Speed_KMH", "Coolant_Temp_C", "Engine_Load_Pct"])
        csv_file.flush()

    print("\n[+] Data logging active! Press Ctrl+C to stop.\n")
    print(f"{'Timestamp':<20} | {'RPM':<8} | {'Speed':<8} | {'Coolant Temp':<12} | {'Engine Load':<12}")
    print("-" * 70)

    try:
        while True:
            # Stagger queries with small delays to avoid bus collision on ISO 9141
            rpm = query_pid_safely(connection, obd.commands.RPM, "RPM")
            time.sleep(0.05)
            
            speed = query_pid_safely(connection, obd.commands.SPEED, "Speed")
            time.sleep(0.05)
            
            temp = query_pid_safely(connection, obd.commands.COOLANT_TEMP, "Coolant_Temp")
            time.sleep(0.05)
            
            load = query_pid_safely(connection, obd.commands.ENGINE_LOAD, "Engine_Load")

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Print to terminal
            print(f"{timestamp:<20} | {rpm:<8.0f} | {speed:<8.0f} | {temp:<12.1f} | {load:<12.1f}")

            # Append row to CSV
            csv_writer.writerow([timestamp, rpm, speed, temp, load])
            csv_file.flush()

            # Main loop delay (1 second)
            time.sleep(0.8)

    except KeyboardInterrupt:
        print("\n\n[*] Logging stopped by user.")
    finally:
        csv_file.close()
        connection.close()
        print(f"[+] Telemetry saved to '{CSV_FILENAME}'.")

if __name__ == "__main__":
    main()