import subprocess
import sys
import os
from pathlib import Path

def install_dependencies():
    """Checks and installs required Python packages"""
    # Added 'qrcode' to the list of required pip packages
    required_pip_packages = ['pygame', 'psutil', 'Flask', 'Pillow', 'qrcode']
    
    print("Checking and installing required Python packages...")
    for package in required_pip_packages:
        try:
            # Try importing to check if installed. For 'Pillow', the import name is 'PIL'.
            if package == 'Pillow':
                __import__('PIL')
            else:
                __import__(package.split('-')[0]) # Try importing by common package name
            print(f"  ✓ {package} is already installed.")
        except ImportError:
            print(f"  Installing {package}...")
            try:
                subprocess.run([sys.executable, '-m', 'pip', 'install', package], check=True)
                print(f"  Successfully installed {package}.")
            except subprocess.CalledProcessError as e:
                print(f"  Error installing {package}: {e}. Please install manually.")
            except Exception as e:
                print(f"  Unexpected error during {package} installation: {e}")


def setup_system():
    """System setup - ensures Raspberry Pi is in an optimal state"""
    print("Checking system setup...")

    # Ensure required apt packages are installed (for pygame, basic fonts, image processing libs etc.)
    required_apt_packages = ['python3-pygame', 'python3-psutil', 'fonts-dejavu', 'fonts-freefont-ttf', 'libjpeg-dev', 'zlib1g-dev']
    
    for package in required_apt_packages:
        try:
            result = subprocess.run(['dpkg', '-l', package], capture_output=True)
            if result.returncode != 0:
                print(f"  Installing system package {package}...")
                subprocess.run(['sudo', 'apt', 'install', '-y', package], check=True)
                print(f"  Successfully installed {package}.")
            else:
                print(f"  ✓ System package {package} is already installed.")
        except subprocess.CalledProcessError as e:
            print(f"  Error installing system package {package}: {e.stderr.decode()}")
            print(f"  Please try 'sudo apt install {package}' manually if needed.")
        except Exception as e:
            print(f"  Unexpected error during system package {package} installation: {e}")


    # Set up autologin (if needed)
    try:
        subprocess.run(['sudo', 'raspi-config', 'nonint', 'do_boot_behaviour', 'B4'],
                     capture_output=True)
        print("  ✓ Autologin behavior set (if applicable).")
    except Exception as e:
        print(f"  Warning: Could not set up autologin - {e}")

    # Set up auto-startup on boot
    setup_auto_startup()

    print("✓ System setup complete")

def setup_auto_startup():
    """Sets up auto-startup on boot"""
    script_dir = Path(__file__).parent
    main_script_path = script_dir / "main.py"

    startup_script = f"""#!/bin/bash
# Raspberry Pi Monitor and File Manager System Autostart Script

# Navigate to the script's directory
cd {script_dir}

# Give some time for graphical environment to start
sleep 5

# Start the main Python application in the background and log output
python3 {main_script_path} &> /var/log/pi-monitor.log &

# Exit this script, the python app runs in background
exit 0
"""

    # Create startup script
    script_path = "/home/pi/start_monitor.sh"
    try:
        with open(script_path, 'w') as f:
            f.write(startup_script)
        os.chmod(script_path, 0o755)
        print(f"  ✓ Startup script created at {script_path}")

        # Create systemd service
        service_content = f"""[Unit]
Description=Pi Touch Monitor and File Manager
After=graphical-session.target network.target
Wants=graphical-session.target

[Service]
Type=forking  # Use forking because the bash script forks the python app
User=pi
# Environment=DISPLAY=:0 # Not strictly needed if started from graphical-session or within a screen session
ExecStart={script_path}
Restart=always
RestartSec=3

[Install]
WantedBy=graphical-session.target
"""

        service_path = "/etc/systemd/system/pi-monitor.service"
        with open(service_path, 'w') as f:
            f.write(service_content)
        print(f"  ✓ systemd service created at {service_path}")

        # Enable service
        subprocess.run(['sudo', 'systemctl', 'enable', 'pi-monitor.service'],
                     capture_output=True, check=True)
        print("  ✓ systemd service 'pi-monitor.service' enabled.")
        print("  Note: You may need to reboot for autostart to take effect.")

    except subprocess.CalledProcessError as e:
        print(f"  Error with systemctl command: {e.stderr.decode()}")
        print(f"  Warning: Could not set up auto-startup via systemd.")
    except Exception as e:
        print(f"  Warning: Could not set up auto-startup - {e}")

