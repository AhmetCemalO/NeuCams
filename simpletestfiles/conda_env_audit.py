import subprocess
import yaml
import json

# Load environment.yml dependencies
with open('requirementsold.txt', 'r') as f:
    env = yaml.safe_load(f)

yml_pkgs = set()
for dep in env.get('dependencies', []):
    if isinstance(dep, str):
        pkg = dep.split('=')[0].lower()
        yml_pkgs.add(pkg)
    elif isinstance(dep, dict) and 'pip' in dep:
        for pipdep in dep['pip']:
            pkg = pipdep.split('==')[0].lower()
            yml_pkgs.add(pkg)

# Get installed packages via conda
proc = subprocess.run(['conda', 'list', '--json'], capture_output=True, text=True)
installed = json.loads(proc.stdout)
installed_pkgs = set(pkg['name'].lower() for pkg in installed)

# Find extras
extras = installed_pkgs - yml_pkgs

print('Packages installed but not in requirementsold.txt:')
for pkg in sorted(extras):
    print('  ', pkg)

if not extras:
    print('No extra packages found!') 