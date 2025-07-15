import sys
from argparse import ArgumentParser
from PyQt5.QtWidgets import QApplication
from view_ng.widgets import PyCamsWindow
from utils import get_preferences, display

def main():
    """
    Parses the arguments, gets preferences and calls GUI_initializer
    """
    parser = ArgumentParser(description='Labcams: multiple camera control and recording.')
    parser.add_argument('-p','--pref',metavar='preference',
                        type=str,help='Preference filename',default = None)
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    args = parser.parse_args()

    # Set global verbose flag before any display calls
    import builtins
    builtins.LABCAMS_VERBOSE = args.verbose

    ret, prefs = get_preferences(args.pref)
    
    if not ret:
        display('Warning: could not load preferences')

    app = QApplication(sys.argv)
    w = PyCamsWindow(preferences = prefs)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()