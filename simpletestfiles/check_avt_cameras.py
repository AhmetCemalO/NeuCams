from vmbpy import VmbSystem

with VmbSystem.get_instance() as vmb:
    cameras = vmb.get_all_cameras()
    print("Cameras I can see:")
    for cam in cameras:
        print(f"  ID: {cam.get_id()}, Name: {cam.get_name()}, Model: {cam.get_model()}") 