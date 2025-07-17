from harvesters.core import Harvester
import os

def get_gentl_producer_path():
    # Adjust this path if needed
    cfg_path = os.path.join(os.path.dirname(__file__), "neucams", "python_code", "cams", "genicam_gen_tl.cfg")
    if os.path.isfile(cfg_path):
        with open(cfg_path, "r") as f:
            for line in f:
                if line.startswith("GENTL_PATH"):
                    return line.split("=")[1].strip()
    return ""

def print_detected_genicam_cameras():
    h = Harvester()
    gentl_path = get_gentl_producer_path()
    if gentl_path:
        h.add_file(gentl_path)
    h.update()
    print("[INFO] Detected GenICam cameras:")
    for idx, info in enumerate(h.device_info_list):
        print(f"  Index: {idx}")
        for k, v in info.__dict__.items():
            print(f"    {k}: {v}")
    h.reset()

if __name__ == "__main__":
    print_detected_genicam_cameras() 