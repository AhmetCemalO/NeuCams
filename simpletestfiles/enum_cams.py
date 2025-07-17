from harvesters.core import Harvester

# Path to your GenTL producer .cti file (update this if needed)
GENTL_PATH = r"C:\Program Files\Allied Vision\Vimba X\cti\VimbaGigETL.cti"  # Example for AVT
# For Dalsa, it might be something like:
# GENTL_PATH = r"C:\Program Files\Teledyne DALSA\CamExpert\GenICam\bin\win64_x64\TLProducer.cti"

def main():
    h = Harvester()
    h.add_file(GENTL_PATH)
    h.update()
    print(f"Found {len(h.device_info_list)} camera(s).")
    for i, info in enumerate(h.device_info_list):
        print(f"\nCamera {i}:")
        print(f"  Serial Number: {info.serial_number}")
        print(f"  Model: {info.model}")
        print(f"  Vendor: {info.vendor}")
        print(f"  Display Name: {info.display_name}")
        print(f"  ID: {info.id_}")
        # Try to open the camera
        try:
            acquirer = h.create(list_index=i)
            print("  Status: Opened successfully!")
            acquirer.destroy()
        except Exception as e:
            print(f"  Status: FAILED to open ({e})")
    h.reset()

if __name__ == "__main__":
    main()